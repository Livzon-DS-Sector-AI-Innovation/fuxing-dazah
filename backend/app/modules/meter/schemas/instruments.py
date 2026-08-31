"""标准计量器具请求/响应 schema。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.meter.schemas.common import NormalizedDepartment, StrUUID
from app.modules.meter.schemas.reports import ReportItem
from app.shared.schemas import PageParams


class InstrumentCreate(BaseModel):
    """新增标准计量器具。"""
    asset_number: str = Field(..., min_length=1, max_length=80, description="资产编号")
    instrument_name: str = Field(..., min_length=1, max_length=200, description="器具名称")
    model_spec: str | None = Field(default=None, max_length=200, description="型号规格")
    measurement_range: str | None = Field(default=None, max_length=100, description="测量范围")
    accuracy_grade: str | None = Field(default=None, max_length=50, description="精度等级")
    serial_number: str | None = Field(default=None, max_length=100, description="器具出厂编号")
    calibration_cycle_months: int | None = Field(default=None, ge=1, description="检定周期(月)")
    location: str | None = Field(default=None, max_length=500, description="使用地点")
    manufacturer: str | None = Field(default=None, max_length=200, description="器具制造商")
    status: str | None = Field(default=None, max_length=20, description="器具状态")
    color_marking: str | None = Field(default=None, max_length=20, description="彩色标志")
    calibration_date: date | None = Field(default=None, description="检定日期")
    calibration_unit: str | None = Field(default=None, max_length=200, description="检定单位")
    calibration_result: str | None = Field(default=None, max_length=50, description="检定结论")
    next_calibration_date: date | None = Field(default=None, description="下次检定日期")
    department: str | None = Field(default=None, max_length=200, description="部门/区域")
    remark: str | None = Field(default=None, max_length=500, description="备注")





class InstrumentUpdate(BaseModel):
    """更新标准计量器具。"""
    asset_number: str | None = Field(default=None, min_length=1, max_length=80, description="资产编号")
    instrument_name: str | None = Field(default=None, min_length=1, max_length=200, description="器具名称")
    model_spec: str | None = Field(default=None, max_length=200, description="型号规格")
    measurement_range: str | None = Field(default=None, max_length=100, description="测量范围")
    accuracy_grade: str | None = Field(default=None, max_length=50, description="精度等级")
    serial_number: str | None = Field(default=None, max_length=100, description="器具出厂编号")
    calibration_cycle_months: int | None = Field(default=None, ge=1, description="检定周期(月)")
    location: str | None = Field(default=None, max_length=500, description="使用地点")
    manufacturer: str | None = Field(default=None, max_length=200, description="器具制造商")
    status: str | None = Field(default=None, max_length=20, description="器具状态")
    color_marking: str | None = Field(default=None, max_length=20, description="彩色标志")
    calibration_date: date | None = Field(default=None, description="检定日期")
    calibration_unit: str | None = Field(default=None, max_length=200, description="检定单位")
    calibration_result: str | None = Field(default=None, max_length=50, description="检定结论")
    next_calibration_date: date | None = Field(default=None, description="下次检定日期")
    department: str | None = Field(default=None, max_length=200, description="部门/区域")
    remark: str | None = Field(default=None, max_length=500, description="备注")





class InstrumentResponse(BaseModel):
    """标准计量器具响应。"""
    id: StrUUID
    asset_number: str | None = None
    instrument_name: str
    model_spec: str | None = None
    measurement_range: str | None = None
    accuracy_grade: str | None = None
    serial_number: str | None = None
    calibration_cycle_months: int | None = None
    location: str | None = None
    manufacturer: str | None = None
    status: str | None = None
    color_marking: str | None = None
    calibration_date: date | None = None
    calibration_unit: str | None = None
    calibration_result: str | None = None
    next_calibration_date: date | None = None
    department: NormalizedDepartment = None
    sheet_name: str | None = None
    remark: str | None = None
    anomaly_flags: dict[str, Any] | None = None
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    reports: list[ReportItem] = Field(default_factory=list, description="关联检测报告")

    model_config = ConfigDict(from_attributes=True)





class InstrumentListResponse(BaseModel):
    """标准计量器具列表项（不含 reports 和 anomaly_flags 详情）。"""
    id: StrUUID
    department: NormalizedDepartment = None
    asset_number: str | None = None
    instrument_name: str
    model_spec: str | None = None
    measurement_range: str | None = None
    accuracy_grade: str | None = None
    serial_number: str | None = None
    calibration_cycle_months: int | None = None
    color_marking: str | None = None
    location: str | None = None
    manufacturer: str | None = None
    status: str | None = None
    calibration_date: date | None = None
    next_calibration_date: date | None = None
    calibration_unit: str | None = None
    calibration_result: str | None = None
    remark: str | None = None
    has_anomaly: bool = False
    report_count: int = 0
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)





class InstrumentFilter(PageParams):
    """标准计量器具筛选参数。"""
    department: str | None = Field(default=None, description="部门/区域")
    asset_number: str | None = Field(default=None, description="资产编号（精确匹配）")
    instrument_name: str | None = Field(default=None, description="器具名称（模糊搜索）")
    model_spec: str | None = Field(default=None, description="型号规格（精确匹配）")
    accuracy_grade: str | None = Field(default=None, description="精度等级（精确匹配）")
    serial_number: str | None = Field(default=None, description="器具编号（精确匹配）")
    measurement_range: str | None = Field(default=None, description="测量范围（精确匹配）")
    location: str | None = Field(default=None, description="使用地点（精确匹配）")
    manufacturer: str | None = Field(default=None, description="制造商（精确匹配）")
    status: str | None = Field(default=None, description="器具状态")
    calibration_unit: str | None = Field(default=None, description="检定单位（精确匹配）")
    calibration_result: str | None = Field(default=None, description="检定结论（精确匹配）")
    color_marking: str | None = Field(default=None, description="彩色标志（精确匹配）")
    next_calibration_before: date | None = Field(default=None, description="下次检定日期在此日期之前")
    next_calibration_after: date | None = Field(default=None, description="下次检定日期在此日期之后")
    calibration_date_before: date | None = Field(default=None, description="检定日期在此日期之前")
    calibration_date_after: date | None = Field(default=None, description="检定日期在此日期之后")
    keyword: str | None = Field(default=None, description="全局关键词搜索（匹配资产编号、器具名称、型号）")
    has_report: bool | None = Field(default=None, description="是否有检测报告（True=有, False=无, None=不限）")
    # ── 文本列部分匹配（输入即过滤） ──
    asset_number_like: str | None = Field(default=None, max_length=100, description="资产编号（包含匹配）")
    instrument_name_like: str | None = Field(default=None, max_length=200, description="器具名称（包含匹配）")
    model_spec_like: str | None = Field(default=None, max_length=200, description="型号规格（包含匹配）")
    measurement_range_like: str | None = Field(default=None, max_length=100, description="测量范围（包含匹配）")
    accuracy_grade_like: str | None = Field(default=None, max_length=50, description="精度等级（包含匹配）")
    serial_number_like: str | None = Field(default=None, max_length=100, description="器具编号（包含匹配）")
    location_like: str | None = Field(default=None, max_length=100, description="使用地点（包含匹配）")
    manufacturer_like: str | None = Field(default=None, max_length=100, description="制造商（包含匹配）")
    calibration_unit_like: str | None = Field(default=None, max_length=100, description="检定单位（包含匹配）")
    calibration_result_like: str | None = Field(default=None, max_length=50, description="检定结论（包含匹配）")
    color_marking_like: str | None = Field(default=None, max_length=50, description="彩色标志（包含匹配）")


# ═══════════════════════════════════════════
# 有毒有害可燃探测器
# ═══════════════════════════════════════════




class InstrumentFilterOptions(BaseModel):
    """标准计量器具筛选选项（全表 distinct 值）。"""
    department: list[str] = Field(default_factory=list)
    asset_number: list[str] = Field(default_factory=list)
    instrument_name: list[str] = Field(default_factory=list)
    model_spec: list[str] = Field(default_factory=list)
    measurement_range: list[str] = Field(default_factory=list)
    accuracy_grade: list[str] = Field(default_factory=list)
    serial_number: list[str] = Field(default_factory=list)
    location: list[str] = Field(default_factory=list)
    manufacturer: list[str] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)
    calibration_unit: list[str] = Field(default_factory=list)
    calibration_result: list[str] = Field(default_factory=list)
    color_marking: list[str] = Field(default_factory=list)





class BatchCreateItem(BaseModel):
    """批量新增中的单条记录。asset_number 可选，department 必填。"""
    asset_number: str | None = Field(default=None, max_length=80, description="资产编号")
    instrument_name: str = Field(..., min_length=1, max_length=200, description="器具名称")
    model_spec: str | None = Field(default=None, max_length=200)
    measurement_range: str | None = Field(default=None, max_length=100)
    accuracy_grade: str | None = Field(default=None, max_length=50)
    serial_number: str | None = Field(default=None, max_length=100)
    calibration_cycle_months: int | None = Field(default=None, ge=1)
    location: str | None = Field(default=None, max_length=500)
    manufacturer: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=20)
    color_marking: str | None = Field(default=None, max_length=20)
    calibration_date: date | None = None
    calibration_unit: str | None = Field(default=None, max_length=200)
    calibration_result: str | None = Field(default=None, max_length=50)
    next_calibration_date: date | None = None
    department: str = Field(..., max_length=200, description="部门")
    remark: str | None = Field(default=None, max_length=500, description="备注")





class BatchCreateRequest(BaseModel):
    """批量新增请求。"""
    items: list[BatchCreateItem] = Field(..., min_length=1, max_length=200)





class BatchCreateRowResult(BaseModel):
    """批量新增单行结果。"""
    index: int = Field(..., description="行号（从0开始）")
    asset_number: str | None = None
    status: str = Field(..., description="created / skipped")
    id: str | None = Field(default=None, description="创建成功后的 ID")
    message: str | None = Field(default=None, description="失败/跳过原因")





class BatchCreateResult(BaseModel):
    """批量新增结果汇总。"""
    total: int
    created: int = 0
    skipped: int = 0
    results: list[BatchCreateRowResult] = Field(default_factory=list)
