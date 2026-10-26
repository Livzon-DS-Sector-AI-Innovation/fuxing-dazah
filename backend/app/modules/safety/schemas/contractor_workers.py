"""承包商在册人员副台账响应模型（3.x 平台关联 F1）。

字段口径的唯一事实源是 .scratch/f1-contractor-workers/spec.md 与
docs/DESIGN-3x平台关联-承包商实名台账全员主档与风险分区底图-20261026.md
§8.1。行字段多且随平台字段微调（service 层映射负责口径），workers 行用
受信封约束的宽松类型（dict）——骨架先例见 domain_pages.py。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ContractorWorkersStatus = Literal["live", "degraded", "empty"]


class OrgPostRowOut(BaseModel):
    """岗位字典行：postName 分组、deptName 聚合、人数（无个人级字段）。"""

    post_name: str
    dept_names: list[str] = Field(default_factory=list)
    headcount: int = Field(description="该岗位主档人数（全厂口径，不受过滤影响）")


class OrgPostsOut(BaseModel):
    """岗位字典三态信封（口径同 ContractorWorkersOut）。"""

    status: ContractorWorkersStatus
    fetched_at: str | None = Field(
        default=None, description="主档时点（ISO 时间；live=本次拉取，degraded=缓存时点）"
    )
    message: str | None = Field(default=None, description="降级/空态提示；live 为 null")
    posts: list[OrgPostRowOut] = Field(default_factory=list)


class ContractorWorkersStatsOut(BaseModel):
    """5 张统计卡：在册人数/承包商数/保险覆盖%/特种工持证率/超龄数。"""

    total: int = Field(description="在册人员总数")
    contractors: int = Field(description="在册人员覆盖的承包商单位数")
    insurance_covered_pct: int = Field(
        description="保险覆盖率（covered+expiring 占总数百分比，四舍五入取整）"
    )
    special_total: int = Field(description="特种工种在册人数（持证率分母）")
    cert_covered_pct: int | None = Field(
        default=None, description="特种工持证率；特种在册为 0 时为 null"
    )
    overage_count: int = Field(description="超龄人数（≥60，红档）")
    overage_warn_count: int = Field(description="超龄预警人数（55-59，黄档）")


class ContractorWorkersOut(BaseModel):
    """三态信封：live=本次/TTL 窗口内拉取成功；degraded=拉取失败回退旧缓存
    （fetched_at 为缓存时点）；empty=首次失败且无缓存（EmptyGuide）。"""

    status: ContractorWorkersStatus
    fetched_at: str | None = Field(
        default=None, description="台账时点（ISO 时间；live=本次拉取，degraded=缓存时点）"
    )
    message: str | None = Field(
        default=None, description="降级/空态时的提示文案；live 为 null"
    )
    stats: ContractorWorkersStatsOut | None = Field(
        default=None, description="统计卡；empty 为 null"
    )
    workers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="全量人员行（客户端分页）；身份证/手机已打码（前 3 后 2）",
    )
