from __future__ import annotations

from dataclasses import asdict

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.owui.client import get_owui_client


class OwuiKnowledgeBaseSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    files = serializers.ListField(child=serializers.DictField(), required=False)


@extend_schema(tags=["Open WebUI"])
class OwuiStatusView(APIView):
    @extend_schema(
        summary="Open WebUI integratsiyasi holati",
        description="Sozlangan Open WebUI nusxasiga ulanish va autentifikatsiyani tekshiradi.",
        responses={200: dict},
        examples=[
            OpenApiExample(
                "Ulangan",
                value={
                    "connected": True,
                    "baseUrl": "http://localhost:8080",
                    "hasApiKey": True,
                    "knowledgeBasesCount": 4,
                    "message": "Open WebUI ga muvaffaqiyatli ulandi (4 ta Knowledge Base topildi)",
                },
            )
        ],
    )
    def get(self, request):
        return Response(get_owui_client().check_connection().as_dict())


@extend_schema(tags=["Open WebUI"])
class OwuiKnowledgeBasesView(APIView):
    @extend_schema(
        summary="Open WebUI'dagi Knowledge Base'lar ro'yxati",
        responses={200: OwuiKnowledgeBaseSerializer(many=True)},
    )
    def get(self, request):
        knowledge_bases = get_owui_client().list_knowledge_bases()
        return Response([asdict(kb) for kb in knowledge_bases])
