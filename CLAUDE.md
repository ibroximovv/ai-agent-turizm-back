# CLAUDE.md — AI Agent Turizm Backend Guide

This file provides comprehensive guidelines, project architecture, commands, and coding standards for Claude Code when working in this repository.

---

## 1. Project Overview & Mission

This project is the **Backend API and Ingestion Pipeline** for the **AI Agent Turizm** educational system.

- **Stack**: **Bun** runtime + **NestJS 12** + **PostgreSQL** + **TypeORM** + **SWC** compiler + **Oxlint** + **Vitest**.
- **Mission**: Manages educational content hierarchy (**Modules** ➔ **Topics** ➔ **Materials**) and converts raw documents (PDF, PPTX, DOCX, TXT, MD) into grounded Markdown knowledge bases synced with **Open WebUI** RAG agents.

### Core Domain Features:
1. **Source Grounding (`[MANBA: ...]`)**:
   - Open WebUI vector chunking loses source context. The pipeline injects repeated source grounding markers every **~600 characters**:
     ```markdown
     [MANBA: Constitution.pdf | page 14 | topic-01 | literature]
     ```
   - Every converted Markdown document begins with standard YAML frontmatter (`module_id`, `topic_id`, `source`, `script`, `chunks`, etc.).
2. **Uzbek Transliteration (`uz-cyrl` -> `uz-latn`)**:
   - Queries in Latin script fail to match Cyrillic documents in RAG.
   - The pipeline auto-detects script (`detectScript`); if Uzbek Cyrillic, it transliterates to Latin (`toLatin`).
   - Russian texts (`ru`) are preserved as-is without transliteration.
   - Corrupted PDF font encodings (`final -ии` -> `-ий`) and all-caps digraphs (`TO‘RTINChI` -> `TO‘RTINCHI`) are repaired automatically.
3. **Open WebUI Integration**:
   - Pure HTTP REST API integration (`OWUI_URL` + Bearer `OWUI_API_KEY`).
   - Automatically creates or links module Knowledge Bases, uploads processed Markdown, and links them to the KB.

---

## 2. Common Execution Commands

All commands are run using **Bun**:

```bash
# Development server with hot reload (SWC watch mode):
bun run start:dev
# (or equivalent: bun run nest start -b swc -w)

# Build production bundle (SWC):
bun run build

# Type check (TypeScript):
bun x tsc --noEmit

# Lint (Oxlint with type-aware rules):
bun run lint

# Code formatting (Prettier):
bun run format

# Run unit tests (Vitest):
bun run test

# Run e2e tests (Vitest):
bun run test:e2e
```

---

## 3. Architecture & Directory Organization

The project follows a modular, feature-first NestJS architecture located under `src/`:

```text
src/
├── common/                     # Global utilities, filters, interceptors, common DTOs
│   ├── dto/                    # PaginationQueryDto (page, limit, search)
│   ├── filters/                # AllExceptionsFilter (maps PG errors to 409/400)
│   ├── interceptors/           # LoggingInterceptor
│   ├── constants.ts            # CODE_PATTERN for module/topic codes
│   └── filename.ts             # multipart filename decoding & path-safe names
├── config/                     # Environment configuration & validation
│   ├── configuration.ts        # typed config factory (database, owui, uploads)
│   └── env.validation.ts       # fail-fast startup validation
├── database/                   # Database provider & TypeORM entities
│   └── entities/               # module, topic, material, audit-log, user entities
│       ├── module.entity.ts
│       ├── topic.entity.ts
│       ├── material.entity.ts
│       ├── audit-log.entity.ts
│       └── user.entity.ts
├── modules/
│   ├── modules/                # Modules CRUD + OWUI Knowledge Base sync + batch processing
│   ├── topics/                 # Topics CRUD (belongs to Module)
│   ├── materials/              # Materials CRUD + multipart file upload + pipeline trigger
│   ├── audit-logs/             # Audit logs querying & pipeline execution history
│   ├── owui/                   # Open WebUI HTTP REST API client (KB create, file upload)
│   └── pipeline/               # Ingestion & document conversion pipeline
│       ├── services/
│       │   ├── parser.service.ts       # PDF (pdf-parse), PPTX (adm-zip), DOCX (mammoth), TXT, MD
│       │   ├── cleaner.service.ts      # Typography, line unwrap, font repair
│       │   ├── translit.service.ts     # Script detection & Uzbek Cyrillic -> Latin translit
│       │   └── chunker.service.ts      # Grounding marker injection (~600 chars) & YAML frontmatter
│       └── pipeline.service.ts         # End-to-end pipeline coordinator
├── app.module.ts               # Root module registering all feature modules
└── main.ts                     # NestJS bootstrap, Swagger OpenAPI setup, CORS, ValidationPipe
```

---

## 4. PostgreSQL Database Conventions

- All table names, columns, constraints, and enums MUST be written in **English** using `snake_case`.
- Primary keys are **UUIDv4** (`gen_random_uuid()`).
- All entities inherit standard audit timestamps (`created_at`, `updated_at` with `timestamptz`).

### Hierarchy & Cascade Deletes:
```
Module (1) ───< (N) Topic (1) ───< (N) Material (1) ───< (N) AuditLog
   │                                                         │
   └─────────────────────────────────────────────────────────┘
```
- Deleting a `Module` cascades to its `Topics`, `Materials`, and `AuditLogs`.
- Deleting a `Topic` cascades to its `Materials` and `AuditLogs`.
- Constraints:
  - `modules`: `UNIQUE(code)` (e.g. `module-01`).
  - `topics`: `UNIQUE(module_id, code)` (unique within the module).
  - `materials`: `file_hash` indexed for deduplication — uploading a
    byte-identical file into the same topic is rejected with `409 Conflict`.
- `modules.code` and `topics.code` must match `CODE_PATTERN`
  (`/^[A-Za-z0-9][A-Za-z0-9._-]*$/`). They are used as directory names under
  `UPLOADS_DIR`, so anything else would allow a path escape.

### Enum Types:
- `MaterialType`: `'presentation'`, `'questions'`, `'literature'`
- `MaterialStatus`: `'new'`, `'queued'`, `'converting'`, `'md_ready'`, `'uploading'`, `'indexed'`, `'failed'`
- `LogLevel`: `'info'`, `'warn'`, `'error'`

---

## 5. Coding & Development Standards

### 5.1. ESM & NodeNext Imports (CRITICAL)
- The project runs in native ESM (`"type": "module"` in `package.json`).
- With TypeScript `"moduleResolution": "nodenext"`, **all relative imports MUST explicitly include the `.js` file extension**:
  ```typescript
  // CORRECT:
  import { TopicEntity } from './topic.entity.js';
  import { PaginationQueryDto } from '../../../common/dto/pagination.dto.js';

  // INCORRECT (will cause TS2307 / runtime failure):
  import { TopicEntity } from './topic.entity';
  ```

### 5.2. TypeORM Relations
- Always use type-safe object syntax for `relations`:
  ```typescript
  // CORRECT:
  this.materialRepo.findOne({
    where: { id },
    relations: { topic: { module: true } },
  });

  // INCORRECT (causes TS2559):
  this.materialRepo.findOne({
    where: { id },
    relations: ['topic', 'topic.module'],
  });
  ```
- Use `Relation<T>` wrapper from TypeORM for entity relationship properties.

### 5.3. Avoid Spreading Class Instances
- Oxlint enforces `no-misused-spread`: spreading class entities (`{ ...entity }`) loses class prototype methods and getters.
- Use `Object.assign(entity, { extraProp: value })` or assign properties directly.

### 5.4. DTOs & Validation
- Use `class-validator` and `class-transformer` on all incoming request objects.
- Use `@ApiProperty` / `@ApiPropertyOptional` from `@nestjs/swagger` on all DTO fields.
- For multipart file uploads, use `@UseInterceptors(FileInterceptor('file'))`, `@ApiConsumes('multipart/form-data')`, and `@ApiBody({ type: UploadDto })`.

### 5.5. Open WebUI Client Protocol
- Base endpoints:
  - `GET /api/v1/knowledge/` — list KBs
  - `POST /api/v1/knowledge/create` — create KB (`{ name, description }`)
  - `POST /api/v1/files/` — upload Markdown (`FormData`, `process=true`)
  - `POST /api/v1/knowledge/{kb_id}/file/add` — link file (`{ file_id }`)
  - `POST /api/v1/knowledge/{kb_id}/file/remove` — unlink file (`{ file_id }`)
  - `DELETE /api/v1/files/{file_id}` — purge file

---

## 6. Environment Variables (`.env`)

```env
# Application
NODE_ENV=development
PORT=3005

# PostgreSQL Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=turizm_db
POSTGRES_SYNC=true
POSTGRES_LOGGING=false

# Storage
UPLOADS_DIR=          # defaults to <project>/uploads; holds raw/ and ready/
MAX_UPLOAD_MB=200     # uploads above this are rejected with HTTP 413

# Open WebUI Integration
OWUI_URL=http://localhost:8080
OWUI_API_KEY=
OWUI_KB_ID=
OWUI_TIMEOUT_MS=30000
```

All of the above are validated at bootstrap by `src/config/env.validation.ts`
and exposed as a typed, pre-parsed object by `src/config/configuration.ts`.
Read them through `ConfigService.get<...>('database' | 'owui' | 'uploads')`
rather than touching `process.env` in feature code.

---

## 7. Quality Checklist for Any New Code
Before submitting any changes, verify:
1. `bun x tsc --noEmit` exits with `0 issues`.
2. `bun run lint` exits with `0 warnings and 0 errors`.
3. `bun run build` compiles successfully with SWC.
4. `bun run test` and `bun run test:e2e` pass without failures.
5. All new endpoints are documented with `@ApiTags`, `@ApiOperation`, and `@ApiResponse`.
