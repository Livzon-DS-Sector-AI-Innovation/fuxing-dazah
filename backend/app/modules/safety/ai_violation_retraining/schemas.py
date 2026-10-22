"""AI 违章定向培训要点卡插件 — 输入/输出数据结构。

链5（违章→定向培训）的生成器：输入违章上下文，输出可直接推送/落表的
定向培训要点卡（一句话主题 + 行为要点清单）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ViolationRetrainingInput(BaseModel):
    """生成输入 — 违章档案行上下文（人可缺省：回流行违章人待补录）"""

    description: str = Field(default="", description="违章描述")
    category: str | None = Field(None, description="违章类别")
    level: str | None = Field(None, description="违章等级：一般/严重/重大")
    handling: str | None = Field(None, description="处理方式")
    department: str | None = Field(None, description="所属单位")
    person_name: str | None = Field(None, description="违章人员")
    hazard_no: str | None = Field(None, description="关联隐患编号")
    position_hints: str | None = Field(
        None,
        description="岗位行为要点（hazard_id 岗位不规范行为清单等；R1 通常缺省）",
    )


class ViolationRetrainingOutput(BaseModel):
    """生成输出 — 要点卡"""

    summary: str = Field(default="", description="一句话主题")
    key_points: list[str] = Field(default_factory=list, description="行为要点清单")

    @property
    def card_markdown(self) -> str:
        lines = [self.summary] + [f"- {p}" for p in self.key_points]
        return "\n".join(lines)
