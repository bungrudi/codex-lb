"""add external model route admin tables

Revision ID: 20260610_000000_add_external_model_route_admin_tables
Revises: 20260609_000000_add_external_provider_request_log_fields
Create Date: 2026-06-10 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260610_000000_add_external_model_route_admin_tables"
down_revision = "20260609_000000_add_external_provider_request_log_fields"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    if not _table_exists("external_providers"):
        op.create_table(
            "external_providers",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), server_default=sa.text("'openai_compatible'"), nullable=False),
            sa.Column("base_url", sa.String(), nullable=False),
            sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=True),
            sa.Column("api_key_env", sa.String(), nullable=True),
            sa.Column("default_headers_json", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
            sa.Column("timeout_seconds", sa.Float(), server_default=sa.text("600.0"), nullable=False),
            sa.Column("stream_idle_timeout_seconds", sa.Float(), server_default=sa.text("600.0"), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("allow_insecure_base_url", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _table_exists("external_model_routes"):
        op.create_table(
            "external_model_routes",
            sa.Column("public_model", sa.String(), nullable=False),
            sa.Column("provider_id", sa.String(), nullable=False),
            sa.Column("target_model", sa.String(), nullable=False),
            sa.Column("endpoints_json", sa.Text(), nullable=False),
            sa.Column("request_overrides_json", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
            sa.Column("strip_request_fields_json", sa.Text(), server_default=sa.text("'[]'"), nullable=False),
            sa.Column("preserve_public_model", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("fallback_to_codex_pool", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("pricing_json", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["provider_id"], ["external_providers.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("public_model"),
        )
    if _table_exists("external_model_routes") and not _index_exists(
        "external_model_routes",
        "idx_external_model_routes_provider",
    ):
        op.create_index(
            "idx_external_model_routes_provider",
            "external_model_routes",
            ["provider_id", "is_active"],
        )


def downgrade() -> None:
    if _table_exists("external_model_routes") and _index_exists(
        "external_model_routes",
        "idx_external_model_routes_provider",
    ):
        op.drop_index("idx_external_model_routes_provider", table_name="external_model_routes")
    if _table_exists("external_model_routes"):
        op.drop_table("external_model_routes")
    if _table_exists("external_providers"):
        op.drop_table("external_providers")


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))
