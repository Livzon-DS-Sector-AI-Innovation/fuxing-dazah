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


class ProductStandard(BaseModel):
    """产品标准配置 —— 每个产品的各项指标限度值。"""

    __tablename__ = "product_standards"
    __table_args__ = (
        Index(
            "uq_quality_product_standards_item",
            "product_name",
            "form_id",
            "item_name",
            "sop_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    form_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="代号/表号（同一产品不同制剂/工艺的细分，如 3229）"
    )
    sop_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="检验项目绑定的 SOP 编号（同名项目按 SOP 号区分匹配）"
    )
    standard_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="标准类型：USP、EP、CP"
    )
    item_name: Mapped[str] = mapped_column(String(100), comment="指标名称（如 万古霉素B、总杂质、RS1）")
    operator: Mapped[str] = mapped_column(
        String(10), default="≤", server_default="'≤'", comment="比较运算符"
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


class DocumentCategory(BaseModel):
    """标准文档大类（产品→大类层级）。"""

    __tablename__ = "document_categories"
    __table_args__ = (
        Index(
            "uq_quality_doc_cats",
            "product_name",
            "category_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称")
    category_name: Mapped[str] = mapped_column(String(200), comment="大类名称")
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="排序"
    )


class StandardDocument(BaseModel):
    """标准文件记录。"""

    __tablename__ = "standard_documents"
    __table_args__ = (
        Index("ix_quality_std_docs_cat", "category_id"),
        Index(
            "uq_quality_std_docs_file",
            "category_id",
            "original_filename",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        comment="所属大类，逻辑引用 quality.document_categories.id"
    )
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名称（冗余便于查询）")
    original_filename: Mapped[str] = mapped_column(String(500), comment="原始文件名")
    file_path: Mapped[str] = mapped_column(
        String(1000), comment="文件存储路径"
    )
    file_size: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="文件大小（字节）"
    )
