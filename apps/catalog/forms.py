from __future__ import annotations

from django import forms
from unfold.widgets import UnfoldAdminSelectWidget

from apps.catalog.models import MaterialType, Module, Topic
from apps.common.constants import ALLOWED_UPLOAD_EXTENSIONS
from apps.owui.client import OwuiError, get_owui_client
from config.app_config import owui_config, uploads_config


class MaterialUploadForm(forms.Form):
    """Admin-side counterpart of `POST /api/materials/upload`."""

    topic = forms.ModelChoiceField(
        queryset=Topic.objects.select_related("module").order_by(
            "module__order_index", "order_index"
        ),
        label="Mavzu",
        help_text="Material biriktiriladigan mavzu.",
    )
    type = forms.ChoiceField(
        choices=MaterialType.choices,
        initial=MaterialType.LITERATURE,
        label="Turi",
    )
    file = forms.FileField(
        label="Hujjat",
        help_text=f"Ruxsat etilgan formatlar: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}",
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        uploads = uploads_config()
        if upload.size and upload.size > uploads.max_bytes:
            raise forms.ValidationError(
                f"Fayl hajmi {uploads.max_mb} MB chegarasidan oshdi "
                f"({upload.size / (1024 * 1024):.1f} MB)."
            )
        return upload

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].label_from_instance = (
            lambda topic: f"{topic.module.code} / {topic.code} — {topic.name}"
        )


#: Choice label for "let the backend create it".
AUTO_CREATE = ("", "— Avtomatik yaratish —")


class ModuleAdminForm(forms.ModelForm):
    """Lets an operator attach a module to an Open WebUI KB and agent that
    already exist — the only way a hand-built preset (and the KB it reads)
    comes under the admin panel's control.

    The choices come from Open WebUI when the form is built. Without a
    connection the fields fall back to plain text inputs, so the form still
    works and an id can be typed in.
    """

    class Meta:
        model = Module
        fields = [
            "code", "name", "description", "order_index", "is_active",
            "owui_kb_id", "owui_model_id",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        kb_choices, model_choices = _owui_choices()

        for name, choices, help_text in (
            (
                "owui_kb_id",
                kb_choices,
                "Bo'sh qoldirilsa, modul uchun yangi Knowledge Base yaratiladi.",
            ),
            (
                "owui_model_id",
                model_choices,
                "Bo'sh qoldirilsa, modul agenti shablon asosida yaratiladi. "
                "Tanlangan agentning prompti o'zgarmaydi — faqat bilim bazasi "
                "shu modulga bog'lanadi.",
            ),
        ):
            field = self.fields[name]
            if choices is None:
                field.help_text = (
                    f"{help_text} Open WebUI'ga ulanib bo'lmadi — ID ni qo'lda kiriting."
                )
                continue
            current = getattr(self.instance, name, None)
            if current and current not in dict(choices):
                choices = [*choices, (current, f"{current} (Open WebUI'da topilmadi)")]
            self.fields[name] = forms.ChoiceField(
                choices=[AUTO_CREATE, *choices],
                required=False,
                label=field.label,
                help_text=help_text,
                widget=UnfoldAdminSelectWidget,
            )

    def _clean_unique(self, name: str, what: str) -> str | None:
        value = (self.cleaned_data.get(name) or "").strip() or None
        if value:
            clash = Module.objects.filter(**{name: value}).exclude(pk=self.instance.pk).first()
            if clash is not None:
                raise forms.ValidationError(
                    f'Bu {what} allaqachon "{clash.code}" moduliga biriktirilgan.'
                )
        return value

    def clean_owui_kb_id(self):
        return self._clean_unique("owui_kb_id", "Knowledge Base")

    def clean_owui_model_id(self):
        value = self._clean_unique("owui_model_id", "agent")
        if value and value == owui_config().master_model_id:
            raise forms.ValidationError(
                "Umumiy agentni modulga biriktirib bo'lmaydi — u barcha modullarniki."
            )
        return value


def _owui_choices() -> tuple[list[tuple[str, str]] | None, list[tuple[str, str]] | None]:
    """(KB choices, agent choices); None where Open WebUI could not be read."""
    client = get_owui_client()
    if not client.is_configured:
        return None, None
    try:
        kbs = [(kb.id, f"{kb.name} ({kb.id[:8]})") for kb in client.list_knowledge_bases()]
    except OwuiError:
        kbs = None
    try:
        master = client.config.master_model_id
        agents = [
            (str(m["id"]), f'{m.get("name") or m["id"]} ({m["id"]})')
            for m in client.list_models()
            if m.get("id") and m["id"] != master
        ]
    except OwuiError:
        agents = None
    return kbs, agents
