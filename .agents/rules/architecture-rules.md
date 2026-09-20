# NestJS + Bun Architecture Rules

This document defines architecture standards, coding conventions, and directory organization for the backend built on **Bun + NestJS + PostgreSQL**. All module names, file names, class names, and endpoints MUST be written in English.

---

## 1. Runtime & Environment
- **Runtime**: `bun` (package manager, script runner, and execution runtime).
- **Compiler**: `swc` (`nest start -b swc -w`). Module format is ESM (`"type": "module"` in `package.json` and `"type": "es6"` in `.swcrc`).
- **Code Standards**: `oxlint` for type-aware linting and `prettier` for code formatting.

---

## 2. Directory Structure (English Modular Architecture)

The `src/` directory is organized into feature-first domain modules:

```text
src/
├── common/                     # Global utilities, filters, guards, and decorators
│   ├── decorators/
│   ├── filters/                # Global exception filters (e.g. AllExceptionsFilter)
│   ├── guards/                 # Auth and role guards
│   ├── interceptors/           # Logging, response transformation
│   └── utils/
├── config/                     # Environment configuration (ConfigModule / validation)
├── database/                   # Database connection provider, entities, migrations
│   ├── entities/               # Module, Topic, Material, AuditLog, User entities
│   └── migrations/
├── modules/
│   ├── auth/                   # Authentication (JWT / Session)
│   ├── users/                  # User / Admin profile management
│   ├── modules/                # Modules CRUD + Open WebUI Knowledge Base creation
│   ├── topics/                 # Topics CRUD
│   ├── materials/              # Materials CRUD + file upload (multipart)
│   ├── audit-logs/             # Audit logs and operation history
│   ├── pipeline/               # Document ingestion & conversion pipeline
│   │   ├── services/
│   │   │   ├── parser.service.ts       # PDF, PPTX, DOCX, TXT, MD text extraction
│   │   │   ├── translit.service.ts     # Uzbek Cyrillic -> Latin transliteration
│   │   │   ├── cleaner.service.ts      # Unwrapping, typography & font repair
│   │   │   └── chunker.service.ts      # [MANBA: ...] marker injection (~600 chars)
│   ├── owui/                   # Open WebUI HTTP API client
│   │   ├── owui.service.ts             # KB create/list, file upload/delete, KB sync
│   │   └── interfaces/
│   └── queue/                  # Background worker queue for async ingestion
│       ├── queue.service.ts
│       └── processors/
└── main.ts
```

---

## 3. DTOs and Validation
- Every incoming HTTP request (Body, Query, Params) MUST have a dedicated `DTO` class using `class-validator` and `class-transformer`.
- Global `ValidationPipe({ whitelist: true, transform: true })` must be enabled in `main.ts`.
- Avoid `any` types; all contracts, entity relations, and service methods must be strongly typed.

---

## 4. Error Handling & Auditing
- Domain errors must map to standard NestJS exceptions (`NotFoundException`, `BadRequestException`, `ConflictException`).
- Processing errors during the pipeline must be recorded into the `audit_logs` table with `level: 'error'`, and the material status set to `'failed'`.

---

## 5. Storage Layout
- Raw uploaded files: `uploads/raw/{module_code}/{topic_code}/{filename}`.
- Converted markdown files: `uploads/ready/{module_code}/{topic_code}__{type}__{slug}.md`.
- File size limit: 200 MB maximum.
- SHA-256 hash must be computed before queue dispatching.
