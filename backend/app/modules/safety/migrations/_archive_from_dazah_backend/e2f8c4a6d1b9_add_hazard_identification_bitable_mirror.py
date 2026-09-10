"""hazard_identifications 扩展 Bitable 镜像同步字段

Revision ID: e2f8c4a6d1b9
Revises: f3db08a3b9a2
Create Date: 2026-08-07

为 HazardIdentification 增加危险源辨识自动化多维表格的镜像同步字段：
- feishu_record_id（部分唯一索引，同步主键）/ feishu_url / feishu_table_id
- 提交/审核人员（姓名 + 飞书 ID）
- 脚本8 四类排查内容（AI + 人工 各一列）
- bitable_snapshot（JSONB 完整快照）
- department/position/production_step 改为可空（Bitable 无部门字段）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

from alembic import op

revision: str = "e2f8c4a6d1b9"
down_revision: str | None = "f3db08a3b9a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 新增列（按列名列表，downgrade 复用）
_NEW_COLUMNS = [
    "feishu_record_id",
    "feishu_url",
    "feishu_table_id",
    "submitter_name",
    "submitter_feishu_id",
    "reviewer_name",
    "reviewer_feishu_id",
    "engineering_check_items_ai",
    "engineering_check_items_manual",
    "management_check_items_ai",
    "management_check_items_manual",
    "ppe_check_items_ai",
    "ppe_check_items_manual",
    "emergency_check_items_ai",
    "emergency_check_items_manual",
    "bitable_snapshot",
]


def upgrade() -> None:
    # 1. 新增镜像同步列（均 nullable，存量记录不受影响）
    columns = [
        sa.Column("feishu_record_id", sa.String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）"),
        sa.Column("feishu_url", sa.String(500), nullable=True, comment="飞书 Bitable 记录 URL"),
        sa.Column("feishu_table_id", sa.String(64), nullable=True, comment="飞书 Bitable 表 ID"),
        sa.Column("submitter_name", sa.String(100), nullable=True, comment="提交人员姓名"),
        sa.Column("submitter_feishu_id", sa.String(100), nullable=True, comment="提交人员飞书 ID"),
        sa.Column("reviewer_name", sa.String(100), nullable=True, comment="审核人员姓名"),
        sa.Column("reviewer_feishu_id", sa.String(100), nullable=True, comment="审核人员飞书 ID"),
        # 脚本8 四类排查内容（AI + 人工 各一列）
        sa.Column("engineering_check_items_ai", sa.Text, nullable=True, comment="工程措施排查内容（AI）"),
        sa.Column("engineering_check_items_manual", sa.Text, nullable=True, comment="工程措施排查内容（人工）"),
        sa.Column("management_check_items_ai", sa.Text, nullable=True, comment="管理措施排查内容（AI）"),
        sa.Column("management_check_items_manual", sa.Text, nullable=True, comment="管理措施排查内容（人工）"),
        sa.Column("ppe_check_items_ai", sa.Text, nullable=True, comment="个人防护措施排查内容（AI）"),
        sa.Column("ppe_check_items_manual", sa.Text, nullable=True, comment="个人防护措施排查内容（人工）"),
        sa.Column("emergency_check_items_ai", sa.Text, nullable=True, comment="应急措施排查内容（AI）"),
        sa.Column("emergency_check_items_manual", sa.Text, nullable=True, comment="应急措施排查内容（人工）"),
        sa.Column("bitable_snapshot", JSON, nullable=True, comment="Bitable 完整字段快照（AI/人工双份 + 公式结果）"),
    ]
    for col in columns:
        op.add_column("hazard_identifications", col, schema="safety")

    # 2. feishu_record_id 部分唯一索引（仅有效记录，避免软删冲突）
    op.create_index(
        "uq_hazard_identifications_feishu_id",
        "hazard_identifications",
        ["feishu_record_id"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("feishu_record_id IS NOT NULL AND is_deleted = false"),
    )

    # 3. 基础字段可空化（Bitable 无部门字段，镜像时从提交人员派生，派不到置空）
    op.alter_column("hazard_identifications", "department", existing_type=sa.String(100), nullable=True, schema="safety")
    op.alter_column("hazard_identifications", "position", existing_type=sa.String(100), nullable=True, schema="safety")
    op.alter_column("hazard_identifications", "production_step", existing_type=sa.Text, nullable=True, schema="safety")


def downgrade() -> None:
    # 1. 恢复 NOT NULL（存量均为镜像前的人工记录，department/position 均有值）
    op.alter_column("hazard_identifications", "department", existing_type=sa.String(100), nullable=False, schema="safety")
    op.alter_column("hazard_identifications", "position", existing_type=sa.String(100), nullable=False, schema="safety")
    op.alter_column("hazard_identifications", "production_step", existing_type=sa.Text, nullable=False, schema="safety")

    # 2. 删除部分唯一索引
    op.drop_index("uq_hazard_identifications_feishu_id", table_name="hazard_identifications", schema="safety")

    # 3. 删除新增列
    for col_name in _NEW_COLUMNS:
        op.drop_column("hazard_identifications", col_name, schema="safety")
