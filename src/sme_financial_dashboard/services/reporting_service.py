"""Company-scoped CSV/PDF exports, import history and audit history."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from sme_financial_dashboard.db.models import (
    AuditEvent,
    Company,
    ImportBatch,
    ImportRow,
    Transaction,
)
from sme_financial_dashboard.security.company_scope import (
    CompanyContext,
    resolve_company_context,
)
from sme_financial_dashboard.security.rbac import Permission, require_permission
from sme_financial_dashboard.services.dashboard_service import (
    DashboardFilters,
    DashboardService,
)


MAX_EXPORT_ROWS = 10_000


class ReportingError(ValueError):
    """Raised when an export/history query violates reporting rules."""


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    filename: str
    content_type: str
    data: bytes
    row_count: int
    format: Literal["CSV", "PDF"]


def _verified_context(
    session: Session,
    context: CompanyContext,
    permission: Permission,
) -> CompanyContext:
    verified = resolve_company_context(
        session,
        user_id=context.user_id,
        company_id=context.company_id,
    )
    require_permission(verified.role, permission)
    return verified


def _safe_csv_text(value: str | None) -> str:
    """Neutralize spreadsheet formula prefixes while preserving the source text."""
    if value is None:
        return ""
    text = str(value)
    trimmed = text.lstrip(" \t\r\n")
    if text.startswith(("\t", "\r", "\n")) or (
        trimmed and trimmed[0] in {"=", "+", "-", "@"}
    ):
        return "'" + text
    return text


def _record_export(
    session: Session,
    *,
    context: CompanyContext,
    export_format: str,
    filters: DashboardFilters,
    row_count: int,
    filename: str,
) -> None:
    session.add(
        AuditEvent(
            company_id=context.company_id,
            actor_user_id=context.user_id,
            action=f"EXPORT_{export_format}_PREPARED",
            entity_type="EXPORT",
            entity_id=uuid4(),
            after_json={
                "format": export_format,
                "filename": filename,
                "row_count": row_count,
                "start_date": filters.start_date.isoformat(),
                "end_date": filters.end_date.isoformat(),
                "currency": filters.currency,
                "account_name": filters.account_name,
                "category_id": str(filters.category_id) if filters.category_id else None,
                "direction": filters.direction.value if hasattr(filters.direction, "value") else filters.direction,
            },
        )
    )
    session.flush()


def _filename(export_format: str, filters: DashboardFilters) -> str:
    return (
        f"sme_transactions_{filters.start_date:%Y%m%d}_"
        f"{filters.end_date:%Y%m%d}.{export_format.lower()}"
    )


class ExportService:
    """Generate CSV and PDF exports using the dashboard's exact filter contract."""

    @staticmethod
    def export_csv(
        session: Session,
        context: CompanyContext,
        filters: DashboardFilters,
    ) -> ExportArtifact:
        verified = _verified_context(session, context, Permission.EXPORT)
        rows = DashboardService.transactions(
            session, verified, filters, limit=MAX_EXPORT_ROWS + 1
        )
        if len(rows) > MAX_EXPORT_ROWS:
            raise ReportingError(
                f"Export exceeds the {MAX_EXPORT_ROWS:,}-row safety limit; narrow the filters."
            )

        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(
            [
                "Transaction date",
                "Value date",
                "Amount",
                "Currency",
                "Direction",
                "Account",
                "Category",
                "Description",
                "Counterparty",
                "Reference",
            ]
        )
        for transaction, category_name in rows:
            writer.writerow(
                [
                    transaction.transaction_date.isoformat(),
                    transaction.value_date.isoformat() if transaction.value_date else "",
                    format(transaction.amount, "f"),
                    transaction.currency,
                    transaction.direction.value,
                    _safe_csv_text(transaction.account_name),
                    _safe_csv_text(category_name),
                    _safe_csv_text(transaction.description),
                    _safe_csv_text(transaction.counterparty),
                    _safe_csv_text(transaction.reference),
                ]
            )

        filename = _filename("csv", filters)
        data = buffer.getvalue().encode("utf-8-sig")
        _record_export(
            session,
            context=verified,
            export_format="CSV",
            filters=filters,
            row_count=len(rows),
            filename=filename,
        )
        return ExportArtifact(
            filename=filename,
            content_type="text/csv; charset=utf-8",
            data=data,
            row_count=len(rows),
            format="CSV",
        )

    @staticmethod
    def export_pdf(
        session: Session,
        context: CompanyContext,
        filters: DashboardFilters,
    ) -> ExportArtifact:
        verified = _verified_context(session, context, Permission.EXPORT)
        rows = DashboardService.transactions(session, verified, filters)
        if len(rows) > MAX_EXPORT_ROWS:
            raise ReportingError(
                f"Export exceeds the {MAX_EXPORT_ROWS:,}-row safety limit; narrow the filters."
            )

        company = session.scalar(
            select(Company).where(Company.id == verified.company_id)
        )
        if company is None:
            raise ReportingError("Active company could not be resolved.")

        report = DashboardService.report(session, verified, filters)
        output = io.BytesIO()
        document = SimpleDocTemplate(
            output,
            pagesize=landscape(A4),
            rightMargin=12 * mm,
            leftMargin=12 * mm,
            topMargin=12 * mm,
            bottomMargin=12 * mm,
            title="SME Financial Dashboard — Transactions",
            author="SME Financial Dashboard",
        )
        styles = getSampleStyleSheet()
        cell_style = ParagraphStyle(
            "ExportCell",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=6,
            leading=7,
        )
        title_style = styles["Title"]
        title_style.alignment = TA_CENTER
        story = [
            Paragraph("SME Financial Dashboard — Transaction report", title_style),
            Spacer(1, 4 * mm),
            Paragraph(f"<b>Company:</b> {escape(company.name)}", styles["Normal"]),
            Paragraph(
                f"<b>Period:</b> {filters.start_date.isoformat()} to {filters.end_date.isoformat()}",
                styles["Normal"],
            ),
            Paragraph(
                f"<b>Filters:</b> currency={escape(filters.currency or 'all')}; "
                f"account={escape(filters.account_name or 'all')}; "
                f"category={escape(str(filters.category_id) if filters.category_id else 'all')}; "
                f"direction={escape(str(filters.direction.value if hasattr(filters.direction, 'value') else filters.direction or 'all'))}",
                styles["Normal"],
            ),
            Spacer(1, 5 * mm),
            Paragraph("<b>Cash-flow totals by currency</b>", styles["Heading2"]),
        ]

        summary_data = [["Currency", "Inflows", "Outflows", "Net", "Transactions"]]
        for item in report.current.totals:
            summary_data.append(
                [
                    item.currency,
                    format(item.inflows, ",.6f"),
                    format(item.outflows, ",.6f"),
                    format(item.net, ",.6f"),
                    str(item.transaction_count),
                ]
            )
        summary_table = Table(summary_data, repeatRows=1, hAlign="LEFT")
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#26384A")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB4BE")),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("PADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([summary_table, Spacer(1, 5 * mm)])
        story.append(Paragraph("<b>Filtered transactions</b>", styles["Heading2"]))

        detail_data = [
            [
                "Date",
                "Currency",
                "Amount",
                "Direction",
                "Account",
                "Category",
                "Counterparty",
                "Reference",
                "Description",
            ]
        ]
        for transaction, category_name in rows:
            detail_data.append(
                [
                    transaction.transaction_date.isoformat(),
                    escape(transaction.currency),
                    format(transaction.amount, ",.6f"),
                    transaction.direction.value,
                    Paragraph(escape(transaction.account_name or ""), cell_style),
                    Paragraph(escape(category_name or "Uncategorized"), cell_style),
                    Paragraph(escape(transaction.counterparty or ""), cell_style),
                    Paragraph(escape(transaction.reference or ""), cell_style),
                    Paragraph(escape(transaction.description or ""), cell_style),
                ]
            )
        if not rows:
            detail_data.append(["No matching transactions", "", "", "", "", "", "", "", ""])
        detail_table = Table(
            detail_data,
            repeatRows=1,
            colWidths=[20 * mm, 15 * mm, 25 * mm, 20 * mm, 25 * mm, 27 * mm, 32 * mm, 27 * mm, 55 * mm],
            hAlign="LEFT",
        )
        detail_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#26384A")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C5CDD5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(detail_table)
        document.build(story)
        data = output.getvalue()
        filename = _filename("pdf", filters)
        _record_export(
            session,
            context=verified,
            export_format="PDF",
            filters=filters,
            row_count=len(rows),
            filename=filename,
        )
        return ExportArtifact(
            filename=filename,
            content_type="application/pdf",
            data=data,
            row_count=len(rows),
            format="PDF",
        )


class ImportHistoryService:
    """Company-scoped read access to import batches and their staged row provenance."""

    @staticmethod
    def list_batches(
        session: Session,
        context: CompanyContext,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ImportBatch]:
        verified = _verified_context(session, context, Permission.VIEW)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ReportingError("Batch limit must be an integer from 1 to 500.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ReportingError("Batch offset must be a non-negative integer.")
        statement = (
            select(ImportBatch)
            .where(ImportBatch.company_id == verified.company_id)
            .order_by(ImportBatch.created_at.desc(), ImportBatch.id)
            .limit(limit)
            .offset(offset)
        )
        return list(session.scalars(statement).all())

    @staticmethod
    def list_rows(
        session: Session,
        context: CompanyContext,
        *,
        batch_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ImportRow]:
        verified = _verified_context(session, context, Permission.VIEW)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ReportingError("Import row limit must be an integer from 1 to 500.")
        if isinstance(batch_id, str):
            try:
                batch_id = UUID(batch_id)
            except ValueError as exc:
                raise ReportingError("Import batch id must be a UUID.") from exc
        if not isinstance(batch_id, UUID):
            raise ReportingError("Import batch id must be a UUID.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ReportingError("Import row offset must be a non-negative integer.")
        batch_exists = session.scalar(
            select(ImportBatch.id).where(
                ImportBatch.id == batch_id,
                ImportBatch.company_id == verified.company_id,
            )
        )
        if batch_exists is None:
            raise ReportingError("Import batch was not found in the active company.")
        statement = (
            select(ImportRow)
            .where(
                ImportRow.import_batch_id == batch_id,
                ImportRow.company_id == verified.company_id,
            )
            .order_by(ImportRow.source_row_number, ImportRow.id)
            .limit(limit)
            .offset(offset)
        )
        return list(session.scalars(statement).all())


class AuditService:
    """Read company-scoped audit metadata for roles granted VIEW_AUDIT."""

    @staticmethod
    def list_events(
        session: Session,
        context: CompanyContext,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        verified = _verified_context(session, context, Permission.VIEW_AUDIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ReportingError("Audit limit must be an integer from 1 to 500.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ReportingError("Audit offset must be a non-negative integer.")
        statement = (
            select(AuditEvent)
            .where(AuditEvent.company_id == verified.company_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .limit(limit)
            .offset(offset)
        )
        return list(session.scalars(statement).all())
