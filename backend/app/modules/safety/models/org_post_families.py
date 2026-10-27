"""Safety ORM models — org_post_families（#4 岗位族归类资产）。

org_directory 唯一 postName → 9 标准岗位族（DESIGN v3 §13.1 枚举一次定死）。
source='ai'=AI 归类待确认（重跑 upsert 覆盖）；source='manual'=人工确认/修正
（重跑不覆盖）。post_name 软删下唯一。
"""

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

# 9 个标准岗位族（§13.1，枚举一次定死——新增族需迁移历史行，不动此清单）
FAMILY_SPECIAL = "特种作业相关"
FAMILY_CHEM_PROCESS = "危化工艺操作"
FAMILY_GENERAL_PROD = "一般生产操作"
FAMILY_QC_LAB = "质检与实验"
FAMILY_MAINTENANCE = "设备维护"
FAMILY_LOGISTICS = "物流仓储"
FAMILY_SUPPORT = "辅助后勤"
FAMILY_MANAGEMENT = "管理职能"
FAMILY_OTHER = "其他"

POST_FAMILIES: tuple[str, ...] = (
    FAMILY_SPECIAL,
    FAMILY_CHEM_PROCESS,
    FAMILY_GENERAL_PROD,
    FAMILY_QC_LAB,
    FAMILY_MAINTENANCE,
    FAMILY_LOGISTICS,
    FAMILY_SUPPORT,
    FAMILY_MANAGEMENT,
    FAMILY_OTHER,
)

SOURCE_AI = "ai"
SOURCE_MANUAL = "manual"


class OrgPostFamily(BaseModel):
    """岗位名 → 标准岗位族（AI 归类 + 人工确认门）。"""

    __tablename__ = "org_post_families"
    __table_args__ = (
        Index(
            "uq_org_post_families_post_name",
            "post_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_org_post_families_family", "family"),
        {"schema": "safety"},
    )

    post_name: Mapped[str] = mapped_column(
        String(length=128), nullable=False, comment="岗位名（org_directory postName 原文）"
    )
    family: Mapped[str] = mapped_column(
        String(length=32), nullable=False, comment="标准岗位族（§13.1 九族枚举）"
    )
    confidence: Mapped[str] = mapped_column(
        String(length=8), nullable=False, default="low", server_default="low",
        comment="high|mid|low（AI 置信度；manual 行保留原值）",
    )
    note: Mapped[str] = mapped_column(
        String(length=512), nullable=False, default="", server_default="",
        comment="AI 判断说明 / 人工修正备注",
    )
    source: Mapped[str] = mapped_column(
        String(length=8), nullable=False, default=SOURCE_AI, server_default=SOURCE_AI,
        comment="ai（AI 归类，重跑覆盖）| manual（人工确认/修正，重跑不覆盖）",
    )
