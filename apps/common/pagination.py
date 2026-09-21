"""Pagination that keeps the `{items, total, page, limit, totalPages}` payload."""

from __future__ import annotations

import math

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class ItemsPagination(PageNumberPagination):
    page_query_param = "page"
    page_size_query_param = "limit"
    page_size = 20
    max_page_size = 100

    def get_paginated_response(self, data) -> Response:
        limit = self.get_page_size(self.request) or self.page_size
        total = self.page.paginator.count
        return Response(
            {
                "items": data,
                "total": total,
                "page": self.page.number,
                "limit": limit,
                # Django reports 1 page for an empty queryset; an empty list has
                # zero pages as far as a client paging through it is concerned.
                "totalPages": math.ceil(total / limit) if limit else 0,
            }
        )

    def get_paginated_response_schema(self, schema) -> dict:
        return {
            "type": "object",
            "required": ["items", "total", "page", "limit", "totalPages"],
            "properties": {
                "items": schema,
                "total": {"type": "integer", "example": 123},
                "page": {"type": "integer", "example": 1},
                "limit": {"type": "integer", "example": 20},
                "totalPages": {"type": "integer", "example": 7},
            },
        }
