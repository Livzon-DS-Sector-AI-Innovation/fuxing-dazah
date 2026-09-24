"""Quality ORM 模型 —— 检验记录、杂质明细、报告单。"""

import uuid

from sqlalchemy import Boolean, Float, Index, String, text
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
    is_pass: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="合格判定"
    )
