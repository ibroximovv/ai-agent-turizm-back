---
name: postgres-schema
description: >-
  Guide for managing PostgreSQL database schemas, entity relationships,
  migrations, and indexing in Django + PostgreSQL using standard English conventions.
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
```python
# Inside apps/pipeline/service.py:
# 1. Update materials.status (e.g. 'converting' -> 'md_ready' -> 'indexed')
#    with save(update_fields=[...]) so a concurrent run is not clobbered.
# 2. Insert a row into audit_logs for each milestone.
# 3. On error: status = 'failed', error_message = str(exc), audit level='error'.
```

---

## 4. Migrations & Schema Sync
- Migrations live under `apps/<app>/migrations/` and are generated with
  `python manage.py makemigrations`. Never hand-edit an applied migration.
- `python manage.py makemigrations --check --dry-run` must report no drift.
- Choice columns (`materials.type`, `materials.status`, `audit_logs.level`) are
  plain `varchar` with Django `TextChoices` — **not** native PostgreSQL enums.
  A database inherited from the TypeORM service is converted by
  `python manage.py adopt_legacy_schema --apply`, after which the tables are
  adopted with `migrate --fake-initial`.
