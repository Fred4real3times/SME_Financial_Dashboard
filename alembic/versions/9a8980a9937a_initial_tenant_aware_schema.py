"""initial tenant-aware schema

Revision ID: 9a8980a9937a
Revises:
Create Date: 2026-11-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9a8980a9937a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(base_currency) = 3", name="ck_company_currency_length"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_companies_id_workspace"),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("ADMIN", "ACCOUNTANT", "VIEWER", name="membership_role", native_enum=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_membership_workspace_user"),
    )
    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("account_name", sa.String(length=120), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("opening_balance", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("source_description", sa.String(length=250), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(currency) = 3", name="ck_snapshot_currency_length"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_snapshots_company_account_date_currency",
        "account_snapshots",
        ["company_id", "account_name", "as_of_date", "currency"],
        unique=False,
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_company_created", "audit_events", ["company_id", "created_at"], unique=False
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("normalized_name", sa.String(length=80), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("INFLOW", "OUTFLOW", "BOTH", name="category_kind", native_enum=False),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "normalized_name", name="uq_category_company_normalized_name"),
        sa.UniqueConstraint("id", "company_id", name="uq_category_id_company"),
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "file_type",
            sa.Enum("CSV", "XLSX", "PDF", name="file_type", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "extraction_method",
            sa.Enum("CSV_ROWS", "XLSX_SHEET", "PDF_TABLE", "PDF_TEXT", name="import_method", native_enum=False),
            nullable=False,
        ),
        sa.Column("source_page_count", sa.Integer(), nullable=True),
        sa.Column("parser_version", sa.String(length=40), nullable=True),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PREVIEWED", "PARTIALLY_COMMITTED", "COMMITTED", "FAILED", "CANCELLED",
                name="import_batch_status", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("blank_count", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("outlier_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_import_batches_id_company"),
    )
    op.create_index(
        "ix_import_batches_company_created", "import_batches", ["company_id", "created_at"], unique=False
    )
    op.create_table(
        "categorization_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column(
            "match_field",
            sa.Enum("KEYWORD", "COUNTERPARTY", "REFERENCE", name="match_field", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "operator",
            sa.Enum("CONTAINS", "EQUALS", "STARTS_WITH", name="match_operator", native_enum=False),
            nullable=False,
        ),
        sa.Column("match_value", sa.String(length=200), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id", "company_id"],
            ["categories.id", "categories.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_categorization_rules_id_company"),
    )
    op.create_index(
        "ix_categorization_rules_company_active_priority",
        "categorization_rules",
        ["company_id", "is_active", "priority"],
        unique=False,
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("INFLOW", "OUTFLOW", name="transaction_direction", native_enum=False),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("counterparty", sa.String(length=200), nullable=True),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("account_name", sa.String(length=120), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column(
            "categorization_source",
            sa.Enum("RULE", "MANUAL", "NONE", name="categorization_source", native_enum=False),
            nullable=False,
        ),
        sa.Column("categorization_rule_id", sa.Uuid(), nullable=True),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("is_validated", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("deletion_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        sa.CheckConstraint("length(currency) = 3", name="ck_transaction_currency_length"),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND deleted_by_user_id IS NULL AND deletion_reason IS NULL) "
            "OR (deleted_at IS NOT NULL AND deleted_by_user_id IS NOT NULL "
            "AND deletion_reason IS NOT NULL AND length(trim(deletion_reason)) > 0)",
            name="ck_transaction_soft_delete_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["categorization_rule_id", "company_id"],
            ["categorization_rules.id", "categorization_rules.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "company_id"], ["categories.id", "categories.company_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deleted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["import_batch_id", "company_id"],
            ["import_batches.id", "import_batches.company_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "fingerprint_version", "source_fingerprint",
            name="uq_transaction_company_fingerprint",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_transactions_id_company"),
    )
    op.create_index(
        "ix_transactions_company_currency_direction_date",
        "transactions",
        ["company_id", "currency", "direction", "transaction_date"],
        unique=False,
    )
    op.create_index(
        "ix_transactions_company_date", "transactions", ["company_id", "transaction_date"], unique=False
    )
    op.create_table(
        "import_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("source_page_number", sa.Integer(), nullable=True),
        sa.Column("source_table_index", sa.Integer(), nullable=True),
        sa.Column("raw_values_json", sa.JSON(), nullable=False),
        sa.Column("normalized_values_json", sa.JSON(), nullable=True),
        sa.Column(
            "row_status",
            sa.Enum(
                "BLANK", "INVALID", "DUPLICATE", "VALID", "VALID_WITH_WARNING", "REVIEW",
                name="import_row_status", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("issues_json", sa.JSON(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "review_decision",
            sa.Enum(
                "ACCEPTED", "REJECTED", "CONFIRMED_DUPLICATE", "CORRECTED_AND_ACCEPTED",
                name="review_decision", native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("resolution_note", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "(review_decision IS NULL AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL) "
            "OR (review_decision IS NOT NULL AND reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_import_row_review_metadata_consistent",
        ),
        sa.CheckConstraint(
            "row_status != 'REVIEW' OR transaction_id IS NULL",
            name="ck_review_row_has_no_transaction",
        ),
        sa.CheckConstraint(
            "transaction_id IS NULL OR row_status IN ('VALID', 'VALID_WITH_WARNING')",
            name="ck_only_valid_rows_link_transaction",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id", "company_id"],
            ["import_batches.id", "import_batches.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["transaction_id", "company_id"],
            ["transactions.id", "transactions.company_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_import_rows_id_company"),
        sa.UniqueConstraint("import_batch_id", "source_row_number", name="uq_import_row_batch_row"),
        sa.UniqueConstraint("transaction_id", name="uq_import_row_transaction_link"),
    )
    op.create_index(
        "ix_import_rows_company_status", "import_rows", ["company_id", "row_status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_import_rows_company_status", table_name="import_rows")
    op.drop_table("import_rows")
    op.drop_index("ix_transactions_company_date", table_name="transactions")
    op.drop_index("ix_transactions_company_currency_direction_date", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_categorization_rules_company_active_priority", table_name="categorization_rules")
    op.drop_table("categorization_rules")
    op.drop_index("ix_import_batches_company_created", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_table("categories")
    op.drop_index("ix_audit_events_company_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_snapshots_company_account_date_currency", table_name="account_snapshots")
    op.drop_table("account_snapshots")
    op.drop_table("workspace_memberships")
    op.drop_table("companies")
    op.drop_table("workspaces")
    op.drop_table("users")
