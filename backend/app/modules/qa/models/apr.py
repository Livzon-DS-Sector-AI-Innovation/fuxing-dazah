"""QA 年度产品审核（APR）数据集中管理 ORM 模型。

抽象自各产品年终 Excel（附件4 生产数据汇总 / 附件6、7 检验结果汇总）：
产品 → 模板段（对应 sheet 或横向块）→ 列定义（工艺参数/检验项目+标准限）
→ 批次登记 → 值（EAV）。统计量（均值/±3σ/OOT）一律查询时计算，不入库。
跨对象只保存逻辑引用（裸 UUID + 注释），不声明业务外键。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class AprDataKind(enum.StrEnum):
    """段的数据类型：生产工艺数据（附件4） / 检验结果数据（附件6、7）。"""

    PRODUCTION = "production"
    INSPECTION = "inspection"


class AprItemCategory(enum.StrEnum):
    """列定义类别：关键工艺参数 / 中间控制参数 / 检验项目 / 批次信息。"""

    CPP = "cpp"
    IPC = "ipc"
    TEST = "test"
    INFO = "info"


class AprValueType(enum.StrEnum):
    """值类型：数值（value_num）/ 文字判定（value_text，含半定量如 "<1"）。"""

    NUMBER = "number"
    TEXT = "text"


class AprNdPolicy(enum.StrEnum):
    """数值列「未检出」统计口径：zero 按 0 计入统计 / exclude 不进统计。

    原始记录永远保留文字（如 未检出），口径只作用于查询时统计量计算。
    """

    ZERO = "zero"
    EXCLUDE = "exclude"


class AprReviewStatus(enum.StrEnum):
    """年度审核状态：open 可录入 / locked 年终定稿冻结。"""

    OPEN = "open"
    LOCKED = "locked"


def _enum_sql_list(values: type[enum.StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in values)


class AprProduct(BaseModel):
    """APR 产品目录：一个产品一套模板，年年复用。

    短码与名称均唯一（仅约束未删除行，删掉后可重新启用同名/同码）。
    短码在 schema 层统一转大写后落库，避免 ``dt``/``DT`` 并存。
    """

    __tablename__ = "apr_products"
    __table_args__ = (
        Index(
            "uq_qa_apr_products_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_qa_apr_products_name",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "qa"},
    )

    code: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="产品短码（批号前缀来源），大写，如 DT/KA/ST"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="产品中文名")
    name_en: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="产品英文名"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", comment="是否启用"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="排序"
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )


class AprSection(BaseModel):
    """APR 模板段：对应 Excel 一个 sheet 或 sheet 内一个横向块。

    单卡「发酵生产」左右两块 = 两个段；DT 三个药典 = 三个段（market 各异）。
    段名在同一产品内唯一（不同产品可同名，如各自的「成品检验-USP」）。
    """

    __tablename__ = "apr_sections"
    __table_args__ = (
        CheckConstraint(
            f"data_kind IN ({_enum_sql_list(AprDataKind)})",
            name="ck_qa_apr_sections_data_kind",
        ),
        Index("ix_qa_apr_sections_product", "product_id", "sort_order"),
        Index(
            "uq_qa_apr_sections_product_name",
            "product_id",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "qa"},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.apr_products.id"
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="段名（同一产品内唯一），如 菌种-摇瓶培养 / 成品检验-USP"
    )
    data_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AprDataKind.PRODUCTION.value,
        server_default=AprDataKind.PRODUCTION.value,
        comment="production/inspection",
    )
    market: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="市场/药典：US/EP/Ch.P，仅检验段有"
    )
    stage: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="工序阶段短码：seed/fermentation/extraction/finished_test",
    )
    multi_row: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="一批是否多行（多罐/续行），默认 false",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="段顺序"
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )


class AprItem(BaseModel):
    """APR 列定义：工艺参数/检验项目及其标准限。

    不可硬删只能停用（is_active），保证历史值可解释；MIN/MAX 子列建模为
    同名成对 item（code 带 ``#min``/``#max`` 后缀），录入界面渲染成双格。
    """

    __tablename__ = "apr_items"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({_enum_sql_list(AprItemCategory)})",
            name="ck_qa_apr_items_category",
        ),
        CheckConstraint(
            f"value_type IN ({_enum_sql_list(AprValueType)})",
            name="ck_qa_apr_items_value_type",
        ),
        CheckConstraint(
            f"nd_policy IN ({_enum_sql_list(AprNdPolicy)})",
            name="ck_qa_apr_items_nd_policy",
        ),
        CheckConstraint(
            "spec_min IS NULL OR spec_max IS NULL OR spec_min <= spec_max",
            name="ck_qa_apr_items_spec_range",
        ),
        CheckConstraint(
            "oot_min IS NULL OR oot_max IS NULL OR oot_min <= oot_max",
            name="ck_qa_apr_items_oot_range",
        ),
        Index(
            "uq_qa_apr_items_section_code",
            "section_id",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_apr_items_section", "section_id", "sort_order"),
        {"schema": "qa"},
    )

    section_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.apr_sections.id"
    )
    code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="段内稳定标识，导出列匹配/趋势接口用"
    )
    group_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="表头第一层分组，如 解吸/脱钙/纳滤"
    )
    category: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=AprItemCategory.TEST.value,
        server_default=AprItemCategory.TEST.value,
        comment="cpp/ipc/test/info",
    )
    name_cn: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="名称（中文）"
    )
    name_en: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="名称（英文）"
    )
    value_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=AprValueType.NUMBER.value,
        server_default=AprValueType.NUMBER.value,
        comment="number/text",
    )
    unit: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="单位：℃/rpm/EU/mg/ppm 等"
    )
    spec_text: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="标准原文，如 4.0-4.6 / ≤5.0% / 无杂菌生长"
    )
    spec_min: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="标准下限；只有 min 即 ≥，双值即区间"
    )
    spec_max: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="标准上限；只有 max 即 ≤"
    )
    oot_min: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="OOT 预警下限（通常比标准限窄，人工设定）"
    )
    oot_max: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="OOT 预警上限"
    )
    nd_policy: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=AprNdPolicy.ZERO.value,
        server_default=AprNdPolicy.ZERO.value,
        comment="数值列未检出统计口径：zero 按0计入 / exclude 不计入",
    )
    quick_values: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: ["未检出", "<1"],
        server_default=text("""'["未检出","<1"]'::jsonb"""),
        comment="数值列允许录入的文字结果（录入页快捷按钮）；非白名单文字拒绝保存",
    )
    trend_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="是否纳入趋势图；文字项应设 false",
    )
    required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否必填",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="停用后不可再录入",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="列顺序"
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )


class AprBatch(BaseModel):
    """APR 批次登记：粒度 =（产品，段，批号，年度）。

    同一成品批在三个市场段各自登记（贴合 Excel 形态）；生产链各段批号
    天然不同、各自登记；parent_batch_id 留批次血缘后手。
    """

    __tablename__ = "apr_batches"
    __table_args__ = (
        Index(
            "uq_qa_apr_batches_section_year_no",
            "section_id",
            "year",
            "batch_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_apr_batches_section_year", "section_id", "year"),
        Index("ix_qa_apr_batches_product", "product_id"),
        {"schema": "qa"},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.apr_products.id"
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.apr_sections.id"
    )
    year: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="所属年度（年终汇总切片键；批号本身跨年）"
    )
    batch_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="批号，如 DT2402001 / KA-ET-2017-001"
    )
    seq: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="段内序号（Excel 序号列；空则按创建序）"
    )
    parent_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="可选血缘：上一段批次（发酵批→种子批）",
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )


class AprValue(BaseModel):
    """APR 值：批次 × 列定义 × 行号。数值走 value_num，文字判定/半定量走 value_text。

    保存为硬删+批量插入（网格单元格非审计对象），软删列仅备用。
    """

    __tablename__ = "apr_values"
    __table_args__ = (
        Index(
            "uq_qa_apr_values_batch_item_row",
            "batch_id",
            "item_id",
            "row_seq",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_apr_values_item", "item_id"),
        Index("ix_qa_apr_values_batch", "batch_id"),
        {"schema": "qa"},
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.apr_batches.id"
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.apr_items.id"
    )
    row_seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="行号；multi_row 段的 1/2/3…",
    )
    row_label: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="行标签，如 1号罐"
    )
    value_num: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="数值型结果"
    )
    value_text: Mapped[str | None] = mapped_column(
        String(300), nullable=True, comment="文字判定/半定量：符合规定/未检出/<1/N/A"
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )


class AprAnnualReview(BaseModel):
    """APR 年度锁定：产品×年度定稿后冻结数据，录入/修改按此拦截。"""

    __tablename__ = "apr_annual_reviews"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_enum_sql_list(AprReviewStatus)})",
            name="ck_qa_apr_annual_reviews_status",
        ),
        Index(
            "uq_qa_apr_annual_reviews_product_year",
            "product_id",
            "year",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "qa"},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.apr_products.id"
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="年度")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AprReviewStatus.OPEN.value,
        server_default=AprReviewStatus.OPEN.value,
        comment="open/locked",
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="锁定时间"
    )
    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="锁定人（逻辑引用 identity.users.id）",
    )
