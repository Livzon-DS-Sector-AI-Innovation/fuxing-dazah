"""replace unique constraints with partial unique indexes for soft delete

业务表均使用软删除（is_deleted），原纯字段唯一约束会导致「软删→重建同编号」
触发唯一约束冲突。本迁移将所有 safety schema 的唯一约束替换为 PostgreSQL
部分唯一索引（WHERE is_deleted = false）。

Revision ID: 949d3efb8bf8
Revises: 6541942e5eaf
Create Date: 2026-06-23 20:51:24.292747
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '949d3efb8bf8'
down_revision: Union[str, None] = '6541942e5eaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (旧约束名, 表名, 列名) — 15 个 safety schema 业务表
_CONSTRAINTS: list[tuple[str, str, str]] = [
    ("uq_safety_checks_check_no", "safety_checks", "check_no"),
    ("uq_hazard_reports_hazard_no", "hazard_reports", "hazard_no"),
    ("uq_accidents_accident_no", "accidents", "accident_no"),
    ("uq_safety_trainings_training_no", "safety_trainings", "training_no"),
    ("uq_hazard_identifications_no", "hazard_identifications", "hazard_id_no"),
    ("uq_operation_regulations_no", "operation_regulations", "regulation_no"),
    ("uq_regulation_revisions_no", "regulation_revisions", "revision_no"),
    ("uq_ai_workflow_config_module_code", "ai_workflow_configs", "module_code"),
    ("uq_special_op_personnel_no", "special_operation_personnel", "personnel_no"),
    ("uq_special_op_permits_permit_no", "special_operation_permits", "permit_no"),
    ("uq_special_operation_reports_no", "special_operation_reports", "report_no"),
    ("uq_daily_risk_reports_no", "daily_risk_reports", "report_no"),
    ("uq_ehs_changes_change_no", "ehs_changes", "change_no"),
    ("uq_oh_hazard_monitors_monitor_no", "oh_hazard_monitors", "monitor_no"),
    ("uq_oh_health_exams_exam_no", "oh_health_exams", "exam_no"),
    ("uq_contractors_contractor_no", "contractors", "contractor_no"),
    ("uq_scheduled_tasks_name", "scheduled_tasks", "name"),
]


def upgrade() -> None:
    for constraint_name, table, column in _CONSTRAINTS:
        # 1. 删除旧唯一约束
        op.drop_constraint(constraint_name, table, schema="safety", type_="unique")
        # 2. 建部分唯一索引（仅对未软删除的行生效）
        op.execute(
            f"CREATE UNIQUE INDEX {constraint_name} ON safety.{table} "
            f"({column}) WHERE is_deleted = false"
        )


def downgrade() -> None:
    for constraint_name, table, column in _CONSTRAINTS:
        # 1. 删除部分唯一索引
        op.execute(f"DROP INDEX IF EXISTS safety.{constraint_name}")
        # 2. 重建旧唯一约束
        op.create_unique_constraint(constraint_name, table, [column], schema="safety")
