"""URL routing.

The API keeps the paths the NestJS service exposed (``/api/modules``,
``/api/materials/upload``, …). Every API route also accepts a trailing slash,
so `/api/modules` and `/api/modules/` both resolve without a redirect — a 301
would turn a client's POST into a GET.

The admin panel lives at ``/admin/``.
"""

from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import SimpleRouter

from apps.accounts.api.views import LoginView, LogoutView, MeView, RefreshView, UserViewSet
from apps.catalog.api.views import (
    AuditLogViewSet,
    MaterialViewSet,
    ModuleViewSet,
    TopicViewSet,
)
from apps.common.views import HealthView
from apps.owui.views import OwuiKnowledgeBasesView, OwuiStatusView

# A SimpleRouter (not DefaultRouter) so that nothing claims `/api/` itself —
# that path is the health check. The constructor coerces `trailing_slash` to a
# plain "/", so the optional-slash pattern is assigned afterwards; the routes
# are only rendered when `.urls` is first read.
router = SimpleRouter()
router.trailing_slash = "/?"
router.register("modules", ModuleViewSet, basename="module")
router.register("topics", TopicViewSet, basename="topic")
router.register("materials", MaterialViewSet, basename="material")
router.register("audit-logs", AuditLogViewSet, basename="auditlog")
router.register("auth/users", UserViewSet, basename="user")


def flexible(route: str, view, name: str):
    """A route that matches with and without a trailing slash."""
    return re_path(rf"^{route}/?$", view, name=name)


api_patterns = [
    re_path(r"^$", HealthView.as_view(), name="health"),
    flexible("auth/login", LoginView.as_view(), name="auth-login"),
    flexible("auth/refresh", RefreshView.as_view(), name="auth-refresh"),
    flexible("auth/logout", LogoutView.as_view(), name="auth-logout"),
    flexible("auth/me", MeView.as_view(), name="auth-me"),
    flexible("owui/status", OwuiStatusView.as_view(), name="owui-status"),
    flexible("owui/knowledge-bases", OwuiKnowledgeBasesView.as_view(), name="owui-kbs"),
    flexible("schema", SpectacularAPIView.as_view(), name="schema"),
    flexible("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("", include(router.urls)),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api_patterns)),
    # DRF's browsable-API login/logout, handy while developing.
    path("api-auth/", include("rest_framework.urls")),
]
