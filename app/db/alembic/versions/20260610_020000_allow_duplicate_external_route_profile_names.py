"""allow duplicate external route profile names

Revision ID: 20260610_020000_allow_duplicate_external_route_profile_names
Revises: 20260610_010000_add_external_model_route_profiles
Create Date: 2026-06-10 02:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260610_020000_allow_duplicate_external_route_profile_names"
down_revision = "20260610_010000_add_external_model_route_profiles"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_CONSTRAINT_NAME = "uq_external_model_routes_public_model_name"
_TABLE_NAME = "external_model_routes"


def upgrade() -> None:
    if not _table_exists(_TABLE_NAME) or not _unique_constraint_exists(_TABLE_NAME, _CONSTRAINT_NAME):
        return
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="unique")


def downgrade() -> None:
    if not _table_exists(_TABLE_NAME) or _unique_constraint_exists(_TABLE_NAME, _CONSTRAINT_NAME):
        return
    _deduplicate_profile_names_for_downgrade()
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.create_unique_constraint(_CONSTRAINT_NAME, ["public_model", "name"])


def _deduplicate_profile_names_for_downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, public_model, name
            FROM external_model_routes
            ORDER BY public_model ASC, name ASC, created_at ASC, id ASC
            """
        )
    ).mappings()
    seen: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row["public_model"]), str(row["name"]))
        count = seen.get(key, 0)
        seen[key] = count + 1
        if count == 0:
            continue
        suffix = f" ({count + 1})"
        new_name = f"{key[1][: 255 - len(suffix)]}{suffix}"
        bind.execute(
            sa.text("UPDATE external_model_routes SET name = :name WHERE id = :id"),
            {"name": new_name, "id": row["id"]},
        )


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint.get("name") == constraint_name
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    )
