"""Django settings for the AI Agent Turizm backend.

Every value is read from the environment (`.env`) exactly once, here, and
exposed to feature code either as a Django setting or through the typed
objects in :mod:`config.app_config`.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import environ

from config.app_config import build_owui_config, build_uploads_config

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

APP_ENV = env.str("APP_ENV", default="development")
DEBUG = env.bool("DJANGO_DEBUG", default=APP_ENV == "development")

# A generated fallback keeps `manage.py` usable in development; production must
# supply its own key so that sessions survive a restart.
SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError(
            "DJANGO_SECRET_KEY majburiy (DEBUG=False). "
            "`python -c \"import secrets;print(secrets.token_urlsafe(50))\"` bilan yarating."
        )
    SECRET_KEY = "django-insecure-development-only-key-do-not-use-in-production"

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# Port used by `manage.py runserver` when none is given on the command line.
PORT = env.int("PORT", default=8000)

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------

INSTALLED_APPS = [
    # Unfold must precede django.contrib.admin — it overrides the admin
    # templates, and the first app in the list wins template resolution.
    # `BasicAppConfig`, not plain "unfold": the default config's ready() hook
    # overwrites `admin.site` with its own AdminSite, which would silently
    # discard TurizmAdminSite (and with it the dashboard and the tree view).
    "unfold.apps.BasicAppConfig",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    # Branded admin site with the pipeline dashboard (see config/admin.py).
    "config.admin.TurizmAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "corsheaders",
    # Local
    "apps.common",
    "apps.accounts",
    "apps.catalog",
    "apps.owui",
    "apps.pipeline",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.RequestLoggingMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env.str("POSTGRES_HOST", default="localhost"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "USER": env.str("POSTGRES_USER", default="postgres"),
        "PASSWORD": env.str("POSTGRES_PASSWORD", default="postgres"),
        "NAME": env.str("POSTGRES_DB", default="turizm_db"),
        # Reusing connections matters because the pipeline runs in worker
        # threads that would otherwise open a socket per material.
        "CONN_MAX_AGE": env.int("POSTGRES_CONN_MAX_AGE", default=60),
        "CONN_HEALTH_CHECKS": True,
    }
}

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/admin/"
LOGOUT_REDIRECT_URL = "/admin/login/"

# --------------------------------------------------------------------------
# REST framework
# --------------------------------------------------------------------------

# Set to False to expose the API without a token (development convenience only).
API_REQUIRE_AUTH = env.bool("API_REQUIRE_AUTH", default=True)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Lets the browsable API and admin-embedded views reuse the admin login.
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "apps.common.permissions.RoleBasedPermission"
        if API_REQUIRE_AUTH
        else "rest_framework.permissions.AllowAny"
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.ItemsPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=60)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=14)),
    "ROTATE_REFRESH_TOKENS": True,
    "UPDATE_LAST_LOGIN": True,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AI Agent Turizm Backend API",
    "DESCRIPTION": (
        "Educational content management and grounding pipeline for Open WebUI RAG AI agents"
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    "TAGS": [
        {"name": "System", "description": "Health and system diagnostics"},
        {"name": "Auth", "description": "Login, token refresh and current user"},
        {"name": "Modules", "description": "Educational modules management and KB creation"},
        {"name": "Topics", "description": "Topics within educational modules"},
        {"name": "Materials", "description": "Document upload and grounding pipeline"},
        {"name": "Audit Logs", "description": "Activity history and pipeline execution logs"},
        {"name": "Open WebUI", "description": "Open WebUI integration and Knowledge Bases"},
    ],
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True},
}

CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=True)
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# --------------------------------------------------------------------------
# Admin panel theme (django-unfold)
# --------------------------------------------------------------------------


def _sidebar_badge_failed(request) -> str | None:
    """Red counter next to "Materiallar" when something needs attention."""
    from apps.catalog.models import Material, MaterialStatus

    count = Material.objects.filter(status=MaterialStatus.FAILED).count()
    return str(count) if count else None


UNFOLD = {
    "SITE_TITLE": "AI Agent Turizm",
    "SITE_HEADER": "AI Agent Turizm",
    "SITE_SUBHEADER": "Bilim bazasi boshqaruvi",
    "SITE_SYMBOL": "travel_explore",
    "SITE_URL": "/api/docs",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "ENVIRONMENT": "config.admin.environment_callback",
    "DASHBOARD_CALLBACK": "config.admin.dashboard_callback",
    "LOGIN": {"image": None},
    "COLORS": {
        # Teal — reads as "travel / water" and stays legible on both themes.
        "primary": {
            "50": "oklch(98.4% 0.014 180.72)",
            "100": "oklch(95.3% 0.051 180.801)",
            "200": "oklch(91% 0.096 180.426)",
            "300": "oklch(85.5% 0.138 181.071)",
            "400": "oklch(77.7% 0.152 181.912)",
            "500": "oklch(70.4% 0.14 182.503)",
            "600": "oklch(60% 0.118 184.704)",
            "700": "oklch(51.1% 0.096 186.391)",
            "800": "oklch(43.7% 0.078 188.216)",
            "900": "oklch(38.6% 0.063 188.416)",
            "950": "oklch(27.7% 0.046 192.524)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Boshqaruv",
                "separator": False,
                "items": [
                    {
                        "title": "Dashboard",
                        "icon": "dashboard",
                        "link": "/admin/",
                    },
                    {
                        "title": "Kontent daraxti",
                        "icon": "account_tree",
                        "link": "/admin/catalog/tree/",
                    },
                    {
                        "title": "Hujjat yuklash",
                        "icon": "upload_file",
                        "link": "/admin/catalog/material/upload/",
                    },
                ],
            },
            {
                "title": "O'quv kontenti",
                "separator": True,
                "items": [
                    {
                        "title": "Modullar",
                        "icon": "folder_special",
                        "link": "/admin/catalog/module/",
                    },
                    {
                        "title": "Mavzular",
                        "icon": "topic",
                        "link": "/admin/catalog/topic/",
                    },
                    {
                        "title": "Materiallar",
                        "icon": "description",
                        "link": "/admin/catalog/material/",
                        "badge": "config.settings._sidebar_badge_failed",
                    },
                ],
            },
            {
                "title": "Tizim",
                "separator": True,
                "items": [
                    {
                        "title": "Audit yozuvlari",
                        "icon": "receipt_long",
                        "link": "/admin/catalog/auditlog/",
                    },
                    {
                        "title": "Foydalanuvchilar",
                        "icon": "group",
                        "link": "/admin/accounts/user/",
                    },
                    {
                        "title": "API hujjatlari",
                        "icon": "api",
                        "link": "/api/docs",
                    },
                ],
            },
        ],
    },
}

# --------------------------------------------------------------------------
# Storage & uploads
# --------------------------------------------------------------------------

MAX_UPLOAD_MB = env.int("MAX_UPLOAD_MB", default=200)
UPLOADS = build_uploads_config(
    uploads_dir=env.str("UPLOADS_DIR", default="") or None,
    max_upload_mb=MAX_UPLOAD_MB,
    base_dir=BASE_DIR,
)

# Anything larger than this is spooled to a temporary file instead of being
# held in memory — a 200 MB PDF must not cost 200 MB of heap per request.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
# Applies to the non-file part of a multipart body only.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = UPLOADS.root_dir

# --------------------------------------------------------------------------
# Open WebUI integration
# --------------------------------------------------------------------------

OWUI = build_owui_config(
    url=env.str("OWUI_URL", default="http://localhost:8080"),
    api_key=env.str("OWUI_API_KEY", default=""),
    timeout_ms=env.int("OWUI_TIMEOUT_MS", default=30000),
)

# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

# How many materials are converted at the same time. Parsing keeps whole
# documents in memory, so an unbounded fan-out would exhaust the process.
PIPELINE_CONCURRENCY = env.int("PIPELINE_CONCURRENCY", default=2)
# Run the pipeline inline instead of on a worker thread (used by the tests).
PIPELINE_RUN_SYNC = env.bool("PIPELINE_RUN_SYNC", default=False)

# --------------------------------------------------------------------------
# I18N / misc
# --------------------------------------------------------------------------

LANGUAGE_CODE = env.str("LANGUAGE_CODE", default="uz")
TIME_ZONE = env.str("TIME_ZONE", default="Asia/Tashkent")
USE_I18N = True
USE_TZ = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[{asctime}] {levelname:<7} {name} — {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.db.backends": {
            "level": "DEBUG" if env.bool("POSTGRES_LOGGING", default=False) else "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        "apps": {"level": env.str("LOG_LEVEL", default="INFO"), "propagate": True},
    },
}

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_HTTPONLY = True
    # The admin's JS reads this one to send X-CSRFToken with the uploader's XHR.
    CSRF_COOKIE_HTTPONLY = False
    X_FRAME_OPTIONS = "DENY"
    # nginx terminates TLS; without this header Django sees plain "http" and
    # the admin's CSRF origin check rejects every form post.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # Cookies go over HTTPS only. Set these to false in .env for an internal
    # deployment that genuinely has no TLS — otherwise nobody can log in.
    SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
    CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"

    # nginx + certbot already redirect http → https, so this stays off by
    # default; turning it on as well would only add a second hop.
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)

    # HSTS is opt-in on purpose: once a browser has seen the header it refuses
    # plain HTTP for that long, which is painful to undo if the certificate
    # lapses. Enable it (e.g. 2592000 = 30 days) after HTTPS is proven stable.
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
    if SECURE_HSTS_SECONDS:
        SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
            "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False
        )
        SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
