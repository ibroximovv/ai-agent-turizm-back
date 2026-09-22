from __future__ import annotations

import time

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

SERVICE_NAME = "ai-agent-turizm-back"
_STARTED_AT = time.monotonic()


@extend_schema(tags=["System"])
class HealthView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(summary="Health check & servis holati", responses={200: dict})
    def get(self, request):
        return Response(
            {
                "status": "ok",
                "service": SERVICE_NAME,
                "environment": settings.APP_ENV,
                "uptimeSeconds": round(time.monotonic() - _STARTED_AT),
                "timestamp": timezone.now().isoformat(),
            }
        )
