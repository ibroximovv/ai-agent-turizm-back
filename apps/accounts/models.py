"""Authentication model.

The table keeps the legacy name (`users`) and the legacy password column
(`password_hash`) so an existing database does not need to be rewritten;
Django's own `password` attribute is mapped onto it via ``db_column``.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    ADMIN = "admin", _("Administrator")
    EDITOR = "editor", _("Muharrir")
    VIEWER = "viewer", _("Kuzatuvchi")


class UserManager(BaseUserManager):
    """Email-keyed manager — this project has no `username` column."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra) -> User:
        if not email:
            raise ValueError("Email majburiy")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra) -> User:
        extra.setdefault("role", Role.EDITOR)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra) -> User:
        extra.setdefault("role", Role.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("Superuser uchun is_staff va is_superuser True bo'lishi kerak")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_("Email"), max_length=150, unique=True)
    # Django calls this attribute `password`; the column predates the port.
    password = models.CharField(_("Parol"), max_length=255, db_column="password_hash")
    full_name = models.CharField(_("To'liq ism"), max_length=100, null=True, blank=True)
    role = models.CharField(_("Rol"), max_length=30, choices=Role.choices, default=Role.EDITOR)
    is_active = models.BooleanField(_("Faol"), default=True)
    is_staff = models.BooleanField(
        _("Adminkaga kira oladi"),
        default=True,
        help_text=_("Django admin paneliga kirish huquqi."),
    )
    created_at = models.DateTimeField(_("Yaratilgan"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Yangilangan"), auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"
        verbose_name = _("Foydalanuvchi")
        verbose_name_plural = _("Foydalanuvchilar")
        ordering = ["email"]

    def __str__(self) -> str:
        return self.full_name or self.email

    def get_full_name(self) -> str:
        return self.full_name or self.email

    def get_short_name(self) -> str:
        return self.full_name.split(" ")[0] if self.full_name else self.email

    @property
    def is_admin_role(self) -> bool:
        return self.is_superuser or self.role == Role.ADMIN

    @property
    def can_write(self) -> bool:
        return self.is_superuser or self.role in {Role.ADMIN, Role.EDITOR}
