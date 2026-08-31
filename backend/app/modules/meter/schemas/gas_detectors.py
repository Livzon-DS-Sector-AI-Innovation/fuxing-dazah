"""有毒有害可燃探测器请求/响应 schema。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.meter.schemas.common import NormalizedDepartment, StrUUID
from app.modules.meter.schemas.reports import ReportItem
from app.shared.schemas import PageParams


class GasDetectorCreate(BaseModel):
    """新增有毒有害可燃探测器。"""
    instrument_name: str = Field(..., min_length=1, max_length=200, description="器具名称")
    detection_model: str | None = Field(default=None, max_length=200, description="检测型号")
    measurement_range: str | None = Field(default=None, max_length=100, description="量程")
    product_number: str | None = Field(default=None, max_length=100, description="产品编号")
    installation_type: str | None = Field(default=None, max_length=50, description="安装方式")
    installation_location: str | None = Field(default=None, max_length=500, description="安装位置")
    medium: str | None = Field(default=None, max_length=500, description="使用介质")
    calibration_factor: str | None = Field(default=None, max_length=100, description="标定系数")
    manufacturer_supplier: str | None = Field(default=None, max_length=500, description="制造商/供应商")
    calibration_date: date | None = Field(default=None, description="检定时间")
    calibration_result: str | None = Field(default=None, max_length=50, description="检定结论")
    detection_unit: str | None = Field(default=None, max_length=200, description="检测单位")
    next_calibration_date: date | None = Field(default=None, description="下次检定时间")
    manufacturer: str | None = Field(default=None, max_length=200, description="制造单位")
    status: str | None = Field(default=None, max_length=20, description="器具状态：在用/停用/超期")
    department: str | None = Field(default=None, max_length=200, description="部门")
    remark: str | None = Field(default=None, max_length=500, description="备注")





class GasDetectorUpdate(BaseModel):
    """更新有毒有害可燃探测器。"""
    instrument_name: str | None = Field(default=None, min_length=1, max_length=200, description="器具名称")
    detection_model: str | None = Field(default=None, max_length=200, description="检测型号")
    measurement_range: str | None = Field(default=None, max_length=100, description="量程")
    product_number: str | None = Field(default=None, max_length=100, description="产品编号")
    installation_type: str | None = Field(default=None, max_length=50, description="安装方式")
    installation_location: str | None = Field(default=None, max_length=500, description="安装位置")
    medium: str | None = Field(default=None, max_length=500, description="使用介质")
    calibration_factor: str | None = Field(default=None, max_length=100, description="标定系数")
    manufacturer_supplier: str | None = Field(default=None, max_length=500, description="制造商/供应商")
    calibration_date: date | None = Field(default=None, description="检定时间")
    calibration_result: str | None = Field(default=None, max_length=50, description="检定结论")
    detection_unit: str | None = Field(default=None, max_length=200, description="检测单位")
    next_calibration_date: date | None = Field(default=None, description="下次检定时间")
    manufacturer: str | None = Field(default=None, max_length=200, description="制造单位")
    status: str | None = Field(default=None, max_length=20, description="器具状态：在用/停用/超期")
    department: str | None = Field(default=None, max_length=200, description="部门")
    remark: str | None = Field(default=None, max_length=500, description="备注")





class GasDetectorResponse(BaseModel):
    """有毒有害可燃探测器响应。"""
    id: StrUUID
    instrument_name: str
    detection_model: str | None = None
    measurement_range: str | None = None
    product_number: str | None = None
    installation_type: str | None = None
    installation_location: str | None = None
    medium: str | None = None
    calibration_factor: str | None = None
    manufacturer_supplier: str | None = None
    calibration_date: date | None = None
    detection_unit: str | None = None
    next_calibration_date: date | None = None
    manufacturer: str | None = None
    status: str | None = None
    department: NormalizedDepartment = None
    calibration_result: str | None = None
    sheet_name: str | None = None
    remark: str | None = None
    anomaly_flags: dict[str, Any] | None = None
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    reports: list[ReportItem] = Field(default_factory=list, description="关联检测报告")

    model_config = ConfigDict(from_attributes=True)





class GasDetectorListResponse(BaseModel):
    """有毒有害可燃探测器列表项。"""
    id: StrUUID
    department: NormalizedDepartment = None
    instrument_name: str
    detection_model: str | None = None
    measurement_range: str | None = None
    product_number: str | None = None
    installation_type: str | None = None
    installation_location: str | None = None
    medium: str | None = None
    calibration_factor: str | None = None
    manufacturer_supplier: str | None = None
    manufacturer: str | None = None
    status: str | None = None
    calibration_date: date | None = None
    next_calibration_date: date | None = None
    detection_unit: str | None = None
    calibration_result: str | None = None
    remark: str | None = None
    has_anomaly: bool = False
    report_count: int = 0
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)





class GasDetectorFilter(PageParams):
    """有毒有害可燃探测器筛选参数。"""
    department: str | None = Field(default=None, description="部门")
    instrument_name: str | None = Field(default=None, description="器具名称（模糊搜索）")
    detection_model: str | None = Field(default=None, description="检测型号（精确匹配）")
    product_number: str | None = Field(default=None, description="产品编号（精确匹配）")
    measurement_range: str | None = Field(default=None, description="量程（精确匹配，支持逗号多选）")
    installation_type: str | None = Field(default=None, description="安装方式")
    installation_location: str | None = Field(default=None, description="安装位置（精确匹配）")
    medium: str | None = Field(default=None, description="使用介质（精确匹配）")
    detection_unit: str | None = Field(default=None, description="检测单位（精确匹配）")
    calibration_result: str | None = Field(default=None, description="检定结论（精确匹配）")
    calibration_factor: str | None = Field(default=None, description="标定系数（精确匹配）")
    manufacturer_supplier: str | None = Field(default=None, description="制造商/供应商（精确匹配）")
    manufacturer: str | None = Field(default=None, description="制造单位（精确匹配）")
    status: str | None = Field(default=None, description="器具状态：在用/停用/超期")
    next_calibration_before: date | None = Field(default=None, description="下次检定日期在此日期之前")
    next_calibration_after: date | None = Field(default=None, description="下次检定日期在此日期之后")
    calibration_date_before: date | None = Field(default=None, description="检定日期在此日期之前")
    calibration_date_after: date | None = Field(default=None, description="检定日期在此日期之后")
    keyword: str | None = Field(default=None, description="全局关键词搜索")
    has_report: bool | None = Field(default=None, description="是否有检测报告（True=有, False=无, None=不限）")
    # ── 文本列部分匹配（输入即过滤） ──
    instrument_name_like: str | None = Field(default=None, max_length=200, description="器具名称（包含匹配）")
    detection_model_like: str | None = Field(default=None, max_length=200, description="检测型号（包含匹配）")
    product_number_like: str | None = Field(default=None, max_length=100, description="产品编号（包含匹配）")
    measurement_range_like: str | None = Field(default=None, max_length=100, description="量程（包含匹配）")
    installation_type_like: str | None = Field(default=None, max_length=50, description="安装方式（包含匹配）")
    installation_location_like: str | None = Field(default=None, max_length=200, description="安装位置（包含匹配）")
    medium_like: str | None = Field(default=None, max_length=200, description="使用介质（包含匹配）")
    calibration_factor_like: str | None = Field(default=None, max_length=100, description="标定系数（包含匹配）")
    manufacturer_supplier_like: str | None = Field(default=None, max_length=200, description="制造商/供应商（包含匹配）")
    manufacturer_like: str | None = Field(default=None, max_length=200, description="制造单位（包含匹配）")
    detection_unit_like: str | None = Field(default=None, max_length=200, description="检测单位（包含匹配）")
    calibration_result_like: str | None = Field(default=None, max_length=50, description="检定结论（包含匹配）")


# ═══════════════════════════════════════════
# 检测报告
# ═══════════════════════════════════════════




class GasDetectorFilterOptions(BaseModel):
    """有毒有害可燃探测器筛选选项（全表 distinct 值）。"""
    department: list[str] = Field(default_factory=list)
    instrument_name: list[str] = Field(default_factory=list)
    detection_model: list[str] = Field(default_factory=list)
    product_number: list[str] = Field(default_factory=list)
    measurement_range: list[str] = Field(default_factory=list)
    installation_type: list[str] = Field(default_factory=list)
    installation_location: list[str] = Field(default_factory=list)
    medium: list[str] = Field(default_factory=list)
    calibration_factor: list[str] = Field(default_factory=list)
    manufacturer_supplier: list[str] = Field(default_factory=list)
    manufacturer: list[str] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)
    detection_unit: list[str] = Field(default_factory=list)
    calibration_result: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════
# 批量新增
# ═══════════════════════════════════════════





class GasDetectorBatchCreateItem(BaseModel):
    """批量新增有毒有害可燃探测器中的单条记录。"""
    instrument_name: str = Field(..., min_length=1, max_length=200, description="器具名称")
    detection_model: str | None = Field(default=None, max_length=200)
    measurement_range: str | None = Field(default=None, max_length=100)
    product_number: str | None = Field(default=None, max_length=100)
    installation_type: str | None = Field(default=None, max_length=50)
    installation_location: str | None = Field(default=None, max_length=500)
    medium: str | None = Field(default=None, max_length=500)
    calibration_factor: str | None = Field(default=None, max_length=100)
    manufacturer_supplier: str | None = Field(default=None, max_length=500)
    calibration_date: date | None = None
    calibration_result: str | None = Field(default=None, max_length=50)
    detection_unit: str | None = Field(default=None, max_length=200)
    next_calibration_date: date | None = None
    manufacturer: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=20)
    department: str = Field(..., max_length=200, description="部门")
    remark: str | None = Field(default=None, max_length=500, description="备注")





class GasDetectorBatchCreateRequest(BaseModel):
    """批量新增有毒有害可燃探测器请求。"""
    items: list[GasDetectorBatchCreateItem] = Field(..., min_length=1, max_length=200)


# ═══════════════════════════════════════════
# Excel 台账导入
# ═══════════════════════════════════════════
