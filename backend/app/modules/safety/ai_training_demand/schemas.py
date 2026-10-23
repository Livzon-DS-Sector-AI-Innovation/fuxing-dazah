"""AI 年度培训需求生成插件 — 输入/输出数据结构（链1）。

输入=服务层五源取数拼好的五段汇报文本（digest），输出=需求清单草案
（供安环科评审，落 PG training_demand_drafts，采纳后才写台账）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrainingDemandInput(BaseModel):
    """生成输入 — 五源汇报文本（空源由服务层降级为占位说明，不留空串）"""

    hazard_id_digest: str = Field(default="", description="危险源辨识摘要")
    hazard_stats: str = Field(default="", description="本年度隐患统计")
    violation_stats: str = Field(default="", description="本年度违章档案统计")
    regulation_list: str = Field(default="", description="本年度新收录/修订法规清单")
    last_year_summary: str = Field(default="", description="上学年培训完成情况")


class TrainingDemandItem(BaseModel):
    """单条需求草案（basis 必须可溯源——引用输入中出现过的行为/类别/次数/法规标题）"""

    position: str = Field(default="", description="岗位")
    topic: str = Field(default="", description="培训主题")
    suggested_hours: float | None = Field(default=None, description="建议学时")
    form: str | None = Field(default=None, description="建议形式：线下/线上/实操")
    audience: str = Field(default="", description="对象说明")
    basis: str = Field(default="", description="可溯源依据")
    is_statutory_gap: bool = Field(default=False, description="是否法定缺口行")


class TrainingDemandOutput(BaseModel):
    """生成输出 — 需求清单草案"""

    summary: str = Field(default="", description="一句话总评")
    demands: list[TrainingDemandItem] = Field(default_factory=list, description="需求清单")
    statutory_notes: list[str] = Field(default_factory=list, description="法定缺口补充说明")
