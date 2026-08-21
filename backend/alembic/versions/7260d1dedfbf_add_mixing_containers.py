"""add mixing containers

Revision ID: 7260d1dedfbf
Revises: 77804745dd04
Create Date: 2026-08-21 14:49:30.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7260d1dedfbf'
down_revision: Union[str, None] = '77804745dd04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mixing_containers',
        sa.Column('name', sa.String(length=100), nullable=False, comment='容器名称'),
        sa.Column('intermediate_type_id', sa.Uuid(), nullable=False, comment='装存的中间体类型'),
        sa.Column('line_id', sa.Uuid(), nullable=False, comment='所属产线'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='production',
    )
    op.create_index('ix_production_mixing_containers_line', 'mixing_containers', ['line_id'], unique=False, schema='production')
    op.create_index('ix_production_mixing_containers_type', 'mixing_containers', ['intermediate_type_id'], unique=False, schema='production')
    op.create_index('uq_production_mixing_containers_type_name', 'mixing_containers', ['intermediate_type_id', 'name'], unique=True, schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.add_column('batch_intermediate_consumptions', sa.Column('container_id', sa.Uuid(), nullable=True, comment='混装消耗来源容器（混装消耗时 output_id 为空）'), schema='production')
    op.alter_column('batch_intermediate_consumptions', 'output_id',
                    existing_type=sa.UUID(),
                    nullable=True,
                    comment='引用的产出记录，溯源关键字段（混装消耗为空）',
                    existing_comment='引用的产出记录，溯源关键字段',
                    schema='production')
    op.add_column('batch_intermediate_outputs', sa.Column('container_id', sa.Uuid(), nullable=True, comment='混装入库容器（选容器则混装，line_id 自动取容器所属产线）'), schema='production')


def downgrade() -> None:
    op.drop_column('batch_intermediate_outputs', 'container_id', schema='production')
    op.alter_column('batch_intermediate_consumptions', 'output_id',
                    existing_type=sa.UUID(),
                    nullable=False,
                    comment='引用的产出记录，溯源关键字段',
                    existing_comment='引用的产出记录，溯源关键字段（混装消耗为空）',
                    schema='production')
    op.drop_column('batch_intermediate_consumptions', 'container_id', schema='production')
    op.drop_index('uq_production_mixing_containers_type_name', table_name='mixing_containers', schema='production', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_production_mixing_containers_type', table_name='mixing_containers', schema='production')
    op.drop_index('ix_production_mixing_containers_line', table_name='mixing_containers', schema='production')
    op.drop_table('mixing_containers', schema='production')
