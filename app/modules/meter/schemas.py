"""Meter request and response schemas live here."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.shared.schemas import PageParams

StrUUID = Annotated[str, BeforeValidator(str)]


def _normalize_department(value: str | None) -> str | None:
    """去除部门字段前后空白字符。"""
    if value is None:
        return None
    return value.strip()


# 响应 schema 中 department 字段统一使用此类型，自动去除前导数字
NormalizedDepartment = Annotated[str | None, BeforeValidator(_normalize_department)]


# ═══════════════════════════════════════════
# 通用
# ═══════════════════════════════════════════


class ReportItem(BaseModel):
    """检测报告简要信息（嵌套在仪表详情中返回）。"""
    id: StrUUID
    file_name: str
    file_size: int | None = None
    content_type: str | None = None
    report_date: date | None = None
    remark: str | None = None
    uploaded_at: datetime | None = None
    download_url: str | None = Field(default=None, description="MinIO 预签名下载链接")


# ═══════════════════════════════════════════
# 标准计量器具
# ═══════════════════════════════════════════

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
    keyword: str | None = Field(default=None, description="全局关键词搜索（匹配资产编号、器具名称、型号）")


# ═══════════════════════════════════════════
# 有毒有害可燃探测器
# ═══════════════════════════════════════════

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
    installation_type: str | None = Field(default=None, description="安装方式")
    installation_location: str | None = Field(default=None, description="安装位置（精确匹配）")
    medium: str | None = Field(default=None, description="使用介质（精确匹配）")
    detection_unit: str | None = Field(default=None, description="检测单位（精确匹配）")
    calibration_result: str | None = Field(default=None, description="检定结论（精确匹配）")
    calibration_factor: str | None = Field(default=None, description="标定系数（精确匹配）")
    manufacturer_supplier: str | None = Field(default=None, description="制造商/供应商（精确匹配）")
    manufacturer: str | None = Field(default=None, description="制造单位（精确匹配）")
    next_calibration_before: date | None = Field(default=None, description="下次检定日期在此日期之前")
    next_calibration_after: date | None = Field(default=None, description="下次检定日期在此日期之后")
    keyword: str | None = Field(default=None, description="全局关键词搜索")


# ═══════════════════════════════════════════
# 检测报告
# ═══════════════════════════════════════════

class ReportCreate(BaseModel):
    """上传检测报告元数据（文件通过 multipart/form-data 上传）。"""
    instrument_id: str | None = Field(default=None, description="关联标准计量器具 ID")
    gas_detector_id: str | None = Field(default=None, description="关联探测器 ID")
    report_date: date | None = Field(default=None, description="报告日期")
    remark: str | None = Field(default=None, max_length=500, description="备注")


class ReportResponse(BaseModel):
    """检测报告响应。"""
    id: StrUUID
    instrument_id: str | None = None
    gas_detector_id: str | None = None
    file_name: str
    file_size: int | None = None
    content_type: str | None = None
    report_date: date | None = None
    remark: str | None = None
    download_url: str | None = Field(default=None, description="MinIO 预签名下载链接")
    uploaded_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════
# 检定到期提醒
# ═══════════════════════════════════════════

class CalibrationAlertResponse(BaseModel):
    """检定到期提醒项。"""
    source: str = Field(..., description="数据来源: instrument / gas_detector")
    id: StrUUID
    serial_number: str | None = Field(default=None, description="器具编号")
    instrument_name: str
    location: str | None = None
    department: NormalizedDepartment = None
    next_calibration_date: date | None = None
    days_until_due: int | None = Field(default=None, description="距到期天数（负数=已过期）")


class ExtractDateResponse(BaseModel):
    """提取日期结果。"""
    success: bool
    calibration_date: str | None = None
    next_calibration_date: str | None = None
    calibration_cycle_months: int | None = None
    error: str | None = None


# ═══════════════════════════════════════════
# 批量导出
# ═══════════════════════════════════════════


class ExportReportRequest(BaseModel):
    """批量导出报告请求。"""
    ids: list[str] = Field(default_factory=list, max_length=200, description="仪表 ID 列表")


# ═══════════════════════════════════════════
# 批量上传 + 文件匹配
# ═══════════════════════════════════════════


class FileMatchItem(BaseModel):
    """单个文件的匹配结果。"""
    filename: str
    matched_type: str | None = Field(default=None, description="instrument / gas_detector / None(未匹配)")
    matched_id: str | None = Field(default=None, description="匹配到的仪表 ID")
    matched_name: str | None = Field(default=None, description="匹配到的仪表名称")
    matched_department: NormalizedDepartment = Field(default=None, description="匹配到的仪表部门")


class FileMatchRequest(BaseModel):
    """批量匹配请求：前端发送文件名列表。"""
    filenames: list[str] = Field(default_factory=list, max_length=200)


class BatchUploadItem(BaseModel):
    """批量上传中单个文件的确认信息。"""
    filename: str
    instrument_id: str | None = Field(default=None, description="关联标准计量器具 ID")
    gas_detector_id: str | None = Field(default=None, description="关联探测器 ID")
    report_date: date | None = Field(default=None)


class BatchUploadRequest(BaseModel):
    """批量上传请求。"""
    items: list[BatchUploadItem] = Field(default_factory=list, max_length=200)


class BatchUploadResult(BaseModel):
    """批量上传结果。"""
    success: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    report_ids: list[str] = Field(default_factory=list, description="成功上传的报告 ID 列表")


# ═══════════════════════════════════════════
# 批量 AI 日期提取
# ═══════════════════════════════════════════


class BatchExtractRequest(BaseModel):
    """批量提取日期请求。"""
    report_ids: list[str] = Field(default_factory=list, min_length=1, max_length=200, description="报告 ID 列表")


class BatchExtractItem(BaseModel):
    """单份报告的提取结果。"""
    report_id: str
    file_name: str
    success: bool
    calibration_date: str | None = None
    next_calibration_date: str | None = None
    error: str | None = None


class BatchExtractResponse(BaseModel):
    """批量提取日期响应。"""
    total: int = 0
    success: int = 0
    failed: int = 0
    results: list[BatchExtractItem] = Field(default_factory=list)


# ═══════════════════════════════════════════
# 筛选选项
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


class GasDetectorFilterOptions(BaseModel):
    """有毒有害可燃探测器筛选选项（全表 distinct 值）。"""
    department: list[str] = Field(default_factory=list)
    instrument_name: list[str] = Field(default_factory=list)
    detection_model: list[str] = Field(default_factory=list)
    product_number: list[str] = Field(default_factory=list)
    installation_type: list[str] = Field(default_factory=list)
    installation_location: list[str] = Field(default_factory=list)
    medium: list[str] = Field(default_factory=list)
    calibration_factor: list[str] = Field(default_factory=list)
    manufacturer_supplier: list[str] = Field(default_factory=list)
    manufacturer: list[str] = Field(default_factory=list)
    detection_unit: list[str] = Field(default_factory=list)
    calibration_result: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════
# 批量新增
# ═══════════════════════════════════════════


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
    department: str = Field(..., max_length=200, description="部门")
    remark: str | None = Field(default=None, max_length=500, description="备注")


class GasDetectorBatchCreateRequest(BaseModel):
    """批量新增有毒有害可燃探测器请求。"""
    items: list[GasDetectorBatchCreateItem] = Field(..., min_length=1, max_length=200)


# ═══════════════════════════════════════════
# Excel 台账导入
# ═══════════════════════════════════════════


class LedgerImportError(BaseModel):
    """单条导入错误详情。"""
    sheet: str = Field(..., description="Sheet 名称")
    row: int | None = Field(default=None, description="Excel 行号（1-based）")
    type: str = Field(default="error", description="error / warning")
    message: str = Field(..., description="错误描述")
    missing_fields: list[str] = Field(default_factory=list, description="缺少的字段名列表")


class LedgerImportSheetDetail(BaseModel):
    """单个 sheet 的导入结果。"""
    sheet_name: str = Field(..., description="Sheet 名称")
    department: str | None = Field(default=None, description="从 sheet 中提取的部门名")
    rows: int = Field(default=0, description="本 sheet 导入的数据行数")


class LedgerImportResult(BaseModel):
    """台账导入结果汇总。"""
    deleted_count: int = Field(default=0, description="软删除的旧记录数")
    imported_count: int = Field(default=0, description="新导入的记录数")
    sheet_count: int = Field(default=0, description="处理的 sheet 数")
    sheet_details: list[LedgerImportSheetDetail] = Field(default_factory=list)
    warnings: list[LedgerImportError] = Field(default_factory=list, description="字段缺失提醒")


# ═══════════════════════════════════════════
# 仪表总览
# ═══════════════════════════════════════════


class MeterOverviewResponse(BaseModel):
    """仪表总览统计数据。"""
    total: int = Field(default=0, description="总数量")
    in_use: int = Field(default=0, description="在用数量")
    overdue: int = Field(default=0, description="超期数量")
    stopped: int = Field(default=0, description="停用数量")
    due_today: int = Field(default=0, description="截止今天到期（含已过期）")
    due_7d: int = Field(default=0, description="未来 7 天到期")
    due_30d: int = Field(default=0, description="未来 30 天到期")
    due_90d: int = Field(default=0, description="未来 90 天到期")


# ═══════════════════════════════════════════
# 部门管理
# ═══════════════════════════════════════════


class DepartmentCreate(BaseModel):
    """新增部门。"""
    source: str = Field(..., pattern="^(instrument|gas_detector)$", description="来源: instrument / gas_detector")
    name: str = Field(..., min_length=1, max_length=200, description="部门名称")
    heads: list[dict[str, str]] = Field(
        default_factory=list,
        description="负责人列表 [{\"name\": \"张三\", \"feishu_open_id\": \"ou_xxx\"}]",
    )


class DepartmentUpdate(BaseModel):
    """更新部门名称（改名联动更新对应表）。"""
    name: str = Field(..., min_length=1, max_length=200, description="新部门名称")
    heads: list[dict[str, str]] | None = Field(
        default=None,
        description="负责人列表 [{\"name\": \"张三\", \"feishu_open_id\": \"ou_xxx\"}]",
    )
    auto_notify_enabled: bool | None = Field(default=None, description="部门级自动提醒开关")


class DepartmentResponse(BaseModel):
    """部门响应。"""
    id: StrUUID
    source: str
    name: str
    heads: list[dict[str, str]] = Field(default_factory=list, description="负责人列表")
    auto_notify_enabled: bool = False
    record_count: int = Field(default=0, description="关联记录数")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PersonnelCandidate(BaseModel):
    """负责人候选人（从 identity.users 查询，前端下拉列表用）。"""
    name: str
    feishu_open_id: str
    department: str | None = None


# ═══════════════════════════════════════════
# 全局设置
# ═══════════════════════════════════════════


class MeterSettingsResponse(BaseModel):
    """全局设置响应。"""
    notify_time: str = Field(..., description="每日提醒时间 HH:MM")


class MeterSettingsUpdate(BaseModel):
    """更新全局设置。"""
    notify_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="提醒时间 HH:MM")
