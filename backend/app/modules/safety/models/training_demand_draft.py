"""S6 教育培训 — 年度培训需求草案 ORM（二期链1）。

DESIGN 二期 §4.1/§4.3：AI 五源生成的需求清单草案先落本表供安环科评审，
**不直接写 Bitable 培训表**（草案入表会污染 D3-05 完成率分母）；逐行采纳
时才写台账并回填 adopted_record_id。幂等口径：同年重新生成=全量替换
status=draft 的行（adopted/rejected 保留）。
status 三态英文键：draft=草案 / adopted=已采纳 / rejected=已驳回。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

STATUS_DRAFT = "draft"
STATUS_ADOPTED = "adopted"
STATUS_REJECTED = "rejected"

STATUS_LABELS = {
    STATUS_DRAFT: "草案",
    STATUS_ADOPTED: "已采纳",
    STATUS_REJECTED: "已驳回",
}


class TrainingDemandDraft(BaseModel):
    """一条年度培训需求草案（AI 生成，人终判）。"""

    __tablename__ = "training_demand_drafts"
    __table_args__ = (
        Index("ix_training_demand_drafts_year_status", "year", "status"),
        {"schema": "safety"},
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="计划年度")
    position: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default="",
        comment="岗位（采纳时拆分写台账组织部门多选列）",
    )
    topic: Mapped[str] = mapped_column(String(500), nullable=False, comment="培训主题")
    suggested_hours: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="建议学时",
    )
    form: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="建议形式：线下/线上/实操",
    )
    audience: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="", comment="对象说明",
    )
    basis: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
        comment="可溯源依据（AI 只能引用输入中出现过的行为/类别/次数/法规标题）",
    )
    is_statutory_gap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="法定缺口行（新员工≥72h/年度再培训≥20h/安管≥16h）",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_DRAFT, server_default=STATUS_DRAFT,
        comment="draft=草案 / adopted=已采纳 / rejected=已驳回",
    )
    adopted_record_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="采纳后 Bitable 培训表行 record_id",
    )
