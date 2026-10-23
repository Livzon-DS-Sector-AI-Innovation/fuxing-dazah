"""AI 培训课件/试卷生成插件 — 输入/输出数据结构（链2）。

讲义（§5.4）：培训行信息 + 知识片段 → 讲义要点卡 JSON。
试卷（§5.5）结构随 T3 落码，JSON 键结构对齐 HR EXAM_QUESTION_KEYS
（契约复用、safety 侧独立实现）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LectureInput(BaseModel):
    """讲义生成输入 — 培训行上下文 + 知识片段"""

    topic: str = Field(default="", description="培训主题（培训名称）")
    category: str | None = Field(default=None, description="培训类别")
    hours: str | None = Field(default=None, description="培训学时（展示文本）")
    position: str | None = Field(default=None, description="对象岗位（组织部门）")
    knowledge_md: str = Field(default="", description="知识片段 markdown（空=无检索）")


class LectureSection(BaseModel):
    heading: str = Field(default="", description="章节名")
    points: list[str] = Field(default_factory=list, description="章节要点")


class LectureOutput(BaseModel):
    """讲义生成输出 — 要点卡"""

    title: str = Field(default="", description="讲义标题")
    objectives: list[str] = Field(default_factory=list, description="培训目标")
    sections: list[LectureSection] = Field(default_factory=list, description="章节")
    key_takeaways: list[str] = Field(default_factory=list, description="核心要点（≤8）")
    references: list[str] = Field(default_factory=list, description="来源名")

    @property
    def card_markdown(self) -> str:
        lines = [f"# {self.title}"] + [f"- 目标：{o}" for o in self.objectives]
        for section in self.sections:
            lines.append(f"## {section.heading}")
            lines.extend(f"- {p}" for p in section.points)
        if self.key_takeaways:
            lines.append("## 核心要点")
            lines.extend(f"- {p}" for p in self.key_takeaways)
        if self.references:
            lines.append("## 参考资料")
            lines.extend(f"- {r}" for r in self.references)
        return "\n".join(lines)


class ExamInput(BaseModel):
    """试卷生成输入 — 材料（讲义要点 + 检索片段）+ 题型配置"""

    material: str = Field(default="", description="命题材料（讲义要点卡+检索片段）")
    config: dict | None = Field(
        None, description="题型配置：choice/true_false/multi_choice/fill 计数"
    )


class ExamOutput(BaseModel):
    """试卷生成输出 — 键结构对齐 HR EXAM_QUESTION_KEYS（契约复用）"""

    questions: dict[str, list[dict]] = Field(
        default_factory=dict, description="按题型键分组的题目（已校验清洗）"
    )

    @property
    def total_count(self) -> int:
        return sum(len(qs) for qs in self.questions.values())
