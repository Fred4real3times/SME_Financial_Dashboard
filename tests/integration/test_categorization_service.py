from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from conftest import seed_workspace
from sme_financial_dashboard.db.models import (
    AuditEvent,
    CategorizationSource,
    Category,
    CategoryKind,
    Direction,
    MatchField,
    MatchOperator,
    MembershipRole,
    Transaction,
)
from sme_financial_dashboard.security.company_scope import resolve_company_context
from sme_financial_dashboard.services.categorization_service import (
    CategorizationError,
    CategorizationOutcome,
    CategorizationRuleService,
    CategorizationService,
    CategoryNotFound,
    CategoryService,
)


def _context(session, *, role=MembershipRole.ACCOUNTANT, suffix="categorize"):
    workspace, user, company = seed_workspace(
        session,
        f"Workspace {suffix}",
        f"{suffix}@example.test",
        f"Company {suffix}",
        role,
    )
    session.flush()
    context = resolve_company_context(
        session, user_id=user.id, company_id=company.id
    )
    return workspace, user, company, context


def _transaction(
    session,
    company,
    *,
    suffix="transaction",
    description="Vendor payment",
    counterparty="Vendor",
    reference="REF-1",
    direction=Direction.OUTFLOW,
):
    transaction = Transaction(
        company_id=company.id,
        transaction_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        currency="XAF",
        direction=direction,
        description=description,
        counterparty=counterparty,
        reference=reference,
        fingerprint_version=1,
        source_fingerprint=hashlib.sha256(suffix.encode()).hexdigest(),
        is_validated=True,
    )
    session.add(transaction)
    session.flush()
    return transaction


def test_category_names_are_normalized_and_unique_with_audit(session):
    _workspace, _user, company, context = _context(session)
    category = CategoryService.create_category(
        session, context, name="  Office   Supplies ", kind=CategoryKind.OUTFLOW
    )
    assert category.name == "Office   Supplies"
    assert category.normalized_name == "office supplies"
    with pytest.raises(CategorizationError, match="already exists"):
        CategoryService.create_category(
            session, context, name="office supplies", kind=CategoryKind.BOTH
        )
    assert session.scalar(
        select(func.count()).select_from(Category).where(Category.company_id == company.id)
    ) == 1
    event = session.scalar(
        select(AuditEvent).where(AuditEvent.entity_id == category.id)
    )
    assert event.action == "CATEGORY_CREATED"


def test_viewer_cannot_create_categories_or_rules(session):
    _workspace, _user, _company, context = _context(
        session, role=MembershipRole.VIEWER, suffix="viewer-categories"
    )
    with pytest.raises(PermissionError):
        CategoryService.create_category(session, context, name="Office")
    with pytest.raises(PermissionError):
        CategorizationRuleService.create_rule(
            session,
            context,
            category_id=uuid4(),
            match_field=MatchField.KEYWORD,
            operator=MatchOperator.CONTAINS,
            match_value="office",
        )


def test_higher_numeric_priority_wins_and_repeat_application_is_idempotent(session):
    _workspace, _user, company, context = _context(session, suffix="priority")
    general = CategoryService.create_category(
        session, context, name="General transport", kind=CategoryKind.OUTFLOW
    )
    preferred = CategoryService.create_category(
        session, context, name="Preferred transport", kind=CategoryKind.OUTFLOW
    )
    CategorizationRuleService.create_rule(
        session,
        context,
        category_id=general.id,
        match_field=MatchField.KEYWORD,
        operator=MatchOperator.CONTAINS,
        match_value="taxi",
        priority=50,
    )
    winning_rule = CategorizationRuleService.create_rule(
        session,
        context,
        category_id=preferred.id,
        match_field=MatchField.COUNTERPARTY,
        operator=MatchOperator.EQUALS,
        match_value="RideCo",
        priority=100,
    )
    transaction = _transaction(
        session,
        company,
        suffix="priority-transaction",
        description="Taxi charge",
        counterparty="  RIDECO ",
    )

    result = CategorizationService.apply_rules(
        session, context, transaction_id=transaction.id
    )
    assert result.outcome is CategorizationOutcome.APPLIED
    assert result.category_id == preferred.id
    assert result.rule_id == winning_rule.id
    repeated = CategorizationService.apply_rules(
        session, context, transaction_id=transaction.id
    )
    assert repeated.outcome is CategorizationOutcome.ALREADY_APPLIED
    assert session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == transaction.id,
            AuditEvent.action == "CATEGORIZATION_RULE_APPLIED",
        )
    ) == 1


def test_tied_highest_priority_rules_require_manual_review(session):
    _workspace, _user, company, context = _context(session, suffix="tie")
    one = CategoryService.create_category(session, context, name="Bank fees")
    two = CategoryService.create_category(session, context, name="Finance")
    CategorizationRuleService.create_rule(
        session,
        context,
        category_id=one.id,
        match_field=MatchField.KEYWORD,
        operator=MatchOperator.CONTAINS,
        match_value="bank",
        priority=100,
    )
    CategorizationRuleService.create_rule(
        session,
        context,
        category_id=two.id,
        match_field=MatchField.KEYWORD,
        operator=MatchOperator.CONTAINS,
        match_value="bank",
        priority=100,
    )
    transaction = _transaction(
        session, company, suffix="tie-transaction", description="Bank service charge"
    )
    result = CategorizationService.apply_rules(
        session, context, transaction_id=transaction.id
    )
    assert result.outcome is CategorizationOutcome.NEEDS_REVIEW
    session.refresh(transaction)
    assert transaction.category_id is None
    assert transaction.categorization_source is CategorizationSource.NONE
    assert session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == transaction.id,
            AuditEvent.action == "CATEGORIZATION_RULE_CONFLICT",
        )
    ) == 1


def test_manual_category_assignment_is_audited_and_not_overwritten_by_rules(session):
    _workspace, _user, company, context = _context(session, suffix="manual")
    manual = CategoryService.create_category(session, context, name="Manual category")
    auto = CategoryService.create_category(session, context, name="Automatic category")
    CategorizationRuleService.create_rule(
        session,
        context,
        category_id=auto.id,
        match_field=MatchField.KEYWORD,
        operator=MatchOperator.CONTAINS,
        match_value="supplier",
        priority=10,
    )
    transaction = _transaction(
        session, company, suffix="manual-transaction", description="Supplier payment"
    )
    updated = CategorizationService.assign_manual_category(
        session, context, transaction_id=transaction.id, category_id=manual.id
    )
    assert updated.category_id == manual.id
    assert updated.categorization_source is CategorizationSource.MANUAL
    result = CategorizationService.apply_rules(
        session, context, transaction_id=transaction.id
    )
    assert result.outcome is CategorizationOutcome.MANUAL_OVERRIDE
    session.refresh(transaction)
    assert transaction.category_id == manual.id
    audit_actions = session.scalars(
        select(AuditEvent.action).where(AuditEvent.entity_id == transaction.id)
    ).all()
    assert "TRANSACTION_CATEGORY_MANUALLY_UPDATED" in audit_actions


def test_category_kind_must_match_transaction_direction(session):
    _workspace, _user, company, context = _context(session, suffix="kind")
    outgoing = CategoryService.create_category(
        session, context, name="Outflows only", kind=CategoryKind.OUTFLOW
    )
    CategorizationRuleService.create_rule(
        session,
        context,
        category_id=outgoing.id,
        match_field=MatchField.KEYWORD,
        operator=MatchOperator.CONTAINS,
        match_value="customer",
    )
    transaction = _transaction(
        session,
        company,
        suffix="inflow-transaction",
        description="Customer payment",
        direction=Direction.INFLOW,
    )
    result = CategorizationService.apply_rules(
        session, context, transaction_id=transaction.id
    )
    assert result.outcome is CategorizationOutcome.NO_MATCH
    assert transaction.category_id is None


def test_category_cannot_be_deactivated_while_active_rules_reference_it(session):
    _workspace, _user, _company, context = _context(session, suffix="deactivate")
    category = CategoryService.create_category(session, context, name="Utilities")
    CategorizationRuleService.create_rule(
        session,
        context,
        category_id=category.id,
        match_field=MatchField.KEYWORD,
        operator=MatchOperator.CONTAINS,
        match_value="electricity",
    )
    with pytest.raises(CategorizationError, match="Deactivate this category's active rules"):
        CategoryService.update_category(
            session, context, category_id=category.id, is_active=False
        )


def test_cross_company_category_cannot_be_attached_to_a_rule(session):
    _workspace_a, _user_a, _company_a, context_a = _context(session, suffix="company-a")
    _workspace_b, _user_b, _company_b, context_b = _context(session, suffix="company-b")
    foreign_category = CategoryService.create_category(
        session, context_b, name="Foreign category"
    )
    with pytest.raises(CategoryNotFound):
        CategorizationRuleService.create_rule(
            session,
            context_a,
            category_id=foreign_category.id,
            match_field=MatchField.KEYWORD,
            operator=MatchOperator.CONTAINS,
            match_value="foreign",
        )
