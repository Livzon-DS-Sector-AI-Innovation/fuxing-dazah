"""AI 培训课件/试卷生成插件 — 提示词（链2：讲义 + 试卷，同包两套）。

定稿于 docs/DESIGN-教育培训与行为管控域-二期培训生产链-开发规格-20261023.md
§5.4（讲义）/§5.5（试卷，2026-10-23 二审修订版），SYSTEM_PROMPT 逐字落码；
讲义 user 模板逐字；试卷 user prompt 按 §5.5 拼装句式动态构建（f-string，
仅含数量>0 的题型）。改字需回报。
"""

from __future__ import annotations

# ═══════════════════════════ 讲义要点卡（§5.4，temp 0.2） ═══════════════════════════

LECTURE_SYSTEM_PROMPT = """你是工厂安全培训讲师。根据培训基本信息与检索到的法规/规程/MSDS 片段，生成讲义要点卡（授课大纲级，非逐字稿）。

要求：
1. 章节要点必须来自给定片段或普适安全常识；引用条款、限值、数字时必须与片段一致，并标注来源名（如「GB 30871-2022 §5.2」须在片段中真实出现）；
2. 检索片段为空时，按主题通用要求编制，并在 references 中注明「待补法规出处，讲师定稿前补核」；
3. 要点密度与学时匹配：每学时 3-5 个要点；每个要点是可直接讲授的行为或规则表述；
4. key_takeaways 不超过 8 条，是学员必须带走的内容；
5. 只输出 JSON。

输出格式：{"title": "<讲义标题>", "objectives": ["<培训目标>"], "sections": [{"heading": "<章节名>", "points": ["<要点>"]}], "key_takeaways": ["<核心要点>"], "references": ["<来源名>"]}"""

_LECTURE_USER_TEMPLATE = """## 培训信息
- 主题：{topic}　类别：{category}　学时：{hours}　对象岗位：{position}

## 检索片段（来源见 [N] 编号标注）
{knowledge_md}

请生成讲义要点卡。"""


def build_lecture_user_prompt(
    *,
    topic: str,
    category: str,
    hours: str,
    position: str,
    knowledge_md: str,
) -> str:
    return _LECTURE_USER_TEMPLATE.format(
        topic=topic or "（未填写）",
        category=category or "（未填写）",
        hours=hours or "（未填写）",
        position=position or "（未填写）",
        knowledge_md=knowledge_md or "（无检索片段）",
    )


# ═══════════════════════════ 试卷（§5.5，temp 0.1） ═══════════════════════════

EXAM_SYSTEM_PROMPT = """你是工厂安全培训考核出题人。根据给定材料（讲义要点 + 检索片段）生成试卷，严格基于材料内容命题，禁止编造材料中不存在的知识点；每道题标注 source（材料中的来源名或「讲义要点」）。
各题型题量必须严格按指定数量出足，不得少出或多出。
干扰选项要合理、有区分度，正确答案在各选项间均匀分布，不要固定为 A；多选题有 2-3 个正确答案，answer 用逗号连接（如 "A,B"）；判断题 answer 只能是"正确"或"错误"，正确与错误大致各半；填空题 question 中用______表示空位且不能出现答案。
只输出 JSON，不输出其他内容。"""

# 题型配置键（对齐 HR ai_exam_service：默认 5 单选 / 5 判断 / 0 多选 / 0 填空）
EXAM_CONFIG_DEFAULTS = {
    "choice_count": 5,
    "true_false_count": 5,
    "multi_choice_count": 0,
    "fill_blank_count": 0,
}

# 题型要求句式（§5.5 逐字，数量>0 才出现）
_EXAM_REQ_TEMPLATES = {
    "choice_questions": "出 {n} 道单选题（4 选项 A/B/C/D，只有一个正确答案）",
    "true_false_questions": "出 {n} 道判断题（answer 只能是\"正确\"或\"错误\"，正确与错误大致各半）",
    "multi_choice_questions": "出 {n} 道多选题（4 选项，有 2-3 个正确答案）",
    "fill_blank_questions": "出 {n} 道填空题（将关键知识点挖空，question 中用______表示空位，question 里不能出现答案）",
}

# 输出格式骨架片段（§5.5 逐字，数量>0 才出现）
_EXAM_SKELETON_FRAGMENTS = {
    "choice_questions": '"choice_questions": [{"question":"...","options":[{"label":"A","text":"..."},...],"answer":"A","source":"..."}]',
    "true_false_questions": '"true_false_questions": [{"question":"...","answer":"正确","source":"..."}]',
    "multi_choice_questions": '"multi_choice_questions": [{"question":"...","options":[{"label":"A","text":"..."},...],"answer":"A,B","source":"..."}]',
    "fill_blank_questions": '"fill_blank_questions": [{"question":"...","answer":"关键词","source":"..."}]',
}


# 题型键 → config 计数键（对齐 HR ai_exam_service 的 config 键名；HR 实键
# 为 fill_blank_count，开发规格 §5.5 行文写作 fill_count——两键兼容，避免
# 按规格文档调用的请求落空）
_EXAM_COUNT_KEYS = {
    "choice_questions": ("choice_count",),
    "true_false_questions": ("true_false_count",),
    "multi_choice_questions": ("multi_choice_count",),
    "fill_blank_questions": ("fill_blank_count", "fill_count"),
}


def resolve_exam_counts(config: dict | None) -> dict[str, int]:
    """config → 各题型期望数量（负数归零；非法值回退默认）。"""
    counts: dict[str, int] = {}
    for question_key, count_keys in _EXAM_COUNT_KEYS.items():
        raw = None
        for count_key in count_keys:
            if config and count_key in config:
                raw = config[count_key]
                break
        if raw is None:
            raw = EXAM_CONFIG_DEFAULTS[count_keys[0]]
        try:
            counts[question_key] = max(0, int(raw))
        except (TypeError, ValueError):
            counts[question_key] = EXAM_CONFIG_DEFAULTS[count_keys[0]]
    return counts


def build_exam_user_prompt(*, material: str, config: dict | None = None) -> str:
    """按 §5.5 拼装句式动态构建 user prompt（f-string 拼装，仅含数量>0 的题型）。

    注意 expected_keys 也只列数量>0 的题型键——chat_parsed 对缺失键直接抛错
    （platform/integrations/ai/client.py），把缺省题型列进去会让默认路径必失败。
    """
    counts = resolve_exam_counts(config)
    reqs = [
        template.format(n=counts[key])
        for key, template in _EXAM_REQ_TEMPLATES.items()
        if counts[key] > 0
    ]
    skeleton = [
        _EXAM_SKELETON_FRAGMENTS[key]
        for key in _EXAM_SKELETON_FRAGMENTS
        if counts[key] > 0
    ]
    if not reqs:
        raise ValueError("试卷题型配置全为 0，无法生成试卷")
    return (
        f"请根据以下材料生成试卷：{'; '.join(reqs)}。\n\n"
        f"输出格式：{{ {', '.join(skeleton)} }}\n\n"
        f"材料：\n{material}"
    )
