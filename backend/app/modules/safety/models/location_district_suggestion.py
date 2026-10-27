"""Safety ORM models — location_district_suggestions（#2 AI 建议映射中间表）。

建议=过程，映射=资产（location_district_map）——两表职责分离（DESIGN v3 §12.2）：
AI 只落建议行，人工确认后写映射表（source='ai_confirmed'）。location_text
软删下唯一（同文本至多一条活建议，DB 兜底幂等）；dist_id 可空（AI 允许
无法判断不硬配）。
"""

from sqlalchemy import JSON, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class LocationDistrictSuggestion(BaseModel):
    """未映射地点文本 → 分区建议（#2 AI 批量建议 → 人工确认流）。"""

    __tablename__ = "location_district_suggestions"
    __table_args__ = (
        Index(
            "uq_location_district_suggestions_text",
            "location_text",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_location_district_suggestions_status", "status"),
        {"schema": "safety"},
    )

    location_text: Mapped[str] = mapped_column(
        String(length=128), nullable=False, comment="地点/部位文本（unmapped 归一原文）"
    )
    count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
        comment="近 N 天出现事件次数（收集时累计）",
    )
    kinds: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]",
        comment="来源种类（job/fire/central 去重）",
    )
    dist_id: Mapped[str | None] = mapped_column(
        String(length=64), nullable=True, comment="建议分区 distId（AI 无法判断为 null）"
    )
    confidence: Mapped[str] = mapped_column(
        String(length=8), nullable=False, default="low", server_default="low",
        comment="high|mid|low（mid=AI 输出 medium 归一）",
    )
    reason: Mapped[str] = mapped_column(
        String(length=512), nullable=False, default="", server_default="",
        comment="AI 判断理由（引用分区名/厂区常识）",
    )
    batch_id: Mapped[str] = mapped_column(
        String(length=32), nullable=False, comment="扫描批次号（uuid 截断，排查用）"
    )
    status: Mapped[str] = mapped_column(
        String(length=16), nullable=False, default="pending", server_default="pending",
        comment="pending（待确认）| confirmed（已入映射表）| ignored（人工忽略）",
    )
