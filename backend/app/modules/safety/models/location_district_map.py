"""Safety ORM models — location_district_map（F2 地点→分区映射底座）。"""

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class LocationDistrictMap(BaseModel):
    """地点文本 → 厂区风险分区的确认映射资产（F2）。

    初灌=64 分区名原文+人工同义词（source='manual'）；后续 AI 建议确认
    （source='ai_confirmed'，§9.3 另议）。运行时只读（pins 端点查询），
    写入仅经 seed 脚本。location_text 软删下唯一（一分区名一文本一行）。
    """

    __tablename__ = "location_district_map"
    __table_args__ = (
        Index(
            "uq_location_district_map_text",
            "location_text",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_location_district_map_dist_id", "dist_id"),
        {"schema": "safety"},
    )

    location_text: Mapped[str] = mapped_column(
        String(length=128), nullable=False, comment="地点/部位文本（分区名原文或人工同义词）"
    )
    dist_id: Mapped[str] = mapped_column(
        String(length=64),
        nullable=False,
        comment="3.x 平台风险分区 distId（无本地主表，不外键）",
    )
    source: Mapped[str] = mapped_column(
        String(length=16),
        nullable=False,
        default="manual",
        server_default="manual",
        comment="manual（人工）/ ai_confirmed（AI 建议确认，另议）",
    )
