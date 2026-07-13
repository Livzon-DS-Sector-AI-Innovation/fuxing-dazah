"""Meter ORM models: instrument_records, gas_detector_records, calibration_reports."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel

SCHEMA = "meter"


class InstrumentRecord(BaseModel):
    """标准计量器具台账。"""

    __tablename__ = "instrument_records"
    __table_args__ = (
        # asset_number 非唯一索引（允许同一资产编号出现多次）
        Index("ix_instrument_records_asset_number_active", "asset_number",
              postgresql_where=text("is_deleted = false")),
        Index("ix_instrument_records_department", "department"),
        Index("ix_instrument_records_instrument_name", "instrument_name"),
        Index("ix_instrument_records_next_calibration_date", "next_calibration_date"),
        Index("ix_instrument_records_status", "status"),
        {"schema": SCHEMA},
    )

    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", comment="排序序号（Excel 行顺序）")
    asset_number: Mapped[str | None] = mapped_column(String(80), nullable=True, comment="资产编号")
    instrument_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="器具名称")
    model_spec: Mapped[str | None] = mapped_column(String(200), comment="型号规格")
    measurement_range: Mapped[str | None] = mapped_column(String(100), comment="测量范围")
    accuracy_grade: Mapped[str | None] = mapped_column(String(50), comment="精度等级")
    serial_number: Mapped[str | None] = mapped_column(String(100), comment="器具出厂编号")
    calibration_cycle_months: Mapped[int | None] = mapped_column(Integer, comment="检定周期(月)")
    location: Mapped[str | None] = mapped_column(String(500), comment="使用地点")
    manufacturer: Mapped[str | None] = mapped_column(String(200), comment="器具制造商")
    status: Mapped[str | None] = mapped_column(String(20), comment="器具状态：在用/停用/超期")
    color_marking: Mapped[str | None] = mapped_column(String(20), comment="彩色标志")
    calibration_date: Mapped[date | None] = mapped_column(Date, comment="检定日期")
    calibration_unit: Mapped[str | None] = mapped_column(String(200), comment="检定单位")
    calibration_result: Mapped[str | None] = mapped_column(String(50), comment="检定结论")
    next_calibration_date: Mapped[date | None] = mapped_column(Date, comment="下次检定日期")
    department: Mapped[str | None] = mapped_column(String(200), comment="部门/区域")
    sheet_name: Mapped[str | None] = mapped_column(String(200), comment="来源 sheet 名（追溯用）")
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")
    anomaly_flags: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, server_default="'{}'::jsonb", comment="异常标记"
    )

    # 关联报告
    reports: Mapped[list[CalibrationReport]] = relationship(
        "CalibrationReport",
        primaryjoin="and_(InstrumentRecord.id == foreign(CalibrationReport.instrument_id), "
        "CalibrationReport.is_deleted == False)",
        viewonly=True,
    )


class GasDetectorRecord(BaseModel):
    """有毒有害可燃探测器台账。"""

    __tablename__ = "gas_detector_records"
    __table_args__ = (
        # product_number 非唯一索引（允许同一编号出现多次）
        Index("ix_gas_detector_product_number_active", "product_number",
              postgresql_where=text("is_deleted = false")),
        Index("ix_gas_detector_department", "department"),
        Index("ix_gas_detector_instrument_name", "instrument_name"),
        Index("ix_gas_detector_next_calibration_date", "next_calibration_date"),
        Index("ix_gas_detector_installation_type", "installation_type"),
        {"schema": SCHEMA},
    )

    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", comment="排序序号（Excel 行顺序）")
    instrument_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="器具名称")
    detection_model: Mapped[str | None] = mapped_column(String(200), comment="检测型号")
    measurement_range: Mapped[str | None] = mapped_column(String(100), comment="量程")
    product_number: Mapped[str | None] = mapped_column(String(100), comment="产品编号")
    installation_type: Mapped[str | None] = mapped_column(String(50), comment="安装方式")
    installation_location: Mapped[str | None] = mapped_column(String(500), comment="安装位置")
    medium: Mapped[str | None] = mapped_column(String(500), comment="使用介质")
    calibration_factor: Mapped[str | None] = mapped_column(String(100), comment="标定系数")
    manufacturer_supplier: Mapped[str | None] = mapped_column(String(500), comment="制造商/供应商")
    calibration_date: Mapped[date | None] = mapped_column(Date, comment="检定时间")
    detection_unit: Mapped[str | None] = mapped_column(String(200), comment="检测单位")
    next_calibration_date: Mapped[date | None] = mapped_column(Date, comment="下次检定时间")
    calibration_result: Mapped[str | None] = mapped_column(String(50), comment="检定结论")
    manufacturer: Mapped[str | None] = mapped_column(String(200), comment="制造单位")
    status: Mapped[str | None] = mapped_column(String(20), comment="器具状态：在用/停用/超期")
    department: Mapped[str | None] = mapped_column(String(200), comment="部门")
    sheet_name: Mapped[str | None] = mapped_column(String(200), comment="来源 sheet 名")
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")
    anomaly_flags: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=dict, server_default="'{}'::jsonb", comment="异常标记"
    )

    reports: Mapped[list[CalibrationReport]] = relationship(
        "CalibrationReport",
        primaryjoin="and_(GasDetectorRecord.id == foreign(CalibrationReport.gas_detector_id), "
        "CalibrationReport.is_deleted == False)",
        viewonly=True,
    )


class CalibrationReport(BaseModel):
    """检测报告文件元数据。"""

    __tablename__ = "calibration_reports"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(instrument_id, gas_detector_id) = 1",
            name="ck_calibration_reports_single_parent",
        ),
        Index("ix_calibration_reports_instrument_id", "instrument_id"),
        Index("ix_calibration_reports_gas_detector_id", "gas_detector_id"),
        {"schema": SCHEMA},
    )

    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="关联标准计量器具"
    )
    gas_detector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="关联有毒有害可燃探测器"
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="MinIO 对象路径")
    file_size: Mapped[int | None] = mapped_column(BigInteger, comment="文件字节数")
    content_type: Mapped[str | None] = mapped_column(String(100), comment="MIME 类型")
    report_date: Mapped[date | None] = mapped_column(Date, comment="报告日期")
    remark: Mapped[str | None] = mapped_column(String(500), comment="备注")


class Department(BaseModel):
    """部门管理 — 按来源（标准计量器具 / 探测器）独立管理。"""

    __tablename__ = "departments"
    __table_args__ = (
        Index(
            "ix_departments_source_name_active",
            "source",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": SCHEMA},
    )

    source: Mapped[str] = mapped_column(String(20), nullable=False, comment="来源: instrument / gas_detector")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="部门名称")

    # ── 负责人 & 自动提醒 ──
    heads: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, default=list, server_default="'[]'::jsonb",
        comment="负责人列表 JSON: [{\"name\": \"张三\", \"feishu_open_id\": \"ou_xxx\"}]"
    )
    auto_notify_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="部门级自动提醒开关"
    )


class MeterSettings(BaseModel):
    """仪表全局设置 — 单行配置表。"""

    __tablename__ = "meter_settings"
    __table_args__ = (
        {"schema": SCHEMA},
    )

    notify_time: Mapped[time] = mapped_column(
        Time, default=time(17, 45), server_default=text("'17:45'::time"),
        comment="每日提醒时间",
    )
    # TODO: 通过 Alembic 迁移移除此废弃字段
    last_notify_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="[DEPRECATED] 请使用 last_sent_at",
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="上次实际发送的日期时间，用于判断'今天+当前设定时间'是否已推送过",
    )
