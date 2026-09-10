"""监护补贴统计 — Pydantic 请求/响应模型。

数据来源：平台作业票（WorkTicketParser 归一化，guardian/apply_unit/起止时间）
+ 监护人证书台账（person_certificates，A/B 证映射），经
``SubsidyPlanBuilder`` 整理为补贴记录；不再有飞书导出/Excel 上传入口。
"""

from pydantic import BaseModel, Field


class SubsidyRecordInput(BaseModel):
    """单条监护记录输入 — 平台作业票整理后的补贴记录（起始/结束时间 ISO 8601）"""

    guardian_name: str = Field(..., max_length=100, description="监护人姓名")
    guardian_level: str | None = Field(None, max_length=10, description="监护人证书级别: A证 / B证")
    ticket_no: str | None = Field(None, max_length=64, description="作业票号")
    department: str | None = Field(None, max_length=100, description="申请部门（平台作业申请单位）")
    operation_type: str = Field(..., max_length=50, description="特殊作业类型（中文标签）")
    operation_level: str | None = Field(None, max_length=20, description="作业级别（中文标签）")
    location_content: str = Field(..., max_length=500, description="作业地点+作业内容")
    start_time: str = Field(..., description="开始时间（ISO 8601 格式）")
    end_time: str = Field(..., description="结束时间（ISO 8601 格式）")
    interval_hours: str = Field("0", description="作业间隔时间(h)，字符串形式")


class SubsidyDetailItem(BaseModel):
    """单条监护补贴计算结果"""

    guardian_name: str
    guardian_level: str
    ticket_no: str = ""
    department: str = ""
    operation_type: str
    operation_level: str
    location_content: str
    start_time: str
    end_time: str
    interval_hours: str
    raw_hours: float = Field(..., description="原始时长（小时）")
    adjusted_hours: float = Field(..., description="扣除午休/间隔后时长（小时）")
    billing_units: int = Field(..., description="计费单位数")
    billing_unit_label: str = Field(..., description="计费单位: 半小时 / 天 / 次/块/罐")
    unit_price: float = Field(..., description="单价（元）")
    subsidy_amount: float = Field(..., description="补贴金额（元）")
    remark: str = Field("", description="备注（如扣除午休、B证系数、连续作业等）")


class SubsidySummaryItem(BaseModel):
    """按监护人汇总的补贴金额 — 按作业类型拆分"""

    guardian_name: str
    guardian_level: str
    hot_work: float = 0.0
    height_work: float = 0.0
    confined_space: float = 0.0
    temporary_electricity: float = 0.0
    blind_plate: float = 0.0
    excavation: float = 0.0
    road_breaking: float = 0.0
    lifting: float = 0.0
    total: float = 0.0


class SubsidyStats(BaseModel):
    """补贴统计汇总"""

    total_records: int = 0
    guardian_count: int = 0
    a_cert_count: int = 0
    b_cert_count: int = 0
    total_amount: float = 0.0


class SubsidyCalculateResponse(BaseModel):
    """补贴计算完整结果"""

    details: list[SubsidyDetailItem] = []
    summaries: list[SubsidySummaryItem] = []
    stats: SubsidyStats = Field(default_factory=SubsidyStats)


__all__ = [
    "SubsidyRecordInput",
    "SubsidyDetailItem",
    "SubsidySummaryItem",
    "SubsidyStats",
    "SubsidyCalculateResponse",
]
