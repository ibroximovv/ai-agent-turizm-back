"""Uniform error payloads for every API failure.

Port of the NestJS `AllExceptionsFilter`: driver-level failures (unique / FK
violations) are translated instead of surfacing as opaque 500s, and every
response carries the same shape::

    {"statusCode": 409, "message": "...", "error": "Conflict",
     "path": "/api/modules", "timestamp": "2026-01-01T00:00:00Z"}
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError, IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class PayloadTooLarge(APIException):
    """413 — the upload exceeds `MAX_UPLOAD_MB`. DRF has no built-in for this."""

    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = "Fayl hajmi ruxsat etilgan chegaradan katta."
    default_code = "payload_too_large"

# PostgreSQL error codes we can translate into meaningful HTTP responses.
PG_UNIQUE_VIOLATION = "23505"
PG_FOREIGN_KEY_VIOLATION = "23503"
PG_NOT_NULL_VIOLATION = "23502"

_DB_ERROR_MAP = {
    PG_UNIQUE_VIOLATION: (
        status.HTTP_409_CONFLICT,
        "Bunday qiymatlarga ega yozuv allaqachon mavjud",
        "Conflict",
    ),
    PG_FOREIGN_KEY_VIOLATION: (
        status.HTTP_400_BAD_REQUEST,
        "Bog'langan yozuv topilmadi",
        "Bad Request",
    ),
    PG_NOT_NULL_VIOLATION: (
        status.HTTP_400_BAD_REQUEST,
        "Majburiy maydon to'ldirilmagan",
        "Bad Request",
    ),
}


def _sqlstate(exc: Exception) -> str | None:
    """Pull the SQLSTATE out of a wrapped psycopg error."""
    cause = exc.__cause__ or exc
    return getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)


def _flatten_detail(detail: Any, prefix: str = "") -> Any:
    """Turn a nested DRF validation detail into a flat list of messages."""
    if isinstance(detail, dict):
        messages: list[str] = []
        for field, value in detail.items():
            label = f"{prefix}{field}"
            flattened = _flatten_detail(value, prefix=f"{label}.")
            if isinstance(flattened, list):
                messages.extend(
                    msg if str(msg).startswith(label) else f"{label}: {msg}" for msg in flattened
                )
            else:
                messages.append(f"{label}: {flattened}")
        return messages
    if isinstance(detail, list):
        messages = []
        for item in detail:
            flattened = _flatten_detail(item, prefix=prefix)
            messages.extend(flattened if isinstance(flattened, list) else [flattened])
        return messages
    return str(detail)


def _error_label(status_code: int) -> str:
    try:
        from http import HTTPStatus

        return HTTPStatus(status_code).phrase
    except ValueError:  # pragma: no cover - non-standard status
        return "Error"


def _build_body(request, status_code: int, message: Any, error: str | None) -> dict:
    return {
        "statusCode": status_code,
        "message": message,
        "error": error or _error_label(status_code),
        "path": request.get_full_path() if request is not None else "",
        "timestamp": timezone.now().isoformat(),
    }


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    request = context.get("request")

    # 1. Anything DRF already understands (validation, 404, throttling, auth).
    response = drf_exception_handler(exc, context)
    if response is not None:
        detail = response.data
        if isinstance(detail, dict) and set(detail) == {"detail"}:
            message: Any = str(detail["detail"])
        else:
            message = _flatten_detail(detail)
        response.data = _build_body(request, response.status_code, message, None)
        return response

    # 2. Database failures that would otherwise be a bare 500.
    if isinstance(exc, IntegrityError):
        code = _sqlstate(exc)
        status_code, message, error = _DB_ERROR_MAP.get(
            code or "",
            (status.HTTP_409_CONFLICT, "Ma'lumotlar bazasi cheklovi buzildi", "Conflict"),
        )
        logger.warning("IntegrityError (%s): %s", code, exc)
        return Response(_build_body(request, status_code, message, error), status=status_code)

    if isinstance(exc, DatabaseError):
        logger.exception("Database query failed")
        return Response(
            _build_body(
                request,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Ma'lumotlar bazasi so'rovi bajarilmadi",
                "Internal Server Error",
            ),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # 3. Everything else keeps Django's own 500 handling (and its traceback in
    #    DEBUG), so returning None here is deliberate.
    return None
