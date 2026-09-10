"""add eval_ai_file and eval_source_record_file_token to emergency_drill_records

演练评估表（AI）自动生成：
- eval_ai_file：AI 生成的评估表 docx 附件（Bitable「演练评估表（AI）」镜像）
- eval_source_record_file_token：最近一次 AI 评估所用演练记录表 file_token，
  作为 changed 事件触发去重依据（记录表未变则不重复生成）
- plan_final_file：演练方案（定稿）人工附件（评估的对照基准之一）

Revision ID: b3e4f5a6c7d8
Revises: c9d8e7f6a5b4
Create Date: 2026-09-02 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3e4f5a6c7d8"
down_revision: str | None = "c9d8e7f6a5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "emergency_drill_records",
        sa.Column("eval_ai_file", sa.JSON(), nullable=True, comment="演练评估表（AI）附件"),
        schema="safety",
    )
    op.add_column(
        "emergency_drill_records",
        sa.Column(
            "eval_source_record_file_token",
            sa.String(128),
            nullable=True,
            comment="最近一次AI评估所用演练记录表 file_token（触发去重依据）",
        ),
        schema="safety",
    )
    op.add_column(
        "emergency_drill_records",
        sa.Column("plan_final_file", sa.JSON(), nullable=True, comment="演练方案（定稿）附件"),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("emergency_drill_records", "plan_final_file", schema="safety")
    op.drop_column("emergency_drill_records", "eval_source_record_file_token", schema="safety")
    op.drop_column("emergency_drill_records", "eval_ai_file", schema="safety")
