from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from conftest import seed_workspace
from sme_financial_dashboard.db.models import (
    AuditEvent,
    FileType,
    ImportBatch,
    ImportMethod,
    ImportRow,
    ImportRowStatus,
    MembershipRole,
)
from sme_financial_dashboard.security.company_scope import resolve_company_context
from sme_financial_dashboard.services.reporting_service import (
    AuditService,
    ImportHistoryService,
    ReportingError,
)


def _context(session, *, role=MembershipRole.ACCOUNTANT, suffix="history"):
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


def _batch(session, company, user, *, filename: str):
    batch = ImportBatch(
        company_id=company.id,
        uploaded_by_user_id=user.id,
        file_name=filename,
        file_sha256=hashlib.sha256(filename.encode("utf-8")).hexdigest(),
        file_type=FileType.CSV,
        extraction_method=ImportMethod.CSV_ROWS,
        mapping_json={"date_format": "%d/%m/%Y"},
    )
    session.add(batch)
    session.flush()
    row = ImportRow(
        company_id=company.id,
        import_batch_id=batch.id,
        source_row_number=2,
        raw_values_json={"Date": "10/01/2026", "Amount": "10,00"},
        normalized_values_json=None,
        row_status=ImportRowStatus.REVIEW,
        issues_json=[{"code": "REFERENCELESS_MATCH_REVIEW"}],
        source_fingerprint="a" * 64,
    )
    session.add(row)
    session.flush()
    return batch, row


def test_import_history_is_company_scoped_and_supports_pagination(session):
    _workspace_a, user_a, company_a, context_a = _context(session, suffix="history-a")
    _workspace_b, user_b, company_b, context_b = _context(session, suffix="history-b")
    batch_a1, row_a1 = _batch(session, company_a, user_a, filename="a1.csv")
    batch_a2, _row_a2 = _batch(session, company_a, user_a, filename="a2.csv")
    batch_b, row_b = _batch(session, company_b, user_b, filename="b.csv")

    batches = ImportHistoryService.list_batches(session, context_a, limit=1)
    assert len(batches) == 1
    all_batches = ImportHistoryService.list_batches(session, context_a, limit=10)
    assert {batch.id for batch in all_batches} == {batch_a1.id, batch_a2.id}
    assert all(batch.company_id == company_a.id for batch in all_batches)

    rows = ImportHistoryService.list_rows(
        session, context_a, batch_id=batch_a1.id
    )
    assert len(rows) == 1
    assert rows[0].id == row_a1.id
    assert rows[0].row_status is ImportRowStatus.REVIEW

    with pytest.raises(ReportingError, match="not found in the active company"):
        ImportHistoryService.list_rows(
            session, context_a, batch_id=batch_b.id
        )
    with pytest.raises(ReportingError, match="limit"):
        ImportHistoryService.list_batches(session, context_a, limit=501)
    assert row_b.company_id == company_b.id


def test_audit_history_is_company_scoped_and_viewer_is_denied(session):
    _workspace_a, user_a, company_a, context_a = _context(session, suffix="audit-a")
    _workspace_b, user_b, company_b, _context_b = _context(session, suffix="audit-b")
    event_a = AuditEvent(
        company_id=company_a.id,
        actor_user_id=user_a.id,
        action="SYNTHETIC_AUDIT_A",
        entity_type="TEST",
        entity_id=uuid4(),
        after_json={"source": "company-a"},
    )
    event_b = AuditEvent(
        company_id=company_b.id,
        actor_user_id=user_b.id,
        action="SYNTHETIC_AUDIT_B",
        entity_type="TEST",
        entity_id=uuid4(),
        after_json={"source": "company-b"},
    )
    session.add_all([event_a, event_b])
    session.flush()

    events = AuditService.list_events(session, context_a)
    assert [item.id for item in events] == [event_a.id]
    assert events[0].company_id == company_a.id

    _workspace_v, _user_v, _company_v, viewer_context = _context(
        session, role=MembershipRole.VIEWER, suffix="audit-viewer"
    )
    with pytest.raises(PermissionError):
        AuditService.list_events(session, viewer_context)
