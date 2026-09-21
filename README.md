# AI Agent Turizm — Backend

Backend API and ingestion pipeline for the **AI Agent Turizm** educational
system. It manages the content hierarchy (**Modules → Topics → Materials**) and
converts raw documents (PDF, PPTX, DOCX, TXT, MD) into grounded Markdown
knowledge bases synced with **Open WebUI** RAG agents.

**Stack:** Bun · NestJS 12 · PostgreSQL · TypeORM · SWC · Oxlint · Vitest

---

## Why the pipeline exists

Open WebUI chunks documents for its vector store, and two things break in the
process. This service fixes both before the text ever reaches the index.

### 1. Source grounding (`[MANBA: ...]`)

Vector chunking discards the surrounding context, so an answer cannot cite where
it came from. The pipeline repeats a grounding marker roughly every 600
characters, which guarantees that every vector chunk carries its own attribution:

```markdown
[MANBA: Constitution.pdf | page 14 | topic-01 | literature]
```

Every generated document also starts with YAML frontmatter (`module_id`,
`topic_id`, `source`, `script`, `chunks`, …).

### 2. Uzbek transliteration (`uz-cyrl` → `uz-latn`)

Latin-script queries do not match Cyrillic documents. The pipeline detects the
script and transliterates Uzbek Cyrillic to Latin; Russian text is preserved
as-is. Two common PDF/PPTX font-encoding defects are repaired on the way:

| Defect | Example | Repaired to |
| --- | --- | --- |
| Corrupted word-final digraph | `-ии` | `-ий` |
| Lowercase digraph tail in all-caps headings | `TO‘RTINChI` | `TO‘RTINCHI` |

---

## Setup

```bash
bun install
```

Copy the example environment file and adjust it:

```bash
cp .env.example .env
```

Start PostgreSQL (and, optionally, the app itself) with Docker:

```bash
docker compose up -d postgres
```

Run the API:

```bash
bun run start:dev
```

- API: <http://localhost:3005/api>
- Swagger: <http://localhost:3005/api/docs>

---

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `NODE_ENV` | `development` | `development` \| `production` \| `test` |
| `PORT` | `3000` | HTTP port |
| `POSTGRES_HOST` | `localhost` | Database host |
| `POSTGRES_PORT` | `5432` | Database port |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | `postgres` | Database password |
| `POSTGRES_DB` | `turizm_db` | Database name |
| `POSTGRES_SYNC` | `true` | Create/update the schema from entities |
| `POSTGRES_LOGGING` | `false` | Log SQL statements |
| `UPLOADS_DIR` | `<project>/uploads` | Root of `raw/` and `ready/` |
| `MAX_UPLOAD_MB` | `200` | Upload size cap (HTTP 413 above it) |
| `OWUI_URL` | `http://localhost:8080` | Open WebUI base URL |
| `OWUI_API_KEY` | — | Bearer token; without it indexing is skipped |
| `OWUI_KB_ID` | — | Optional default knowledge base |
| `OWUI_TIMEOUT_MS` | `30000` | Open WebUI HTTP timeout |

Values are validated at startup (`src/config/env.validation.ts`), so a bad port
or an unknown `NODE_ENV` fails immediately instead of surfacing later as an
obscure driver error.

`POSTGRES_SYNC=true` lets TypeORM create and alter tables from the entities.
There are **no migrations yet**, so turning it off in production leaves the
database without a schema.

---

## Ingestion flow

```
POST /api/materials/upload
  └─ sha256 + duplicate check → {UPLOADS_DIR}/raw/{module}/{topic}/{hash}__{name}
     └─ pipeline (background)
        1. parse    PDF pages / PPTX slides / DOCX+TXT sections
        2. clean    typography, line unwrap, font repair
        3. translit detect script; uz-cyrl → uz-latn
        4. chunk    grounding markers + frontmatter
                    → {UPLOADS_DIR}/ready/{module}/{topic}__{type}__{slug}-{hash}.md
        5. index    upload to Open WebUI and link it to the module's KB
```

Material status moves `queued → converting → md_ready → uploading → indexed`,
and lands on `failed` (with `error_message`) if a stage throws. If Open WebUI is
unreachable or unconfigured, the material stays at `md_ready` and can be picked
up later with `POST /api/materials/:id/retry`.

Each run is recorded in `audit_logs`, queryable via `GET /api/audit-logs`.

Batch processing (`POST /api/modules/:id/process-all`) runs at a fixed
concurrency of 2 so that a module with hundreds of documents cannot exhaust
memory.

---

## API surface

| Method & path | Purpose |
| --- | --- |
| `GET /api` | Health and service status |
| `GET/POST /api/modules`, `GET/PATCH/DELETE /api/modules/:id` | Module CRUD |
| `POST /api/modules/:id/kb` | Create or sync the module's Open WebUI KB |
| `POST /api/modules/:id/process-all` | Re-run the pipeline for every material |
| `GET/POST /api/topics`, `GET/PATCH/DELETE /api/topics/:id` | Topic CRUD |
| `GET /api/materials`, `GET/DELETE /api/materials/:id` | Material listing and removal |
| `POST /api/materials/upload` | Upload a document and start the pipeline |
| `GET /api/materials/:id/content` | Preview the generated Markdown |
| `POST /api/materials/:id/retry` | Re-run the pipeline |
| `GET /api/audit-logs` | Pipeline and system history |
| `GET /api/owui/status`, `GET /api/owui/knowledge-bases` | Open WebUI diagnostics |

> **No authentication yet.** Every endpoint is open, so do not expose this
> service directly to the internet. `users` and `materials.uploaded_by_id`
> already exist in the schema for when auth is added.

---

## Commands

```bash
bun run start:dev     # dev server with hot reload (SWC watch)
bun run build         # production build
bun x tsc --noEmit    # type check
bun run lint          # Oxlint with type-aware rules
bun run format        # Prettier
bun run test          # unit tests
bun run test:e2e      # e2e tests (needs a reachable PostgreSQL)
bun run test:cov      # coverage
```

---

## Project layout

```text
src/
├── common/       # pagination DTO, exception filter, logging interceptor, shared constants
├── config/       # typed configuration factory + startup env validation
├── database/     # TypeORM setup and entities
└── modules/
    ├── modules/  ├── topics/  ├── materials/  ├── audit-logs/
    ├── owui/     # Open WebUI REST client
    └── pipeline/ # parser, cleaner, translit, chunker + coordinator
```

See [CLAUDE.md](CLAUDE.md) for the full conventions (ESM `.js` import
extensions, TypeORM relation syntax, database naming rules).
