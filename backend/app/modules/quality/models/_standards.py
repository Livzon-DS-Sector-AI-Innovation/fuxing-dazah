"""Quality ORM 模型 —— 检验记录、杂质明细、报告单。"""

import uuid
from typing import Any

from sqlalchemy import Float, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class QualityStandardDocument(BaseModel):
    """质量标准文档（一个产品代号一份，如 SOP.02.3292.003 ↔ 代号 HAS）。"""

    __tablename__ = "quality_standard_documents"
    __table_args__ = (
        Index(
            "uq_quality_std_doc_file_no",
            "file_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_std_doc_product", "product_name"),
        {"schema": "quality"},
    )

    file_no: Mapped[str] = mapped_column(
        String(100), comment="文件编号，如 SOP.02.3292.003"
    )
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    product_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="产品代号，如 HAS"
    )
    product_internal_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="产品代码，如 30205"
    )
    specification: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="产品规格，如 5kg/听"
    )
    valid_years: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="有效期，如 36个月"
    )
    effective_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="生效日期"
    )
    version: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="版本号，如 003"
    )
    template_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="绑定的 COA 报告模板路径（如 万古霉素/3205.docx）"
    )

class QualityStandardItem(BaseModel):
    """标准项目行：以 SOP 号为匹配键；数值标准自动判定，纯文字标准保留（operator/limit 为空，人工判定）。"""

    __tablename__ = "quality_standard_items"
    __table_args__ = (
        Index("ix_quality_std_item_doc", "document_id"),
        Index("ix_quality_std_item_sop", "sop_no"),
        Index(
            "uq_quality_std_item_sop",
            "document_id",
            "sop_no",
            "item_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        comment="关联标准文档，逻辑引用 quality.quality_standard_documents.id"
    )
    seq: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="序号（文档中的检验项目序号）"
    )
    category: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="检验项目大类，如 性状/有关物质"
    )
    item_name: Mapped[str] = mapped_column(
        String(200), comment="子项目名称（仅展示参考，匹配以 SOP 号为准）"
    )
    sop_no: Mapped[str] = mapped_column(
        String(64), comment="检验方法 SOP 编号（匹配键）"
    )
    standard_text: Mapped[str] = mapped_column(
        String(300), comment="合格标准原文，如 ≤3.0%"
    )
    operator: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="比较运算符：≤ ≥ < > 范围"
    )
    limit_min: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="限度下限（范围时使用）"
    )
    limit_max: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="限度上限"
    )
    method_source: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="方法来源：IP / Ph.Eur. / USP / 内部"
    )
    remark: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="备注，如 加*每年仅1批"
    )

class CoaTemplateBinding(BaseModel):
    """COA 模板 ↔ 标准文档绑定（业务规则：一份 COA 唯一绑定一份 SOP；
    一份 SOP 可绑定多份 COA）。绑定关系存在 COA 一侧。"""

    __tablename__ = "quality_coa_template_bindings"
    __table_args__ = (
        Index(
            "uq_quality_coa_binding_template",
            "template_path",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_coa_binding_doc", "standard_document_id"),
        {"schema": "quality"},
    )

    template_path: Mapped[str] = mapped_column(
        String(500), comment="COA 模板路径（如 3205.docx），唯一"
    )
    standard_document_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="绑定的标准文档，逻辑引用 quality.quality_standard_documents.id"
    )
    sop_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="绑定的 SOP 号快照（标准文档 file_no）"
    )
    description: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="备注，如 赞比亚专用"
    )

class LcTemplateConfig(BaseModel):
    """液相计算表模板配置：以表号（EX-xx-xxxx-vvv）为键，描述取值位置。"""

    __tablename__ = "quality_lc_template_configs"
    __table_args__ = (
        Index(
            "uq_quality_lc_template_table_no",
            "table_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    table_no: Mapped[str] = mapped_column(
        String(50), comment="计算表表号，如 EX-HA-8329-002（模板识别键）"
    )
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称（与标准库一致）")
    sop_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="表号对应的检测 SOP 号（一般 1:1 映射，例外清单另行整理）",
    )
    description: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="模板描述，如 万古霉素冻干粉-赞比亚"
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, comment="取值配置 JSON：批号标签、组分区块（名称列/结果列/行距/平均规则/值格式）"
    )
