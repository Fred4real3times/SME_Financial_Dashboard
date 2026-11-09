"""Initial tenant-aware persistence model for the approved MVP contract."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sme_financial_dashboard.db.base import Base, TimestampMixin


class MembershipRole(StrEnum):
    ADMIN = "ADMIN"
    ACCOUNTANT = "ACCOUNTANT"
    VIEWER = "VIEWER"


class FileType(StrEnum):
    CSV = "CSV"
    XLSX = "XLSX"
    PDF = "PDF"


class ImportMethod(StrEnum):
    CSV_ROWS = "CSV_ROWS"
    XLSX_SHEET = "XLSX_SHEET"
    PDF_TABLE = "PDF_TABLE"
    PDF_TEXT = "PDF_TEXT"


class ImportBatchStatus(StrEnum):
    PREVIEWED = "PREVIEWED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ImportRowStatus(StrEnum):
    BLANK = "BLANK"
    INVALID = "INVALID"
    DUPLICATE = "DUPLICATE"
    VALID = "VALID"
    VALID_WITH_WARNING = "VALID_WITH_WARNING"
    REVIEW = "REVIEW"


class Direction(StrEnum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class CategoryKind(StrEnum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"
    BOTH = "BOTH"


class MatchField(StrEnum):
    KEYWORD = "KEYWORD"
    COUNTERPARTY = "COUNTERPARTY"
    REFERENCE = "REFERENCE"


class MatchOperator(StrEnum):
    CONTAINS = "CONTAINS"
    EQUALS = "EQUALS"
    STARTS_WITH = "STARTS_WITH"


class CategorizationSource(StrEnum):
    RULE = "RULE"
    MANUAL = "MANUAL"
    NONE = "NONE"


class ReviewDecision(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE"
    CORRECTED_AND_ACCEPTED = "CORRECTED_AND_ACCEPTED"


def enum_type(enum_cls: type[StrEnum], name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        values_callable=lambda values: [value.value for value in values],
    )


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    companies: Mapped[list[Company]] = relationship(back_populates="workspace")
    memberships: Mapped[list[WorkspaceMembership]] = relationship(back_populates="workspace")


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_companies_id_workspace"),
        CheckConstraint("length(base_currency) = 3", name="ck_company_currency_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Douala")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    workspace: Mapped[Workspace] = relationship(back_populates="companies")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    memberships: Mapped[list[WorkspaceMembership]] = relationship(back_populates="user")


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_membership_workspace_user"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        enum_type(MembershipRole, "membership_role"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_import_batches_id_company"),
        Index("ix_import_batches_company_created", "company_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_type: Mapped[FileType] = mapped_column(enum_type(FileType, "file_type"), nullable=False)
    extraction_method: Mapped[ImportMethod] = mapped_column(
        enum_type(ImportMethod, "import_method"), nullable=False
    )
    source_page_count: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str | None] = mapped_column(String(40))
    mapping_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[ImportBatchStatus] = mapped_column(
        enum_type(ImportBatchStatus, "import_batch_status"),
        nullable=False,
        default=ImportBatchStatus.PREVIEWED,
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blank_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outlier_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows: Mapped[list[ImportRow]] = relationship(back_populates="batch")


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["import_batch_id", "company_id"],
            ["import_batches.id", "import_batches.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["transaction_id", "company_id"],
            ["transactions.id", "transactions.company_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("import_batch_id", "source_row_number", name="uq_import_row_batch_row"),
        UniqueConstraint("id", "company_id", name="uq_import_rows_id_company"),
        UniqueConstraint("transaction_id", name="uq_import_row_transaction_link"),
        CheckConstraint(
            "row_status != 'REVIEW' OR transaction_id IS NULL",
            name="ck_review_row_has_no_transaction",
        ),
        CheckConstraint(
            "transaction_id IS NULL OR row_status IN ('VALID', 'VALID_WITH_WARNING')",
            name="ck_only_valid_rows_link_transaction",
        ),
        CheckConstraint(
            "(review_decision IS NULL AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL) "
            "OR (review_decision IS NOT NULL AND reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_import_row_review_metadata_consistent",
        ),
        Index("ix_import_rows_company_status", "company_id", "row_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    import_batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_page_number: Mapped[int | None] = mapped_column(Integer)
    source_table_index: Mapped[int | None] = mapped_column(Integer)
    raw_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    normalized_values_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    row_status: Mapped[ImportRowStatus] = mapped_column(
        enum_type(ImportRowStatus, "import_row_status"), nullable=False
    )
    issues_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    transaction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_decision: Mapped[ReviewDecision | None] = mapped_column(
        enum_type(ReviewDecision, "review_decision")
    )
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    batch: Mapped[ImportBatch] = relationship(back_populates="rows")


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("company_id", "normalized_name", name="uq_category_company_normalized_name"),
        UniqueConstraint("id", "company_id", name="uq_category_id_company"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[CategoryKind] = mapped_column(
        enum_type(CategoryKind, "category_kind"), nullable=False, default=CategoryKind.BOTH
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CategorizationRule(Base, TimestampMixin):
    __tablename__ = "categorization_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "company_id"],
            ["categories.id", "categories.company_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_categorization_rules_id_company"),
        Index("ix_categorization_rules_company_active_priority", "company_id", "is_active", "priority"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    match_field: Mapped[MatchField] = mapped_column(enum_type(MatchField, "match_field"), nullable=False)
    operator: Mapped[MatchOperator] = mapped_column(enum_type(MatchOperator, "match_operator"), nullable=False)
    match_value: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "company_id"],
            ["categories.id", "categories.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["import_batch_id", "company_id"],
            ["import_batches.id", "import_batches.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["categorization_rule_id", "company_id"],
            ["categorization_rules.id", "categorization_rules.company_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        CheckConstraint(
            "(deleted_at IS NULL AND deleted_by_user_id IS NULL AND deletion_reason IS NULL) "
            "OR (deleted_at IS NOT NULL AND deleted_by_user_id IS NOT NULL "
            "AND deletion_reason IS NOT NULL AND length(trim(deletion_reason)) > 0)",
            name="ck_transaction_soft_delete_metadata",
        ),
        UniqueConstraint(
            "company_id",
            "fingerprint_version",
            "source_fingerprint",
            name="uq_transaction_company_fingerprint",
        ),
        UniqueConstraint("id", "company_id", name="uq_transactions_id_company"),
        CheckConstraint("length(currency) = 3", name="ck_transaction_currency_length"),
        Index("ix_transactions_company_date", "company_id", "transaction_date"),
        Index(
            "ix_transactions_company_currency_direction_date",
            "company_id",
            "currency",
            "direction",
            "transaction_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    import_batch_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6, asdecimal=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    direction: Mapped[Direction] = mapped_column(
        enum_type(Direction, "transaction_direction"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(500))
    counterparty: Mapped[str | None] = mapped_column(String(200))
    reference: Mapped[str | None] = mapped_column(String(200))
    account_name: Mapped[str | None] = mapped_column(String(120))
    category_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    categorization_source: Mapped[CategorizationSource] = mapped_column(
        enum_type(CategorizationSource, "categorization_source"),
        nullable=False,
        default=CategorizationSource.NONE,
    )
    categorization_rule_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    fingerprint_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    deletion_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="ck_snapshot_currency_length"),
        Index(
            "ix_snapshots_company_account_date_currency",
            "company_id",
            "account_name",
            "as_of_date",
            "currency",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(20, 6, asdecimal=True), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_description: Mapped[str | None] = mapped_column(String(250))
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_company_created", "company_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    correlation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )



class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_session_token_hash"),
        Index("ix_auth_sessions_user_expiry", "user_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BootstrapState(Base):
    __tablename__ = "bootstrap_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_bootstrap_state_singleton"),
        UniqueConstraint("initial_admin_user_id", name="uq_bootstrap_initial_admin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    initial_admin_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    initialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
