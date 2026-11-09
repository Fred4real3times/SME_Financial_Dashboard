"""Workspace-wide role permissions and authorization checks."""

from __future__ import annotations

from enum import StrEnum

from sme_financial_dashboard.db.models import MembershipRole


class Permission(StrEnum):
    VIEW = "view"
    EXPORT = "export"
    IMPORT = "import"
    MANAGE_CATEGORIES = "manage_categories"
    MANAGE_RULES = "manage_rules"
    CORRECT_TRANSACTIONS = "correct_transactions"
    VIEW_AUDIT = "view_audit"
    DELETE_TRANSACTION = "delete_transaction"
    RESTORE_TRANSACTION = "restore_transaction"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_WORKSPACE = "manage_workspace"


ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.ADMIN: frozenset(Permission),
    MembershipRole.ACCOUNTANT: frozenset(
        {
            Permission.VIEW,
            Permission.EXPORT,
            Permission.IMPORT,
            Permission.MANAGE_CATEGORIES,
            Permission.MANAGE_RULES,
            Permission.CORRECT_TRANSACTIONS,
            Permission.VIEW_AUDIT,
            Permission.DELETE_TRANSACTION,
        }
    ),
    MembershipRole.VIEWER: frozenset({Permission.VIEW, Permission.EXPORT}),
}


class AuthorizationError(PermissionError):
    """Raised when a workspace role does not grant the requested permission."""


def has_permission(role: MembershipRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def require_permission(role: MembershipRole, permission: Permission) -> None:
    if not has_permission(role, permission):
        raise AuthorizationError(f"Role {role.value} is not permitted to {permission.value}")
