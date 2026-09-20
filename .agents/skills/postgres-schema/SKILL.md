---
name: postgres-schema
description: >-
  Guide for managing PostgreSQL database schemas, entity relationships,
  migrations, and indexing in Bun + NestJS using standard English conventions.
---

# PostgreSQL Database Management Skill

This skill provides step-by-step instructions for managing the PostgreSQL database schema, migrations, constraints, and relationships in the project.

---

## 1. Entity Relationships Hierarchy

```
Module (1) ───< (N) Topic (1) ───< (N) Material (1) ───< (N) AuditLog
   │                                                         │
   └─────────────────────────────────────────────────────────┘
```

- **Module (1) -> (N) Topic**: `topics.module_id -> modules.id` (`ON DELETE CASCADE`)
- **Topic (1) -> (N) Material**: `materials.topic_id -> topics.id` (`ON DELETE CASCADE`)
- **Material (1) -> (N) AuditLog**: `audit_logs.material_id -> materials.id` (`ON DELETE CASCADE`)
- **Module (1) -> (N) AuditLog**: `audit_logs.module_id -> modules.id` (`ON DELETE CASCADE`)
- **User (1) -> (N) Material**: `materials.uploaded_by_id -> users.id` (`ON DELETE SET NULL`)

---

## 2. Constraints & Uniqueness
- `topics`: `UNIQUE(module_id, code)` — topic codes are unique within their parent module.
- `modules`: `UNIQUE(code)` — module codes are globally unique (e.g. `module-01`).
- `users`: `UNIQUE(email)`.

---

## 3. Safe Transactions & Status Changes
When processing a material file:
```typescript
// Inside a database transaction / service method:
// 1. Update materials.status (e.g. 'converting' -> 'md_ready' -> 'indexed')
// 2. Insert record into audit_logs
// 3. On error: update materials.status = 'failed', materials.error_message = err.message
```

---

## 4. Migrations & Schema Sync
- Always maintain migration scripts under `src/database/migrations/`.
- Ensure custom PostgreSQL ENUM types (`material_type`, `material_status`, `log_level`) are defined before dependent tables.
