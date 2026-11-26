"""离职台账增强（筛选 / 导出 / 保存视图）的请求契约。

筛选条件的键名是「列表查询、保存视图、导出留痕」三处共用的口径——视图里存的就是
这些键，导出留痕记的也是这些键，改键名等于改历史数据格式。
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

# 排序只放开这三个字段：其余列直接拿用户输入做 getattr 会变成任意列排序
_SORT_FIELDS = ("offboarding_date", "name", "department")


class DepartureLedgerFilters(BaseModel):
    """离职台账筛选条件（需求「筛选与导出」十类，可任意组合、可单独使用）。"""

    keyword: str | None = Field(None, max_length=64, description="姓名/工号/部门/职位关键词")
    department: str | None = Field(None, max_length=64, description="部门")
    position: str | None = Field(None, max_length=64, description="岗位")
    offboarding_type: str | None = Field(None, max_length=16, description="离职类型")
    offboarding_reason: str | None = Field(None, max_length=64, description="离职原因（多选值之一）")
    gender: str | None = Field(None, max_length=8, description="性别")
    education: str | None = Field(None, max_length=32, description="学历")
    employee_category: str | None = Field(None, max_length=64, description="用工类型（员工性质）")
    offboarding_date_from: date | None = Field(None, description="离职日期起")
    offboarding_date_to: date | None = Field(None, description="离职日期止")
    approval_status: str | None = Field(
        None, max_length=24, description="办理状态（办结单状态）；none = 未发起办理",
    )
    cert_issued: bool | None = Field(None, description="是否已开具证明")
    cert_signed: bool | None = Field(None, description="是否已签收证明")

    def active(self) -> dict[str, Any]:
        """只保留显式设置了值的条件（保存视图 / 导出留痕用，不存一堆 null）。"""
        return self.model_dump(exclude_unset=True)


class DepartureLedgerQuery(DepartureLedgerFilters):
    sort_by: str = Field("offboarding_date", pattern="^(" + "|".join(_SORT_FIELDS) + ")$")
    sort_order: str = Field("desc", pattern="^(asc|desc)$")
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=200)


class DepartureExportRequest(DepartureLedgerFilters):
    columns: list[str] = Field(..., min_length=1, max_length=80, description="导出字段 key（见导出字段注册表）")


class DepartureSavedViewIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="视图名称")
    filters: DepartureLedgerFilters = Field(default_factory=DepartureLedgerFilters)
    columns: list[str] = Field(default_factory=list, max_length=80, description="导出字段 key 列表")
    is_default: bool = Field(False, description="设为我的默认视图（同一人只保留一个）")
