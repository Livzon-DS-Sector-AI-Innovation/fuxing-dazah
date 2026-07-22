"""add equipment_templates to inspection_tasks

Revision ID: 706fdf53f046
Revises: 3203f5f17333
Create Date: 2026-06-22 11:25:50.533023
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '706fdf53f046'
down_revision: Union[str, None] = '3203f5f17333'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'inspection_tasks',
        sa.Column(
            'equipment_templates',
            sa.JSON(),
            nullable=True,
            comment='设备-模板绑定 {equipment_id: [template_id,...]}',
        ),
        schema='equipment',
    )
    op.alter_column(
        'inspection_tasks',
        'template_ids',
        existing_type=postgresql.JSON(astext_type=sa.Text()),
        comment='[DEPRECATED] 设备巡检绑定的模板ID列表，推荐用 equipment_templates',
        existing_comment='设备巡检绑定的模板ID列表',
        existing_nullable=True,
        schema='equipment',
    )


def downgrade() -> None:
    op.alter_column(
        'inspection_tasks',
        'template_ids',
        existing_type=postgresql.JSON(astext_type=sa.Text()),
        comment='设备巡检绑定的模板ID列表',
        existing_comment='[DEPRECATED] 设备巡检绑定的模板ID列表，推荐用 equipment_templates',
        existing_nullable=True,
        schema='equipment',
    )
    op.drop_column('inspection_tasks', 'equipment_templates', schema='equipment')
