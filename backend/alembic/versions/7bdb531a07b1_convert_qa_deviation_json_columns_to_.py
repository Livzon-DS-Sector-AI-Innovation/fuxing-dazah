"""convert qa deviation json columns to jsonb

why_chain / repeat_deviation_ids 使用 JSON 列并带 server_default '[]' 时，
alembic 的 compare_server_default 会执行 ``json = json`` 比较；PostgreSQL 的
json 类型没有等号操作符，``alembic check`` / ``revision --autogenerate`` 会直接
报 “operator does not exist: json = unknown”。与 meter 模块保持一致改用 JSONB。

Revision ID: 7bdb531a07b1
Revises: 0186560836f7
Create Date: 2026-10-23 10:05:13.701385
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7bdb531a07b1"
down_revision: str | None = "0186560836f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("why_chain", "repeat_deviation_ids")


def upgrade() -> None:
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE qa.deviations "
            f"ALTER COLUMN {column} TYPE jsonb USING {column}::jsonb"
        )
        op.execute(
            f"ALTER TABLE qa.deviations "
            f"ALTER COLUMN {column} SET DEFAULT '[]'::jsonb"
        )


def downgrade() -> None:
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE qa.deviations "
            f"ALTER COLUMN {column} SET DEFAULT '[]'::json"
        )
        op.execute(
            f"ALTER TABLE qa.deviations "
            f"ALTER COLUMN {column} TYPE json USING {column}::json"
        )
