"""End-to-end ingestion pipeline: parse → clean → transliterate → ground → index."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.catalog.models import AuditLog, LogLevel, Material, MaterialStatus, Module
from apps.owui.client import OwuiError, get_owui_client
from apps.pipeline import runner
from apps.pipeline.services.chunker import GroundingMetadata, build_grounded_markdown
from apps.pipeline.services.cleaner import clean_text
from apps.pipeline.services.parser import ParsedChunk, parse_file
from apps.pipeline.services.translit import detect_script, to_latin
from config.app_config import uploads_config

logger = logging.getLogger(__name__)

#: Characters of document text inspected when detecting the script.
SCRIPT_SAMPLE_CHARS = 8000


def is_processing(material_id: str) -> bool:
    return runner.is_processing(material_id)


def process_material(material_id: str) -> Material:
    """Run the full pipeline for one material.

    Raises whatever the conversion raised, after recording it on the material
    and in the audit log.
    """
    material = (
        Material.objects.select_related("topic__module").filter(pk=material_id).first()
    )
    if material is None:
        raise Material.DoesNotExist(f"Material topilmadi: {material_id}")

    topic = material.topic
    module = topic.module

    if not runner.claim(str(material.id)):
        logger.warning(
            "Material %s allaqachon ishlanmoqda — takroriy ishga tushirish o'tkazib yuborildi.",
            material_id,
        )
        return material

    try:
        # 1. Stage: CONVERTING
        _set_status(material, MaterialStatus.CONVERTING, error_message=None)
        _log_audit(
            material.id,
            module.id,
            "conversion",
            LogLevel.INFO,
            f'Hujjatni o\'qish boshlandi: "{material.original_filename}"',
        )

        # 2. Parse the raw file
        parsed = parse_file(material.raw_file_path)
        if not parsed.chunks:
            raise ValueError("Hujjatdan matn ajratib bo'lmadi — indekslash uchun kontent yo'q.")

        # 3. Clean and transliterate
        detected = detect_script(_build_script_sample(parsed.chunks))
        processed = [
            ParsedChunk(
                label=chunk.label,
                text=to_latin(clean_text(chunk.text))
                if detected == "uz-cyrl"
                else clean_text(chunk.text),
            )
            for chunk in parsed.chunks
        ]

        # 4. Inject grounding markers and build Markdown
        result = build_grounded_markdown(
            processed,
            GroundingMetadata(
                material_id=str(material.id),
                module_code=module.code,
                module_name=module.name,
                topic_code=topic.code,
                topic_name=topic.name,
                material_type=material.type,
                original_filename=material.original_filename,
                detected_script=detected,
            ),
            uploads_config().ready_dir,
        )

        # A rename (different filename fingerprint) would otherwise leave the
        # previous markdown behind as an orphan.
        _remove_stale_markdown(material.md_file_path, result.file_path)

        material.detected_script = detected
        material.md_file_path = str(result.file_path)
        material.chunk_count = result.chunk_count
        material.char_count = result.char_count
        material.status = MaterialStatus.MD_READY
        material.save(
            update_fields=[
                "detected_script",
                "md_file_path",
                "chunk_count",
                "char_count",
                "status",
                "updated_at",
            ]
        )

        _log_audit(
            material.id,
            module.id,
            "conversion",
            LogLevel.INFO,
            f"Markdown tayyor: {result.chunk_count} ta chunk, "
            f"{result.marker_count} ta grounding marker, "
            f"{result.char_count:,} belgi, yozuv: {detected}",
        )

        for warning in parsed.warnings:
            _log_audit(material.id, module.id, "conversion", LogLevel.WARN, warning)

        # 5. Stage: Open WebUI indexing
        _index_to_owui(material, module)

        return material

    except Exception as exc:
        message = str(exc)
        logger.error("Pipeline xatosi (material %s): %s", material_id, message)

        material.status = MaterialStatus.FAILED
        material.error_message = message
        material.save(update_fields=["status", "error_message", "updated_at"])

        _log_audit(
            material.id, module.id, "pipeline", LogLevel.ERROR, f"Pipeline xatosi: {message}"
        )
        raise
    finally:
        runner.release(str(material.id))


def queue_module_materials(module: Module) -> dict:
    """Enqueue every material of a module for a full pipeline run.

    Anything already mid-run is left alone rather than processed twice. The
    worker pool itself provides the concurrency limit.
    """
    materials = list(
        Material.objects.filter(topic__module=module).order_by("created_at").only(
            "id", "original_filename"
        )
    )
    queueable = [m for m in materials if not runner.is_processing(str(m.id))]

    if queueable:
        Material.objects.filter(pk__in=[m.id for m in queueable]).update(
            status=MaterialStatus.QUEUED, error_message=None, updated_at=timezone.now()
        )

    for material in queueable:
        runner.submit(str(material.id))

    return {
        "moduleId": str(module.id),
        "totalQueued": len(queueable),
        "skipped": len(materials) - len(queueable),
        "concurrency": getattr(settings, "PIPELINE_CONCURRENCY", 2),
        "materials": [
            {"id": str(m.id), "filename": m.original_filename} for m in queueable
        ],
    }


def _index_to_owui(material: Material, module: Module) -> None:
    client = get_owui_client()

    # A cheap local check; the HTTP calls below report real connectivity
    # problems through the except block instead of costing an extra round trip
    # per material.
    if not client.is_configured:
        logger.info("OWUI_API_KEY sozlanmagan. Material md_ready holatida qoldirildi.")
        _log_audit(
            material.id,
            module.id,
            "indexing",
            LogLevel.WARN,
            "Open WebUI indekslash o'tkazib yuborildi: OWUI_API_KEY sozlanmagan",
        )
        return

    try:
        _set_status(material, MaterialStatus.UPLOADING)

        # Ensure a Knowledge Base exists for the module.
        kb_id = module.owui_kb_id
        if not kb_id:
            created = client.create_knowledge_base(
                f"{module.code} - {module.name}", module.description or module.name
            )
            kb_id = created.id
            module.owui_kb_id = kb_id
            module.save(update_fields=["owui_kb_id", "updated_at"])
            _log_audit(
                material.id,
                module.id,
                "kb_create",
                LogLevel.INFO,
                f"Open WebUI Knowledge Base yaratildi: {kb_id}",
            )

        # Re-indexing: drop the previous copy before uploading a new one.
        if material.owui_file_id:
            client.remove_file_from_knowledge_base(kb_id, material.owui_file_id)
            client.delete_file(material.owui_file_id)
            material.owui_file_id = None

        if not material.md_file_path:
            raise OwuiError("Markdown fayl yo'li yo'q — konvertatsiya tugallanmagan")

        md_path = Path(material.md_file_path)
        uploaded = client.upload_markdown_file(
            md_path.name, md_path.read_text(encoding="utf-8")
        )
        material.owui_file_id = uploaded.id

        client.add_file_to_knowledge_base(kb_id, uploaded.id)

        material.status = MaterialStatus.INDEXED
        material.error_message = None
        material.indexed_at = timezone.now()
        material.save(
            update_fields=[
                "owui_file_id",
                "status",
                "error_message",
                "indexed_at",
                "updated_at",
            ]
        )

        _log_audit(
            material.id,
            module.id,
            "indexing",
            LogLevel.INFO,
            f"Knowledge Base {kb_id} ga muvaffaqiyatli indekslandi (fayl ID: {uploaded.id})",
        )

    except Exception as exc:
        message = str(exc)
        logger.warning("Open WebUI indekslash xatosi: %s", message)
        # Conversion succeeded, so the material stays usable as md_ready.
        material.status = MaterialStatus.MD_READY
        material.error_message = f"Open WebUI indekslash ogohlantirishi: {message}"
        material.save(update_fields=["status", "error_message", "owui_file_id", "updated_at"])

        _log_audit(
            material.id,
            module.id,
            "indexing",
            LogLevel.WARN,
            f"OWUI indekslash tugallanmadi: {message}",
        )


def _set_status(material: Material, status: str, error_message: str | None = ...) -> None:
    fields = ["status", "updated_at"]
    material.status = status
    if error_message is not ...:
        material.error_message = error_message
        fields.append("error_message")
    material.save(update_fields=fields)


def _build_script_sample(chunks: list[ParsedChunk]) -> str:
    """Concatenate the leading chunks up to the script-detection sample size."""
    parts: list[str] = []
    length = 0
    for chunk in chunks:
        parts.append(chunk.text)
        length += len(chunk.text) + 1
        if length >= SCRIPT_SAMPLE_CHARS:
            break
    return " ".join(parts)[:SCRIPT_SAMPLE_CHARS]


def _remove_stale_markdown(previous_path: str | None, current_path: Path) -> None:
    if not previous_path or previous_path == str(current_path):
        return
    try:
        Path(previous_path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Eski markdown faylni o'chirib bo'lmadi (%s): %s", previous_path, exc)


def _log_audit(material_id, module_id, stage: str, level: str, message: str) -> None:
    """Audit logging must never be the reason a pipeline run fails."""
    try:
        AuditLog.objects.create(
            material_id=material_id,
            module_id=module_id,
            stage=stage,
            level=level,
            message=message,
        )
    except Exception as exc:
        logger.error("Audit yozuvini saqlab bo'lmadi (%s): %s", stage, exc)
