"""add external provider request log fields

Revision ID: 20260609_000000_add_external_provider_request_log_fields
Revises: 20260607_000000_merge_weekly_monthly_useragent_heads
Create Date: 2026-06-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260609_000000_add_external_provider_request_log_fields"
down_revision = "20260607_000000_merge_weekly_monthly_useragent_heads"
branch_labels = None
depends_on = None

_REQUEST_LOGS_TABLE = "request_logs"
_EXTERNAL_COLUMNS = (
    ("external_provider_id", sa.Column("external_provider_id", sa.String(), nullable=True)),
    ("external_provider_model", sa.Column("external_provider_model", sa.String(), nullable=True)),
    ("external_route_public_model", sa.Column("external_route_public_model", sa.String(), nullable=True)),
    ("external_route_endpoint", sa.Column("external_route_endpoint", sa.String(), nullable=True)),
    ("external_fallback_used", sa.Column("external_fallback_used", sa.Boolean(), nullable=True)),
    ("external_fallback_reason", sa.Column("external_fallback_reason", sa.String(), nullable=True)),
)


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def _add_column_if_missing(connection: Connection, table_name: str, column_name: str, column: sa.Column) -> None:
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
    if not sa.inspect(bind).has_table(_REQUEST_LOGS_TABLE):
        return
    for column_name, column in _EXTERNAL_COLUMNS:
        _add_column_if_missing(bind, _REQUEST_LOGS_TABLE, column_name, column)


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_REQUEST_LOGS_TABLE):
        return
    for column_name, _column in reversed(_EXTERNAL_COLUMNS):
        _drop_column_if_present(bind, _REQUEST_LOGS_TABLE, column_name)
