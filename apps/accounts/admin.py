from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm
from unfold.admin import ModelAdmin
from unfold.decorators import display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm

from apps.accounts.models import Role, User

ROLE_VARIANTS = {
    Role.ADMIN: "danger",
    Role.EDITOR: "info",
    Role.VIEWER: "",
}


class UserCreateForm(AdminUserCreationForm):
    """`AdminUserCreationForm`, not `UserCreationForm`: only the admin variant
    declares the `usable_password` toggle that `add_fieldsets` references."""

    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ["email", "full_name", "role"]


class UserEditForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    form = UserEditForm
    add_form = UserCreateForm
    change_password_form = AdminPasswordChangeForm

    list_display = ["email_display", "role_badge", "is_active", "is_staff", "last_login"]
    list_filter = ["role", "is_active", "is_staff", "is_superuser"]
    list_filter_submit = True
    search_fields = ["email", "full_name"]
    ordering = ["email"]
    compressed_fields = True
    warn_unsaved_form = True
    readonly_fields = ["id", "last_login", "created_at", "updated_at"]

    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Profil", {"fields": ["full_name", "role"]}),
        (
            "Huquqlar",
            {
                "fields": [
                    "is_active", "is_staff", "is_superuser", "groups", "user_permissions"
                ],
                "description": (
                    "<b>Rol</b> API huquqlarini belgilaydi: admin — hammasi, "
                    "muharrir — o'chirishdan tashqari, kuzatuvchi — faqat o'qish. "
                    "Django guruh/ruxsatlari adminka ko'rinishini boshqaradi."
                ),
            },
        ),
        (
            "Tizim",
            {
                "fields": ["id", "last_login", "created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    add_fieldsets = [
        (
            None,
            {
                "classes": ["wide"],
                "fields": [
                    "email", "full_name", "role",
                    "usable_password", "password1", "password2",
                ],
            },
        )
    ]

    @display(description="Foydalanuvchi", ordering="email", header=True)
    def email_display(self, obj: User) -> list[str]:
        return [obj.email, obj.full_name or "—"]

    @display(description="Rol", ordering="role", label=ROLE_VARIANTS)
    def role_badge(self, obj: User) -> tuple[str, str]:
        return obj.role, obj.get_role_display()
