"""Restore `materials.uploaded_by_id` → `users.id`.

Adopting a TypeORM-era database means dropping its `users` table (it predates
authentication and has none of Django's auth columns). That `DROP ... CASCADE`
also removes the foreign key on `materials.uploaded_by_id`, and because the
catalog tables are adopted with `--fake-initial`, no migration ever recreates
it. This one does, guarded so it is a no-op on a database that already has it.
"""

from django.db import migrations

CONSTRAINT_NAME = "materials_uploaded_by_id_fk_users_id"

ADD_FK = f"""
DO $$
BEGIN
    IF to_regclass('public.materials') IS NULL OR to_regclass('public.users') IS NULL THEN
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN unnest(c.conkey) AS k ON TRUE
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k
        WHERE c.conrelid = 'public.materials'::regclass
          AND c.contype = 'f'
          AND a.attname = 'uploaded_by_id'
    ) THEN
        RETURN;
    END IF;

    ALTER TABLE materials
        ADD CONSTRAINT {CONSTRAINT_NAME}
        FOREIGN KEY (uploaded_by_id) REFERENCES users(id)
        ON DELETE SET NULL
        DEFERRABLE INITIALLY DEFERRED;
END $$;
"""

DROP_FK = f'ALTER TABLE materials DROP CONSTRAINT IF EXISTS "{CONSTRAINT_NAME}";'


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=ADD_FK, reverse_sql=DROP_FK),
    ]
