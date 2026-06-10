"""add external model route profiles

Revision ID: 20260610_010000_add_external_model_route_profiles
Revises: 20260610_000000_add_external_model_route_admin_tables
Create Date: 2026-06-10 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260610_010000_add_external_model_route_profiles"
down_revision = "20260610_000000_add_external_model_route_admin_tables"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_NEW_TABLE = "external_model_routes_profile_migration"


def upgrade() -> None:
    if not _table_exists("external_model_routes"):
        return
    columns = _columns("external_model_routes")
    if "id" in columns:
        _ensure_indexes()
        return

    op.create_table(
        _NEW_TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_model", "name", name="uq_external_model_routes_public_model_name"),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT public_model, provider_id, target_model, endpoints_json,
                   request_overrides_json, strip_request_fields_json,
                   preserve_public_model, fallback_to_codex_pool, pricing_json,
                   is_active, created_at, updated_at
            FROM external_model_routes
            """
        )
    ).mappings()
    for row in rows:
        bind.execute(
            sa.text(
                f"""
                INSERT INTO {_NEW_TABLE} (
                    id, name, public_model, provider_id, target_model, endpoints_json,
                    request_overrides_json, strip_request_fields_json, preserve_public_model,
                    fallback_to_codex_pool, pricing_json, is_active, created_at, updated_at
                ) VALUES (
                    :id, :name, :public_model, :provider_id, :target_model, :endpoints_json,
                    :request_overrides_json, :strip_request_fields_json, :preserve_public_model,
                    :fallback_to_codex_pool, :pricing_json, :is_active, :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "name": _default_profile_name(str(row["provider_id"]), str(row["target_model"])),
                **dict(row),
            },
        )

    if _index_exists("external_model_routes", "idx_external_model_routes_provider"):
        op.drop_index("idx_external_model_routes_provider", table_name="external_model_routes")
    op.drop_table("external_model_routes")
    op.rename_table(_NEW_TABLE, "external_model_routes")
    _ensure_indexes()


def downgrade() -> None:
    if not _table_exists("external_model_routes"):
        return
    columns = _columns("external_model_routes")
    if "id" not in columns:
        return

    op.create_table(
        _NEW_TABLE,
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
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT public_model, provider_id, target_model, endpoints_json,
                   request_overrides_json, strip_request_fields_json,
                   preserve_public_model, fallback_to_codex_pool, pricing_json,
                   is_active, created_at, updated_at
            FROM external_model_routes
            ORDER BY public_model ASC, is_active DESC, updated_at DESC
            """
        )
    ).mappings()
    copied_models: set[str] = set()
    for row in rows:
        public_model = str(row["public_model"])
        if public_model in copied_models:
            continue
        copied_models.add(public_model)
        bind.execute(
            sa.text(
                f"""
                INSERT INTO {_NEW_TABLE} (
                    public_model, provider_id, target_model, endpoints_json,
                    request_overrides_json, strip_request_fields_json, preserve_public_model,
                    fallback_to_codex_pool, pricing_json, is_active, created_at, updated_at
                ) VALUES (
                    :public_model, :provider_id, :target_model, :endpoints_json,
                    :request_overrides_json, :strip_request_fields_json, :preserve_public_model,
                    :fallback_to_codex_pool, :pricing_json, :is_active, :created_at, :updated_at
                )
                """
            ),
            dict(row),
        )

    _drop_profile_indexes()
    op.drop_table("external_model_routes")
    op.rename_table(_NEW_TABLE, "external_model_routes")
    op.create_index(
        "idx_external_model_routes_provider",
        "external_model_routes",
        ["provider_id", "is_active"],
    )


def _ensure_indexes() -> None:
    if not _index_exists("external_model_routes", "idx_external_model_routes_public_model"):
        op.create_index(
            "idx_external_model_routes_public_model",
            "external_model_routes",
            ["public_model", "is_active"],
        )
    if not _index_exists("external_model_routes", "idx_external_model_routes_provider"):
        op.create_index(
            "idx_external_model_routes_provider",
            "external_model_routes",
            ["provider_id", "is_active"],
        )


def _drop_profile_indexes() -> None:
    for index_name in ("idx_external_model_routes_public_model", "idx_external_model_routes_provider"):
        if _index_exists("external_model_routes", index_name):
            op.drop_index(index_name, table_name="external_model_routes")


def _default_profile_name(provider_id: str, target_model: str) -> str:
    return f"{provider_id} → {target_model}"[:255]


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))
