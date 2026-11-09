"""Human review queue for ambiguous statement rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import (
    AuditEvent,
    Direction,
    ImportBatch,
    ImportBatchStatus,
    ImportRow,
    ImportRowStatus,
    ReviewDecision,
    Transaction,
)
from sme_financial_dashboard.domain.fingerprints import (
    FINGERPRINT_VERSION,
    transaction_fingerprint,
)
from sme_financial_dashboard.domain.money import MoneyValidationError, parse_amount
from sme_financial_dashboard.security.company_scope import (
    CompanyContext,
    resolve_company_context,
)
from sme_financial_dashboard.security.rbac import Permission, require_permission


class ReviewResolutionError(ValueError):
    """Raised when a review decision or correction is invalid."""


@dataclass(frozen=True, slots=True)
class ReviewQueueItem:
    row_id: UUID
    batch_id: UUID
    file_name: str
    file_type: str
    source_row_number: int
    source_page_number: int | None
    source_table_index: int | None
    raw_values: dict[str, Any]
    normalized_values: dict[str, Any] | None
    issues: tuple[dict[str, Any], ...]
    batch_created_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewResolutionResult:
    row_id: UUID
    batch_id: UUID
    decision: str
    row_status: str
    transaction_id: UUID | None
    remaining_review_count: int
    batch_status: str


def _verified_import_context(
    session: Session, context: CompanyContext
) -> CompanyContext:
    verified = resolve_company_context(
        session, user_id=context.user_id, company_id=context.company_id
    )
    require_permission(verified.role, Permission.IMPORT)
    return verified


def _required_note(value: str) -> str:
    if not isinstance(value, str):
        raise ReviewResolutionError("A review note is required.")
    note = " ".join(value.split())
    if not note:
        raise ReviewResolutionError("A review note is required.")
    if len(note) > 500:
        raise ReviewResolutionError("Review note exceeds 500 characters.")
    return note


def _optional_text(
    values: dict[str, Any], field_name: str, max_length: int
) -> str | None:
    raw = values.get(field_name)
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if len(value) > max_length:
        raise ReviewResolutionError(
            f"{field_name} exceeds its {max_length}-character limit."
        )
    if any(ord(char) < 32 and char not in "\t" for char in value):
        raise ReviewResolutionError(f"{field_name} contains unsupported control characters.")
    return value


def _corrected_transaction_values(
    values: dict[str, Any], company_id: UUID
) -> tuple[dict[str, Any], str]:
    allowed = {
        "transaction_date",
        "value_date",
        "amount",
        "currency",
        "direction",
        "description",
        "counterparty",
        "reference",
        "account_name",
    }
    unknown = set(values) - allowed
    if unknown:
        raise ReviewResolutionError(
            f"Unsupported correction fields: {', '.join(sorted(unknown))}"
        )
    required = {"transaction_date", "amount", "currency", "direction", "reference"}
    missing = required - set(values)
    if missing:
        raise ReviewResolutionError(
            f"Correction is missing required fields: {', '.join(sorted(missing))}"
        )
    try:
        transaction_date = date.fromisoformat(str(values["transaction_date"]).strip())
    except (TypeError, ValueError) as exc:
        raise ReviewResolutionError("Corrected transaction_date must use ISO YYYY-MM-DD.") from exc
    raw_value_date = values.get("value_date")
    try:
        value_date = (
            date.fromisoformat(str(raw_value_date).strip()) if raw_value_date else None
        )
    except (TypeError, ValueError) as exc:
        raise ReviewResolutionError("Corrected value_date must use ISO YYYY-MM-DD.") from exc
    try:
        amount_input = values["amount"]
        amount_decimal = (
            amount_input
            if isinstance(amount_input, Decimal)
            else Decimal(str(amount_input).strip())
        )
        amount = parse_amount(amount_decimal)
    except (InvalidOperation, ValueError, MoneyValidationError) as exc:
        raise ReviewResolutionError(f"Corrected amount is invalid: {exc}") from exc
    currency = str(values["currency"]).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ReviewResolutionError("Currency must be a three-letter alphabetic code.")
    try:
        direction = Direction(str(values["direction"]).strip().upper())
    except ValueError as exc:
        raise ReviewResolutionError("Direction must be INFLOW or OUTFLOW.") from exc
    reference = _optional_text(values, "reference", 200)
    if reference is None:
        raise ReviewResolutionError(
            "Corrected acceptance requires a manual unique reference to distinguish this row."
        )
    description = _optional_text(values, "description", 500)
    counterparty = _optional_text(values, "counterparty", 200)
    account_name = _optional_text(values, "account_name", 120)
    normalized = {
        "transaction_date": transaction_date.isoformat(),
        "value_date": value_date.isoformat() if value_date else None,
        "amount": format(amount, "f"),
        "currency": currency,
        "direction": direction.value,
        "description": description,
        "counterparty": counterparty,
        "reference": reference,
        "account_name": account_name,
    }
    fingerprint = transaction_fingerprint(
        company_id=company_id,
        transaction_date=transaction_date,
        amount=amount,
        currency=currency,
        direction=direction.value,
        reference=reference,
        counterparty=counterparty,
    )
    return normalized, fingerprint


class ReviewService:
    """List REVIEW rows and resolve them without bypassing tenant, role or audit rules."""

    @staticmethod
    def list_pending(
        session: Session,
        context: CompanyContext,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReviewQueueItem]:
        verified = _verified_import_context(session, context)
        if isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ReviewResolutionError("Review queue limit must be between 1 and 500.")
        if isinstance(offset, bool) or offset < 0:
            raise ReviewResolutionError("Review queue offset cannot be negative.")
        results = session.execute(
            select(ImportRow, ImportBatch)
            .join(
                ImportBatch,
                (ImportBatch.id == ImportRow.import_batch_id)
                & (ImportBatch.company_id == ImportRow.company_id),
            )
            .where(
                ImportRow.company_id == verified.company_id,
                ImportRow.row_status == ImportRowStatus.REVIEW,
            )
            .order_by(ImportBatch.created_at, ImportRow.source_row_number, ImportRow.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return [
            ReviewQueueItem(
                row_id=row.id,
                batch_id=batch.id,
                file_name=batch.file_name,
                file_type=batch.file_type.value,
                source_row_number=row.source_row_number,
                source_page_number=row.source_page_number,
                source_table_index=row.source_table_index,
                raw_values=row.raw_values_json,
                normalized_values=row.normalized_values_json,
                issues=tuple(row.issues_json or []),
                batch_created_at=batch.created_at,
            )
            for row, batch in results
        ]

    @staticmethod
    def resolve(
        session: Session,
        context: CompanyContext,
        *,
        row_id: UUID,
        decision: ReviewDecision | str,
        note: str,
        corrected_values: dict[str, Any] | None = None,
    ) -> ReviewResolutionResult:
        verified = _verified_import_context(session, context)
        try:
            review_decision = (
                decision if isinstance(decision, ReviewDecision) else ReviewDecision(decision)
            )
        except ValueError as exc:
            raise ReviewResolutionError("Unsupported review decision.") from exc
        if review_decision is ReviewDecision.ACCEPTED:
            raise ReviewResolutionError(
                "Use CORRECTED_AND_ACCEPTED with a unique manual reference to accept a REVIEW row."
            )
        resolution_note = _required_note(note)
        row = session.scalar(
            select(ImportRow).where(
                ImportRow.id == row_id,
                ImportRow.company_id == verified.company_id,
                ImportRow.row_status == ImportRowStatus.REVIEW,
            )
        )
        if row is None:
            raise ReviewResolutionError("Pending REVIEW row was not found in the active company.")
        batch = session.scalar(
            select(ImportBatch).where(
                ImportBatch.id == row.import_batch_id,
                ImportBatch.company_id == verified.company_id,
            )
        )
        if batch is None:
            raise ReviewResolutionError("The import batch is unavailable in the active company.")
        if batch.status in {ImportBatchStatus.FAILED, ImportBatchStatus.CANCELLED}:
            raise ReviewResolutionError("A failed or cancelled import batch cannot be reviewed.")

        corrected: dict[str, Any] | None = None
        fingerprint: str | None = None
        if review_decision is ReviewDecision.CORRECTED_AND_ACCEPTED:
            if not isinstance(corrected_values, dict):
                raise ReviewResolutionError("Corrected transaction values are required.")
            corrected, fingerprint = _corrected_transaction_values(
                corrected_values, verified.company_id
            )
            existing = session.scalar(
                select(Transaction.id).where(
                    Transaction.company_id == verified.company_id,
                    Transaction.fingerprint_version == FINGERPRINT_VERSION,
                    Transaction.source_fingerprint == fingerprint,
                )
            )
            if existing is not None:
                raise ReviewResolutionError(
                    "Corrected row still matches an existing transaction; confirm it as a duplicate or correct the unique reference."
                )
        elif corrected_values is not None:
            raise ReviewResolutionError(
                "Corrected values may only be supplied with CORRECTED_AND_ACCEPTED."
            )

        now = datetime.now(UTC)
        before = {
            "row_status": row.row_status.value,
            "review_decision": row.review_decision.value if row.review_decision else None,
        }
        created_transaction: Transaction | None = None
        try:
            with session.begin_nested():
                if review_decision is ReviewDecision.CONFIRMED_DUPLICATE:
                    row.row_status = ImportRowStatus.DUPLICATE
                    row.review_decision = ReviewDecision.CONFIRMED_DUPLICATE
                elif review_decision is ReviewDecision.REJECTED:
                    row.row_status = ImportRowStatus.INVALID
                    row.review_decision = ReviewDecision.REJECTED
                    row.issues_json = [
                        *(row.issues_json or []),
                        {
                            "code": "REVIEW_REJECTED",
                            "message": "A reviewer rejected this ambiguous source row.",
                        },
                    ]
                else:
                    assert corrected is not None and fingerprint is not None
                    created_transaction = Transaction(
                        id=uuid4(),
                        company_id=verified.company_id,
                        import_batch_id=batch.id,
                        transaction_date=date.fromisoformat(corrected["transaction_date"]),
                        value_date=(
                            date.fromisoformat(corrected["value_date"])
                            if corrected["value_date"]
                            else None
                        ),
                        amount=Decimal(corrected["amount"]),
                        currency=corrected["currency"],
                        direction=Direction(corrected["direction"]),
                        description=corrected["description"],
                        counterparty=corrected["counterparty"],
                        reference=corrected["reference"],
                        account_name=corrected["account_name"],
                        fingerprint_version=FINGERPRINT_VERSION,
                        source_fingerprint=fingerprint,
                        is_validated=True,
                    )
                    session.add(created_transaction)
                    session.flush()
                    row.normalized_values_json = corrected
                    row.source_fingerprint = fingerprint
                    row.row_status = ImportRowStatus.VALID_WITH_WARNING
                    row.review_decision = ReviewDecision.CORRECTED_AND_ACCEPTED
                    row.transaction_id = created_transaction.id

                row.reviewed_by_user_id = verified.user_id
                row.reviewed_at = now
                row.resolution_note = resolution_note
                session.flush()

                batch_rows = session.scalars(
                    select(ImportRow).where(
                        ImportRow.company_id == verified.company_id,
                        ImportRow.import_batch_id == batch.id,
                    )
                ).all()
                batch.total_count = len(batch_rows)
                batch.blank_count = sum(
                    item.row_status is ImportRowStatus.BLANK for item in batch_rows
                )
                batch.valid_count = sum(
                    item.row_status in {
                        ImportRowStatus.VALID,
                        ImportRowStatus.VALID_WITH_WARNING,
                    }
                    for item in batch_rows
                )
                batch.invalid_count = sum(
                    item.row_status is ImportRowStatus.INVALID for item in batch_rows
                )
                batch.duplicate_count = sum(
                    item.row_status is ImportRowStatus.DUPLICATE for item in batch_rows
                )
                batch.review_count = sum(
                    item.row_status is ImportRowStatus.REVIEW for item in batch_rows
                )
                batch.status = (
                    ImportBatchStatus.PARTIALLY_COMMITTED
                    if batch.review_count or batch.invalid_count or batch.duplicate_count
                    else ImportBatchStatus.COMMITTED
                )
                if batch.committed_at is None:
                    batch.committed_at = now

                after = {
                    "row_status": row.row_status.value,
                    "review_decision": row.review_decision.value,
                    "transaction_id": (
                        str(created_transaction.id) if created_transaction else None
                    ),
                    "remaining_review_count": batch.review_count,
                    "batch_status": batch.status.value,
                }
                session.add(
                    AuditEvent(
                        company_id=verified.company_id,
                        actor_user_id=verified.user_id,
                        action="IMPORT_REVIEW_RESOLVED",
                        entity_type="IMPORT_ROW",
                        entity_id=row.id,
                        before_json=before,
                        after_json={
                            "row_status": after["row_status"],
                            "review_decision": after["review_decision"],
                            "transaction_created": created_transaction is not None,
                            "remaining_review_count": batch.review_count,
                            "batch_status": batch.status.value,
                        },
                    )
                )
                if created_transaction is not None:
                    session.add(
                        AuditEvent(
                            company_id=verified.company_id,
                            actor_user_id=verified.user_id,
                            action="TRANSACTION_CREATED_FROM_REVIEW",
                            entity_type="TRANSACTION",
                            entity_id=created_transaction.id,
                            after_json={
                                "import_batch_id": str(batch.id),
                                "source_row_id": str(row.id),
                                "review_row_number": row.source_row_number,
                                "decision": review_decision.value,
                            },
                        )
                    )
                session.flush()
        except IntegrityError as exc:
            raise ReviewResolutionError(
                "Review resolution conflicted with an existing transaction fingerprint or row link; no change was committed."
            ) from exc

        return ReviewResolutionResult(
            row_id=row.id,
            batch_id=batch.id,
            decision=row.review_decision.value,
            row_status=row.row_status.value,
            transaction_id=row.transaction_id,
            remaining_review_count=batch.review_count,
            batch_status=batch.status.value,
        )
