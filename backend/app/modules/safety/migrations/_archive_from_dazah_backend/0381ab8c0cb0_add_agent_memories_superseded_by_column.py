"""add agent_memories superseded_by column

Revision ID: 0381ab8c0cb0
Revises: ca64274cbd89
Create Date: 2026-08-19 16:36:59.844188

手工清理：autogenerate 混入了大量其它模块无关变更（permissions 建表、safety 业务表
误 drop/alter、scheduler_job_runs FK 等），只保留本任务「agent_memories 加 superseded_by
列 + 索引」的 DDL，避免破坏现有数据与 schema。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0381ab8c0cb0'
down_revision: Union[str, None] = 'ca64274cbd89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # agent_memories 增加 superseded_by 列（冲突合并留痕：指向取代它的新记忆 id）
    op.add_column(
        'agent_memories',
        sa.Column('superseded_by', sa.Uuid(), nullable=True,
                  comment='被哪条记忆取代（冲突合并：相似度>0.85 时旧记忆置 superseded_by=新记忆 id）'),
        schema='safety',
    )
    op.create_index(
        'ix_agent_memories_superseded_by', 'agent_memories', ['superseded_by'],
        unique=False, schema='safety',
    )


def downgrade() -> None:
    op.drop_index('ix_agent_memories_superseded_by', table_name='agent_memories', schema='safety')
    op.drop_column('agent_memories', 'superseded_by', schema='safety')