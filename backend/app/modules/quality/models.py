"""Quality ORM 模型 —— 检验记录、杂质明细、报告单。"""

import uuid

from sqlalchemy import Boolean, Float, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class InspectionRecord(BaseModel):
    """液相解析检验记录。"""

    __tablename__ = "inspection_records"
    __table_args__ = (
        Index(
            "uq_quality_inspection_records_batch",
            "product_name",
            "batch_number",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_inspection_records_product", "product_name"),
        Index("ix_quality_inspection_records_created", "created_at"),
        {"schema": "quality"},
    )

    # 基本信息
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    batch_number: Mapped[str] = mapped_column(String(100), comment="批号")
    form_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="表格编号（如 EX-HA-5246-001）"
    )
    standard_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="标准类型：USP、EP、CP"
    )

    # 供试液 A 峰面积
    total_peak_area_a_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液A 总峰面积 第一份"
    )
    total_peak_area_a_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液A 总峰面积 第二份"
    )
    main_peak_area_a_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液A 主峰面积 第一份"
    )
    main_peak_area_a_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液A 主峰面积 第二份"
    )
    total_impurity_area_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="杂质总峰面积 At 第一份"
    )
    total_impurity_area_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="杂质总峰面积 At 第二份"
    )
    any_unknown_impurity_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="任何未知杂质 Ax 第一份"
    )
    any_unknown_impurity_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="任何未知杂质 Ax 第二份"
    )

    # 供试液 B 峰面积
    main_peak_area_b_first: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液B 主峰面积 Ab 第一份"
    )
    main_peak_area_b_second: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="供试液B 主峰面积 Ab 第二份"
    )

    # 判定结果
    all_pass: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否全部合格"
    )
    has_oot: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="是否存在超趋势"
    )

    # 原始数据与文件
    raw_data: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="完整原始解析数据备份"
    )
    excel_filename: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="上传的原始 Excel 文件名"
    )


class InspectionImpurity(BaseModel):
    """检验杂质明细（一对多关联检验记录）。"""

    __tablename__ = "inspection_impurities"
    __table_args__ = (
        Index("ix_quality_impurities_record", "inspection_record_id"),
        {"schema": "quality"},
    )

    inspection_record_id: Mapped[uuid.UUID] = mapped_column(
        comment="关联检验记录，逻辑引用 quality.inspection_records.id"
    )
    name: Mapped[str] = mapped_column(String(100), comment="杂质名称（如 RS1、杂质A）")
    first_percent: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="第一份百分比"
    )
    second_percent: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="第二份百分比"
    )
    limit_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="合格限度值"
    )
    oot_haf: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="OOT 阈值（HAF 产品线）"
    )
    oot_haa: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="OOT 阈值（HAA 产品线）"
    )
    is_pass: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="合格判定"
    )
    is_oot: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="OOT 判定"
    )


class ReportRecord(BaseModel):
    """报告单记录（生成的 COA 文件）。"""

    __tablename__ = "report_records"
    __table_args__ = (
        Index("ix_quality_report_record_inspection", "inspection_record_id"),
        {"schema": "quality"},
    )

    inspection_record_id: Mapped[uuid.UUID] = mapped_column(
        comment="关联检验记录，逻辑引用 quality.inspection_records.id"
    )
    template_path: Mapped[str] = mapped_column(
        String(500), comment="使用的模板路径（如 万古霉素/3205.docx）"
    )
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    batch_number: Mapped[str] = mapped_column(String(100), comment="批号")
    file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="生成的 docx 文件存储路径（本地或 MinIO）"
    )
    file_size: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="文件大小（字节）"
    )


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


class QualityStandardItem(BaseModel):
    """标准项目行：以 SOP 号为匹配键；合格标准为数值型（纯文字标准不收录）。"""

    __tablename__ = "quality_standard_items"
    __table_args__ = (
        Index("ix_quality_std_item_doc", "document_id"),
        Index(
            "uq_quality_std_item_sop",
            "document_id",
            "sop_no",
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


