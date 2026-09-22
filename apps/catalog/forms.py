from __future__ import annotations

from django import forms

from apps.catalog.models import MaterialType, Topic
from apps.common.constants import ALLOWED_UPLOAD_EXTENSIONS
from config.app_config import uploads_config


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
