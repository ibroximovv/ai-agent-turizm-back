"""API representations.

Field names deliberately mirror the previous TypeORM payloads (snake_case
columns, camelCase computed extras) so existing clients keep working.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import AuditLog, Material, MaterialType, Module, Topic


class ModuleBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ["id", "code", "name", "owui_kb_id", "is_active"]


class TopicBriefSerializer(serializers.ModelSerializer):
    module_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Topic
        fields = ["id", "module_id", "code", "name", "description", "order_index"]


class ModuleSerializer(serializers.ModelSerializer):
    topics = TopicBriefSerializer(many=True, read_only=True)
    topicsCount = serializers.SerializerMethodField()
    materialsCount = serializers.SerializerMethodField()
    materialsByStatus = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = [
            "id", "code", "name", "description", "order_index",
            "owui_kb_id", "is_active", "created_at", "updated_at",
            "topics", "topicsCount", "materialsCount", "materialsByStatus",
        ]
        read_only_fields = ["id", "owui_kb_id", "created_at", "updated_at"]

    # The view attaches `_stats` from one grouped query for the whole page.
    def _stats(self, obj) -> dict:
        return (self.context.get("material_stats") or {}).get(str(obj.id)) or {}

    def get_topicsCount(self, obj) -> int:
        return len(obj.topics.all())

    def get_materialsCount(self, obj) -> int:
        return self._stats(obj).get("total", 0)

    def get_materialsByStatus(self, obj) -> dict:
        return self._stats(obj).get("byStatus", {})


class ModuleWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ["code", "name", "description", "order_index", "is_active"]
        extra_kwargs = {
            "code": {"help_text": "Masalan: module-01"},
            "name": {"help_text": "Modulning to'liq nomi"},
        }

    def validate_code(self, value: str) -> str:
        queryset = Module.objects.filter(code=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(f'"{value}" kodli modul allaqachon mavjud')
        return value


class TopicSerializer(serializers.ModelSerializer):
    module_id = serializers.UUIDField(read_only=True)
    module = ModuleBriefSerializer(read_only=True)
    materialsCount = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = [
            "id", "module_id", "code", "name", "description", "order_index",
            "created_at", "updated_at", "module", "materialsCount",
        ]

    def get_materialsCount(self, obj) -> int:
        count = getattr(obj, "materials_count", None)
        return count if count is not None else obj.materials.count()


class TopicWriteSerializer(serializers.ModelSerializer):
    module_id = serializers.PrimaryKeyRelatedField(
        source="module", queryset=Module.objects.all(), help_text="Ota modul UUID'i"
    )

    class Meta:
        model = Topic
        fields = ["module_id", "code", "name", "description", "order_index"]

    def validate(self, attrs: dict) -> dict:
        module = attrs.get("module") or getattr(self.instance, "module", None)
        code = attrs.get("code") or getattr(self.instance, "code", None)
        if module is None or code is None:
            return attrs

        queryset = Topic.objects.filter(module=module, code=code)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                {"code": f'Bu modulda "{code}" kodli mavzu allaqachon mavjud'}
            )
        return attrs


class MaterialSerializer(serializers.ModelSerializer):
    topic_id = serializers.UUIDField(read_only=True)
    topic = TopicBriefSerializer(read_only=True)
    module = ModuleBriefSerializer(source="topic.module", read_only=True)
    uploaded_by_email = serializers.EmailField(source="uploaded_by.email", read_only=True)

    class Meta:
        model = Material
        fields = [
            "id", "topic_id", "type", "raw_file_path", "original_filename",
            "file_size", "file_hash", "status", "error_message", "md_file_path",
            "chunk_count", "char_count", "detected_script", "owui_file_id",
            "indexed_at", "created_at", "updated_at",
            "topic", "module", "uploaded_by_email",
        ]


class UploadMaterialSerializer(serializers.Serializer):
    topic_id = serializers.PrimaryKeyRelatedField(
        queryset=Topic.objects.all(), help_text="Maqsadli mavzu UUID'i"
    )
    type = serializers.ChoiceField(
        choices=MaterialType.choices,
        default=MaterialType.LITERATURE,
        help_text="Material toifasi",
    )
    file = serializers.FileField(
        help_text="Hujjat fayli (PDF, PPTX, DOCX, TXT, MD)"
    )


class MaterialContentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    filename = serializers.CharField()
    markdown = serializers.CharField()
    chunkCount = serializers.IntegerField()
    charCount = serializers.IntegerField()
    detectedScript = serializers.CharField(allow_null=True)


class AuditLogSerializer(serializers.ModelSerializer):
    module_id = serializers.UUIDField(read_only=True, allow_null=True)
    material_id = serializers.UUIDField(read_only=True, allow_null=True)
    module = ModuleBriefSerializer(read_only=True)
    material_filename = serializers.CharField(
        source="material.original_filename", read_only=True, default=None
    )

    class Meta:
        model = AuditLog
        fields = [
            "id", "material_id", "module_id", "stage", "level", "message",
            "created_at", "module", "material_filename",
        ]


class DeleteResultSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()


class KbSyncResultSerializer(serializers.Serializer):
    module = ModuleBriefSerializer()
    kb = serializers.DictField()
    created = serializers.BooleanField()


class BatchProcessResultSerializer(serializers.Serializer):
    moduleId = serializers.UUIDField()
    totalQueued = serializers.IntegerField()
    skipped = serializers.IntegerField()
    concurrency = serializers.IntegerField()
    materials = serializers.ListField(child=serializers.DictField())
