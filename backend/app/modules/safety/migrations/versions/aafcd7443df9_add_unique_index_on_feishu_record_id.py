"""Add partial unique index on feishu_record_id to prevent duplicate hazard creation.

当飞书 WebSocket 事件竞态（record_added + record_edited 同时触发）导致
并发 INSERT 时，此索引在数据库层面兜底防止重复记录创建。

注意：建索引前会先清理已存在的 feishu_record_id 重复记录（保留最早创建的，
其余软删除），否则已有脏数据会导致 CREATE UNIQUE INDEX 失败。
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'aafcd7443df9'
down_revision: str | tuple[str, ...] | None = 'd640ce4ef846'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 步骤 1：清理已有的 feishu_record_id 重复记录
    # 对每组重复，保留 created_at 最早的一条，其余软删除
    op.execute("""
        WITH duplicates AS (
            SELECT feishu_record_id
            FROM safety.hazard_reports
            WHERE is_deleted = false
              AND feishu_record_id IS NOT NULL
            GROUP BY feishu_record_id
            HAVING COUNT(*) > 1
        ),
        keep AS (
            SELECT DISTINCT ON (feishu_record_id) id
            FROM safety.hazard_reports
            WHERE feishu_record_id IN (SELECT feishu_record_id FROM duplicates)
              AND is_deleted = false
            ORDER BY feishu_record_id, created_at ASC
        )
        UPDATE safety.hazard_reports
        SET is_deleted = true, updated_at = now()
        WHERE feishu_record_id IN (SELECT feishu_record_id FROM duplicates)
          AND is_deleted = false
          AND id NOT IN (SELECT id FROM keep)
    """)

    # 步骤 2：创建部分唯一索引
    op.create_index(
        "uq_hazard_reports_feishu_record_id",
        "hazard_reports",
        ["feishu_record_id"],
        unique=True,
        schema="safety",
        postgresql_where="is_deleted = false AND feishu_record_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_hazard_reports_feishu_record_id",
        table_name="hazard_reports",
        schema="safety",
        postgresql_where="is_deleted = false AND feishu_record_id IS NOT NULL",
    )
