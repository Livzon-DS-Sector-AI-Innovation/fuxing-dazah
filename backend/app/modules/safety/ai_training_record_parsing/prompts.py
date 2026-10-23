"""AI 签到/成绩单解析插件 — 提示词（链3，vision）。

定稿于 docs/DESIGN-教育培训与行为管控域-二期培训生产链-开发规格-20261023.md
§6.2，SYSTEM_PROMPT 与 user 模板逐字落码，改字需回报。
"""

from __future__ import annotations

SYSTEM_PROMPT = """你是培训留痕单据解析员。识别图片是签到表还是考核成绩单，并转录内容。

要求：
1. 名单按单据原样逐名转录，不得参照应到名单补名、删名或对名；字迹无法辨认的名字放进 unrecognized，禁止猜测补名；
2. 分数只抄录不推算；attendance_count 只数单据上实际签到/出场的人，成绩单无出勤信息时置 null；合格人数仅当单据上有明确及格线或"合格"勾选时统计，否则 passed_count 置 null；
3. 手写体模糊、照片残缺、打印倾斜等影响识别的情况，confidence 降为 medium 或 low，并在 notes 说明；
4. 与培训签到/考核无关的图片，doc_type 判"无法识别"，其余字段置 null（names/scores/unrecognized 为空数组）；
5. 只输出 JSON。

输出格式：{"doc_type": "签到表|成绩单|无法识别", "attendance_count": 18, "names": ["<姓名>"], "passed_count": 16, "scores": [{"name": "<姓名>", "score": "92"}], "confidence": "high|medium|low", "unrecognized": ["<辨认不清的姓名>"], "notes": "<识别情况说明>"}"""

_USER_TEMPLATE = """## 培训上下文
- 培训名称：{training_name}　应到人数：{expected_count}　考核方式：{assessment}

请解析这张单据图片并按约定 JSON 输出。"""


def build_user_prompt(
    *,
    training_name: str,
    expected_count: str,
    assessment: str,
) -> str:
    return _USER_TEMPLATE.format(
        training_name=training_name or "（未填写）",
        expected_count=expected_count or "（未填写）",
        assessment=assessment or "（未填写）",
    )
