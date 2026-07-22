"""spare_parts 新增 department_id 字段

Revision ID: 651178fee589
Revises: adb348005928
Create Date: 2026-07-20 18:08:47.159249
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '651178fee589'
down_revision: Union[str, None] = 'adb348005928'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'spare_parts',
        sa.Column(
            'department_id',
            sa.Uuid(),
            nullable=True,
            comment='归属部门ID，逻辑引用 identity.departments.id',
        ),
        schema='equipment',
    )


def downgrade() -> None:
    op.drop_column('spare_parts', 'department_id', schema='equipment')
