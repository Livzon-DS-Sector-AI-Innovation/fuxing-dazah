"""QA COA（客户标准与出具登记）ORM 模型。

抽象自 COA 质检报告 docx（表1 基础信息 + 表2 检测项目/标准/结果）：
产品 → 客户标准 → 检测项目定义（列）→ 出具报告（一份 COA 一行）→ 结果值（EAV）。
与 APR 同构，但第二层是「客户标准」（一个产品 N 个客户各一套项目集）。
跨对象只保存逻辑引用（裸 UUID + 注释），不声明业务外键。
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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


class CoaSourceType(enum.StrEnum):
    """数据来源：人工创建 / docx 导入。"""

    MANUAL = "manual"
    IMPORT = "import"


class CoaValueType(enum.StrEnum):
    """值类型：数值（value_num）/ 文字判定（value_text，含半定量如 ＜1cfu/g）。"""

    NUMBER = "number"
    TEXT = "text"


class CoaFieldType(enum.StrEnum):
    """产品级批次信息字段类型：文本 / 日期（阶段二按配置提取时的解析路由）。"""

    TEXT = "text"
    DATE = "date"


def _enum_sql_list(values: type[enum.StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in values)


class CoaProduct(BaseModel):
    """COA 产品目录：一个产品 N 份客户标准。

    短码=批号/COA 编号前缀（如 HAF），唯一约束仅限未删除行。
    与 apr_products 完全独立（业务解耦，不做复制联动）。
    """

    __tablename__ = "coa_products"
    __table_args__ = (
        Index(
            "uq_qa_coa_products_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_qa_coa_products_name",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "qa"},
    )

    code: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="产品短码（批号/COA编号前缀），大写，如 HAF"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="产品中文名")
    name_en: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="产品英文名"
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


class CoaStandard(BaseModel):
    """客户标准：一份 COA 标准模板，归属一个产品。

    code 为模板编号（docx 报告编号 COA-HAF-3205-006 的中缀 3205），
    是 docx 导入时自动匹配标准的锚点；同一产品内唯一。
    """

    __tablename__ = "coa_standards"
    __table_args__ = (
        CheckConstraint(
            f"source IN ({_enum_sql_list(CoaSourceType)})",
            name="ck_qa_coa_standards_source",
        ),
        Index(
            "uq_qa_coa_standards_product_code",
            "product_id",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_coa_standards_product", "product_id"),
        {"schema": "qa"},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.coa_products.id"
    )
    code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="模板编号（docx 导入匹配锚点），如 3205"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="标准名称")
    customer: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="客户名称"
    )
    market: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="市场/药典：USP/EP/ChP"
    )
    version: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="版本文字标注（仅展示，不做版本演进）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", comment="是否启用"
    )
    batch_fields_overridden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="批次字段集是否自定义覆盖（true 时即使无行也按空自定义集，不再回落产品默认）",
    )
    source: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=CoaSourceType.MANUAL.value,
        server_default=CoaSourceType.MANUAL.value,
        comment="manual/import",
    )
    raw_extract: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="导入来源 docx 的原始提取结果（重放/复核用）"
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )


class CoaStandardItem(BaseModel):
    """标准检测项目定义：每份标准自有一套项目集，名称在标准内唯一。

    docx 表2 的列定义（项目名/大类/标准原文/顺序）。code 由名称归一化生成，
    是报告导入时项目对齐的匹配键，也是出具登记矩阵跨标准合并同名列的依据
    （改名会同步重算）。项目必然启用（无停用态）；被报告值引用的移除项
    软删保留行（值行 FK 有效，历史值可解释）。
    """

    __tablename__ = "coa_standard_items"
    __table_args__ = (
        CheckConstraint(
            f"value_type IN ({_enum_sql_list(CoaValueType)})",
            name="ck_qa_coa_items_value_type",
        ),
        CheckConstraint(
            "spec_min IS NULL OR spec_max IS NULL OR spec_min <= spec_max",
            name="ck_qa_coa_items_spec_range",
        ),
        Index(
            "uq_qa_coa_items_standard_code",
            "standard_id",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_coa_items_standard", "standard_id", "sort_order"),
        {"schema": "qa"},
    )

    standard_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.coa_standards.id"
    )
    code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="项目稳定标识（名称归一化生成），导入匹配键"
    )
    group_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="大类分组（docx 纵向合并单元格），如 性状/鉴别",
    )
    name_cn: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="项目名（中文）"
    )
    name_en: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="项目名（英文）"
    )
    value_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=CoaValueType.TEXT.value,
        server_default=CoaValueType.TEXT.value,
        comment="number/text",
    )
    unit: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="单位：%/ppm/EU/mg 等"
    )
    spec_text: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="标准原文：≤3.0% / 2.5～4.5 / 白色粉末（全角原样）",
    )
    spec_min: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="标准下限（导入解析成功才填，仅 ≥ 语义）"
    )
    spec_max: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="标准上限（导入解析成功才填，仅 ≤ 语义）"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="列顺序=docx 原序",
    )
    default_value: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="text 型项目登记时的预填默认值（如 符合规定），number 型禁用",
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )


class CoaReport(BaseModel):
    """出具登记：一份 COA 报告一行（表1 基础信息 + 归属标准）。

    (product, standard, batch) 唯一——同批同标准只登记一份，补发走软删重登。
    无报告编号：docx 里印的编号只作导入解析的匹配锚点，不落本表。
    product_id 冗余存，矩阵页查询锚点。
    """

    __tablename__ = "coa_reports"
    __table_args__ = (
        CheckConstraint(
            f"source IN ({_enum_sql_list(CoaSourceType)})",
            name="ck_qa_coa_reports_source",
        ),
        Index(
            "uq_qa_coa_reports_product_standard_batch",
            "product_id",
            "standard_id",
            "batch_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_coa_reports_product", "product_id", "created_at"),
        {"schema": "qa"},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.coa_products.id"
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.coa_standards.id"
    )
    serial_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="流水号（docx 右上角数字串），如 26081215"
    )
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="批号")
    mfg_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="生产日期"
    )
    exp_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="有效期至"
    )
    packaging: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="包装规格，如 5kg/Tin"
    )
    batch_size: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="批量，如 41.120kg"
    )
    storage: Mapped[str | None] = mapped_column(
        String(300), nullable=True, comment="贮存条件"
    )
    source: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=CoaSourceType.MANUAL.value,
        server_default=CoaSourceType.MANUAL.value,
        comment="manual/import",
    )
    raw_extract: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="导入时的原始提取结果（复核/重放用）"
    )
    batch_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="模板动态批次字段值（key=生效字段集 key；固定列别名键镜像写固定列）",
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )


class CoaProductField(BaseModel):
    """产品级批次信息字段默认配置：该产品 COA 报告要记录哪些批次信息字段。

    来源=docx 模板导入（结构提取的标签清单）或人工维护；不同产品字段集
    不同（如达托是「复验期」而非「有效期」）。key 为阶段二报告导入按配置
    渲染提取 schema 的锚点；保存为硬删+批量重插（配置非审计对象）。
    命名避开 batch_info（已被解析管线/raw_extract 留底占用）。

    个别模板字段集与产品默认不同时走 CoaStandardField 覆盖（稀疏，只有
    差异模板有行）；生效集 = 标准覆盖 ?? 产品默认。
    """

    __tablename__ = "coa_product_fields"
    __table_args__ = (
        CheckConstraint(
            f"field_type IN ({_enum_sql_list(CoaFieldType)})",
            name="ck_qa_coa_fields_field_type",
        ),
        Index(
            "uq_qa_coa_fields_product_key",
            "product_id",
            "key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_coa_fields_product", "product_id", "sort_order"),
        {"schema": "qa"},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.coa_products.id"
    )
    key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="字段键（产品内唯一，阶段二提取 schema 锚点），如 retest_date",
    )
    label_cn: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="字段中文标签，如 复验期"
    )
    label_en: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="字段英文标签，如 Retest Date"
    )
    field_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=CoaFieldType.TEXT.value,
        server_default=CoaFieldType.TEXT.value,
        comment="text/date",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="行顺序"
    )


class CoaStandardField(BaseModel):
    """标准级批次信息字段覆盖：字段集与产品默认不同的模板才落行（稀疏）。

    「空自定义集」由 CoaStandard.batch_fields_overridden 表达，本表无行。

    生效集 = 标准标志 batch_fields_overridden ? 本表行 : 产品默认
    （CoaProductField）。创建标准时随载荷带入的字段集与产品默认对比，
    一致不落覆盖；恢复默认=删本表行并清标志。删除标准时硬删
    （配置非审计对象）。
    """

    __tablename__ = "coa_standard_fields"
    __table_args__ = (
        CheckConstraint(
            f"field_type IN ({_enum_sql_list(CoaFieldType)})",
            name="ck_qa_coa_std_fields_field_type",
        ),
        Index(
            "uq_qa_coa_std_fields_standard_key",
            "standard_id",
            "key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_coa_std_fields_standard", "standard_id", "sort_order"),
        {"schema": "qa"},
    )

    standard_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.coa_standards.id"
    )
    key: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="字段键（标准内唯一），如 retest_date"
    )
    label_cn: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="字段中文标签，如 复验期"
    )
    label_en: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="字段英文标签，如 Retest Date"
    )
    field_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=CoaFieldType.TEXT.value,
        server_default=CoaFieldType.TEXT.value,
        comment="text/date",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="行顺序"
    )


class CoaReportValue(BaseModel):
    """COA 结果值：报告 × 项目。数值走 value_num，文字判定/半定量走 value_text。

    保存为硬删+批量重插（矩阵单元格非审计对象）；软删列仅备用。
    """

    __tablename__ = "coa_report_values"
    __table_args__ = (
        Index(
            "uq_qa_coa_values_report_item",
            "report_id",
            "item_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_coa_values_item", "item_id"),
        Index("ix_qa_coa_values_report", "report_id"),
        {"schema": "qa"},
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.coa_reports.id"
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="逻辑引用 qa.coa_standard_items.id"
    )
    value_num: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="数值型结果（按项目 value_type 落列）"
    )
    value_text: Mapped[str | None] = mapped_column(
        String(300), nullable=True, comment="结果原文（永远保留，如 符合规定/＜1cfu/g）"
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )
