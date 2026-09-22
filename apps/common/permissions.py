"""Role-aware API permissions.

The roles are deliberately coarse — this backend has one kind of client (the
admin panel and its operators):

======  ============================================
role    allowed
======  ============================================
admin   everything, including deletes
editor  read + create/update, but not delete
viewer  read only
======  ============================================
"""

from __future__ import annotations

from rest_framework import permissions

SAFE_METHODS = permissions.SAFE_METHODS
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})
DELETE_METHODS = frozenset({"DELETE"})


class RoleBasedPermission(permissions.BasePermission):
    """Default permission for every API view."""

    message = "Bu amal uchun huquqingiz yetarli emas."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if user.is_superuser:
            return True

        role = getattr(user, "role", None)
        if request.method in SAFE_METHODS:
            return True
        if request.method in DELETE_METHODS:
            return role == "admin"
        if request.method in WRITE_METHODS:
            return role in {"admin", "editor"}
        return False


class IsAdminRole(permissions.BasePermission):
    """For endpoints that manage other users or global integration settings."""

    message = "Faqat administrator uchun."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and (user.is_superuser or getattr(user, "role", None) == "admin")
        )
