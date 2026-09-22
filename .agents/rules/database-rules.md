# PostgreSQL Database Rules & Conventions

This document defines strict rules, conventions, and schema specifications for
PostgreSQL in the project. All tables, columns, constraints and choice values
MUST be named in English using standard conventions. The DDL below is the
reference shape; the authoritative definition lives in the Django models
under `apps/*/models.py`.

---

## 1. Naming Conventions
- **Tables and Columns**: All names must be in lowercase **snake_case** (e.g., `modules`, `topics`, `materials`, `audit_logs`, `users`).
- **Table Names**: Plural nouns (`modules`, `topics`, `materials`, `audit_logs`, `users`).
- **Primary Keys**: `id UUID PRIMARY KEY` — the value comes from `uuid.uuid4` on the Django model, not from a database default.
- **Foreign Keys**: `<singular_table_name>_id` (e.g., `module_id`, `topic_id`, `material_id`, `uploaded_by_id`).
- **Timestamps**:
  - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- **Boolean Flags**: Prefix with `is_` or `has_` (e.g., `is_active`).

---

## 2. PostgreSQL DDL Schema

### 2.1. Choice Columns

Choice columns are plain `VARCHAR` backed by Django `TextChoices` — **never**
native PostgreSQL `ENUM` types. Django does not model native enums, and a
mismatch there is what `adopt_legacy_schema` exists to repair on databases
inherited from the TypeORM service.

| Column | Type | Allowed values |
| --- | --- | --- |
| `materials.type` | `VARCHAR(20)` | `presentation` (taqdimot), `questions` (savollar), `literature` (adabiyotlar) |
| `materials.status` | `VARCHAR(20)` | `new`, `queued`, `converting`, `md_ready`, `uploading`, `indexed`, `failed` |
| `audit_logs.level` | `VARCHAR(10)` | `info`, `warn`, `error` |
| `users.role` | `VARCHAR(30)` | `admin`, `editor`, `viewer` |

Status meanings: `new` — uploaded, untouched · `queued` — waiting for a worker ·
`converting` — text extraction and Markdown formatting · `md_ready` — Markdown
generated, ready for Open WebUI · `uploading` — being sent to the knowledge
base · `indexed` — successfully indexed · `failed` — error during processing.

### 2.2. Tables DDL

```sql
-- 1. Modules Table
CREATE TABLE modules (
  id UUID PRIMARY KEY,
  code VARCHAR(40) UNIQUE NOT NULL, -- e.g., 'module-01'
  name VARCHAR(300) NOT NULL,
  description TEXT,
  order_index INT NOT NULL DEFAULT 0,
  owui_kb_id VARCHAR(64), -- Open WebUI Knowledge Base ID
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Topics Table
CREATE TABLE topics (
  id UUID PRIMARY KEY,
  module_id UUID NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
  code VARCHAR(40) NOT NULL, -- e.g., 'topic-01'
  name VARCHAR(300) NOT NULL,
  description TEXT,
  order_index INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_topics_module_code UNIQUE (module_id, code)
);

-- 3. Users Table (System Admins)
-- Django's AbstractBaseUser + PermissionsMixin; `password` is mapped onto the
-- legacy `password_hash` column. `users_groups` and `users_user_permissions`
-- join tables are created by the auth app.
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email VARCHAR(150) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,   -- Django's `password` field
  full_name VARCHAR(100),
  role VARCHAR(30) NOT NULL DEFAULT 'editor',
  is_active BOOLEAN NOT NULL DEFAULT true,
  is_staff BOOLEAN NOT NULL DEFAULT true,       -- may open the admin panel
  is_superuser BOOLEAN NOT NULL DEFAULT false,
  last_login TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Materials Table (Source and Converted Documents)
CREATE TABLE materials (
  id UUID PRIMARY KEY,
  topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  type VARCHAR(20) NOT NULL DEFAULT 'literature',
  raw_file_path VARCHAR(255) NOT NULL, -- storage relative path (raw/...)
  original_filename VARCHAR(300) NOT NULL, -- original file name
  file_size BIGINT NOT NULL DEFAULT 0, -- size in bytes
  file_hash VARCHAR(64), -- SHA-256 hash for deduplication
  status VARCHAR(20) NOT NULL DEFAULT 'new',
  error_message TEXT,
  md_file_path VARCHAR(255), -- converted markdown path (ready/...)
  chunk_count INT NOT NULL DEFAULT 0, -- number of pages / slides
  char_count INT NOT NULL DEFAULT 0, -- total character count
  detected_script VARCHAR(30), -- 'uz-latn', 'uz-cyrl', 'ru', 'other'
  owui_file_id VARCHAR(64), -- Open WebUI file ID
  indexed_at TIMESTAMPTZ, -- timestamp of successful indexing into KB
  uploaded_by_id UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5. Audit Logs Table (Event Log and Pipeline History)
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY,
  material_id UUID REFERENCES materials(id) ON DELETE CASCADE,
  module_id UUID REFERENCES modules(id) ON DELETE CASCADE,
  stage VARCHAR(50) NOT NULL, -- 'conversion', 'indexing', 'queue', 'kb_create'
  level VARCHAR(10) NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 3. Indexing Strategy
- `materials(status)`: Optimizes queue queries fetching pending/queued jobs.
- `materials(file_hash)`: Rapid duplicate detection on file upload.
- `topics(module_id, order_index)`: Fast ordered retrieval of topics per module.
- `audit_logs(created_at DESC)`: Rapid access to latest activity logs.
- `audit_logs(material_id)`: Filter logs for specific materials.

---

## 4. Integrity and Deletion Handling
- When a `module` or `topic` is deleted, related records are cleaned up via `ON DELETE CASCADE`.
- Service layer MUST trigger cleanup of physical files on disk (`raw_file_path`, `md_file_path`) and purge associated Open WebUI files via the Open WebUI HTTP API (`/api/v1/knowledge/{kb_id}/file/remove` and `DELETE /api/v1/files/{file_id}`).
