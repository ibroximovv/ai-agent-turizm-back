"""Prepare a TypeORM-era database for Django's migrations.

The NestJS service created the schema from its entities, which differs from what
Django expects in two ways:

1. `type`, `status` and `level` are native PostgreSQL enums; Django models them
   as ``varchar`` with choices.
2. The `users` table has no `last_login` / `is_staff` / `is_superuser` columns
   and no permission join tables, because the old service had no auth.

This command fixes (1) in place — data is preserved — and reports what to do
about (2). Afterwards ``python manage.py migrate --fake-initial`` adopts the
existing tables instead of trying to recreate them.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

#: table, column, enum type name
ENUM_COLUMNS = [
    ("materials", "type", "materials_type_enum", 20),
    ("materials", "status", "materials_status_enum", 20),
    ("audit_logs", "level", "audit_logs_level_enum", 10),
]

LEGACY_TABLES = ["modules", "topics", "materials", "audit_logs"]


def _table_exists(cursor, table: str) -> bool:
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [f"public.{table}"])
    return cursor.fetchone()[0]


def _column_type(cursor, table: str, column: str) -> str | None:
    cursor.execute(
        """
        SELECT data_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        """,
        [table, column],
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _column_default(cursor, table: str, column: str) -> str | None:
    cursor.execute(
        """
        SELECT column_default FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        """,
        [table, column],
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _row_count(cursor, table: str) -> int:
    cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
    return cursor.fetchone()[0]


class Command(BaseCommand):
    help = "TypeORM davridagi bazani Django migratsiyalari uchun tayyorlaydi."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="O'zgarishlarni haqiqatan bajarish (aks holda faqat reja ko'rsatiladi).",
        )
        parser.add_argument(
            "--drop-empty-users",
            action="store_true",
            help="Bo'sh `users` jadvalini o'chirish, Django uni qaytadan yaratsin.",
        )

    def handle(self, *args, **options) -> None:
        apply_changes: bool = options["apply"]
        drop_users: bool = options["drop_empty_users"]

        with connection.cursor() as cursor:
            present = [table for table in LEGACY_TABLES if _table_exists(cursor, table)]
            if not present:
                self.stdout.write(
                    self.style.WARNING(
                        "Eski jadvallar topilmadi — bu toza baza. "
                        "To'g'ridan-to'g'ri `migrate` ni ishga tushiring."
                    )
                )
                return

            self.stdout.write(f"Topilgan eski jadvallar: {', '.join(present)}")

            # 1. Native enums -> varchar.
            #    The column default (`'new'::materials_status_enum`) depends on
            #    the type, so it has to go first — Django never relies on
            #    database-level defaults anyway.
            planned: list[str] = []
            drop_types: list[str] = []
            for table, column, enum_type, length in ENUM_COLUMNS:
                if not _table_exists(cursor, table):
                    continue

                is_enum = _column_type(cursor, table, column) == "USER-DEFINED"
                default = _column_default(cursor, table, column) or ""
                if not is_enum and enum_type not in default:
                    continue

                if default:
                    planned.append(
                        f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP DEFAULT'
                    )
                if is_enum:
                    planned.append(
                        f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                        f"TYPE varchar({length}) USING \"{column}\"::text"
                    )
                drop_types.append(f'DROP TYPE IF EXISTS "{enum_type}"')

            planned.extend(drop_types)

            if planned:
                self.stdout.write(self.style.MIGRATE_HEADING("Enum -> varchar:"))
                for statement in planned:
                    self.stdout.write(f"  {statement}")
                if apply_changes:
                    for statement in planned:
                        cursor.execute(statement)
                    self.stdout.write(self.style.SUCCESS("  ✔ bajarildi"))
            else:
                self.stdout.write("Enum ustunlari allaqachon varchar — o'zgarish kerak emas.")

            # 2. The users table
            if _table_exists(cursor, "users"):
                count = _row_count(cursor, "users")
                has_last_login = _column_type(cursor, "users", "last_login") is not None

                if has_last_login:
                    self.stdout.write("`users` jadvali allaqachon Django formatida.")
                elif count == 0:
                    self.stdout.write(
                        self.style.MIGRATE_HEADING(
                            "`users` jadvali eski formatda va bo'sh (0 qator)."
                        )
                    )
                    if not drop_users:
                        self.stdout.write(
                            "  Uni qayta yaratish uchun --drop-empty-users bayrog'ini qo'shing."
                        )
                    elif apply_changes:
                        cursor.execute('DROP TABLE "users" CASCADE')
                        self.stdout.write(
                            self.style.SUCCESS("  ✔ o'chirildi — migrate uni qaytadan yaratadi")
                        )
                    else:
                        self.stdout.write('  DROP TABLE "users" CASCADE')
                else:
                    raise CommandError(
                        f"`users` jadvalida {count} ta qator bor, lekin u eski formatda. "
                        "Django auth ustunlari (last_login, is_staff, is_superuser) va "
                        "ruxsat jadvallari yo'q. Ma'lumotni qo'lda ko'chiring yoki "
                        "jadvalni zaxiralab, so'ng --drop-empty-users bilan qayta yarating."
                    )

        if apply_changes:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nTayyor. Endi ishga tushiring:\n"
                    "  python manage.py migrate --fake-initial"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\nBu faqat reja edi. Bajarish uchun --apply bayrog'ini qo'shing."
                )
            )
