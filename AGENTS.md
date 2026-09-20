# AI Agent Turizm Backend (Bun + NestJS + PostgreSQL)

Ushbu hujjat loyihaning to'liq arxitekturasi, ma'lumotlar bazasi tuzilishi, Python asosidagi dastlabki nusxaning tahlili hamda **Bun + NestJS + PostgreSQL** texnologik steki asosida tizimni qurish qoidalari va ko'rsatmalarini o'z ichiga oladi.

> **Eslatma**: Loyihaning barcha ma'lumotlar bazasi jadvallari, ustunlari, enumlari, entity va modullari xalqaro standartlarga mos ravishda to'liq **ingliz tilida** nomlangan.

---

## 1. Project Overview & Core Mission

The service manages educational content (**Modules**, **Topics**, **Materials**) and converts raw documents (PDF, PPTX, DOCX, TXT, MD) into structured, grounded Markdown knowledge bases for **Open WebUI** RAG agents.

```
┌────────────────────────────────────────────────────────┐         HTTP API         ┌─────────────────────────────────┐
│              NestJS Backend (This Project)             │ ───────────────────────> │           Open WebUI            │
│  Modules  ─►  Topics  ─►  Materials (PDF, PPTX)        │                          │        (ai-agent-turizm)        │
│  • Uzbek Cyrillic -> Latin transliteration             │                          │  • Knowledge Bases (KB)         │
│  • [MANBA: ...] grounding markers (~600 chars)         │                          │  • Vector Search (RAG)          │
│  • PostgreSQL DB + Asynchronous Pipeline               │                          │  • AI Agent / Chat              │
└────────────────────────────────────────────────────────┘                          └─────────────────────────────────┘
```

### Why Pre-processing & Grounding is Required
Directly uploading raw PDFs/PPTXs into Open WebUI results in **loss of source citations (grounding)**. To ensure the AI agent can accurately cite sources (e.g., `Law_Constitution.pdf, page 14`), the pipeline injects repeating source tags every **~600 characters**:
```markdown
[MANBA: Constitution.pdf | page 14 | Topic 1.1 | literature]
```
Additionally, the pipeline:
1. **Uzbek Cyrillic -> Latin**: Automatically converts Uzbek Cyrillic texts to Latin script so Latin queries successfully match Cyrillic documents. Russian texts remain untouched.
2. **Corrupted Font & Glyphs Repair**: Fixes broken PDF font encodings (`final -ии` -> `-ий`, `TO‘RTINChI` -> `TO‘RTINCHI`).
3. **Table & Slide Notes Extraction**: Formats tables into clean Markdown tables and includes presenter slide notes.

---

## 2. Legacy Python Analysis vs Bun + NestJS Architecture

| Feature | Legacy Python Project (`example/`) | New Bun + NestJS + PostgreSQL Project |
|---|---|---|
| **Runtime / Language** | Python 3.12 (CPython) | TypeScript on **Bun** runtime |
| **Framework** | Django 5.2 (Django Admin) | **NestJS 12** (Modular REST API + Admin) |
| **Database** | SQLite3 (`data/db.sqlite3`) | **PostgreSQL** (UUID PKs, Enums, Cascades) |
| **Build Tool / Compiler**| Django runserver | Bun + SWC (`bun run nest start -b swc -w`) |
| **Background Tasks** | `django-q2` (SQLite ORM broker) | Asynchronous Worker / Queue Service |
| **OWUI Integration** | `requests` | HTTP Client via `Axios` / `fetch` |

---

## 3. PostgreSQL Database Schema (English)

All database entities, tables, columns, constraints, and enums are written in **English** using snake_case conventions.

### 3.1. Enum Types
```sql
CREATE TYPE material_type AS ENUM ('presentation', 'questions', 'literature');

CREATE TYPE material_status AS ENUM (
  'new',
  'queued',
  'converting',
  'md_ready',
  'uploading',
  'indexed',
  'failed'
);

CREATE TYPE log_level AS ENUM ('info', 'warn', 'error');
```

### 3.2. Entity Relationship Diagram (ERD)
```
Module (1) ───< (N) Topic (1) ───< (N) Material (1) ───< (N) AuditLog
   │                                                         │
   └─────────────────────────────────────────────────────────┘
```

### 3.3. Tables Specification

1. **`modules`**:
   - `id` (UUID, PRIMARY KEY DEFAULT gen_random_uuid())
   - `code` (VARCHAR(40), UNIQUE NOT NULL) — e.g. `module-01`
   - `name` (VARCHAR(300), NOT NULL) — Full title of the module
   - `description` (TEXT)
   - `order_index` (INT, NOT NULL DEFAULT 0) — Sorting order
   - `owui_kb_id` (VARCHAR(64)) — Knowledge Base ID in Open WebUI
   - `is_active` (BOOLEAN, NOT NULL DEFAULT true)
   - `created_at`, `updated_at` (TIMESTAMPTZ, NOT NULL DEFAULT now())

2. **`topics`**:
   - `id` (UUID, PRIMARY KEY DEFAULT gen_random_uuid())
   - `module_id` (UUID, NOT NULL REFERENCES modules(id) ON DELETE CASCADE)
   - `code` (VARCHAR(40), NOT NULL) — e.g. `topic-01`
   - `name` (VARCHAR(300), NOT NULL)
   - `description` (TEXT)
   - `order_index` (INT, NOT NULL DEFAULT 0)
   - *Constraint*: `UNIQUE(module_id, code)`
   - `created_at`, `updated_at` (TIMESTAMPTZ, NOT NULL DEFAULT now())

3. **`users`** (System Administrators):
   - `id` (UUID, PRIMARY KEY DEFAULT gen_random_uuid())
   - `email` (VARCHAR(150), UNIQUE NOT NULL)
   - `password_hash` (VARCHAR(255), NOT NULL)
   - `full_name` (VARCHAR(100))
   - `role` (VARCHAR(30), NOT NULL DEFAULT 'admin')
   - `is_active` (BOOLEAN, NOT NULL DEFAULT true)
   - `created_at`, `updated_at` (TIMESTAMPTZ, NOT NULL DEFAULT now())

4. **`materials`**:
   - `id` (UUID, PRIMARY KEY DEFAULT gen_random_uuid())
   - `topic_id` (UUID, NOT NULL REFERENCES topics(id) ON DELETE CASCADE)
   - `type` (material_type, NOT NULL DEFAULT 'literature')
   - `raw_file_path` (VARCHAR(255), NOT NULL) — Storage path on disk (e.g. `uploads/raw/...`)
   - `original_filename` (VARCHAR(300), NOT NULL) — Name of uploaded file
   - `file_size` (BIGINT, NOT NULL DEFAULT 0) — Size in bytes
   - `file_hash` (VARCHAR(64), INDEX) — SHA-256 hash for deduplication
   - `status` (material_status, NOT NULL DEFAULT 'new', INDEX)
   - `error_message` (TEXT) — Traceback or reason if processing failed
   - `md_file_path` (VARCHAR(255)) — Converted `.md` storage path
   - `chunk_count` (INT, NOT NULL DEFAULT 0) — Number of pages / slides
   - `char_count` (INT, NOT NULL DEFAULT 0) — Total characters
   - `detected_script` (VARCHAR(30)) — e.g. `latin`, `cyrillic_to_latin`, `russian`
   - `owui_file_id` (VARCHAR(64)) — File ID returned from Open WebUI
   - `indexed_at` (TIMESTAMPTZ) — Timestamp when successfully indexed into Open WebUI
   - `uploaded_by_id` (UUID, REFERENCES users(id) ON DELETE SET NULL)
   - `created_at`, `updated_at` (TIMESTAMPTZ, NOT NULL DEFAULT now())

5. **`audit_logs`**:
   - `id` (UUID, PRIMARY KEY DEFAULT gen_random_uuid())
   - `material_id` (UUID, REFERENCES materials(id) ON DELETE CASCADE, NULLABLE)
   - `module_id` (UUID, REFERENCES modules(id) ON DELETE CASCADE, NULLABLE)
   - `stage` (VARCHAR(50), NOT NULL) — e.g. `conversion`, `indexing`, `queue`, `kb_create`
   - `level` (log_level, NOT NULL DEFAULT 'info')
   - `message` (TEXT, NOT NULL)
   - `created_at` (TIMESTAMPTZ, NOT NULL DEFAULT now(), INDEX)

---

## 4. NestJS Application Modular Structure

The NestJS codebase is organized under `src/`:

```text
src/
├── common/                     # Global filters, guards, interceptors, decorators
├── config/                     # Environment configuration & validation
├── database/                   # Database connection provider, TypeORM entities, migrations
│   ├── entities/               # ModuleEntity, TopicEntity, MaterialEntity, AuditLogEntity, UserEntity
│   └── migrations/
├── modules/
│   ├── auth/                   # Admin authentication (JWT)
│   ├── users/                  # User accounts & roles
│   ├── modules/                # Modules management & Open WebUI KB creation
│   ├── topics/                 # Topics management
│   ├── materials/              # Materials management & file upload
│   ├── audit-logs/             # System audit logs
│   ├── pipeline/               # Ingestion, parsing, transliteration & chunking
│   ├── owui/                   # Open WebUI HTTP client
│   └── queue/                  # Asynchronous job processing
└── main.ts
```

---

## 5. Agent Customizations (Rules & Skills)

The project leverages `.agents/` customizations:

### 5.1. Rules
- [`.agents/rules/database-rules.md`](file:///.agents/rules/database-rules.md): PostgreSQL conventions, DDL, table definitions, and indexes.
- [`.agents/rules/architecture-rules.md`](file:///.agents/rules/architecture-rules.md): NestJS + Bun architecture, module structure, DTO validation standards.
- [`.agents/rules/pipeline-rules.md`](file:///.agents/rules/pipeline-rules.md): `[MANBA: ...]` grounding rules, Uzbek transliteration, and Open WebUI API rules.

### 5.2. Skills
- [`.agents/skills/content-pipeline/SKILL.md`](file:///.agents/skills/content-pipeline/SKILL.md): Procedures for document ingestion, parsing, chunking, and Open WebUI sync.
- [`.agents/skills/postgres-schema/SKILL.md`](file:///.agents/skills/postgres-schema/SKILL.md): PostgreSQL schema management, entity relations, and migrations.

---

## 6. Execution Commands

```bash
# 1. Start development server in watch mode using SWC:
bun run nest start -b swc -w

# or shortcut:
bun run start:dev

# 2. Build the project:
bun run build

# 3. Run tests:
bun run test
```
