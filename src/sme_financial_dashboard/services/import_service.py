"""Preview, validation and atomic commit workflow for statement imports."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from sme_financial_dashboard.db.models import (
    AuditEvent,
    Direction,
    FileType,
    ImportBatch,
    ImportBatchStatus,
    ImportMethod,
    ImportRow,
    ImportRowStatus,
    Transaction,
)
from sme_financial_dashboard.domain.fingerprints import (
    FINGERPRINT_VERSION,
    transaction_fingerprint,
)
from sme_financial_dashboard.domain.import_parsing import (
    PARSER_VERSION,
    PREVIEW_SAMPLE_ROWS,
    ImportFileError,
    ParsedDocument,
    ParsedRow,
    inspect_statement,
)
from sme_financial_dashboard.domain.money import MoneyValidationError, parse_amount
from sme_financial_dashboard.security.company_scope import (
    CompanyContext,
    resolve_company_context,
)
from sme_financial_dashboard.security.rbac import Permission, require_permission


class ImportServiceError(ValueError):
    """Base class for safe, actionable import errors."""


class ImportMappingError(ImportServiceError):
    """Raised when mapping or parsing options are incomplete or invalid."""


class ImportConfirmationRequired(ImportServiceError):
    """Raised when an import has not been explicitly confirmed."""


class ImportStateError(ImportServiceError):
    """Raised when a preview is unavailable or no longer committable."""


@dataclass(frozen=True, slots=True)
class ImportMapping:
    columns: dict[str, int]
    direction_mode: str = "column"
    date_format: str = "%Y-%m-%d"
    decimal_separator: str = "."
    thousands_separator: str | None = ","
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    worksheet_name: str | None = None

    def validate(self, column_count: int) -> None:
        allowed = {
            "transaction_date", "amount", "currency", "direction", "value_date",
            "description", "counterparty", "reference", "account_name",
        }
        unknown = set(self.columns) - allowed
        if unknown:
            raise ImportMappingError(f"Unsupported mapping fields: {', '.join(sorted(unknown))}")
        for required in ("transaction_date", "amount", "currency"):
            if required not in self.columns:
                raise ImportMappingError(f"Mapping is missing required field: {required}")
        if self.direction_mode not in {"column", "signed_amount"}:
            raise ImportMappingError("direction_mode must be 'column' or 'signed_amount'.")
        if self.direction_mode == "column" and "direction" not in self.columns:
            raise ImportMappingError("Map a direction column or explicitly select signed-amount mode.")
        if self.direction_mode == "signed_amount" and "direction" in self.columns:
            raise ImportMappingError("Remove the direction column when using signed-amount mode.")
        if self.decimal_separator not in {".", ","}:
            raise ImportMappingError("Decimal separator must be a dot or comma.")
        if self.thousands_separator == self.decimal_separator:
            raise ImportMappingError("Thousands and decimal separators must be different.")
        if self.thousands_separator not in {None, "", ".", ",", " ", "\u00a0"}:
            raise ImportMappingError("Unsupported thousands separator.")
        if len(self.delimiter) != 1:
            raise ImportMappingError("CSV delimiter must be a single character.")
        for field_name, index in self.columns.items():
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < column_count:
                raise ImportMappingError(f"Invalid source column for {field_name}.")
        if len(set(self.columns.values())) != len(self.columns):
            raise ImportMappingError("Each source column can map to only one transaction field.")
        try:
            sample = datetime(2001, 2, 3)
            rendered = sample.strftime(self.date_format)
            parsed = datetime.strptime(rendered, self.date_format)
            if parsed.date() != sample.date():
                raise ValueError("Date format does not preserve day, month and year.")
        except (ValueError, TypeError) as exc:
            raise ImportMappingError("Date format is invalid; use a strptime format such as %d/%m/%Y.") from exc

    def to_json(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "direction_mode": self.direction_mode,
            "date_format": self.date_format,
            "decimal_separator": self.decimal_separator,
            "thousands_separator": self.thousands_separator,
            "delimiter": self.delimiter,
            "encoding": self.encoding,
            "worksheet_name": self.worksheet_name,
        }


@dataclass(frozen=True, slots=True)
class ImportRowPreview:
    source_row_number: int
    status: str
    values: dict[str, Any]
    issues: tuple[dict[str, str], ...]
    source_page_number: int | None = None
    source_table_index: int | None = None


@dataclass(frozen=True, slots=True)
class ImportPreview:
    preview_id: UUID
    file_name: str
    file_type: str
    file_sha256: str
    extraction_method: str
    total_count: int
    blank_count: int
    valid_count: int
    invalid_count: int
    duplicate_count: int
    review_count: int
    outlier_count: int
    sample_rows: tuple[ImportRowPreview, ...]
    source_page_count: int | None = None


@dataclass(frozen=True, slots=True)
class ImportCommitSummary:
    batch_id: UUID
    status: str
    imported_count: int
    blank_count: int
    invalid_count: int
    duplicate_count: int
    review_count: int


@dataclass(slots=True)
class _Candidate:
    source: ParsedRow
    raw_values: dict[str, str]
    normalized: dict[str, Any] | None
    fingerprint: str | None
    reference: str
    status: ImportRowStatus
    issues: list[dict[str, str]] = field(default_factory=list)


_DIRECTION_VALUES = {
    "INFLOW": Direction.INFLOW,
    "IN": Direction.INFLOW,
    "CREDIT": Direction.INFLOW,
    "CR": Direction.INFLOW,
    "DEPOSIT": Direction.INFLOW,
    "RECEIPT": Direction.INFLOW,
    "INCOME": Direction.INFLOW,
    "OUTFLOW": Direction.OUTFLOW,
    "OUT": Direction.OUTFLOW,
    "DEBIT": Direction.OUTFLOW,
    "DR": Direction.OUTFLOW,
    "WITHDRAWAL": Direction.OUTFLOW,
    "PAYMENT": Direction.OUTFLOW,
    "EXPENSE": Direction.OUTFLOW,
}


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    text = "".join(ch for ch in text if ch in "\t" or ord(ch) >= 32)
    return text.strip()[:500]


def _safe_file_name(file_name: str) -> str:
    name = Path(file_name or "statement").name
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in " ._()-")
    cleaned = cleaned.strip(" .")[:255]
    return cleaned or "statement"


def _row_values(document: ParsedDocument, row: ParsedRow) -> dict[str, str]:
    return {
        header: _clean_cell(row.values[index] if index < len(row.values) else "")
        for index, header in enumerate(document.headers)
    }


def _get(row: ParsedRow, mapping: ImportMapping, field_name: str) -> Any:
    index = mapping.columns.get(field_name)
    if index is None or index >= len(row.values):
        return None
    return row.values[index]


def _parse_date(value: Any, date_format: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean_cell(value)
    if not text:
        raise ValueError("Transaction date is required.")
    try:
        return datetime.strptime(text, date_format).date()
    except ValueError as exc:
        raise ValueError(f"Date does not match the selected format {date_format}.") from exc


def _parse_locale_decimal(value: Any, mapping: ImportMapping) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("Amount is required.")
    text = _clean_cell(value).replace("\u00a0", " ")
    if not text:
        raise ValueError("Amount is required.")
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1].strip()
    sign = ""
    if text[:1] in {"+", "-"}:
        sign, text = text[0], text[1:]
    if not text:
        raise ValueError("Amount is not numeric.")
    thousands = mapping.thousands_separator
    integer_part, separator, fractional_part = text.partition(mapping.decimal_separator)
    if separator and mapping.decimal_separator in fractional_part:
        raise ValueError("Amount contains more than one decimal separator.")
    if thousands and thousands in integer_part:
        groups = integer_part.split(thousands)
        if not groups[0].isdigit() or not 1 <= len(groups[0]) <= 3:
            raise ValueError("Thousands grouping is invalid.")
        if any(not group.isdigit() or len(group) != 3 for group in groups[1:]):
            raise ValueError("Thousands grouping is invalid.")
        integer_part = "".join(groups)
    elif thousands and thousands in fractional_part:
        raise ValueError("Thousands separator appears after the decimal separator.")
    if not integer_part.isdigit() or (separator and fractional_part and not fractional_part.isdigit()):
        raise ValueError("Amount contains unsupported characters or separators.")
    normalized = (sign or ("-" if negative_parentheses else "")) + integer_part
    if separator:
        normalized += "." + fractional_part
    try:
        result = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("Amount is not a valid decimal number.") from exc
    if not result.is_finite() or result == 0:
        raise ValueError("Amount must be a finite non-zero number.")
    return result


def _direction(value: Any) -> Direction:
    normalized = _clean_cell(value).upper()
    try:
        return _DIRECTION_VALUES[normalized]
    except KeyError as exc:
        raise ValueError("Direction must identify an inflow/credit or outflow/debit.") from exc


def _optional(row: ParsedRow, mapping: ImportMapping, field_name: str) -> str | None:
    value = _clean_cell(_get(row, mapping, field_name))
    return value or None


def _normalize_candidate(
    row: ParsedRow, document: ParsedDocument, mapping: ImportMapping, company_id: UUID
) -> _Candidate:
    raw_values = _row_values(document, row)
    if not any(raw_values.values()):
        return _Candidate(row, raw_values, None, None, "", ImportRowStatus.BLANK)

    issues: list[dict[str, str]] = []
    try:
        transaction_date = _parse_date(_get(row, mapping, "transaction_date"), mapping.date_format)
    except ValueError as exc:
        issues.append({"code": "DATE_INVALID", "message": str(exc)})
        transaction_date = None

    try:
        parsed_amount = _parse_locale_decimal(_get(row, mapping, "amount"), mapping)
        if mapping.direction_mode == "signed_amount":
            direction = Direction.OUTFLOW if parsed_amount < 0 else Direction.INFLOW
            amount = parse_amount(abs(parsed_amount))
        else:
            amount = parse_amount(parsed_amount)
            direction = _direction(_get(row, mapping, "direction"))
    except (ValueError, MoneyValidationError) as exc:
        issues.append({"code": "AMOUNT_OR_DIRECTION_INVALID", "message": str(exc)})
        amount = None
        direction = None

    currency = _clean_cell(_get(row, mapping, "currency")).upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        issues.append({"code": "CURRENCY_INVALID", "message": "Currency must be a three-letter ISO 4217 code."})

    if issues or transaction_date is None or amount is None or direction is None:
        return _Candidate(row, raw_values, None, None, _optional(row, mapping, "reference") or "", ImportRowStatus.INVALID, issues)

    reference = _optional(row, mapping, "reference") or ""
    counterparty = _optional(row, mapping, "counterparty")
    value_date = None
    if "value_date" in mapping.columns:
        try:
            raw_value_date = _get(row, mapping, "value_date")
            value_date = _parse_date(raw_value_date, mapping.date_format).isoformat() if _clean_cell(raw_value_date) else None
        except ValueError as exc:
            return _Candidate(
                row,
                raw_values,
                None,
                None,
                _optional(row, mapping, "reference") or "",
                ImportRowStatus.INVALID,
                [{"code": "VALUE_DATE_INVALID", "message": str(exc)}],
            )
    description = _optional(row, mapping, "description")
    account_name = _optional(row, mapping, "account_name")
    normalized = {
        "transaction_date": transaction_date.isoformat(),
        "value_date": value_date,
        "amount": format(amount, "f"),
        "currency": currency,
        "direction": direction.value,
        "description": description,
        "counterparty": counterparty,
        "reference": reference or None,
        "account_name": account_name,
    }
    fingerprint = transaction_fingerprint(
        company_id=company_id,
        transaction_date=transaction_date,
        amount=amount,
        currency=currency,
        direction=direction.value,
        reference=reference or None,
        counterparty=counterparty,
    )
    status = ImportRowStatus.VALID_WITH_WARNING if issues else ImportRowStatus.VALID
    return _Candidate(row, raw_values, normalized, fingerprint, reference, status, issues)


def _preview_from_batch(batch: ImportBatch) -> ImportPreview:
    counts = {status: 0 for status in ImportRowStatus}
    for row in batch.rows:
        counts[row.row_status] += 1
    sample = tuple(
        ImportRowPreview(
            source_row_number=row.source_row_number,
            status=row.row_status.value,
            values=row.normalized_values_json or row.raw_values_json,
            issues=tuple(row.issues_json or []),
            source_page_number=row.source_page_number,
            source_table_index=row.source_table_index,
        )
        for row in batch.rows[:PREVIEW_SAMPLE_ROWS]
    )
    return ImportPreview(
        preview_id=batch.id,
        file_name=batch.file_name,
        file_type=batch.file_type.value,
        file_sha256=batch.file_sha256,
        extraction_method=batch.extraction_method.value,
        total_count=batch.total_count,
        blank_count=counts[ImportRowStatus.BLANK],
        valid_count=counts[ImportRowStatus.VALID] + counts[ImportRowStatus.VALID_WITH_WARNING],
        invalid_count=counts[ImportRowStatus.INVALID],
        duplicate_count=counts[ImportRowStatus.DUPLICATE],
        review_count=counts[ImportRowStatus.REVIEW],
        outlier_count=batch.outlier_count,
        sample_rows=sample,
        source_page_count=batch.source_page_count,
    )


class ImportService:
    """Tenant-scoped import workflow. Preview stages source rows; commit creates transactions."""

    @staticmethod
    def inspect_file(
        file_bytes: bytes,
        file_name: str,
        *,
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
        worksheet_name: str | None = None,
    ) -> ParsedDocument:
        return inspect_statement(
            file_bytes,
            file_name,
            delimiter=delimiter,
            encoding=encoding,
            worksheet_name=worksheet_name,
        )

    @staticmethod
    def preview(
        session: Session,
        *,
        file_bytes: bytes,
        file_name: str,
        mapping: ImportMapping,
        context: CompanyContext,
    ) -> ImportPreview:
        verified = resolve_company_context(
            session, user_id=context.user_id, company_id=context.company_id
        )
        require_permission(verified.role, Permission.IMPORT)
        try:
            document = inspect_statement(
                file_bytes,
                file_name,
                delimiter=mapping.delimiter,
                encoding=mapping.encoding,
                worksheet_name=mapping.worksheet_name,
            )
            mapping.validate(len(document.headers))
        except ImportFileError as exc:
            raise ImportMappingError(f"{exc.code}: {exc.message}") from exc

        candidates = [
            _normalize_candidate(row, document, mapping, verified.company_id)
            for row in document.rows
        ]
        fingerprint_groups: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            if candidate.fingerprint:
                fingerprint_groups.setdefault(candidate.fingerprint, []).append(candidate)

        for group in fingerprint_groups.values():
            if len(group) <= 1:
                continue
            if not group[0].reference:
                for candidate in group:
                    candidate.status = ImportRowStatus.REVIEW
                    candidate.issues.append({
                        "code": "REFERENCELESS_IDENTICAL_ROWS",
                        "message": "Identical business rows have no unique reference; manual review is required.",
                    })
            else:
                for candidate in group[1:]:
                    candidate.status = ImportRowStatus.DUPLICATE
                    candidate.issues.append({
                        "code": "DUPLICATE_IN_BATCH",
                        "message": "This row duplicates an earlier row in the same file.",
                    })

        fingerprints = list(fingerprint_groups)
        existing = set()
        if fingerprints:
            existing = set(
                session.scalars(
                    select(Transaction.source_fingerprint).where(
                        Transaction.company_id == verified.company_id,
                        Transaction.fingerprint_version == FINGERPRINT_VERSION,
                        Transaction.source_fingerprint.in_(fingerprints),
                    )
                ).all()
            )
        for candidate in candidates:
            if candidate.fingerprint and candidate.fingerprint in existing:
                if candidate.reference:
                    candidate.status = ImportRowStatus.DUPLICATE
                    code = "DUPLICATE_EXISTING"
                    message = "This referenced transaction already exists for this company."
                else:
                    candidate.status = ImportRowStatus.REVIEW
                    code = "REFERENCELESS_MATCH_EXISTING"
                    message = "A matching transaction exists but has no unique reference; manual review is required."
                candidate.issues.append({"code": code, "message": message})

        safe_name = _safe_file_name(file_name)
        import_batch = ImportBatch(
            company_id=verified.company_id,
            uploaded_by_user_id=verified.user_id,
            file_name=safe_name,
            file_sha256=hashlib.sha256(file_bytes).hexdigest(),
            file_type=FileType(document.file_type),
            extraction_method=ImportMethod(document.extraction_method),
            source_page_count=document.source_page_count,
            parser_version=PARSER_VERSION,
            mapping_json=mapping.to_json(),
            status=ImportBatchStatus.PREVIEWED,
            total_count=len(candidates),
            blank_count=sum(c.status is ImportRowStatus.BLANK for c in candidates),
            valid_count=sum(c.status in {ImportRowStatus.VALID, ImportRowStatus.VALID_WITH_WARNING} for c in candidates),
            invalid_count=sum(c.status is ImportRowStatus.INVALID for c in candidates),
            duplicate_count=sum(c.status is ImportRowStatus.DUPLICATE for c in candidates),
            review_count=sum(c.status is ImportRowStatus.REVIEW for c in candidates),
            outlier_count=0,
        )
        session.add(import_batch)
        session.flush()
        for candidate in candidates:
            session.add(
                ImportRow(
                    id=uuid4(),
                    company_id=verified.company_id,
                    import_batch_id=import_batch.id,
                    source_row_number=candidate.source.source_row_number,
                    source_page_number=candidate.source.source_page_number,
                    source_table_index=candidate.source.source_table_index,
                    raw_values_json=candidate.raw_values,
                    normalized_values_json=candidate.normalized,
                    row_status=candidate.status,
                    issues_json=candidate.issues,
                    source_fingerprint=candidate.fingerprint,
                )
            )
        session.add(
            AuditEvent(
                company_id=verified.company_id,
                actor_user_id=verified.user_id,
                action="IMPORT_PREVIEW_CREATED",
                entity_type="IMPORT_BATCH",
                entity_id=import_batch.id,
                after_json={
                    "file_type": document.file_type,
                    "file_sha256": import_batch.file_sha256,
                    "total_count": import_batch.total_count,
                    "valid_count": import_batch.valid_count,
                    "invalid_count": import_batch.invalid_count,
                    "duplicate_count": import_batch.duplicate_count,
                    "review_count": import_batch.review_count,
                },
            )
        )
        session.flush()
        import_batch.rows = list(
            session.scalars(
                select(ImportRow)
                .where(ImportRow.import_batch_id == import_batch.id)
                .order_by(ImportRow.source_row_number)
            ).all()
        )
        return _preview_from_batch(import_batch)

    @staticmethod
    def commit(
        session: Session,
        *,
        preview_id: UUID,
        context: CompanyContext,
        confirm: bool,
        confirm_partial: bool = False,
    ) -> ImportCommitSummary:
        if not confirm:
            raise ImportConfirmationRequired("Explicit confirmation is required before importing.")
        verified = resolve_company_context(
            session, user_id=context.user_id, company_id=context.company_id
        )
        require_permission(verified.role, Permission.IMPORT)
        batch = session.scalar(
            select(ImportBatch)
            .options(selectinload(ImportBatch.rows))
            .where(
                ImportBatch.id == preview_id,
                ImportBatch.company_id == verified.company_id,
            )
        )
        if batch is None:
            raise ImportStateError("Import preview was not found in the active company.")
        if batch.status in {ImportBatchStatus.COMMITTED, ImportBatchStatus.PARTIALLY_COMMITTED}:
            return ImportCommitSummary(
                batch_id=batch.id,
                status=batch.status.value,
                imported_count=sum(row.transaction_id is not None for row in batch.rows),
                blank_count=batch.blank_count,
                invalid_count=batch.invalid_count,
                duplicate_count=batch.duplicate_count,
                review_count=batch.review_count,
            )
        if batch.status is not ImportBatchStatus.PREVIEWED:
            raise ImportStateError("This import preview is no longer available for commit.")
        if (batch.invalid_count or batch.duplicate_count or batch.review_count) and not confirm_partial:
            raise ImportConfirmationRequired(
                "This batch contains invalid, duplicate or REVIEW rows. Confirm the partial import explicitly."
            )

        try:
            with session.begin_nested():
                transactions: list[Transaction] = []
                for row in batch.rows:
                    if row.row_status not in {ImportRowStatus.VALID, ImportRowStatus.VALID_WITH_WARNING}:
                        continue
                    values = row.normalized_values_json
                    if not values or row.source_fingerprint is None:
                        raise ImportStateError("A valid staged row is missing normalized values or fingerprint.")
                    transaction = Transaction(
                        id=uuid4(),
                        company_id=verified.company_id,
                        import_batch_id=batch.id,
                        transaction_date=date.fromisoformat(values["transaction_date"]),
                        value_date=date.fromisoformat(values["value_date"]) if values.get("value_date") else None,
                        amount=Decimal(values["amount"]),
                        currency=values["currency"],
                        direction=Direction(values["direction"]),
                        description=values.get("description"),
                        counterparty=values.get("counterparty"),
                        reference=values.get("reference"),
                        account_name=values.get("account_name"),
                        fingerprint_version=FINGERPRINT_VERSION,
                        source_fingerprint=row.source_fingerprint,
                        is_validated=True,
                    )
                    session.add(transaction)
                    row.transaction_id = transaction.id
                    transactions.append(transaction)
                session.flush()
                has_held_rows = bool(batch.invalid_count or batch.duplicate_count or batch.review_count)
                old_status = batch.status.value
                batch.status = (
                    ImportBatchStatus.PARTIALLY_COMMITTED
                    if has_held_rows
                    else ImportBatchStatus.COMMITTED
                )
                batch.committed_at = datetime.now(UTC)
                session.add(
                    AuditEvent(
                        company_id=verified.company_id,
                        actor_user_id=verified.user_id,
                        action="IMPORT_BATCH_COMMITTED",
                        entity_type="IMPORT_BATCH",
                        entity_id=batch.id,
                        before_json={"status": old_status},
                        after_json={
                            "status": batch.status.value,
                            "imported_count": len(transactions),
                            "review_count": batch.review_count,
                            "invalid_count": batch.invalid_count,
                            "duplicate_count": batch.duplicate_count,
                        },
                    )
                )
                session.flush()
        except IntegrityError as exc:
            raise ImportStateError(
                "Import could not be committed because a transaction fingerprint changed or already exists. Refresh the preview."
            ) from exc

        return ImportCommitSummary(
            batch_id=batch.id,
            status=batch.status.value,
            imported_count=len(transactions),
            blank_count=batch.blank_count,
            invalid_count=batch.invalid_count,
            duplicate_count=batch.duplicate_count,
            review_count=batch.review_count,
        )
