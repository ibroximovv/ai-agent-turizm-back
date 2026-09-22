"""Admin panel — the operator-facing front end of this backend.

Themed with django-unfold: every ModelAdmin and inline inherits from
``unfold.admin`` so that the Tailwind templates and widgets apply.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import Count
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html
from rest_framework.exceptions import APIException
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

from apps.catalog import services
from apps.catalog.forms import MaterialUploadForm, ModuleAdminForm
from apps.catalog.models import AuditLog, LogLevel, Material, MaterialStatus, Module, Topic
from apps.owui import sync as owui_sync
from apps.owui.client import OwuiError, get_owui_client
from apps.pipeline import runner
from apps.pipeline import service as pipeline_service
from config.app_config import uploads_config

#: Unfold label variants per pipeline status.
STATUS_VARIANTS = {
    MaterialStatus.NEW: "",
    MaterialStatus.QUEUED: "info",
    MaterialStatus.CONVERTING: "info",
    MaterialStatus.MD_READY: "primary",
    MaterialStatus.UPLOADING: "info",
    MaterialStatus.INDEXED: "success",
    MaterialStatus.FAILED: "danger",
}

LEVEL_VARIANTS = {
    LogLevel.INFO: "info",
    LogLevel.WARN: "warning",
    LogLevel.ERROR: "danger",
}


def _error(model_admin, request, exc: Exception) -> None:
    detail = getattr(exc, "detail", exc)
    model_admin.message_user(request, str(detail), messages.ERROR)


class TopicInline(TabularInline):
    model = Topic
    extra = 0
    fields = ["code", "name", "order_index"]
    show_change_link = True
    tab = True
    verbose_name = "Mavzu"
    verbose_name_plural = "Mavzular"


class MaterialInline(TabularInline):
    model = Material
    extra = 0
    can_delete = False
    show_change_link = True
    tab = True
    fields = ["original_filename", "type", "status_badge", "chunk_count", "created_at"]
    readonly_fields = fields
    verbose_name = "Material"
    verbose_name_plural = "Materiallar"

    def has_add_permission(self, request, obj=None) -> bool:
        # Materials are created by uploading a file, not by typing paths.
        return False

    @display(description="Holati", label=STATUS_VARIANTS)
    def status_badge(self, obj: Material) -> str:
        return obj.get_status_display()


@admin.register(Module)
class ModuleAdmin(ModelAdmin):
    form = ModuleAdminForm
    list_display = [
        "code_display", "topics_count", "materials_count",
        "kb_state", "agent_state", "is_active", "order_index",
    ]
    list_display_links = ["code_display"]
    list_editable = ["is_active", "order_index"]
    list_filter = ["is_active"]
    list_filter_submit = True
    search_fields = ["code", "name", "description"]
    ordering = ["order_index", "code"]
    inlines = [TopicInline]
    actions = ["action_sync_kb", "action_process_all"]
    actions_list = ["list_sync_master"]
    actions_row = ["row_sync_kb", "row_process_all"]
    actions_detail = ["row_sync_kb", "row_process_all"]
    compressed_fields = True
    warn_unsaved_form = True
    readonly_fields = ["id", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["code", "name", "description"]}),
        ("Ko'rsatish", {"fields": ["order_index", "is_active"]}),
        (
            "Open WebUI",
            {
                "fields": ["owui_kb_id", "owui_model_id"],
                "description": (
                    "Har bir modulning o'z Knowledge Base'i va faqat shu bazadan "
                    "javob beradigan agenti bor. Saqlanganda ikkalasi (bo'sh "
                    "bo'lsa — yaratilib) Open WebUI bilan sinxronlanadi va "
                    "umumiy agentning bilim bazalari ro'yxati yangilanadi."
                ),
            },
        ),
        ("Tizim", {"fields": ["id", "created_at", "updated_at"], "classes": ["collapse"]}),
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                num_topics=Count("topics", distinct=True),
                num_materials=Count("topics__materials", distinct=True),
            )
        )

    @display(description="Modul", ordering="code", header=True)
    def code_display(self, obj: Module) -> list[str]:
        # Unfold renders a two-line cell: bold title + muted subtitle.
        return [obj.code, obj.name]

    @display(description="Mavzular", ordering="num_topics")
    def topics_count(self, obj) -> int:
        return obj.num_topics

    @display(description="Materiallar", ordering="num_materials")
    def materials_count(self, obj) -> int:
        return obj.num_materials

    @display(description="Knowledge Base", label={True: "success", False: ""})
    def kb_state(self, obj: Module) -> tuple[bool, str]:
        return (True, obj.owui_kb_id[:14]) if obj.owui_kb_id else (False, "yo'q")

    @display(description="Agent", label={True: "success", False: ""})
    def agent_state(self, obj: Module) -> tuple[bool, str]:
        return (True, obj.owui_model_id) if obj.owui_model_id else (False, "yo'q")

    # -- saving ------------------------------------------------------------

    def save_model(self, request, obj: Module, form, change) -> None:
        synced_fields = {"owui_kb_id", "owui_model_id", "name", "is_active"}
        kb_changed = change and "owui_kb_id" in form.changed_data
        super().save_model(request, obj, form, change)

        if change and not synced_fields.intersection(form.changed_data):
            return
        if not get_owui_client().is_configured:
            return

        try:
            report = owui_sync.sync_module(obj)
        except OwuiError as exc:
            self.message_user(
                request,
                f"{obj.code}: Open WebUI bilan sinxronlanmadi — {exc}. "
                "Keyinroq \"Open WebUI sinxronlash\" tugmasini bosing.",
                messages.WARNING,
            )
            return
        self.message_user(request, f"{obj.code}: {report.summary()}", messages.SUCCESS)

        # Materials indexed into the previous KB have to be re-indexed into
        # the new one, or the module agent would not see them.
        if kb_changed and Material.objects.filter(topic__module=obj).exists():
            result = pipeline_service.queue_module_materials(obj)
            self.message_user(
                request,
                f"{obj.code}: KB o'zgargani uchun {result['totalQueued']} ta material "
                "yangi bazaga qayta indekslash navbatiga qo'yildi.",
                messages.INFO,
            )

    # -- row / detail buttons ---------------------------------------------

    @action(description="Open WebUI sinxronlash", icon="cloud_sync", url_path="sync-kb")
    def row_sync_kb(self, request, object_id):
        module = self.get_object(request, object_id)
        try:
            result = services.create_or_sync_kb(module)
        except (APIException, OwuiError) as exc:
            _error(self, request, exc)
        else:
            self.message_user(request, f'{module.code}: {result["summary"]}', messages.SUCCESS)
        return HttpResponseRedirect(request.META.get("HTTP_REFERER") or _module_list())

    @action(description="Umumiy agentni yangilash", icon="hub", url_path="sync-master")
    def list_sync_master(self, request):
        client = get_owui_client()
        if not client.is_configured:
            self.message_user(request, "OWUI_API_KEY sozlanmagan", messages.ERROR)
        else:
            try:
                master_id = owui_sync.sync_master_agent(client)
            except OwuiError as exc:
                _error(self, request, exc)
            else:
                if master_id:
                    self.message_user(
                        request, f"Umumiy agent yangilandi ({master_id})", messages.SUCCESS
                    )
                else:
                    self.message_user(
                        request,
                        "Hali birorta modulning bilim bazasi yo'q — umumiy agent yaratilmadi.",
                        messages.WARNING,
                    )
        return HttpResponseRedirect(_module_list())

    @action(description="Barchasini qayta ishlash", icon="refresh", url_path="process-all")
    def row_process_all(self, request, object_id):
        module = self.get_object(request, object_id)
        result = pipeline_service.queue_module_materials(module)
        self.message_user(
            request,
            f'{module.code}: {result["totalQueued"]} ta material navbatga qo\'yildi '
            f'({result["skipped"]} ta o\'tkazib yuborildi)',
            messages.SUCCESS,
        )
        return HttpResponseRedirect(request.META.get("HTTP_REFERER") or _module_list())

    # -- bulk actions ------------------------------------------------------

    @admin.action(description="Open WebUI: Knowledge Base va agentlarni sinxronlash")
    def action_sync_kb(self, request, queryset):
        for module in queryset:
            try:
                result = services.create_or_sync_kb(module)
            except (APIException, OwuiError) as exc:
                self.message_user(request, f"{module.code}: {exc}", messages.ERROR)
                continue
            self.message_user(request, f'{module.code}: {result["summary"]}', messages.SUCCESS)

    @admin.action(description="Barcha materiallarni qayta ishlash")
    def action_process_all(self, request, queryset):
        for module in queryset:
            result = pipeline_service.queue_module_materials(module)
            self.message_user(
                request,
                f'{module.code}: {result["totalQueued"]} ta material navbatga qo\'yildi '
                f'({result["skipped"]} ta o\'tkazib yuborildi)',
                messages.SUCCESS,
            )


def _module_list() -> str:
    return reverse("admin:catalog_module_changelist")


def _material_list() -> str:
    return reverse("admin:catalog_material_changelist")


@admin.register(Topic)
class TopicAdmin(ModelAdmin):
    list_display = ["code_display", "module", "materials_count", "order_index"]
    list_display_links = ["code_display"]
    list_editable = ["order_index"]
    list_filter = ["module"]
    list_filter_submit = True
    search_fields = ["code", "name", "description", "module__code", "module__name"]
    ordering = ["module__order_index", "order_index", "code"]
    autocomplete_fields = ["module"]
    inlines = [MaterialInline]
    compressed_fields = True
    warn_unsaved_form = True
    readonly_fields = ["id", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["module", "code", "name", "description", "order_index"]}),
        ("Tizim", {"fields": ["id", "created_at", "updated_at"], "classes": ["collapse"]}),
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("module")
            .annotate(num_materials=Count("materials", distinct=True))
        )

    @display(description="Mavzu", ordering="code", header=True)
    def code_display(self, obj: Topic) -> list[str]:
        return [obj.code, obj.name]

    @display(description="Materiallar", ordering="num_materials")
    def materials_count(self, obj) -> int:
        return obj.num_materials


@admin.register(Material)
class MaterialAdmin(ModelAdmin):
    list_display = [
        "filename_display", "module_code", "topic_code", "type",
        "status_badge", "chunk_count", "size_display", "created_at",
    ]
    list_display_links = ["filename_display"]
    list_filter = ["status", "type", "topic__module", "detected_script"]
    list_filter_submit = True
    search_fields = ["original_filename", "topic__code", "topic__module__code", "error_message"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    autocomplete_fields = ["topic"]
    actions = ["action_retry"]
    actions_list = ["list_upload"]
    actions_row = ["row_retry", "row_markdown"]
    actions_detail = ["row_retry", "row_markdown"]
    compressed_fields = True
    list_before_template = "admin/catalog/material_list_before.html"
    readonly_fields = [
        "id", "status_badge", "raw_file_path", "md_file_path", "file_hash",
        "file_size", "chunk_count", "char_count", "detected_script",
        "owui_file_id", "indexed_at", "uploaded_by", "created_at", "updated_at",
        "error_message",
    ]
    fieldsets = [
        (None, {"fields": ["topic", "type", "original_filename", "status_badge"]}),
        (
            "Konvertatsiya natijasi",
            {"fields": ["chunk_count", "char_count", "detected_script", "md_file_path"]},
        ),
        ("Open WebUI", {"fields": ["owui_file_id", "indexed_at"]}),
        ("Xatolik", {"fields": ["error_message"]}),
        (
            "Fayl",
            {
                "fields": ["raw_file_path", "file_size", "file_hash", "uploaded_by"],
                "classes": ["collapse"],
            },
        ),
        ("Tizim", {"fields": ["id", "created_at", "updated_at"], "classes": ["collapse"]}),
    ]

    # -- custom pages ------------------------------------------------------

    def get_urls(self):
        custom = [
            path(
                "upload/",
                self.admin_site.admin_view(self.upload_view),
                name="catalog_material_upload",
            ),
            path(
                "<uuid:material_id>/markdown/",
                self.admin_site.admin_view(self.markdown_view),
                name="catalog_material_markdown",
            ),
            path(
                "statuses/",
                self.admin_site.admin_view(self.statuses_view),
                name="catalog_material_statuses",
            ),
        ]
        return custom + super().get_urls()

    def add_view(self, request, form_url="", extra_context=None):
        # A material exists because a file was uploaded; there is nothing
        # meaningful to type into a blank model form.
        return HttpResponseRedirect(reverse("admin:catalog_material_upload"))

    def upload_view(self, request):
        """One page, two callers.

        The drag-and-drop uploader posts one file per request and reads the
        JSON reply so it can show per-file progress; a browser without the
        script still submits the plain form and gets a redirect.
        """
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        form = MaterialUploadForm(request.POST or None, request.FILES or None)

        if request.method == "POST":
            if form.is_valid():
                try:
                    material = services.upload_material(
                        upload=form.cleaned_data["file"],
                        topic_id=str(form.cleaned_data["topic"].id),
                        material_type=form.cleaned_data["type"],
                        uploaded_by=request.user,
                    )
                except APIException as exc:
                    message = str(getattr(exc, "detail", exc))
                    if wants_json:
                        return JsonResponse(
                            {"ok": False, "error": message}, status=exc.status_code
                        )
                    form.add_error(None, message)
                else:
                    if wants_json:
                        return JsonResponse(
                            {
                                "ok": True,
                                "id": str(material.id),
                                "name": material.original_filename,
                                "status": material.status,
                                "label": material.get_status_display(),
                                "changeUrl": reverse(
                                    "admin:catalog_material_change", args=[material.id]
                                ),
                            }
                        )
                    self.message_user(
                        request,
                        f'"{material.original_filename}" yuklandi va '
                        "konvertatsiya navbatiga qo'yildi.",
                        messages.SUCCESS,
                    )
                    return HttpResponseRedirect(
                        reverse("admin:catalog_material_change", args=[material.id])
                    )
            elif wants_json:
                first = next(iter(form.errors.values()))[0]
                return JsonResponse({"ok": False, "error": first}, status=400)

        context = {
            **self.admin_site.each_context(request),
            "title": "Hujjat yuklash",
            "form": MaterialUploadForm() if request.method == "GET" else form,
            "opts": self.model._meta,
            "max_upload_mb": uploads_config().max_mb,
            "statuses_url": reverse("admin:catalog_material_statuses"),
            "changelist_url": _material_list(),
        }
        return render(request, "admin/catalog/material_upload.html", context)

    def markdown_view(self, request, material_id):
        material = self.get_object(request, str(material_id))
        if material is None:
            self.message_user(request, "Material topilmadi", messages.ERROR)
            return HttpResponseRedirect(_material_list())

        try:
            markdown = services.read_material_markdown(material)["markdown"]
            error = None
        except APIException as exc:
            markdown = ""
            error = str(getattr(exc, "detail", exc))

        context = {
            **self.admin_site.each_context(request),
            "title": f"Markdown — {material.original_filename}",
            "material": material,
            "markdown": markdown,
            "error": error,
            "opts": self.model._meta,
        }
        return render(request, "admin/catalog/material_markdown.html", context)

    def statuses_view(self, request):
        """Tiny JSON feed so a list page can refresh its badges without a reload."""
        ids = [value for value in request.GET.get("ids", "").split(",") if value]
        rows = Material.objects.filter(pk__in=ids[:100]).values(
            "id", "status", "chunk_count", "error_message"
        )
        return JsonResponse(
            {
                "items": [
                    {
                        "id": str(row["id"]),
                        "status": row["status"],
                        "label": MaterialStatus(row["status"]).label,
                        "chunkCount": row["chunk_count"],
                        "error": row["error_message"],
                    }
                    for row in rows
                ]
            }
        )

    # -- display helpers ---------------------------------------------------

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("topic__module", "uploaded_by")

    @display(description="Hujjat", ordering="original_filename", header=True)
    def filename_display(self, obj: Material) -> list[str]:
        return [obj.original_filename, obj.get_type_display()]

    @display(description="Modul", ordering="topic__module__code")
    def module_code(self, obj: Material) -> str:
        return obj.topic.module.code

    @display(description="Mavzu", ordering="topic__code")
    def topic_code(self, obj: Material) -> str:
        return obj.topic.code

    @display(description="Holati", ordering="status", label=STATUS_VARIANTS)
    def status_badge(self, obj: Material) -> tuple[str, str]:
        return obj.status, obj.get_status_display()

    @display(description="Hajmi", ordering="file_size")
    def size_display(self, obj: Material) -> str:
        return f"{obj.file_size_mb} MB"

    # -- buttons -----------------------------------------------------------

    @action(description="Hujjat yuklash", icon="upload_file", url_path="upload-action")
    def list_upload(self, request):
        return HttpResponseRedirect(reverse("admin:catalog_material_upload"))

    @action(description="Qayta ishlash", icon="refresh", url_path="retry")
    def row_retry(self, request, object_id):
        material = self.get_object(request, object_id)
        try:
            services.retry_material(material)
        except APIException as exc:
            _error(self, request, exc)
        else:
            self.message_user(
                request,
                f'"{material.original_filename}" navbatga qo\'yildi.',
                messages.SUCCESS,
            )
        return HttpResponseRedirect(request.META.get("HTTP_REFERER") or _material_list())

    @action(description="Markdown", icon="article", url_path="view-markdown")
    def row_markdown(self, request, object_id):
        return HttpResponseRedirect(
            reverse("admin:catalog_material_markdown", args=[object_id])
        )

    @admin.action(description="Pipeline'ni qayta ishga tushirish")
    def action_retry(self, request, queryset):
        started = skipped = 0
        for material in queryset:
            if runner.is_processing(str(material.id)):
                skipped += 1
                continue
            services.retry_material(material)
            started += 1

        if started:
            self.message_user(
                request, f"{started} ta material navbatga qo'yildi.", messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} ta material allaqachon ishlanmoqda — o'tkazib yuborildi.",
                messages.WARNING,
            )

    def delete_model(self, request, obj):
        # Keep disk files and the Open WebUI copy in step with the record.
        services.delete_material(obj)

    def delete_queryset(self, request, queryset):
        for material in queryset:
            services.delete_material(material)


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    list_display = ["created_at", "level_badge", "stage", "short_message", "target"]
    list_filter = ["level", "stage", "module"]
    list_filter_submit = True
    search_fields = ["message", "stage", "material__original_filename"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    list_fullwidth = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("material", "module")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        # Append-only history: viewable, never editable.
        return False

    @display(description="Daraja", ordering="level", label=LEVEL_VARIANTS)
    def level_badge(self, obj: AuditLog) -> tuple[str, str]:
        return obj.level, obj.get_level_display()

    @display(description="Xabar")
    def short_message(self, obj: AuditLog) -> str:
        return obj.message if len(obj.message) <= 140 else obj.message[:140] + "…"

    @display(description="Obyekt")
    def target(self, obj: AuditLog) -> str:
        if obj.material_id:
            return format_html(
                '<a href="{}" class="text-primary-600 hover:underline">{}</a>',
                reverse("admin:catalog_material_change", args=[obj.material_id]),
                obj.material.original_filename,
            )
        if obj.module_id:
            return obj.module.code
        return "—"
