"""Admin pages that span more than one model."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from apps.catalog.models import Material, MaterialStatus, Module, Topic

#: Tailwind classes for the small status dots in the tree.
STATUS_DOTS = {
    MaterialStatus.NEW: "bg-base-400",
    MaterialStatus.QUEUED: "bg-purple-500",
    MaterialStatus.CONVERTING: "bg-sky-500",
    MaterialStatus.MD_READY: "bg-primary-500",
    MaterialStatus.UPLOADING: "bg-blue-500",
    MaterialStatus.INDEXED: "bg-green-500",
    MaterialStatus.FAILED: "bg-red-500",
}


def content_tree_view(request: HttpRequest, model_admin=None) -> HttpResponse:
    """Module → Topic → Material on a single screen.

    The changelists answer "which materials are failing"; this answers "how is
    the course actually structured", which is otherwise three clicks deep.
    """
    from django.contrib import admin as django_admin

    search = (request.GET.get("q") or "").strip()

    materials = Material.objects.only(
        "id", "topic_id", "original_filename", "type", "status", "chunk_count"
    ).order_by("original_filename")
    if search:
        materials = materials.filter(original_filename__icontains=search)

    topics = (
        Topic.objects.order_by("order_index", "code")
        .prefetch_related(Prefetch("materials", queryset=materials))
        .annotate(
            num_materials=Count("materials", distinct=True),
            num_indexed=Count(
                "materials",
                filter=Q(materials__status=MaterialStatus.INDEXED),
                distinct=True,
            ),
            num_failed=Count(
                "materials",
                filter=Q(materials__status=MaterialStatus.FAILED),
                distinct=True,
            ),
        )
    )

    modules = list(
        Module.objects.order_by("order_index", "code").prefetch_related(
            Prefetch("topics", queryset=topics)
        )
    )

    if search:
        needle = search.lower()

        def matches(module: Module) -> bool:
            if needle in module.code.lower() or needle in module.name.lower():
                return True
            for topic in module.topics.all():
                if needle in topic.code.lower() or needle in topic.name.lower():
                    return True
                # The prefetch is already filtered by the search term, so any
                # material still attached here is a hit.
                if topic.materials.all():
                    return True
            return False

        modules = [module for module in modules if matches(module)]

    tree: list[dict[str, Any]] = []
    for module in modules:
        topic_rows = []
        for topic in module.topics.all():
            topic_rows.append(
                {
                    "topic": topic,
                    "url": reverse("admin:catalog_topic_change", args=[topic.id]),
                    "materials": [
                        {
                            "material": material,
                            "url": reverse(
                                "admin:catalog_material_change", args=[material.id]
                            ),
                            "dot": STATUS_DOTS.get(material.status, "bg-base-400"),
                        }
                        for material in topic.materials.all()
                    ],
                }
            )

        total = sum(row["topic"].num_materials for row in topic_rows)
        indexed = sum(row["topic"].num_indexed for row in topic_rows)
        tree.append(
            {
                "module": module,
                "url": reverse("admin:catalog_module_change", args=[module.id]),
                "topics": topic_rows,
                "total": total,
                "indexed": indexed,
                "failed": sum(row["topic"].num_failed for row in topic_rows),
                "percent": round(indexed / total * 100) if total else 0,
            }
        )

    context = {
        **django_admin.site.each_context(request),
        "title": "Kontent daraxti",
        "tree": tree,
        "search": search,
        "upload_url": reverse("admin:catalog_material_upload"),
        "module_add_url": reverse("admin:catalog_module_add"),
        "legend": [
            (label, STATUS_DOTS[value]) for value, label in MaterialStatus.choices
        ],
    }
    return render(request, "admin/catalog/content_tree.html", context)
