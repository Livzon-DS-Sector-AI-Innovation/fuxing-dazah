"""参训人明细表 — 签到表/成绩单 vision 解析名单落库（一人一场一行）。

数据来源：training_behavior 域「培训计划与实施表」行的签到表附件经
TrainingRecordParsingPlugin 解析出的 names/scores/unrecognized（链3，
service/training_behavior/record_parsing.py 落库）。培训主事实仍在
Bitable，本表只存个人粒度明细 + 培训行快照（档案页展示不回查 Bitable）。

匹配口径：person_name 是 OCR 转录姓名，职业健康档案按姓名关联
（同名风险由档案页标注「签到表AI转录」口径，无更强身份键可用）。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class TrainingAttendee(BaseModel):
    """参训人明细（AI 转录；重复解析=软删旧行重插，唯一索引保幂等）"""

    __tablename__ = "training_attendees"
    __table_args__ = (
        Index(
            "uq_training_attendees_record_person",
            "training_record_id",
            "person_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_training_attendees_person_name", "person_name"),
        {"schema": "safety"},
    )

    training_record_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="培训行 Bitable record_id"
    )
    training_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="培训名称快照"
    )
    category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="培训类别快照: 入厂三级教育/年度复训/专项培训/转岗培训/外来人员培训"
    )
    form: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="培训形式快照: 线下/线上/实操"
    )
    held_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实施日期快照（UTC）"
    )
    hours: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="培训学时快照"
    )
    assessment: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="考核方式快照: 考试/签到/实操评估/无需考核"
    )
    training_department: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="组织部门快照（多选拼接）"
    )
    person_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="参训人姓名（OCR 转录）"
    )
    score: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="考核成绩（成绩单明细按名匹配；无则 None）"
    )
    passed: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="是否合格（成绩单明细；无则 None）"
    )
    unrecognized: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="姓名辨认不清（原样转录，展示需灰显）",
    )
    confidence: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="解析置信度: high/medium/low"
    )
    source: Mapped[str] = mapped_column(
        String(16), default="ai_parse", server_default="ai_parse", nullable=False,
        comment="来源: ai_parse | manual",
    )
