"""AI 违章定向培训要点卡插件 — 提示词。

防幻觉约束（R1 无 RAG 检索）：只允许基于输入违章上下文生成，禁止编造
法规编号/标准号；引用依据一律落「按公司操作规程与岗位安全要求」表述。
"""

from __future__ import annotations

SYSTEM_PROMPT = """你是工厂安全培训专员。针对一起违章行为，生成一份定向培训要点卡，\
供违章人员复训使用。

要求：
1. 只基于输入的违章信息生成，不得编造具体法规编号或标准号；
2. 要点不超过 5 条，每条是可直接执行的行为要求，与违章事实直接相关；
3. summary 为一句话主题（20 字以内）。

以 JSON 输出：{"summary": "<主题>", "key_points": ["<要点1>", "<要点2>", ...]}"""

_USER_TEMPLATE = """## 违章信息
- 违章描述：{description}
- 违章类别：{category}
- 违章等级：{level}
- 处理方式：{handling}
- 所属单位：{department}
- 违章人员：{person_name}
- 关联隐患编号：{hazard_no}
- 岗位行为要点：{position_hints}

请生成定向培训要点卡。"""


def build_user_prompt(
    *,
    description: str,
    category: str | None = None,
    level: str | None = None,
    handling: str | None = None,
    department: str | None = None,
    person_name: str | None = None,
    hazard_no: str | None = None,
    position_hints: str | None = None,
) -> str:
    return _USER_TEMPLATE.format(
        description=description or "（未填写）",
        category=category or "（未填写）",
        level=level or "（未填写）",
        handling=handling or "（未填写）",
        department=department or "（未填写）",
        person_name=person_name or "（未填写）",
        hazard_no=hazard_no or "（未填写）",
        position_hints=position_hints or "（未提供）",
    )
