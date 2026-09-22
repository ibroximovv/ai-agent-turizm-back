# CLAUDE.md — AI Agent Turizm Backend Guide

This file provides guidelines, project architecture, commands, and coding
standards for Claude Code when working in this repository.

---

## 1. Project Overview & Mission

This project is the **Backend API, Admin Panel and Ingestion Pipeline** for the
**AI Agent Turizm** educational system.

- **Stack**: **Python 3.12** + **Django 5** + **Django REST Framework** +
  **PostgreSQL** + **Django Admin (django-unfold)** + **SimpleJWT** +
  **drf-spectacular** + **pytest** + **Ruff**, managed with **uv**.
- **Mission**: Manages educational content hierarchy (**Modules** ➔ **Topics**
  ➔ **Materials**) and converts raw documents (PDF, PPTX, DOCX, TXT, MD) into
  grounded Markdown knowledge bases synced with **Open WebUI** RAG agents.
- The admin panel is the project's front end — there is no separate frontend
  application.

### Core Domain Features

1. **Source Grounding (`[MANBA: ...]`)**
   - Open WebUI vector chunking loses source context. The pipeline injects
     repeated source grounding markers every **~600 characters**:
     ```markdown
     [MANBA: Constitution.pdf | page 14 | topic-01 | literature]
     ```
   - Every converted Markdown document begins with standard YAML frontmatter
     (`module_id`, `topic_id`, `source`, `script`, `chunks`, …).
2. **Uzbek Transliteration (`uz-cyrl` → `uz-latn`)**
   - Queries in Latin script fail to match Cyrillic documents in RAG.
   - The pipeline auto-detects script (`detect_script`); if Uzbek Cyrillic, it
     transliterates to Latin (`to_latin`).
   - Russian texts (`ru`) are preserved as-is without transliteration.
   - Corrupted PDF font encodings (`final -ии` → `-ий`) and all-caps digraphs
     (`TO‘RTINChI` → `TO‘RTINCHI`) are repaired automatically.
3. **Open WebUI Integration — the admin panel is the source of truth**
   - Pure HTTP REST integration (`OWUI_URL` + Bearer `OWUI_API_KEY`) via httpx.
   - Every module owns one Knowledge Base (`modules.owui_kb_id`) and one agent
     (`modules.owui_model_id`, a workspace model preset reading only that KB).
     One master agent (`OWUI_MASTER_MODEL_ID`) reads every active module's KB;
     its knowledge list is rebuilt from the database on every sync.
   - `apps/owui/sync.py` owns this wiring. Agents are only *created* from
     `apps/owui/prompts/*.md`; an adopted/existing agent keeps its prompt and
     only has its knowledge list, activity and sharing rewritten.
   - Uploads use `process_in_background=false`: linking a file whose
     background extraction has not finished fails with "empty content".
   - Deletions clean Open WebUI up through `apps/catalog/signals.py` (on
     commit), so cascades and admin inlines are covered too. Tests that assert
     on the cleanup need `django_capture_on_commit_callbacks(execute=True)`.

---

## 2. Common Execution Commands

```bash
# Install / sync dependencies
uv sync

# Development server (port from .env)
python manage.py runserver 3005

# Database
python manage.py migrate
python manage.py makemigrations
python manage.py createsuperuser

# Adopt a TypeORM-era database (enums → varchar, legacy users table)
python manage.py adopt_legacy_schema --apply --drop-empty-users
python manage.py migrate --fake-initial

# Quality gates
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
ruff check .
ruff format .

# OpenAPI schema
python manage.py spectacular --file schema.yml
```

---

## 3. Architecture & Directory Organization

```text
config/
├── settings.py             # Single place where the environment is read
├── app_config.py           # Typed UploadsConfig / OwuiConfig dataclasses
├── admin.py                # Branded admin site + dashboard context
├── urls.py                 # /api routes (slash-optional) + /admin
└── wsgi.py, asgi.py
apps/
├── common/                 # Cross-cutting concerns
│   ├── constants.py        # CODE_PATTERN, ALLOWED_UPLOAD_EXTENSIONS
│   ├── filename.py         # multipart filename decoding & path-safe names
│   ├── pagination.py       # {items,total,page,limit,totalPages}
│   ├── exceptions.py       # Uniform error payload + PG error mapping
│   ├── permissions.py      # RoleBasedPermission, IsAdminRole
│   ├── middleware.py       # Request logging
│   └── views.py            # Health check
├── accounts/               # Custom User (email login, `users` table)
│   ├── models.py           # password mapped onto the `password_hash` column
│   ├── admin.py
│   └── api/                # LoginView, RefreshView, MeView, UserViewSet
├── catalog/                # Content hierarchy
│   ├── models.py           # Module, Topic, Material, AuditLog
│   ├── services.py         # upload / retry / delete / KB sync / stats
│   ├── forms.py            # Admin upload form
│   ├── admin.py            # The operator-facing panel (unfold.admin)
│   ├── admin_views.py      # Content tree — spans all three models
│   ├── api/                # serializers.py, views.py
│   └── management/commands/adopt_legacy_schema.py
├── owui/                   # Open WebUI REST client + diagnostics endpoints
│   ├── sync.py             # module KB + module agent + master agent wiring
│   └── prompts/            # module_agent.md / master_agent.md templates
└── pipeline/
    ├── services/parser.py    # PDF (pypdf), PPTX (python-pptx), DOCX (mammoth), TXT, MD
    ├── services/cleaner.py   # Typography, line unwrap, font repair (uses `regex`)
    ├── services/translit.py  # Script detection & Uzbek Cyrillic → Latin
    ├── services/chunker.py   # Grounding marker injection (~600 chars) & frontmatter
    ├── service.py            # End-to-end pipeline coordinator
    ├── runner.py             # Thread pool + in-flight registry
    └── recovery.py           # Re-queues materials a restart interrupted
templates/admin/            # dashboard.html, catalog/{content_tree,material_upload,
                            #   material_markdown,material_list_before}.html
tests/                      # pipeline/, api/, admin/, common/
```

---

## 4. PostgreSQL Database Conventions

- All table names, columns and constraints are **English** `snake_case`. They
  are inherited from the previous TypeORM schema — do not rename them.
- Primary keys are **UUIDv4** (`uuid.uuid4` default on the model).
- Most models inherit `created_at` / `updated_at` (`timestamptz`).

### Hierarchy & Cascade Deletes

```
Module (1) ───< (N) Topic (1) ───< (N) Material (1) ───< (N) AuditLog
   │                                                         │
   └─────────────────────────────────────────────────────────┘
```

- Deleting a `Module` cascades to its `Topics`, `Materials`, and `AuditLogs`.
- Deleting a `Topic` cascades to its `Materials` and `AuditLogs`.
- Constraints:
  - `modules`: `UNIQUE(code)` (e.g. `module-01`).
  - `topics`: `UniqueConstraint(module, code)` named `uq_topics_module_code`.
  - `materials`: `file_hash` indexed for deduplication — uploading a
    byte-identical file into the same topic is rejected with `409 Conflict`.
- `modules.code` and `topics.code` must match `CODE_PATTERN`
  (`^[A-Za-z0-9][A-Za-z0-9._-]*$`). They are used as directory names under
  `UPLOADS_DIR`, so anything else would allow a path escape.

### Choice Types (`TextChoices`, stored as varchar)

- `MaterialType`: `presentation`, `questions`, `literature`
- `MaterialStatus`: `new`, `queued`, `converting`, `md_ready`, `uploading`,
  `indexed`, `failed`
- `LogLevel`: `info`, `warn`, `error`
- `Role`: `admin`, `editor`, `viewer`

> The TypeORM schema used native PostgreSQL enums. `adopt_legacy_schema`
> converts them to `varchar`, which is what Django expects. Never reintroduce
> native enum types.

---

## 5. Coding & Development Standards

### 5.1. Configuration
- The environment is read **once**, in `config/settings.py`. Feature code uses
  `settings.*` or the typed helpers `uploads_config()` / `owui_config()` —
  never `os.environ` directly.

### 5.2. Business logic lives in services
- `apps/catalog/services.py` holds operations shared by the REST API and the
  admin panel (upload, retry, delete, KB sync). Views and admin actions stay
  thin so both entry points behave identically.

### 5.3. Background work
- The pipeline runs on `apps/pipeline/runner.py`'s bounded thread pool. Always
  go through `runner.submit()`; it also guards the in-flight registry, without
  which upload / retry / batch could run the same material twice and overwrite
  each other's status and Open WebUI file ids.
- Worker threads must not hold database connections open: `runner` calls
  `close_old_connections()` around each task.
- Set `PIPELINE_RUN_SYNC=true` in tests so results are observable immediately.
- The queue is in-process: `config/wsgi.py` calls
  `recovery.resume_in_background()` so rows left `queued` / `converting` /
  `uploading` by a restart are submitted again.

### 5.4. API responses
- List endpoints return `{items, total, page, limit, totalPages}` via
  `ItemsPagination`.
- Errors return `{statusCode, message, error, path, timestamp}` via
  `api_exception_handler`, which also maps PG `23505` → 409 and
  `23503` / `23502` → 400.
- Routes accept an optional trailing slash. `SimpleRouter` coerces its
  `trailing_slash` argument, so it is assigned as an attribute after
  construction (see `config/urls.py`).

### 5.5. Unicode-aware regexes
- `apps/pipeline/services/cleaner.py` needs `\p{L}`, `\p{Lu}`, `\p{Ll}` — use
  the third-party `regex` module there, not `re`.

### 5.6. Schema & docs
- Every endpoint carries `@extend_schema` with a summary and, where the shape
  is not a model serializer, an explicit `responses=`. Keep
  `python manage.py spectacular` warning-free.

### 5.7. Admin panel (django-unfold)
- `INSTALLED_APPS` lists **`unfold.apps.BasicAppConfig`**, not plain `"unfold"`.
  The default config's `ready()` overwrites `admin.site` with its own
  `UnfoldAdminSite`, which silently discards `TurizmAdminSite` — and with it the
  dashboard callback and the `/admin/catalog/tree/` route.
- ModelAdmins and inlines inherit from `unfold.admin`; status chips come from
  `@display(label={...})` rather than hand-written HTML.
- The dashboard is built by `config.admin.dashboard_callback` (wired through
  `UNFOLD["DASHBOARD_CALLBACK"]`) and rendered by `templates/admin/dashboard.html`,
  which is registered as `index_template` so it can extend Unfold's own
  `admin/index.html` without extending itself.
- Sidebar entries live in `UNFOLD["SIDEBAR"]["navigation"]`; a new admin page
  has to be added there as well, or it is only reachable by URL.

### 5.8. Tests
- `tests/pipeline/` covers conversion semantics and is ported 1:1 from the
  original TypeScript specs — treat those assertions as the contract.
- `tests/conftest.py` forces uploads into `tmp_path` and blanks `OWUI_API_KEY`,
  because the developer `.env` points at a live Open WebUI instance.
- `tests/owui/fake_owui.py` is an in-memory Open WebUI behind
  `httpx.MockTransport`; use its `owui` fixture pattern (see
  `tests/owui/test_sync.py`) for anything that talks to Open WebUI.
- Admin tests need collected static files (`python manage.py collectstatic`),
  because pytest runs with `DEBUG=False` and the manifest storage.

---

## 6. Environment Variables

See `.env.example` — it is the authoritative list, and every variable is
documented in `README.md`. `DJANGO_SECRET_KEY` is mandatory whenever
`DJANGO_DEBUG=false`.

---

## 7. Quality Checklist for Any New Code

Before submitting any changes, verify:

1. `python manage.py check` reports no issues.
2. `python manage.py makemigrations --check --dry-run` detects no drift.
3. `ruff check .` exits clean.
4. `pytest` passes.
5. `python manage.py spectacular --file /dev/null` emits no warnings.
6. New endpoints are documented with `@extend_schema` and a `tags=` entry that
   exists in `SPECTACULAR_SETTINGS["TAGS"]`.
7. New admin-visible strings are in Uzbek, matching the rest of the panel.
8. Every admin page still renders — `tests/admin/` walks the whole registry,
   because a bad `fieldsets` entry only fails when the page is opened.
