"""检测报告与文件匹配/批量上传 schema。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.meter.schemas.common import NormalizedDepartment, StrUUID


class ReportItem(BaseModel):
    """检测报告简要信息（嵌套在仪表详情中返回）。"""
    id: StrUUID
    file_name: str
    file_size: int | None = None
    content_type: str | None = None
    certificate_no: str | None = None
    report_date: date | None = None
    remark: str | None = None
    uploaded_at: datetime | None = None
    download_url: str | None = Field(default=None, description="MinIO 预签名下载链接")


# ═══════════════════════════════════════════
# 标准计量器具
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
    certificate_no: str | None = None
    report_date: date | None = None
    remark: str | None = None
    download_url: str | None = Field(default=None, description="MinIO 预签名下载链接")
    uploaded_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)





class UpdateReportRequest(BaseModel):
    """手动修改检测报告元数据。"""
    certificate_no: str | None = Field(default=None, max_length=100, description="证书编号")





class ReportFieldExtraction(BaseModel):
    """报告内容识别结果。"""
    instrument_name: str | None = None
    serial_number: str | None = None
    certificate_no: str | None = None
    calibration_date: date | None = None
    method: str | None = Field(default=None, description="text / vision / failed")
    error: str | None = None





class ReportMatchCandidate(BaseModel):
    """匹配候选台账记录。"""
    type: str = Field(..., description="instrument / gas_detector")
    id: StrUUID
    name: str
    code: str | None = Field(default=None, description="serial_number / product_number")
    department: NormalizedDepartment = None





class ReportAnalyzeItem(BaseModel):
    """单文件内容识别 + 匹配结果。"""
    filename: str
    extraction: ReportFieldExtraction
    matched_type: str | None = Field(default=None, description="instrument / gas_detector / None(未匹配)")
    matched_id: str | None = None
    matched_name: str | None = None
    matched_department: NormalizedDepartment = None
    candidates: list[ReportMatchCandidate] = Field(default_factory=list)


# ═══════════════════════════════════════════
# 检定到期提醒
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
    filenames: list[str] = Field(default_factory=list)





class BatchUploadItem(BaseModel):
    """批量上传中单个文件的确认信息。"""
    filename: str
    instrument_id: str | None = Field(default=None, description="关联标准计量器具 ID")
    gas_detector_id: str | None = Field(default=None, description="关联探测器 ID")
    report_date: date | None = Field(default=None)
    certificate_no: str | None = Field(default=None, max_length=100, description="证书编号（防重复上传）")
    calibration_date: date | None = Field(default=None, description="识别出的校准日期（用于条件回写）")





class BatchUploadRequest(BaseModel):
    """批量上传请求。"""
    items: list[BatchUploadItem] = Field(default_factory=list, max_length=200)





class BatchUploadResult(BaseModel):
    """批量上传结果。"""
    success: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="提示信息（如日期较旧未回写）")
    report_ids: list[str] = Field(default_factory=list, description="成功上传的报告 ID 列表")


# ═══════════════════════════════════════════
# 筛选选项
# ═══════════════════════════════════════════
