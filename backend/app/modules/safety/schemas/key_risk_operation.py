"""关键风险作业报备 schemas（只读，Bitable 同步）."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class KeyRiskOperationReportResponse(BaseModel):
    """关键风险作业报备响应（只读）"""

    id: uuid.UUID
    report_no: str
    approval_no_url: str | None = None
    source: str | None = None
    feishu_record_id: str | None = None

    # 审批字段
    apply_status: str | None = None
    approval_node: str | None = None
    approval_flow: str | None = None
    current_handler: str | None = None
    initiator_name: str | None = None
    initiator_department: str | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None

    # 作业主信息
    department: str | None = None
    area: str | None = None
    operation_content: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_hours: float | None = None
    notes: str | None = None

    # 安全措施（主作业）
    personal_protection: str | None = None
    preparation_measures: str | None = None
    operation_precautions: str | None = None
    emergency_measures: str | None = None
    guardian: str | None = None
    site_guardian: str | None = None
    dept_safety_officer: str | None = None

    # 多作业块 / 三阶段现场确认
    operations: list | None = None
    phase_before: dict | None = None
    phase_ongoing: dict | None = None
    phase_after: dict | None = None

    source_id: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KeyRiskOperationLedgerStats(BaseModel):
    """关键风险作业 KPI 统计"""

    today_approved: int = Field(0, description="今日已通过")
    in_progress: int = Field(0, description="审批中")
    month_approved: int = Field(0, description="本月已通过")
    total: int = Field(0, description="累计总记录")


class KeyRiskOperationExportRequest(BaseModel):
    """关键风险作业台账导出请求"""

    department: str | None = Field(None, description="部门")
    area: str | None = Field(None, description="区域")
    operation_content: str | None = Field(None, description="作业内容")
    apply_status: str | None = Field(None, description="申请状态")
    date_from: str | None = Field(None, description="作业开始日期起 YYYY-MM-DD")
    date_to: str | None = Field(None, description="作业开始日期止 YYYY-MM-DD")
    keyword: str | None = Field(None, description="关键词搜索（编号/内容/区域/部门）")
