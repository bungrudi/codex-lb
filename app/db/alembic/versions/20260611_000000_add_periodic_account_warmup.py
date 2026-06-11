"""add periodic account warm-up

Revision ID: 20260611_000000_add_periodic_account_warmup
Revises: 20260607_000000_merge_weekly_monthly_useragent_heads
Create Date: 2026-06-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260611_000000_add_periodic_account_warmup"
down_revision = "20260610_020000_allow_duplicate_external_route_profile_names"
branch_labels = None
depends_on = None

_PERIODIC_TABLE = "account_periodic_warmups"


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def _indexes(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(index["name"]) for index in inspector.get_indexes(table_name) if index.get("name") is not None}


def _add_column_if_missing(
    connection: Connection,
    table_name: str,
    column_name: str,
    column: sa.Column,
) -> None:
    columns = _columns(connection, table_name)
    if not columns or column_name in columns:
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(column)


def _drop_column_if_present(connection: Connection, table_name: str, column_name: str) -> None:
    columns = _columns(connection, table_name)
    if not columns or column_name not in columns:
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_column(column_name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("accounts"):
        _add_column_if_missing(
            bind,
            "accounts",
            "periodic_warmup_enabled",
            sa.Column("periodic_warmup_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    if inspector.has_table("dashboard_settings"):
        dashboard_columns = {
            "periodic_warmup_enabled": sa.Column(
                "periodic_warmup_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            "periodic_warmup_interval_hours": sa.Column(
                "periodic_warmup_interval_hours",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("6"),
            ),
            "periodic_warmup_model": sa.Column(
                "periodic_warmup_model",
                sa.String(),
                nullable=False,
                server_default=sa.text("'auto'"),
            ),
            "periodic_warmup_prompt": sa.Column(
                "periodic_warmup_prompt",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'Say OK.'"),
            ),
            "periodic_warmup_target_scope": sa.Column(
                "periodic_warmup_target_scope",
                sa.String(),
                nullable=False,
                server_default=sa.text("'all_active'"),
            ),
        }
        for column_name, column in dashboard_columns.items():
            _add_column_if_missing(bind, "dashboard_settings", column_name, column)

    if not inspector.has_table(_PERIODIC_TABLE):
        op.create_table(
            _PERIODIC_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("account_id", sa.String(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("claim_key", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("attempted_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("request_id", sa.String(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("claim_key", name="uq_account_periodic_warmups_claim_key"),
        )

    periodic_indexes = _indexes(bind, _PERIODIC_TABLE)
    if "idx_account_periodic_warmups_account_attempted" not in periodic_indexes:
        op.create_index(
            "idx_account_periodic_warmups_account_attempted",
            _PERIODIC_TABLE,
            ["account_id", sa.text("attempted_at DESC")],
            unique=False,
        )
    if "idx_account_periodic_warmups_status_attempted" not in periodic_indexes:
        op.create_index(
            "idx_account_periodic_warmups_status_attempted",
            _PERIODIC_TABLE,
            ["status", sa.text("attempted_at DESC")],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table(_PERIODIC_TABLE):
        periodic_indexes = _indexes(bind, _PERIODIC_TABLE)
        if "idx_account_periodic_warmups_status_attempted" in periodic_indexes:
            op.drop_index("idx_account_periodic_warmups_status_attempted", table_name=_PERIODIC_TABLE)
        if "idx_account_periodic_warmups_account_attempted" in periodic_indexes:
            op.drop_index("idx_account_periodic_warmups_account_attempted", table_name=_PERIODIC_TABLE)
        op.drop_table(_PERIODIC_TABLE)

    if inspector.has_table("dashboard_settings"):
        for column_name in (
            "periodic_warmup_target_scope",
            "periodic_warmup_prompt",
            "periodic_warmup_model",
            "periodic_warmup_interval_hours",
            "periodic_warmup_enabled",
        ):
            _drop_column_if_present(bind, "dashboard_settings", column_name)

    if inspector.has_table("accounts"):
        _drop_column_if_present(bind, "accounts", "periodic_warmup_enabled")
