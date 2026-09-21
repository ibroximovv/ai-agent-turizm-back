"""Branded admin site and the data behind its dashboard.

The panel is themed with django-unfold; the sidebar, colours and callbacks are
configured in ``UNFOLD`` (see :mod:`config.settings`).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.contrib.admin.apps import AdminConfig
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from unfold.sites import UnfoldAdminSite

#: Unfold label variants per pipeline status.
STATUS_VARIANTS = {
    "new": "",
    "queued": "info",
    "converting": "info",
    "md_ready": "primary",
    "uploading": "info",
    "indexed": "success",
    "failed": "danger",
}

#: Tailwind background classes for the dashboard's own bars.
STATUS_BAR_CLASSES = {
    "new": "bg-base-400",
    "queued": "bg-purple-500",
    "converting": "bg-sky-500",
    "md_ready": "bg-primary-500",
    "uploading": "bg-blue-500",
    "indexed": "bg-green-500",
    "failed": "bg-red-500",
}

CHART_DAYS = 14


class TurizmAdminSite(UnfoldAdminSite):
    site_header = "AI Agent Turizm"
    site_title = "AI Agent Turizm"
    index_title = "Boshqaruv paneli"
    # A distinct name so the template can extend Unfold's `admin/index.html`
    # without extending itself.
    index_template = "admin/dashboard.html"

    def get_urls(self):
        from django.urls import path

        from apps.catalog.admin_views import content_tree_view

        # The tree spans three models, so it belongs to the site rather than to
        # any single ModelAdmin.
        return [
            path("catalog/tree/", self.admin_view(content_tree_view), name="catalog_tree"),
            *super().get_urls(),
        ]


class TurizmAdminConfig(AdminConfig):
    default_site = "config.admin.TurizmAdminSite"


def environment_callback(request: HttpRequest) -> list[str]:
    """Small label next to the user menu, so staging is never mistaken for prod."""
    from django.conf import settings

    env = settings.APP_ENV
    variant = {"production": "danger", "staging": "warning"}.get(env, "info")
    return [env, variant]


def _changelist(model_name: str, **params: str) -> str:
    url = reverse(f"admin:catalog_{model_name}_changelist")
    if params:
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return f"{url}?{query}"
    return url


def _status_breakdown(counts: dict[str, int], total: int) -> list[dict[str, Any]]:
    from apps.catalog.models import MaterialStatus

    rows = []
    for value, title in MaterialStatus.choices:
        count = counts.get(value, 0)
        if not count:
            continue
        rows.append(
            {
                "value": value,
                "title": title,
                "count": count,
                "percent": round(count / total * 100) if total else 0,
                "bar_class": STATUS_BAR_CLASSES.get(value, "bg-base-400"),
                "variant": STATUS_VARIANTS.get(value, ""),
                "url": _changelist("material", status__exact=value),
            }
        )
    return rows


def _throughput_chart() -> str:
    """Materials created per day over the last two weeks, as Chart.js data."""
    from apps.catalog.models import Material

    today = timezone.localdate()
    start = today - timedelta(days=CHART_DAYS - 1)

    rows = (
        Material.objects.filter(created_at__date__gte=start)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Count("id"))
    )
    per_day = {row["day"]: row["total"] for row in rows}

    days = [start + timedelta(days=offset) for offset in range(CHART_DAYS)]
    return json.dumps(
        {
            "labels": [day.strftime("%d.%m") for day in days],
            "datasets": [
                {
                    "label": "Yuklangan materiallar",
                    "data": [per_day.get(day, 0) for day in days],
                    "backgroundColor": "var(--color-primary-500)",
                    "borderRadius": 4,
                    "borderSkipped": False,
                }
            ],
        }
    )


def _module_rows(limit: int = 8) -> list[dict[str, Any]]:
    """Per-module indexing progress for the dashboard table."""
    from apps.catalog.models import Material, MaterialStatus, Module

    modules = list(Module.objects.order_by("order_index", "code")[:limit])
    if not modules:
        return []

    counts: dict[str, dict[str, int]] = {}
    rows = (
        Material.objects.filter(topic__module__in=modules)
        .values("topic__module_id", "status")
        .annotate(total=Count("id"))
    )
    for row in rows:
        entry = counts.setdefault(str(row["topic__module_id"]), {})
        entry[row["status"]] = row["total"]

    result = []
    for module in modules:
        by_status = counts.get(str(module.id), {})
        total = sum(by_status.values())
        indexed = by_status.get(MaterialStatus.INDEXED, 0)
        failed = by_status.get(MaterialStatus.FAILED, 0)
        result.append(
            {
                "module": module,
                "total": total,
                "indexed": indexed,
                "failed": failed,
                "percent": round(indexed / total * 100) if total else 0,
                "url": reverse("admin:catalog_module_change", args=[module.id]),
                "materials_url": _changelist(
                    "material", **{"topic__module__id__exact": str(module.id)}
                ),
            }
        )
    return result


def dashboard_callback(request: HttpRequest, context: dict[str, Any]) -> dict[str, Any]:
    """Everything the dashboard template renders. Referenced by UNFOLD."""
    from apps.catalog.models import AuditLog, LogLevel, Material, MaterialStatus, Module, Topic

    by_status = dict(
        Material.objects.values_list("status").annotate(total=Count("id"))
    )
    total_materials = sum(by_status.values())
    in_progress = sum(
        by_status.get(value, 0)
        for value in (
            MaterialStatus.QUEUED,
            MaterialStatus.CONVERTING,
            MaterialStatus.UPLOADING,
        )
    )

    context.update(
        {
            "kpis": [
                {
                    "title": "Modullar",
                    "value": Module.objects.count(),
                    "footer": f"{Module.objects.filter(is_active=True).count()} ta faol",
                    "icon": "folder_special",
                    "url": _changelist("module"),
                },
                {
                    "title": "Mavzular",
                    "value": Topic.objects.count(),
                    "footer": "Modullar ichidagi bo'limlar",
                    "icon": "topic",
                    "url": _changelist("topic"),
                },
                {
                    "title": "Materiallar",
                    "value": total_materials,
                    "footer": f"{in_progress} tasi ishlanmoqda",
                    "icon": "description",
                    "url": _changelist("material"),
                },
                {
                    "title": "Indekslangan",
                    "value": by_status.get(MaterialStatus.INDEXED, 0),
                    "footer": "Open WebUI bilimlar bazasida",
                    "icon": "cloud_done",
                    "url": _changelist("material", status__exact=MaterialStatus.INDEXED),
                },
            ],
            "status_breakdown": _status_breakdown(by_status, total_materials),
            "failed_count": by_status.get(MaterialStatus.FAILED, 0),
            "in_progress_count": in_progress,
            "throughput_chart": _throughput_chart(),
            "module_rows": _module_rows(),
            "recent_errors": list(
                AuditLog.objects.filter(level=LogLevel.ERROR)
                .select_related("material", "module")
                .order_by("-created_at")[:6]
            ),
            "upload_url": reverse("admin:catalog_material_upload"),
            "tree_url": reverse("admin:catalog_tree"),
        }
    )
    return context
