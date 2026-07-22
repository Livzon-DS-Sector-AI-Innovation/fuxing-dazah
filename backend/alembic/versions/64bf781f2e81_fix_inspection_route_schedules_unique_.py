"""fix inspection_route_schedules unique constraint remove assigned_to

Revision ID: 64bf781f2e81
Revises: 0447bceeb298
Create Date: 2026-06-23 18:26:40.774633
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '64bf781f2e81'
down_revision: Union[str, None] = '0447bceeb298'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        'uq_route_schedules_route_cron_assignee',
        'inspection_route_schedules', schema='equipment', type_='unique',
    )
    op.create_unique_constraint(
        'uq_route_schedules_route_cron_deleted',
        'inspection_route_schedules',
        ['route_id', 'cron_expression', 'is_deleted'],
        schema='equipment',
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_route_schedules_route_cron_deleted',
        'inspection_route_schedules', schema='equipment', type_='unique',
    )
    op.create_unique_constraint(
        'uq_route_schedules_route_cron_assignee',
        'inspection_route_schedules',
        ['route_id', 'cron_expression', 'assigned_to', 'is_deleted'],
        schema='equipment',
    )
