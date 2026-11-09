"""Add first-run bootstrap and database-backed authentication sessions.

Revision ID: 2b7ce1a9c4d2
Revises: 9a8980a9937a
Create Date: 2026-11-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "2b7ce1a9c4d2"
down_revision = "9a8980a9937a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "workspace_memberships",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_session_token_hash"),
    )
    op.create_index(
        "ix_auth_sessions_user_expiry", "auth_sessions", ["user_id", "expires_at"], unique=False
    )
    op.create_table(
        "bootstrap_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initial_admin_user_id", sa.Uuid(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_bootstrap_state_singleton"),
        sa.ForeignKeyConstraint(["initial_admin_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("initial_admin_user_id", name="uq_bootstrap_initial_admin"),
    )


def downgrade() -> None:
    op.drop_table("bootstrap_state")
    op.drop_index("ix_auth_sessions_user_expiry", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_column("workspace_memberships", "is_active")
    op.drop_column("users", "must_change_password")
