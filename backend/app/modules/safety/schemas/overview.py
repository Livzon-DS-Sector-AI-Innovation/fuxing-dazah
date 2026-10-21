"""总览驾驶舱（/safety/overview）响应模型——二期 3.0 门面。

一个端点喂饱驾驶舱：6 KPI + 速递回放 + 隐患趋势 + 报警分析 + 下钻三列 +
17 模块健康度。单域采集失败时该域为 None（errors 标注），前端降级空态。
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

__all__ = ["OverviewOut"]


# ── 隐患 ──


class HazardTrendOut(BaseModel):
    dates: list[str] = Field(default_factory=list, description="北京日 iso（近 30 天）")
    created: list[int] = Field(default_factory=list, description="每日新增")
    closed: list[int] = Field(default_factory=list, description="每日闭环")


class HazardsOut(BaseModel):
    unclosed: int = 0
    delta: int = 0
    overdue: int = 0
    trend: HazardTrendOut = Field(default_factory=HazardTrendOut)


# ── 特殊作业 / 报警 ──


class SpecialOpsOut(BaseModel):
    today_total: int = 0
    high: int = 0


class TopAlarmTypeOut(BaseModel):
    name: str
    count: int


class AlarmAnalysisOut(BaseModel):
    dates: list[str] = Field(default_factory=list, description="本周（北京日）")
    fire_daily: list[int] = Field(default_factory=list)
    central_daily: list[int] = Field(default_factory=list)
    top_fire_types: list[TopAlarmTypeOut] = Field(default_factory=list)


class AlarmsOut(BaseModel):
    today_total: int = 0
    fire_today: int = 0
    central_today: int = 0
    fire_real_today: int = 0
    analysis: AlarmAnalysisOut = Field(default_factory=AlarmAnalysisOut)


# ── 证书 / 危化品 / 关键风险作业 ──


class ExpiringCertOut(BaseModel):
    person_name: str
    department: str | None = None
    cert_category: str
    deadline: date | None = None
    remaining_days: int | None = None


class CertsOut(BaseModel):
    within_30d: int = 0
    urgent_or_overdue: int = 0
    items: list[ExpiringCertOut] = Field(default_factory=list)


class OverLimitMaterialOut(BaseModel):
    material_name: str
    department: str | None = None
    storage_location: str | None = None
    total_quantity_t: float
    max_limit: float
    unit: str | None = None


class ChemicalsOut(BaseModel):
    over_limit: int = 0
    materials: list[OverLimitMaterialOut] = Field(default_factory=list)


class KeyRiskOpItemOut(BaseModel):
    start_time: datetime | None = None
    department: str | None = None
    operation_content: str | None = None
    apply_status: str | None = None


class KeyRiskOpsOut(BaseModel):
    today_approved: int = 0
    in_progress: int = 0
    items: list[KeyRiskOpItemOut] = Field(default_factory=list)


class EhsOut(BaseModel):
    """EHS 变更：进行中 = 审核中 + 实施中。"""

    in_progress: int = 0


# ── 速递回放 / 健康度 / 顶层 ──


class DigestCellOut(BaseModel):
    key: str
    tag_color: str = ""
    tag_text: str = ""
    title: str = ""
    stats: str = ""
    zone: str = ""
    detail: str = ""
    sent_at: str | None = Field(None, description="最近推送时间；历史格子为 None")


class DigestOut(BaseModel):
    count: int = 0
    cells: list[DigestCellOut] = Field(default_factory=list)


class ModuleHealthOut(BaseModel):
    """健康度卡：key 与前端菜单项一致（前端由 menu-config 解析名称/路径/分组）。

    status: ok=正常 / warn=预警 / inactive=未开展（灰，可点占位页）/
    upcoming=未上线（灰，不可点，仅全流程监督）
    """

    key: str
    status: str
    metric: str | None = None


class FacilityTasksOut(BaseModel):
    """设施校验任务计数（facilities 卡任务口径覆盖源；前端告警条可用）。"""

    open: int = 0
    overdue: int = 0


class OverviewOut(BaseModel):
    date: str = Field(description="北京日 iso")
    generated_at: datetime
    hazards: HazardsOut | None = None
    special_ops: SpecialOpsOut | None = None
    alarms: AlarmsOut | None = None
    certs: CertsOut | None = None
    chemicals: ChemicalsOut | None = None
    key_risk_ops: KeyRiskOpsOut | None = None
    ehs: EhsOut | None = None
    facility_tasks: FacilityTasksOut | None = None
    digest: DigestOut | None = None
    module_health: list[ModuleHealthOut] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list, description="降级域标注")
