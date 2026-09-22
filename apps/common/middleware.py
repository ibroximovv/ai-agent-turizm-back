"""Request logging, mirroring the NestJS `LoggingInterceptor`."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("apps.http")

# Static assets and the admin's own chrome would drown out the API traffic.
_IGNORED_PREFIXES = ("/static/", "/media/", "/favicon.ico")


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(_IGNORED_PREFIXES):
            return self.get_response(request)

        started_at = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = (time.monotonic() - started_at) * 1000

        log = logger.warning if response.status_code >= 400 else logger.info
        log("%s %s %s — %.0fms", request.method, request.get_full_path(),
            response.status_code, elapsed_ms)
        return response
