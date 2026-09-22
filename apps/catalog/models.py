"""Content hierarchy: Module → Topic → Material, plus the pipeline audit log.

Table and column names are the snake_case originals from the TypeORM schema, so
an existing database is adopted rather than rebuilt. Deleting a module cascades
to its topics, materials and audit logs.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import CODE_PATTERN, CODE_PATTERN_MESSAGE

code_validator = RegexValidator(regex=CODE_PATTERN, message=CODE_PATTERN_MESSAGE)


class MaterialType(models.TextChoices):
    PRESENTATION = "presentation", _("Taqdimot")
    QUESTIONS = "questions", _("Savollar")
    LITERATURE = "literature", _("Adabiyot")


class MaterialStatus(models.TextChoices):
    NEW = "new", _("Yangi")
    QUEUED = "queued", _("Navbatda")
    CONVERTING = "converting", _("Konvertatsiya qilinmoqda")
    MD_READY = "md_ready", _("Markdown tayyor")
    UPLOADING = "uploading", _("Yuklanmoqda")
    INDEXED = "indexed", _("Indekslangan")
    FAILED = "failed", _("Xatolik")


class LogLevel(models.TextChoices):
    INFO = "info", _("Ma'lumot")
    WARN = "warn", _("Ogohlantirish")
    ERROR = "error", _("Xato")


#: Statuses that mean the pipeline still owes this material some work.
IN_PROGRESS_STATUSES = frozenset(
    {MaterialStatus.QUEUED, MaterialStatus.CONVERTING, MaterialStatus.UPLOADING}
)


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(_("Yaratilgan"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Yangilangan"), auto_now=True)

    class Meta:
        abstract = True


class Module(UUIDModel, TimestampedModel):
    code = models.CharField(
        _("Kod"),
        max_length=40,
        unique=True,
        validators=[code_validator],
        help_text=_("Masalan: module-01. Diskda papka nomi sifatida ishlatiladi."),
    )
    name = models.CharField(_("Nomi"), max_length=300)
    # Nullable in the original schema; existing rows may hold NULL, so callers
    # always normalise with `or ""`.
    description = models.TextField(_("Tavsif"), null=True, blank=True)
    order_index = models.IntegerField(_("Tartib raqami"), default=0)
    owui_kb_id = models.CharField(
        _("Open WebUI KB ID"), max_length=64, null=True, blank=True,
        help_text=_("Modul uchun Open WebUI Knowledge Base identifikatori."),
    )
    is_active = models.BooleanField(_("Faol"), default=True)

    class Meta:
        db_table = "modules"
        verbose_name = _("Modul")
        verbose_name_plural = _("Modullar")
        ordering = ["order_index", "created_at"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Topic(UUIDModel, TimestampedModel):
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        db_column="module_id",
        related_name="topics",
        verbose_name=_("Modul"),
    )
    code = models.CharField(_("Kod"), max_length=40, validators=[code_validator])
    name = models.CharField(_("Nomi"), max_length=300)
    description = models.TextField(_("Tavsif"), null=True, blank=True)
    order_index = models.IntegerField(_("Tartib raqami"), default=0)

    class Meta:
        db_table = "topics"
        verbose_name = _("Mavzu")
        verbose_name_plural = _("Mavzular")
        ordering = ["order_index", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["module", "code"], name="uq_topics_module_code"
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Material(UUIDModel, TimestampedModel):
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        db_column="topic_id",
        related_name="materials",
        verbose_name=_("Mavzu"),
    )
    type = models.CharField(
        _("Turi"),
        max_length=20,
        choices=MaterialType.choices,
        default=MaterialType.LITERATURE,
    )
    raw_file_path = models.CharField(_("Manba fayl yo'li"), max_length=255)
    original_filename = models.CharField(_("Asl fayl nomi"), max_length=300)
    file_size = models.BigIntegerField(_("Fayl hajmi (bayt)"), default=0)
    file_hash = models.CharField(
        _("SHA-256"), max_length=64, null=True, blank=True,
        help_text=_("Bir xil faylni ikki marta indekslamaslik uchun."),
    )
    status = models.CharField(
        _("Holati"),
        max_length=20,
        choices=MaterialStatus.choices,
        default=MaterialStatus.NEW,
    )
    error_message = models.TextField(_("Xato matni"), null=True, blank=True)
    md_file_path = models.CharField(
        _("Markdown fayl yo'li"), max_length=255, null=True, blank=True
    )
    chunk_count = models.IntegerField(_("Chunklar soni"), default=0)
    char_count = models.IntegerField(_("Belgilar soni"), default=0)
    detected_script = models.CharField(
        _("Aniqlangan yozuv"), max_length=30, null=True, blank=True
    )
    owui_file_id = models.CharField(
        _("Open WebUI fayl ID"), max_length=64, null=True, blank=True
    )
    indexed_at = models.DateTimeField(_("Indekslangan vaqt"), null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        db_column="uploaded_by_id",
        related_name="uploaded_materials",
        null=True,
        blank=True,
        verbose_name=_("Yuklagan"),
    )

    class Meta:
        db_table = "materials"
        verbose_name = _("Material")
        verbose_name_plural = _("Materiallar")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["file_hash"], name="idx_materials_file_hash"),
            models.Index(fields=["status"], name="idx_materials_status"),
        ]

    def __str__(self) -> str:
        return self.original_filename

    @property
    def module(self) -> Module:
        return self.topic.module

    @property
    def is_in_progress(self) -> bool:
        return self.status in IN_PROGRESS_STATUSES

    @property
    def file_size_mb(self) -> float:
        return round(self.file_size / (1024 * 1024), 2)


class AuditLog(UUIDModel):
    """Append-only pipeline history. Never updated, so it has no `updated_at`."""

    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        db_column="material_id",
        related_name="audit_logs",
        null=True,
        blank=True,
        verbose_name=_("Material"),
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        db_column="module_id",
        related_name="audit_logs",
        null=True,
        blank=True,
        verbose_name=_("Modul"),
    )
    stage = models.CharField(_("Bosqich"), max_length=50)
    level = models.CharField(
        _("Daraja"), max_length=10, choices=LogLevel.choices, default=LogLevel.INFO
    )
    message = models.TextField(_("Xabar"))
    created_at = models.DateTimeField(_("Vaqt"), auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        verbose_name = _("Audit yozuvi")
        verbose_name_plural = _("Audit yozuvlari")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["created_at"], name="idx_audit_logs_created_at")]

    def __str__(self) -> str:
        return f"[{self.level}] {self.stage}: {self.message[:60]}"
