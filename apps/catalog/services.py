"""Domain operations shared by the REST API and the admin panel."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db.models import Count
from rest_framework.exceptions import APIException, NotFound, ValidationError

from apps.catalog.models import Material, MaterialStatus, MaterialType, Module, Topic
from apps.common.constants import ALLOWED_UPLOAD_EXTENSIONS
from apps.common.exceptions import PayloadTooLarge
from apps.common.filename import (
    build_stored_filename,
    decode_multipart_filename,
    sanitize_path_segment,
)
from apps.owui.client import OwuiError, get_owui_client
from apps.pipeline import runner
from config.app_config import uploads_config

logger = logging.getLogger(__name__)


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"


class BadGateway(APIException):
    status_code = 502
    default_code = "bad_gateway"


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


def upload_material(
    upload: UploadedFile | None,
    topic_id: str,
    material_type: str = MaterialType.LITERATURE,
    uploaded_by=None,
) -> Material:
    """Store a raw document and enqueue it for the grounding pipeline."""
    if upload is None:
        raise ValidationError({"file": "Yuklash uchun fayl berilmadi"})

    uploads = uploads_config()
    if upload.size and upload.size > uploads.max_bytes:
        raise PayloadTooLarge(
            f"Fayl hajmi {uploads.max_mb} MB chegarasidan oshdi "
            f"({upload.size / (1024 * 1024):.1f} MB)."
        )

    topic = Topic.objects.select_related("module").filter(pk=topic_id).first()
    if topic is None:
        raise NotFound(f'Mavzu topilmadi: "{topic_id}"')

    # Recover the real name before it reaches the database, the frontmatter
    # and the grounding markers.
    original_name = decode_multipart_filename(upload.name or "")
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValidationError(
            {
                "file": (
                    f"Qo'llab-quvvatlanmaydigan format: {extension or '(kengaytmasiz)'}. "
                    f"Ruxsat etilganlar: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
                )
            }
        )

    # 1. SHA-256 over the upload, streamed so a large file is never fully
    #    resident in memory.
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    file_hash = digest.hexdigest()

    # 2. Reject byte-identical re-uploads instead of indexing the same content
    #    twice into the knowledge base.
    duplicate = Material.objects.filter(topic=topic, file_hash=file_hash).first()
    if duplicate is not None:
        raise Conflict(
            f'Bu mavzuga aynan shu fayl allaqachon biriktirilgan: "{duplicate.id}" '
            f"({duplicate.original_filename}). Avval uni o'chiring yoki "
            f"POST /api/materials/{duplicate.id}/retry dan foydalaning."
        )

    # 3. Save the raw file: {uploads}/raw/{moduleCode}/{topicCode}/{hash}__{filename}
    #    Codes originate from user input, so each segment is sanitised before it
    #    becomes part of a filesystem path.
    raw_dir = (
        uploads.raw_dir
        / sanitize_path_segment(topic.module.code)
        / sanitize_path_segment(topic.code)
    )
    raw_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / build_stored_filename(original_name, extension, file_hash)
    with raw_path.open("wb") as target:
        for chunk in upload.chunks():
            target.write(chunk)

    # 4. Create the record
    material = Material.objects.create(
        topic=topic,
        type=material_type,
        raw_file_path=str(raw_path),
        original_filename=original_name,
        file_size=upload.size or raw_path.stat().st_size,
        file_hash=file_hash,
        status=MaterialStatus.QUEUED,
        uploaded_by=uploaded_by if getattr(uploaded_by, "is_authenticated", False) else None,
    )

    # 5. Trigger the asynchronous processing pipeline
    runner.submit(str(material.id))

    return material


def read_material_markdown(material: Material) -> dict[str, Any]:
    if not material.md_file_path:
        raise ValidationError("Material hali Markdown'ga konvertatsiya qilinmagan")

    path = Path(material.md_file_path)
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotFound(f"Markdown fayl diskda topilmadi: {material.md_file_path}") from exc

    return {
        "id": str(material.id),
        "filename": material.original_filename,
        "markdown": markdown,
        "chunkCount": material.chunk_count,
        "charCount": material.char_count,
        "detectedScript": material.detected_script,
    }


def retry_material(material: Material) -> Material:
    if runner.is_processing(str(material.id)):
        raise Conflict("Bu material hozir ishlanmoqda — joriy ishlov tugashini kuting")

    # Persist the queued state *before* starting the run: the pipeline loads its
    # own copy of the record, so saving this stale one afterwards would
    # overwrite the status and results the run has already written.
    material.status = MaterialStatus.QUEUED
    material.error_message = None
    material.save(update_fields=["status", "error_message", "updated_at"])

    runner.submit(str(material.id))
    return material


def delete_material(material: Material) -> dict[str, Any]:
    """Remove the record, its files on disk, and its copy in Open WebUI."""
    filename = material.original_filename
    kb_id = material.topic.module.owui_kb_id

    if material.owui_file_id and kb_id:
        client = get_owui_client()
        client.remove_file_from_knowledge_base(kb_id, material.owui_file_id)
        client.delete_file(material.owui_file_id)

    for path in (material.raw_file_path, material.md_file_path):
        if not path:
            continue
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Faylni o'chirib bo'lmadi (%s): %s", path, exc)

    material.delete()

    return {"success": True, "message": f'Material "{filename}" o\'chirildi'}


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------


def create_or_sync_kb(module: Module) -> dict[str, Any]:
    """Create the module's Open WebUI Knowledge Base, or adopt the existing one."""
    client = get_owui_client()

    status = client.check_connection()
    if not status.connected:
        raise BadGateway(f"Open WebUI bilan sinxronlab bo'lmadi: {status.message}")

    if module.owui_kb_id:
        try:
            existing = client.get_knowledge_base(module.owui_kb_id)
            return {
                "module": module,
                "kb": {"id": existing.id, "name": existing.name},
                "created": False,
            }
        except OwuiError:
            # The stored id no longer resolves in Open WebUI; create a new KB.
            logger.info(
                "Modul %s uchun saqlangan KB (%s) topilmadi, yangisi yaratiladi.",
                module.code,
                module.owui_kb_id,
            )

    created = client.create_knowledge_base(
        f"{module.code} - {module.name}", module.description or module.name
    )
    module.owui_kb_id = created.id
    module.save(update_fields=["owui_kb_id", "updated_at"])

    return {
        "module": module,
        "kb": {"id": created.id, "name": created.name},
        "created": True,
    }


def material_stats(module_ids: list) -> dict[str, dict[str, Any]]:
    """One grouped query for every module on the page instead of one per module."""
    stats: dict[str, dict[str, Any]] = {}
    if not module_ids:
        return stats

    rows = (
        Material.objects.filter(topic__module_id__in=module_ids)
        .values("topic__module_id", "status")
        .annotate(count=Count("id"))
    )

    for row in rows:
        key = str(row["topic__module_id"])
        entry = stats.setdefault(key, {"total": 0, "byStatus": {}})
        entry["byStatus"][row["status"]] = row["count"]
        entry["total"] += row["count"]

    return stats
