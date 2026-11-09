"""Company-scoped category and deterministic transaction categorization services."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import (
    AuditEvent,
    CategorizationRule,
    CategorizationSource,
    Category,
    CategoryKind,
    Direction,
    MatchField,
    MatchOperator,
    Transaction,
)
from sme_financial_dashboard.security.company_scope import (
    CompanyContext,
    resolve_company_context,
)
from sme_financial_dashboard.security.rbac import Permission, require_permission


class CategorizationError(ValueError):
    """Base class for category and rule validation errors."""


class CategoryNotFound(CategorizationError):
    """Raised when a category does not exist in the active company."""


class RuleNotFound(CategorizationError):
    """Raised when a rule does not exist in the active company."""


class TransactionNotFound(CategorizationError):
    """Raised when an active company transaction cannot be found."""


class CategorizationOutcome(StrEnum):
    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    NO_MATCH = "NO_MATCH"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


@dataclass(frozen=True, slots=True)
class CategorizationResult:
    transaction_id: UUID
    outcome: CategorizationOutcome
    category_id: UUID | None = None
    rule_id: UUID | None = None


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _display_text(value: str, *, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise CategorizationError(f"{field_name} must be text.")
    cleaned = unicodedata.normalize("NFKC", value).strip()
    if not cleaned:
        raise CategorizationError(f"{field_name} is required.")
    if len(cleaned) > max_length:
        raise CategorizationError(f"{field_name} exceeds {max_length} characters.")
    if any(ord(char) < 32 and char not in "\t" for char in cleaned):
        raise CategorizationError(f"{field_name} contains unsupported control characters.")
    return cleaned


def _validated_category_kind(value: CategoryKind | str) -> CategoryKind:
    try:
        return value if isinstance(value, CategoryKind) else CategoryKind(value)
    except ValueError as exc:
        raise CategorizationError("Category kind must be INFLOW, OUTFLOW or BOTH.") from exc


def _validated_match_field(value: MatchField | str) -> MatchField:
    try:
        return value if isinstance(value, MatchField) else MatchField(value)
    except ValueError as exc:
        raise CategorizationError("Unsupported rule match field.") from exc


def _validated_match_operator(value: MatchOperator | str) -> MatchOperator:
    try:
        return value if isinstance(value, MatchOperator) else MatchOperator(value)
    except ValueError as exc:
        raise CategorizationError("Unsupported rule match operator.") from exc


def _validated_priority(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10_000:
        raise CategorizationError("Rule priority must be an integer from 1 to 10,000.")
    return value


def _audit(
    session: Session,
    *,
    context: CompanyContext,
    action: str,
    entity_type: str,
    entity_id: UUID,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            company_id=context.company_id,
            actor_user_id=context.user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
        )
    )


def _verified_context(
    session: Session, context: CompanyContext, permission: Permission
) -> CompanyContext:
    verified = resolve_company_context(
        session, user_id=context.user_id, company_id=context.company_id
    )
    require_permission(verified.role, permission)
    return verified



def _resolve_active_category(
    session: Session, context: CompanyContext, category_id: UUID
) -> Category:
    category = session.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.company_id == context.company_id,
            Category.is_active.is_(True),
        )
    )
    if category is None:
        raise CategoryNotFound("Active category was not found in the active company.")
    return category


class CategoryService:
    """CRUD-like category management; categories are deactivated, never physically deleted."""

    @staticmethod
    def list_categories(
        session: Session, context: CompanyContext, *, include_inactive: bool = False
    ) -> list[Category]:
        verified = _verified_context(session, context, Permission.VIEW)
        statement = select(Category).where(Category.company_id == verified.company_id)
        if not include_inactive:
            statement = statement.where(Category.is_active.is_(True))
        statement = statement.order_by(Category.normalized_name, Category.id)
        return list(session.scalars(statement).all())

    @staticmethod
    def create_category(
        session: Session,
        context: CompanyContext,
        *,
        name: str,
        kind: CategoryKind | str = CategoryKind.BOTH,
    ) -> Category:
        verified = _verified_context(session, context, Permission.MANAGE_CATEGORIES)
        display_name = _display_text(name, field_name="Category name", max_length=80)
        normalized_name = _normalize_text(display_name)
        category_kind = _validated_category_kind(kind)
        existing = session.scalar(
            select(Category.id).where(
                Category.company_id == verified.company_id,
                Category.normalized_name == normalized_name,
            )
        )
        if existing is not None:
            raise CategorizationError("A category with this name already exists in the company.")
        category = Category(
            company_id=verified.company_id,
            name=display_name,
            normalized_name=normalized_name,
            kind=category_kind,
            is_active=True,
        )
        try:
            with session.begin_nested():
                session.add(category)
                session.flush()
                _audit(
                    session,
                    context=verified,
                    action="CATEGORY_CREATED",
                    entity_type="CATEGORY",
                    entity_id=category.id,
                    after={
                        "name": category.name,
                        "kind": category.kind.value,
                        "is_active": category.is_active,
                    },
                )
                session.flush()
        except IntegrityError as exc:
            raise CategorizationError("Category name already exists in this company.") from exc
        return category

    @staticmethod
    def update_category(
        session: Session,
        context: CompanyContext,
        *,
        category_id: UUID,
        name: str | None = None,
        kind: CategoryKind | str | None = None,
        is_active: bool | None = None,
    ) -> Category:
        verified = _verified_context(session, context, Permission.MANAGE_CATEGORIES)
        category = session.scalar(
            select(Category).where(
                Category.id == category_id,
                Category.company_id == verified.company_id,
            )
        )
        if category is None:
            raise CategoryNotFound("Category was not found in the active company.")
        before = {
            "name": category.name,
            "kind": category.kind.value,
            "is_active": category.is_active,
        }
        new_name = (
            _display_text(name, field_name="Category name", max_length=80)
            if name is not None
            else category.name
        )
        new_normalized_name = _normalize_text(new_name)
        new_kind = _validated_category_kind(kind) if kind is not None else category.kind
        if new_normalized_name != category.normalized_name:
            duplicate = session.scalar(
                select(Category.id).where(
                    Category.company_id == verified.company_id,
                    Category.normalized_name == new_normalized_name,
                    Category.id != category.id,
                )
            )
            if duplicate is not None:
                raise CategorizationError("A category with this name already exists in the company.")
        if is_active is not None and not isinstance(is_active, bool):
            raise CategorizationError("is_active must be a boolean.")
        if category.is_active and is_active is False:
            active_rules = session.scalar(
                select(func.count()).select_from(CategorizationRule).where(
                    CategorizationRule.company_id == verified.company_id,
                    CategorizationRule.category_id == category.id,
                    CategorizationRule.is_active.is_(True),
                )
            )
            if active_rules:
                raise CategorizationError(
                    "Deactivate this category's active rules before deactivating the category."
                )
        if new_kind is not category.kind and new_kind is not CategoryKind.BOTH:
            incompatible_direction = (
                Direction.INFLOW if new_kind is CategoryKind.INFLOW else Direction.OUTFLOW
            )
            incompatible_count = session.scalar(
                select(func.count()).select_from(Transaction).where(
                    Transaction.company_id == verified.company_id,
                    Transaction.category_id == category.id,
                    Transaction.direction != incompatible_direction,
                )
            )
            if incompatible_count:
                raise CategorizationError(
                    "Category kind cannot change while transactions use the opposite direction."
                )
        try:
            with session.begin_nested():
                category.name = new_name
                category.normalized_name = new_normalized_name
                category.kind = new_kind
                if is_active is not None:
                    category.is_active = is_active
                session.flush()
                after = {
                    "name": category.name,
                    "kind": category.kind.value,
                    "is_active": category.is_active,
                }
                if before != after:
                    _audit(
                        session,
                        context=verified,
                        action="CATEGORY_UPDATED",
                        entity_type="CATEGORY",
                        entity_id=category.id,
                        before=before,
                        after=after,
                    )
                    session.flush()
        except IntegrityError as exc:
            raise CategorizationError("Category update conflicts with an existing company category.") from exc
        return category


class CategorizationRuleService:
    """Manage company-scoped rules; larger priority numbers have precedence."""

    @staticmethod
    def list_rules(
        session: Session, context: CompanyContext, *, include_inactive: bool = False
    ) -> list[CategorizationRule]:
        verified = _verified_context(session, context, Permission.VIEW)
        statement = select(CategorizationRule).where(
            CategorizationRule.company_id == verified.company_id
        )
        if not include_inactive:
            statement = statement.where(CategorizationRule.is_active.is_(True))
        statement = statement.order_by(
            CategorizationRule.priority.desc(), CategorizationRule.id
        )
        return list(session.scalars(statement).all())

    @staticmethod
    def _resolve_category(
        session: Session, context: CompanyContext, category_id: UUID
    ) -> Category:
        return _resolve_active_category(session, context, category_id)

    @staticmethod
    def create_rule(
        session: Session,
        context: CompanyContext,
        *,
        category_id: UUID,
        match_field: MatchField | str,
        operator: MatchOperator | str,
        match_value: str,
        priority: int = 100,
    ) -> CategorizationRule:
        verified = _verified_context(session, context, Permission.MANAGE_RULES)
        category = CategorizationRuleService._resolve_category(
            session, verified, category_id
        )
        field = _validated_match_field(match_field)
        match_operator = _validated_match_operator(operator)
        display_value = _display_text(
            match_value, field_name="Rule match value", max_length=200
        )
        normalized_value = _normalize_text(display_value)
        rule_priority = _validated_priority(priority)
        rule = CategorizationRule(
            company_id=verified.company_id,
            category_id=category.id,
            match_field=field,
            operator=match_operator,
            match_value=normalized_value,
            priority=rule_priority,
            is_active=True,
        )
        session.add(rule)
        session.flush()
        _audit(
            session,
            context=verified,
            action="CATEGORIZATION_RULE_CREATED",
            entity_type="CATEGORIZATION_RULE",
            entity_id=rule.id,
            after={
                "category_id": str(rule.category_id),
                "match_field": rule.match_field.value,
                "operator": rule.operator.value,
                "match_value": rule.match_value,
                "priority": rule.priority,
                "is_active": rule.is_active,
            },
        )
        return rule

    @staticmethod
    def update_rule(
        session: Session,
        context: CompanyContext,
        *,
        rule_id: UUID,
        category_id: UUID | None = None,
        match_field: MatchField | str | None = None,
        operator: MatchOperator | str | None = None,
        match_value: str | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
    ) -> CategorizationRule:
        verified = _verified_context(session, context, Permission.MANAGE_RULES)
        rule = session.scalar(
            select(CategorizationRule).where(
                CategorizationRule.id == rule_id,
                CategorizationRule.company_id == verified.company_id,
            )
        )
        if rule is None:
            raise RuleNotFound("Categorization rule was not found in the active company.")
        before = {
            "category_id": str(rule.category_id),
            "match_field": rule.match_field.value,
            "operator": rule.operator.value,
            "match_value": rule.match_value,
            "priority": rule.priority,
            "is_active": rule.is_active,
        }
        if category_id is not None:
            rule.category_id = CategorizationRuleService._resolve_category(
                session, verified, category_id
            ).id
        if match_field is not None:
            rule.match_field = _validated_match_field(match_field)
        if operator is not None:
            rule.operator = _validated_match_operator(operator)
        if match_value is not None:
            rule.match_value = _normalize_text(
                _display_text(match_value, field_name="Rule match value", max_length=200)
            )
        if priority is not None:
            rule.priority = _validated_priority(priority)
        if is_active is not None:
            if not isinstance(is_active, bool):
                raise CategorizationError("is_active must be a boolean.")
            rule.is_active = is_active
        session.flush()
        after = {
            "category_id": str(rule.category_id),
            "match_field": rule.match_field.value,
            "operator": rule.operator.value,
            "match_value": rule.match_value,
            "priority": rule.priority,
            "is_active": rule.is_active,
        }
        if before != after:
            _audit(
                session,
                context=verified,
                action="CATEGORIZATION_RULE_UPDATED",
                entity_type="CATEGORIZATION_RULE",
                entity_id=rule.id,
                before=before,
                after=after,
            )
        return rule


class CategorizationService:
    """Apply deterministic priority rules and preserve manual overrides."""

    @staticmethod
    def _field_value(rule: CategorizationRule, transaction: Transaction) -> str:
        value = {
            MatchField.KEYWORD: transaction.description,
            MatchField.COUNTERPARTY: transaction.counterparty,
            MatchField.REFERENCE: transaction.reference,
        }[rule.match_field]
        return _normalize_text(value or "")

    @staticmethod
    def _matches(rule: CategorizationRule, transaction: Transaction) -> bool:
        value = CategorizationService._field_value(rule, transaction)
        target = _normalize_text(rule.match_value)
        if not value or not target:
            return False
        if rule.operator is MatchOperator.CONTAINS:
            return target in value
        if rule.operator is MatchOperator.EQUALS:
            return value == target
        if rule.operator is MatchOperator.STARTS_WITH:
            return value.startswith(target)
        return False

    @staticmethod
    def apply_rules(
        session: Session,
        context: CompanyContext,
        *,
        transaction_id: UUID,
    ) -> CategorizationResult:
        verified = _verified_context(session, context, Permission.MANAGE_RULES)
        transaction = session.scalar(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.company_id == verified.company_id,
                Transaction.deleted_at.is_(None),
            )
        )
        if transaction is None:
            raise TransactionNotFound("Active transaction was not found in the active company.")
        if transaction.categorization_source is CategorizationSource.MANUAL:
            return CategorizationResult(
                transaction_id, CategorizationOutcome.MANUAL_OVERRIDE,
                transaction.category_id, transaction.categorization_rule_id
            )

        rules_with_categories = session.execute(
            select(CategorizationRule, Category)
            .join(
                Category,
                (Category.id == CategorizationRule.category_id)
                & (Category.company_id == CategorizationRule.company_id),
            )
            .where(
                CategorizationRule.company_id == verified.company_id,
                CategorizationRule.is_active.is_(True),
                Category.is_active.is_(True),
            )
            .order_by(CategorizationRule.priority.desc(), CategorizationRule.id)
        ).all()
        matches = [
            (rule, category)
            for rule, category in rules_with_categories
            if (
                category.kind is CategoryKind.BOTH
                or category.kind.value == transaction.direction.value
            )
            and CategorizationService._matches(rule, transaction)
        ]

        before = {
            "category_id": str(transaction.category_id) if transaction.category_id else None,
            "categorization_source": transaction.categorization_source.value,
            "categorization_rule_id": (
                str(transaction.categorization_rule_id)
                if transaction.categorization_rule_id
                else None
            ),
        }
        if not matches:
            if transaction.categorization_source is CategorizationSource.RULE:
                transaction.category_id = None
                transaction.categorization_rule_id = None
                transaction.categorization_source = CategorizationSource.NONE
                session.flush()
                _audit(
                    session,
                    context=verified,
                    action="CATEGORIZATION_RULE_CLEARED",
                    entity_type="TRANSACTION",
                    entity_id=transaction.id,
                    before=before,
                    after={
                        "category_id": None,
                        "categorization_source": CategorizationSource.NONE.value,
                        "categorization_rule_id": None,
                    },
                )
            return CategorizationResult(
                transaction.id, CategorizationOutcome.NO_MATCH, transaction.category_id, None
            )

        highest_priority = max(rule.priority for rule, _category in matches)
        top_matches = [
            (rule, category)
            for rule, category in matches
            if rule.priority == highest_priority
        ]
        if len(top_matches) != 1:
            if transaction.categorization_source is CategorizationSource.RULE:
                transaction.category_id = None
                transaction.categorization_rule_id = None
                transaction.categorization_source = CategorizationSource.NONE
                session.flush()
            _audit(
                session,
                context=verified,
                action="CATEGORIZATION_RULE_CONFLICT",
                entity_type="TRANSACTION",
                entity_id=transaction.id,
                before=before,
                after={
                    "outcome": CategorizationOutcome.NEEDS_REVIEW.value,
                    "priority": highest_priority,
                    "candidate_rule_ids": [str(rule.id) for rule, _ in top_matches],
                },
            )
            return CategorizationResult(
                transaction.id, CategorizationOutcome.NEEDS_REVIEW,
                transaction.category_id, None
            )

        winning_rule, winning_category = top_matches[0]
        if (
            transaction.categorization_source is CategorizationSource.RULE
            and transaction.categorization_rule_id == winning_rule.id
            and transaction.category_id == winning_category.id
        ):
            return CategorizationResult(
                transaction.id, CategorizationOutcome.ALREADY_APPLIED,
                transaction.category_id, winning_rule.id
            )

        transaction.category_id = winning_category.id
        transaction.categorization_source = CategorizationSource.RULE
        transaction.categorization_rule_id = winning_rule.id
        session.flush()
        _audit(
            session,
            context=verified,
            action="CATEGORIZATION_RULE_APPLIED",
            entity_type="TRANSACTION",
            entity_id=transaction.id,
            before=before,
            after={
                "category_id": str(winning_category.id),
                "categorization_source": CategorizationSource.RULE.value,
                "categorization_rule_id": str(winning_rule.id),
            },
        )
        return CategorizationResult(
            transaction.id, CategorizationOutcome.APPLIED,
            winning_category.id, winning_rule.id
        )


    @staticmethod
    def apply_rules_to_transactions(
        session: Session,
        context: CompanyContext,
        *,
        transactions: list[Transaction],
    ) -> dict[UUID, CategorizationResult]:
        """Apply one company rule snapshot to a batch without per-row rule queries."""
        verified = _verified_context(session, context, Permission.MANAGE_RULES)
        rules_with_categories = session.execute(
            select(CategorizationRule, Category)
            .join(
                Category,
                (Category.id == CategorizationRule.category_id)
                & (Category.company_id == CategorizationRule.company_id),
            )
            .where(
                CategorizationRule.company_id == verified.company_id,
                CategorizationRule.is_active.is_(True),
                Category.is_active.is_(True),
            )
            .order_by(CategorizationRule.priority.desc(), CategorizationRule.id)
        ).all()
        results: dict[UUID, CategorizationResult] = {}
        for transaction in transactions:
            if transaction.company_id != verified.company_id or transaction.deleted_at is not None:
                raise TransactionNotFound(
                    "Batch categorization only accepts active transactions from the verified company."
                )
            if transaction.id is None:
                raise CategorizationError("Transactions must be flushed before rule categorization.")
            if transaction.categorization_source is CategorizationSource.MANUAL:
                results[transaction.id] = CategorizationResult(
                    transaction.id,
                    CategorizationOutcome.MANUAL_OVERRIDE,
                    transaction.category_id,
                    transaction.categorization_rule_id,
                )
                continue
            matches = [
                (rule, category)
                for rule, category in rules_with_categories
                if (
                    category.kind is CategoryKind.BOTH
                    or category.kind.value == transaction.direction.value
                )
                and CategorizationService._matches(rule, transaction)
            ]
            before = {
                "category_id": str(transaction.category_id) if transaction.category_id else None,
                "categorization_source": transaction.categorization_source.value,
                "categorization_rule_id": (
                    str(transaction.categorization_rule_id)
                    if transaction.categorization_rule_id
                    else None
                ),
            }
            if not matches:
                if transaction.categorization_source is CategorizationSource.RULE:
                    transaction.category_id = None
                    transaction.categorization_rule_id = None
                    transaction.categorization_source = CategorizationSource.NONE
                    _audit(
                        session,
                        context=verified,
                        action="CATEGORIZATION_RULE_CLEARED",
                        entity_type="TRANSACTION",
                        entity_id=transaction.id,
                        before=before,
                        after={
                            "category_id": None,
                            "categorization_source": CategorizationSource.NONE.value,
                            "categorization_rule_id": None,
                        },
                    )
                results[transaction.id] = CategorizationResult(
                    transaction.id,
                    CategorizationOutcome.NO_MATCH,
                    transaction.category_id,
                    None,
                )
                continue
            highest_priority = max(rule.priority for rule, _category in matches)
            top_matches = [
                (rule, category)
                for rule, category in matches
                if rule.priority == highest_priority
            ]
            if len(top_matches) != 1:
                if transaction.categorization_source is CategorizationSource.RULE:
                    transaction.category_id = None
                    transaction.categorization_rule_id = None
                    transaction.categorization_source = CategorizationSource.NONE
                _audit(
                    session,
                    context=verified,
                    action="CATEGORIZATION_RULE_CONFLICT",
                    entity_type="TRANSACTION",
                    entity_id=transaction.id,
                    before=before,
                    after={
                        "outcome": CategorizationOutcome.NEEDS_REVIEW.value,
                        "priority": highest_priority,
                        "candidate_rule_ids": [str(rule.id) for rule, _ in top_matches],
                    },
                )
                results[transaction.id] = CategorizationResult(
                    transaction.id,
                    CategorizationOutcome.NEEDS_REVIEW,
                    transaction.category_id,
                    None,
                )
                continue
            winning_rule, winning_category = top_matches[0]
            if (
                transaction.categorization_source is CategorizationSource.RULE
                and transaction.categorization_rule_id == winning_rule.id
                and transaction.category_id == winning_category.id
            ):
                results[transaction.id] = CategorizationResult(
                    transaction.id,
                    CategorizationOutcome.ALREADY_APPLIED,
                    transaction.category_id,
                    winning_rule.id,
                )
                continue
            transaction.category_id = winning_category.id
            transaction.categorization_source = CategorizationSource.RULE
            transaction.categorization_rule_id = winning_rule.id
            _audit(
                session,
                context=verified,
                action="CATEGORIZATION_RULE_APPLIED",
                entity_type="TRANSACTION",
                entity_id=transaction.id,
                before=before,
                after={
                    "category_id": str(winning_category.id),
                    "categorization_source": CategorizationSource.RULE.value,
                    "categorization_rule_id": str(winning_rule.id),
                },
            )
            results[transaction.id] = CategorizationResult(
                transaction.id,
                CategorizationOutcome.APPLIED,
                winning_category.id,
                winning_rule.id,
            )
        session.flush()
        return results


    @staticmethod
    def assign_manual_category(
        session: Session,
        context: CompanyContext,
        *,
        transaction_id: UUID,
        category_id: UUID | None,
    ) -> Transaction:
        verified = _verified_context(
            session, context, Permission.CORRECT_TRANSACTIONS
        )
        transaction = session.scalar(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.company_id == verified.company_id,
                Transaction.deleted_at.is_(None),
            )
        )
        if transaction is None:
            raise TransactionNotFound("Active transaction was not found in the active company.")
        category = None
        if category_id is not None:
            category = _resolve_active_category(session, verified, category_id)
            if (
                category.kind is not CategoryKind.BOTH
                and category.kind.value != transaction.direction.value
            ):
                raise CategorizationError("Category kind does not match the transaction direction.")
        before = {
            "category_id": str(transaction.category_id) if transaction.category_id else None,
            "categorization_source": transaction.categorization_source.value,
            "categorization_rule_id": (
                str(transaction.categorization_rule_id)
                if transaction.categorization_rule_id
                else None
            ),
        }
        transaction.category_id = category.id if category else None
        transaction.categorization_rule_id = None
        transaction.categorization_source = (
            CategorizationSource.MANUAL if category else CategorizationSource.NONE
        )
        session.flush()
        after = {
            "category_id": str(transaction.category_id) if transaction.category_id else None,
            "categorization_source": transaction.categorization_source.value,
            "categorization_rule_id": None,
        }
        if before != after:
            _audit(
                session,
                context=verified,
                action="TRANSACTION_CATEGORY_MANUALLY_UPDATED",
                entity_type="TRANSACTION",
                entity_id=transaction.id,
                before=before,
                after=after,
            )
        return transaction

