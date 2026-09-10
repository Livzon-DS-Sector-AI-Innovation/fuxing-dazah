"""refactor_special_ops_daily_report

Revision ID: n2o3p4q5r6s7
Revises: 97454d0f435a
Create Date: 2026-07-27

重构：将日报数据合并到 SpecialOperationReport，删除独立的 daily_logs 表。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "n2o3p4q5r6s7"
down_revision: str | None = "97454d0f435a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. 给 special_operation_reports 增加 Bitable 同步字段 ──
    columns = [
        sa.Column("source", sa.String(16), server_default="manual", nullable=False,
                  comment="数据来源: manual/bitable"),
        sa.Column("feishu_record_id", sa.String(64), nullable=True, comment="飞书 Bitable 记录 ID"),
        sa.Column("personnel_type", sa.String(16), nullable=True, comment="作业人员类型"),
        sa.Column("work_duration_hours", sa.Float, nullable=True, comment="作业时长（小时）"),
        sa.Column("has_other_operations", sa.String(4), nullable=True, comment="是否涉及其他特殊作业"),
        sa.Column("other_operation_types", JSON, nullable=True, comment="涉及特殊作业类型列表"),
        sa.Column("is_weekend_holiday", sa.String(4), nullable=True, comment="周末节假日/非上班时段"),
        sa.Column("is_national_holiday", sa.String(4), nullable=True, comment="是否国家法定节假日"),
        sa.Column("holiday_period", sa.String(64), nullable=True, comment="非上班时间段/节假日"),
        sa.Column("report_type", sa.String(16), nullable=True, comment="报备类型: planned/unplanned"),
        sa.Column("initiator_department", sa.String(100), nullable=True, comment="发起人部门"),
        sa.Column("initiator_name", sa.String(100), nullable=True, comment="发起人姓名"),
        sa.Column("approver_type", sa.String(32), nullable=True, comment="审批人类型"),
        sa.Column("safety_approver_name", sa.String(100), nullable=True, comment="安全审批人"),
        sa.Column("approval_no", sa.String(255), nullable=True, comment="飞书申请编号"),
        sa.Column("work_plan_url", sa.String(500), nullable=True, comment="作业计划 URL"),
        sa.Column("work_scheme_url", sa.String(500), nullable=True, comment="作业方案 URL"),
        sa.Column("approved_permit_url", sa.String(500), nullable=True, comment="已签批作业票 URL"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True, comment="发起时间"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="完成时间"),
        sa.Column("approval_node", sa.String(100), nullable=True, comment="审批节点"),
        # 日报分析字段
        sa.Column("daily_risk_level", sa.String(8), nullable=True, comment="日报风险: high/medium/low"),
        sa.Column("daily_risk_reason", sa.Text, nullable=True, comment="日报风险依据"),
        sa.Column("inferred_operation_types", JSON, nullable=True, comment="推断的特殊作业类型"),
        sa.Column("inferred_operation_detail", sa.Text, nullable=True, comment="推断说明"),
        sa.Column("is_excluded", sa.Boolean, server_default="false", nullable=False, comment="是否排除"),
        sa.Column("exclusion_reason", sa.String(200), nullable=True, comment="排除原因"),
        sa.Column("daily_report_date", sa.Date, nullable=True, comment="所属日报日期"),
    ]
    for col in columns:
        op.add_column("special_operation_reports", col, schema="safety")

    # feishu_record_id 唯一索引（仅 bitable 来源）
    op.create_index(
        "uq_special_op_reports_feishu_id",
        "special_operation_reports",
        ["feishu_record_id"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("source = 'bitable' AND is_deleted = false"),
    )
    op.create_index(
        "ix_special_op_reports_daily_risk",
        "special_operation_reports",
        ["daily_risk_level"],
        schema="safety",
    )

    # ── 2. 删除旧的 daily_logs 表 ──
    op.execute("DROP TABLE IF EXISTS safety.special_operation_daily_logs CASCADE")


def downgrade() -> None:
    # 无法回滚删除的表，但可以移除新增列
    for col_name in [
        "daily_report_date", "exclusion_reason", "is_excluded",
        "inferred_operation_detail", "inferred_operation_types",
        "daily_risk_reason", "daily_risk_level",
        "approval_node", "completed_at", "submitted_at",
        "approved_permit_url", "work_scheme_url", "work_plan_url",
        "approval_no", "safety_approver_name", "approver_type",
        "initiator_name", "initiator_department", "report_type",
        "holiday_period", "is_national_holiday", "is_weekend_holiday",
        "other_operation_types", "has_other_operations",
        "work_duration_hours", "personnel_type",
        "feishu_record_id", "source",
    ]:
        op.drop_column("special_operation_reports", col_name, schema="safety")
