# Django + DRF Architecture Rules

This document defines architecture standards, coding conventions, and directory
organization for the backend built on **Python 3.12 + Django 5 + Django REST
Framework + PostgreSQL**. All app names, module names, class names, database
identifiers, and endpoints MUST be written in English. User-facing strings in
the admin panel are written in Uzbek.

---

## 1. Runtime & Tooling
- **Runtime**: Python 3.12, dependencies managed with `uv` (`uv sync`,
  `uv lock`). `requirements.txt` / `requirements-dev.txt` are exported from the
  lockfile for pip-only environments.
- **Server**: `manage.py runserver` in development, `gunicorn config.wsgi` in
  production (1 worker, multiple threads — see §5).
- **Code standards**: `ruff check` for linting and `ruff format` for
  formatting. `pytest` (with `pytest-django`) for tests.

---

## 2. Directory Structure

```text
config/                         # Django project
├── settings.py                 # The ONLY place the environment is read
├── app_config.py               # Typed UploadsConfig / OwuiConfig dataclasses
├── admin.py                    # Branded AdminSite + dashboard context
├── urls.py                     # /api routes (slash-optional) + /admin
├── wsgi.py / asgi.py
apps/
├── common/                     # Cross-cutting concerns, no domain models
│   ├── constants.py            # CODE_PATTERN, ALLOWED_UPLOAD_EXTENSIONS
│   ├── filename.py             # Multipart filename decoding, path-safe names
│   ├── pagination.py           # {items,total,page,limit,totalPages}
│   ├── exceptions.py           # Uniform error payload + PG error mapping
│   ├── permissions.py          # RoleBasedPermission, IsAdminRole
│   ├── middleware.py           # Request logging
│   └── views.py                # Health check
├── accounts/                   # Authentication
│   ├── models.py               # Custom User on the `users` table
│   ├── admin.py
│   └── api/{serializers,views}.py
├── catalog/                    # Content hierarchy
│   ├── models.py               # Module, Topic, Material, AuditLog
│   ├── services.py             # Domain operations (API + admin share these)
│   ├── forms.py                # Admin upload form
│   ├── admin.py
│   ├── api/{serializers,views}.py
│   └── management/commands/
├── owui/                       # Open WebUI HTTP client + diagnostics endpoints
└── pipeline/                   # Document ingestion
    ├── services/               # parser, cleaner, translit, chunker (pure Python)
    ├── service.py              # End-to-end coordinator
    └── runner.py               # Thread pool + in-flight registry
templates/admin/                # Dashboard, upload form, Markdown preview
tests/                          # pipeline/, api/, common/
```

**Rule**: `apps/pipeline/services/*` must stay free of Django imports. They are
pure functions over text and files, which is what makes them directly testable.

---

## 3. Layering
- **Views / admin** — parse input, delegate, render. No business logic.
- **Services** (`apps/catalog/services.py`, `apps/pipeline/service.py`) — the
  single implementation of each operation, shared by the REST API and the admin
  panel so both behave identically.
- **Models** — schema, constraints, and small derived properties only.

---

## 4. Serializers and Validation
- Every write endpoint uses a dedicated `*WriteSerializer`; reads use the
  richer display serializer. Never reuse one serializer for both when the
  fields differ.
- Cross-field uniqueness (module + topic code) is validated in the serializer
  AND enforced by a database constraint. The `api_exception_handler` converts a
  race-condition `IntegrityError` into `409 Conflict`.
- Codes that become filesystem paths are validated against `CODE_PATTERN`.

---

## 5. Background Work
- Conversions run on `apps/pipeline/runner.py`'s bounded `ThreadPoolExecutor`
  (`PIPELINE_CONCURRENCY`). Always submit through `runner.submit()`.
- The in-flight registry prevents upload / retry / batch from processing the
  same material twice and overwriting each other's status and OWUI file ids.
- Worker threads call `close_old_connections()` around each task.
- Because the queue lives inside the process, production runs **one** gunicorn
  worker with several threads. Scaling horizontally means moving the pipeline
  to Celery/RQ first.

---

## 6. Error Handling & Auditing
- Domain errors raise DRF exceptions (`NotFound`, `ValidationError`,
  `Conflict`, `PayloadTooLarge`, `BadGateway`).
- Every response failure is normalised to
  `{statusCode, message, error, path, timestamp}`.
- Pipeline failures set `materials.status = 'failed'`, populate
  `materials.error_message`, and write an `audit_logs` row with `level='error'`.
- Audit logging is best effort — it must never be the reason a run fails.

---

## 7. Storage Layout
- Raw uploaded files: `uploads/raw/{module_code}/{topic_code}/{hash12}__{filename}`.
- Converted markdown: `uploads/ready/{module_code}/{topic_code}__{type}__{slug}-{fingerprint}.md`.
- File size limit: `MAX_UPLOAD_MB` (default 200 MB), rejected with HTTP 413.
- SHA-256 is computed by streaming the upload, before the record is created.
- Every path segment derived from user input passes through
  `sanitize_path_segment()` so nothing can escape the uploads tree.
