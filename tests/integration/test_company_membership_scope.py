from conftest import seed_workspace

from sme_financial_dashboard.db.models import MembershipRole
from sme_financial_dashboard.security.company_scope import (
    CompanyAccessDenied,
    resolve_company_context,
)


def test_deactivated_workspace_membership_loses_company_access(session):
    workspace, user, company = seed_workspace(
        session, "Workspace", "user@example.test", "Company", MembershipRole.ACCOUNTANT
    )
    membership = workspace.memberships[0]
    membership.is_active = False
    session.flush()
    try:
        resolve_company_context(session, user_id=user.id, company_id=company.id)
    except CompanyAccessDenied:
        pass
    else:
        raise AssertionError("deactivated workspace membership still had company access")
