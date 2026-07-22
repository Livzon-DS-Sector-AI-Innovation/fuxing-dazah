"""add table_id to energy_type_configs

Revision ID: 79faec14363d
Revises: 20fda41cfdd3
Create Date: 2026-07-15 11:15:35.192814
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79faec14363d'
down_revision: Union[str, None] = '20fda41cfdd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS energy")

    # Ensure energy_type_configs table exists before altering it.
    # 7e70c41a9cdc (CREATE TABLE) lives on a dead branch from 241f68a331ab
    # and was never merged into the main migration line, so on fresh
    # databases this table may be missing.  The raw SQL below is the
    # structural equivalent of what 7e70c41a9cdc would have produced.
    op.execute("""
        CREATE TABLE IF NOT EXISTS energy.energy_type_configs (
            type_code   VARCHAR(50)  NOT NULL,
            parent_code VARCHAR(50),
            display_name VARCHAR(100) NOT NULL,
            unit        VARCHAR(20)  NOT NULL,
            icon        VARCHAR(50),
            sort_order  INTEGER      NOT NULL,
            is_enabled  BOOLEAN      NOT NULL,
            remark      TEXT,
            id          UUID         NOT NULL,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            created_by  UUID,
            updated_by  UUID,
            is_deleted  BOOLEAN      NOT NULL DEFAULT false,
            PRIMARY KEY (id),
            CONSTRAINT uq_energy_type_config_code UNIQUE (type_code, is_deleted)
        )
    """)

    op.add_column(
        'energy_type_configs',
        sa.Column('table_id', sa.String(length=100), nullable=True, comment='飞书多维表格 Table ID'),
        schema='energy',
    )


def downgrade() -> None:
    op.drop_column('energy_type_configs', 'table_id', schema='energy')
