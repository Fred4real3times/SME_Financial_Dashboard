import pytest

from sme_financial_dashboard.db.models import MembershipRole
from sme_financial_dashboard.security.rbac import (
    AuthorizationError,
    Permission,
    has_permission,
    require_permission,
)


@pytest.mark.parametrize(
    "role,permission,allowed",
    [
        (MembershipRole.ADMIN, Permission.RESTORE_TRANSACTION, True),
        (MembershipRole.ACCOUNTANT, Permission.DELETE_TRANSACTION, True),
        (MembershipRole.ACCOUNTANT, Permission.RESTORE_TRANSACTION, False),
        (MembershipRole.VIEWER, Permission.EXPORT, True),
        (MembershipRole.VIEWER, Permission.IMPORT, False),
        (MembershipRole.VIEWER, Permission.DELETE_TRANSACTION, False),
    ],
)
def test_role_permission_matrix(role, permission, allowed):
    assert has_permission(role, permission) is allowed
    if allowed:
        require_permission(role, permission)
    else:
        with pytest.raises(AuthorizationError):
            require_permission(role, permission)
