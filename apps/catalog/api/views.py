"""REST endpoints for modules, topics, materials and audit logs."""

from __future__ import annotations

from django.db.models import Count, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.catalog import services
from apps.catalog.api.serializers import (
    AuditLogSerializer,
    BatchProcessResultSerializer,
    DeleteResultSerializer,
    KbSyncResultSerializer,
    MaterialContentSerializer,
    MaterialSerializer,
    ModuleSerializer,
    ModuleWriteSerializer,
    TopicSerializer,
    TopicWriteSerializer,
    UploadMaterialSerializer,
)
from apps.catalog.models import (
    AuditLog,
    LogLevel,
    Material,
    MaterialStatus,
    MaterialType,
    Module,
    Topic,
)
from apps.owui.sync import sync_module_safely
from apps.pipeline import service as pipeline_service

UUID_REGEX = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

SEARCH_PARAM = OpenApiParameter(
    "search", OpenApiTypes.STR, description="Kod, nom yoki tavsif bo'yicha qidiruv"
)


def _bool_param(value: str | None) -> bool | None:
    """Query strings carry booleans as text; an unrecognised value is ignored."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


@extend_schema(tags=["Modules"])
@extend_schema_view(
    list=extend_schema(
        summary="Modullar ro'yxati",
        description=(
            "Mavzular soni va materiallar holati kesimi bilan sahifalangan ro'yxat."
        ),
        parameters=[
            SEARCH_PARAM,
            OpenApiParameter("is_active", OpenApiTypes.BOOL, description="Faollik bo'yicha filtr"),
        ],
    ),
    retrieve=extend_schema(summary="Modul tafsilotlari (mavzulari bilan)"),
    create=extend_schema(summary="Yangi modul yaratish"),
    partial_update=extend_schema(summary="Modulni tahrirlash"),
    update=extend_schema(summary="Modulni to'liq yangilash"),
    destroy=extend_schema(
        summary="Modulni o'chirish",
        description="Modul bilan birga uning mavzulari, materiallari va loglari o'chiriladi.",
        responses={200: DeleteResultSerializer},
    ),
)
class ModuleViewSet(viewsets.ModelViewSet):
    queryset = Module.objects.prefetch_related("topics").all()
    lookup_value_regex = UUID_REGEX

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return ModuleWriteSerializer
        return ModuleSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        is_active = _bool_param(self.request.query_params.get("is_active"))
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(description__icontains=search)
            )
        return queryset

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        # Populated in `list()` with a single grouped query for the whole page.
        context.setdefault("material_stats", {})
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)

        context = {
            **self.get_serializer_context(),
            "material_stats": services.material_stats([row.id for row in rows]),
        }
        data = ModuleSerializer(rows, many=True, context=context).data

        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)

    def create(self, request, *args, **kwargs):
        write = ModuleWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        module = write.save()
        # Best effort: the module exists either way, and POST /modules/{id}/kb
        # retries the Open WebUI side.
        sync_module_safely(module)
        return Response(ModuleSerializer(module).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        write = ModuleWriteSerializer(
            instance, data=request.data, partial=kwargs.pop("partial", False)
        )
        write.is_valid(raise_exception=True)
        synced = ("owui_kb_id", "owui_model_id", "name", "is_active")
        before = {field: getattr(instance, field) for field in synced}
        module = write.save()
        if any(getattr(module, field) != value for field, value in before.items()):
            sync_module_safely(module)
            if module.owui_kb_id != before["owui_kb_id"] and before["owui_kb_id"]:
                # Materials indexed into the previous KB move with the module.
                pipeline_service.queue_module_materials(module)
        return Response(ModuleSerializer(module).data)

    def destroy(self, request, *args, **kwargs):
        module = self.get_object()
        code = module.code
        module.delete()
        return Response(
            {
                "success": True,
                "message": f'"{code}" moduli va unga bog\'liq mavzular/materiallar o\'chirildi',
            }
        )

    @extend_schema(
        summary="Modul uchun Open WebUI Knowledge Base va agentlarni sinxronlash",
        description=(
            "Modul KB'sini yaratadi yoki mavjudini ishlatadi, modul agentini shu KB'ga "
            "bog'laydi va umumiy agentning bilim bazalari ro'yxatini yangilaydi."
        ),
        request=None,
        responses={200: KbSyncResultSerializer},
    )
    @action(detail=True, methods=["post"], url_path="kb")
    def sync_kb(self, request, pk=None):
        result = services.create_or_sync_kb(self.get_object())
        return Response(
            {
                "module": ModuleSerializer(result["module"]).data,
                "kb": result["kb"],
                "created": result["created"],
            }
        )

    @extend_schema(
        summary="Modulning barcha materiallarini qayta ishlash",
        description=(
            "Modul ichidagi barcha materiallarni konvertatsiya, transliteratsiya, "
            "grounding va Open WebUI indekslash uchun navbatga qo'yadi."
        ),
        request=None,
        responses={200: BatchProcessResultSerializer},
    )
    @action(detail=True, methods=["post"], url_path="process-all")
    def process_all(self, request, pk=None):
        return Response(pipeline_service.queue_module_materials(self.get_object()))


@extend_schema(tags=["Topics"])
@extend_schema_view(
    list=extend_schema(
        summary="Mavzular ro'yxati",
        parameters=[
            SEARCH_PARAM,
            OpenApiParameter("module_id", OpenApiTypes.UUID, description="Modul bo'yicha filtr"),
        ],
    ),
    retrieve=extend_schema(summary="Mavzu tafsilotlari"),
    create=extend_schema(summary="Yangi mavzu yaratish"),
    partial_update=extend_schema(summary="Mavzuni tahrirlash"),
    update=extend_schema(summary="Mavzuni to'liq yangilash"),
    destroy=extend_schema(summary="Mavzuni o'chirish", responses={200: DeleteResultSerializer}),
)
class TopicViewSet(viewsets.ModelViewSet):
    # The annotate() adds a GROUP BY, which drops Meta.ordering — hence the
    # explicit order_by, without which pagination would be non-deterministic.
    queryset = (
        Topic.objects.select_related("module")
        .annotate(materials_count=Count("materials", distinct=True))
        .order_by("module__order_index", "order_index", "created_at")
    )
    lookup_value_regex = UUID_REGEX

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return TopicWriteSerializer
        return TopicSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        module_id = self.request.query_params.get("module_id")
        if module_id:
            queryset = queryset.filter(module_id=module_id)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(description__icontains=search)
            )
        return queryset

    def create(self, request, *args, **kwargs):
        write = TopicWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        topic = write.save()
        return Response(TopicSerializer(topic).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        write = TopicWriteSerializer(
            instance, data=request.data, partial=kwargs.pop("partial", False)
        )
        write.is_valid(raise_exception=True)
        topic = write.save()
        return Response(TopicSerializer(topic).data)

    def destroy(self, request, *args, **kwargs):
        topic = self.get_object()
        code = topic.code
        topic.delete()
        return Response(
            {"success": True, "message": f'"{code}" mavzusi va uning materiallari o\'chirildi'}
        )


@extend_schema(tags=["Materials"])
@extend_schema_view(
    list=extend_schema(
        summary="Materiallar ro'yxati",
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, description="Fayl nomi bo'yicha qidiruv"),
            OpenApiParameter("topic_id", OpenApiTypes.UUID),
            OpenApiParameter("module_id", OpenApiTypes.UUID),
            OpenApiParameter("type", OpenApiTypes.STR, enum=MaterialType.values),
            OpenApiParameter("status", OpenApiTypes.STR, enum=MaterialStatus.values),
        ],
    ),
    retrieve=extend_schema(summary="Material tafsilotlari va ishlov holati"),
    destroy=extend_schema(
        summary="Materialni o'chirish",
        description=(
            "Yozuvni, diskdagi fayllarni va Open WebUI Knowledge Base'dagi nusxani o'chiradi."
        ),
        responses={200: DeleteResultSerializer},
    ),
)
class MaterialViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Material.objects.select_related("topic__module", "uploaded_by")
    serializer_class = MaterialSerializer
    lookup_value_regex = UUID_REGEX

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        for param, field in (
            ("topic_id", "topic_id"),
            ("module_id", "topic__module_id"),
            ("type", "type"),
            ("status", "status"),
        ):
            value = params.get(param)
            if value:
                queryset = queryset.filter(**{field: value})

        search = params.get("search")
        if search:
            queryset = queryset.filter(original_filename__icontains=search)
        return queryset

    @extend_schema(
        summary="Hujjat yuklash",
        description=(
            "Xom hujjatni (PDF, PPTX, DOCX, TXT, MD) yuklaydi, SHA-256 hisoblaydi va "
            "konvertatsiya, transliteratsiya, grounding hamda Open WebUI indekslash "
            "uchun navbatga qo'yadi."
        ),
        request={"multipart/form-data": UploadMaterialSerializer},
        responses={
            201: MaterialSerializer,
            409: DeleteResultSerializer,
            413: DeleteResultSerializer,
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload(self, request):
        form = UploadMaterialSerializer(data=request.data)
        form.is_valid(raise_exception=True)

        material = services.upload_material(
            upload=form.validated_data["file"],
            topic_id=str(form.validated_data["topic_id"].id),
            material_type=form.validated_data["type"],
            uploaded_by=request.user,
        )
        return Response(MaterialSerializer(material).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Konvertatsiya qilingan Markdown'ni ko'rish",
        description="[MANBA: ...] markerlari bilan yaratilgan Markdown kontentini qaytaradi.",
        responses={200: MaterialContentSerializer},
    )
    @action(detail=True, methods=["get"], url_path="content")
    def content(self, request, pk=None):
        return Response(services.read_material_markdown(self.get_object()))

    @extend_schema(
        summary="Pipeline'ni qayta ishga tushirish",
        request=None,
        responses={200: MaterialSerializer},
    )
    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request, pk=None):
        material = services.retry_material(self.get_object())
        return Response(MaterialSerializer(material).data)

    def destroy(self, request, *args, **kwargs):
        return Response(services.delete_material(self.get_object()))


@extend_schema(tags=["Audit Logs"])
@extend_schema_view(
    list=extend_schema(
        summary="Tizim va pipeline loglari",
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, description="Xabar bo'yicha qidiruv"),
            OpenApiParameter("module_id", OpenApiTypes.UUID),
            OpenApiParameter("material_id", OpenApiTypes.UUID),
            OpenApiParameter("level", OpenApiTypes.STR, enum=LogLevel.values),
            OpenApiParameter(
                "stage", OpenApiTypes.STR, description="conversion, indexing, kb_create, pipeline"
            ),
        ],
    )
)
class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = AuditLog.objects.select_related("module", "material")
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        for param, field in (
            ("module_id", "module_id"),
            ("material_id", "material_id"),
            ("level", "level"),
            ("stage", "stage"),
        ):
            value = params.get(param)
            if value:
                queryset = queryset.filter(**{field: value})

        search = params.get("search")
        if search:
            queryset = queryset.filter(message__icontains=search)
        return queryset
