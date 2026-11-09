from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sme_financial_dashboard.db.base import Base
from sme_financial_dashboard.db.models import (
    Company,
    MembershipRole,
    User,
    Workspace,
    WorkspaceMembership,
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as active:
        yield active
    engine.dispose()


def seed_workspace(
    session: Session,
    name: str,
    email: str,
    company_name: str,
    role: MembershipRole = MembershipRole.ACCOUNTANT,
) -> tuple[Workspace, User, Company]:
    workspace = Workspace(name=name)
    user = User(email=email, password_hash="test-hash", display_name="Tester", is_active=True)
    company = Company(name=company_name, base_currency="XAF", timezone="Africa/Douala", is_demo=True)
    workspace.companies.append(company)
    workspace.memberships.append(WorkspaceMembership(user=user, role=role))
    session.add(workspace)
    session.flush()
    return workspace, user, company
