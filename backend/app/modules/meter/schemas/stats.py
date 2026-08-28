"""检定提醒、日期聚合与总览统计 schema。"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.modules.meter.schemas.common import NormalizedDepartment, StrUUID


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





class DateStatDay(BaseModel):
    """日期聚合：单日统计。"""
    day: int = Field(..., ge=1, le=31, description="日")
    count: int = Field(..., ge=0, description="该日期条目数")





class DateStatMonth(BaseModel):
    """日期聚合：单月统计。"""
    month: int = Field(..., ge=1, le=12, description="月份")
    count: int = Field(..., ge=0, description="该月总条目数")
    days: list[DateStatDay] = Field(default_factory=list, description="日期明细")





class DateStatYear(BaseModel):
    """日期聚合：单年统计。"""
    year: int = Field(..., description="年份")
    count: int = Field(..., ge=0, description="该年总条目数")
    months: list[DateStatMonth] = Field(default_factory=list, description="月份明细")





class DateStatsResponse(BaseModel):
    """日期聚合统计响应。"""
    field: str = Field(..., description="统计的日期字段: calibration_date | next_calibration_date")
    years: list[DateStatYear] = Field(default_factory=list, description="年份列表（降序）")


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
