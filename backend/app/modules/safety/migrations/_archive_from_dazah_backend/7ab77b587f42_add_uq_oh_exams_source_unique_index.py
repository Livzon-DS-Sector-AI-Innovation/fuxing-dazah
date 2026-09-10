"""add uq_oh_exams_source unique index

来源表联动建体检记录幂等保证（D7，backend-design.md §5.4）：
oh_health_exams 增加部分唯一索引 uq_oh_exams_source (source_table, source_record_id)
WHERE is_deleted = false AND source_table IS NOT NULL AND source_record_id IS NOT NULL
——同一来源记录（新员工登记 / 转岗离岗申请）只建一条体检记录；
软删时清空 source 键，避免「删→加」重复。

存量数据清理（建索引前置步骤）：
体检记录表镜像行存在同源重复（实测 2 组 4 行，Bitable 历史脏数据：
同一来源记录对应多条体检记录，如 张变晖 new_employee/recvgDy55atD2r ×2），
唯一索引无法创建。每组保留最早一条（min id），其余清空 source 键
（source_table/source_record_id 为镜像行信息字段，exam_type 已按 E4 回填，不影响业务）。
downgrade 不恢复已清空的 source 键（数据清理不可逆，属可接受的信息字段丢失）。

Revision ID: 7ab77b587f42
Revises: 4af6c8f79ac8
Create Date: 2026-08-13 16:44:06.246758
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ab77b587f42'
down_revision: Union[str, None] = '4af6c8f79ac8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. 存量同源重复清理：每组 (source_table, source_record_id) 保留最早一条（min id），
    #    其余清空 source 键，保证唯一索引可创建
    op.execute("""
        UPDATE safety.oh_health_exams
        SET source_table = NULL, source_record_id = NULL, updated_at = now()
        WHERE is_deleted = false
          AND source_table IS NOT NULL AND source_record_id IS NOT NULL
          AND id NOT IN (
              SELECT DISTINCT ON (source_table, source_record_id) id
              FROM safety.oh_health_exams
              WHERE is_deleted = false
                AND source_table IS NOT NULL AND source_record_id IS NOT NULL
              ORDER BY source_table, source_record_id, id
          )
    """)

    # 1. 来源表 → 体检记录 一对一唯一索引（D7：幂等，防重复建）
    op.create_index(
        'uq_oh_exams_source', 'oh_health_exams', ['source_table', 'source_record_id'],
        unique=True, schema='safety',
        postgresql_where=sa.text(
            'is_deleted = false AND source_table IS NOT NULL AND source_record_id IS NOT NULL'
        ),
    )


def downgrade() -> None:
    op.drop_index('uq_oh_exams_source', table_name='oh_health_exams', schema='safety')
