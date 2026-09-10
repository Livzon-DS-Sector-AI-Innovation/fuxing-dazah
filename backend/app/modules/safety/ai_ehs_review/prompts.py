"""AI EHS 变更审核 — 提示词。

前缀缓存友好：SYSTEM_PROMPT 固定不变（纯指令/角色定义），
所有动态内容（变更数据、知识库法规片段）放在 user 消息末尾。
"""

# ═══════════════════════════════════════════════════════════════
# System prompt（固定，不注入任何变量 → 前缀缓存命中）
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一名资深的化工制药企业 EHS（环境、健康、安全）变更管理审核专家，依据 T/CCSAS 007-2020《化工企业变更管理实施规范》及国家相关安全生产法规，对变更申请进行专业审核（变更实施涉及特殊作业时，同时依据 GB 30871-2022《危险化学品企业特殊作业安全规范》）。

你的任务：对变更申请从以下 4 个维度逐一审核，每个维度输出「结论」和「审核报告」：

1. **申请变更原因**（reason）：变更的原因是否充分、合理、必要；是否真实反映了需解决的问题或安全风险。
2. **变更计划内容**（plan）：变更实施计划是否完整、具体、可执行；是否包含实施步骤、时间安排、责任人、资源保障；是否涉及工艺/设备/管理变更的具体描述。
3. **预计效果**（effect）：变更预期效果是否明确、可衡量；是否与变更原因对应；是否考虑了潜在副作用或风险。
4. **变更风险评估及建议措施**（risk）：是否识别了合规性、工艺、设备设施、管理四类风险；风险分析是否充分；控制措施是否具体、可操作、有责任人。

每个维度的「结论」必须是以下三者之一（严格使用，不要加标点或解释）：
- **审核通过**：内容充分、合规、可执行，无需补充。
- **需补充完善**：存在缺失项或不清晰处，但无重大安全风险，需补充后通过。
- **审核不通过**：存在重大安全合规风险，或内容严重缺失导致无法评估。

(结论三选一：审核通过/需补充完善/审核不通过)字段为空或信息不足时，结论为「需补充完善」并在报告中说明缺失信息。

「审核报告」用中文撰写，简明扼要：指出问题点、缺失项、具体改进建议（2-5 条）。若审核通过，简要说明判断依据。

最后输出「pre_review」：AI 预审意见，对变更整体做一句话总评，说明是否具备实施条件、是否需要补充材料。

可参考下方「参考法规」片段作为审核依据（仅参考，不要逐条引用）：
- 若参考法规为空，则依据你的专业知识审核。
- 审核要客观、从严，宁缺毋滥，安全底线不可放松。"""


# ═══════════════════════════════════════════════════════════════
# Few-shot 示例（仅供参考格式，占位说明「示例仅示范格式」）
# ═══════════════════════════════════════════════════════════════

FEWSHOT_EXAMPLES = [
    {
        "scenario": "审核通过（四维度完整示例）",
        "input": {
            "change_no": "MOC-2026-001",
            "title": "新增原料干燥工序",
            "reason_text": "现有产能不足，新增干燥工序提高产量",
            "plan_text": "分阶段实施：设备安装、调试、验证",
            "effect_text": "产量提升 20%",
            "risk_text": "已识别粉尘风险，配置防爆除尘与静电接地",
        },
        "output": {
            "reason": {"conclusion": "审核通过", "report": "变更原因充分合理，与产能需求对应"},
            "plan": {"conclusion": "审核通过", "report": "计划完整，含步骤/时间/责任人"},
            "effect": {"conclusion": "审核通过", "report": "效果可衡量，与原因对应"},
            "risk": {"conclusion": "审核通过", "report": "四类风险均已识别并有对应控制措施"},
            "pre_review": "具备实施条件，建议按计划推进",
        },
    },
    {
        "scenario": "需补充完善（四维度完整示例）",
        "input": {
            "change_no": "MOC-2026-002",
            "title": "反应釜搅拌器改造",
            "reason_text": "设备老化",
            "plan_text": "（未填写）",
            "effect_text": "（未填写）",
            "risk_text": "描述了机械风险，未涉及工艺安全",
        },
        "output": {
            "reason": {"conclusion": "需补充完善", "report": "原因较笼统，未说明老化对安全的具体影响"},
            "plan": {"conclusion": "需补充完善", "report": "计划缺失，需补充实施步骤/时间/责任人"},
            "effect": {"conclusion": "需补充完善", "report": "变更效果未填写，需说明预期效果"},
            "risk": {"conclusion": "需补充完善", "report": "仅识别机械风险，需补充工艺/设备/管理风险"},
            "pre_review": "暂不具备实施条件，需补齐计划与风险评估后复审",
        },
    },
    {
        "scenario": "审核不通过（四维度完整示例）",
        "input": {
            "change_no": "MOC-2026-003",
            "title": "危险化学品管线变更",
            "reason_text": "更换为更便宜的管线材质",
            "plan_text": "直接更换管线，无风险评估",
            "effect_text": "降低成本",
            "risk_text": "（未填写）",
        },
        "output": {
            "reason": {"conclusion": "审核不通过", "report": "变更原因以降低成本为主，未体现安全必要性"},
            "plan": {"conclusion": "审核不通过", "report": "未评估材质变更对化学品相容性与泄漏风险的影响"},
            "effect": {"conclusion": "审核不通过", "report": "预期效果未评估潜在安全副作用"},
            "risk": {"conclusion": "审核不通过", "report": "风险内容缺失，涉危险化学品变更无评估，存在重大安全风险"},
            "pre_review": "不通过，需补充风险分析与合规评估后重新提交",
        },
    },
]


# ═══════════════════════════════════════════════════════════════
# User prompt 构造（动态数据放尾部）
# ═══════════════════════════════════════════════════════════════


def build_user_prompt(
    *,
    change_no: str | None,
    title: str,
    reason_text: str,
    plan_text: str,
    effect_text: str,
    risk_text: str,
    change_type: str | None = None,
    change_grade: str | None = None,
    department: str | None = None,
    knowledge_md: str = "",
    include_fewshot: bool = True,
) -> str:
    """构建 user 消息：固定指令在前，变更数据与知识库在后。"""
    parts: list[str] = [
        "请对以下 EHS 变更申请进行 4 维度审核，严格按 JSON 输出 "
        "{\"reason\": {\"conclusion\": ..., \"report\": ...}, \"plan\": {...}, "
        "\"effect\": {...}, \"risk\": {...}, \"pre_review\": \"...\"}：",
        "",
    ]

    parts.append(f"变更编号：{change_no or '-'}")
    parts.append(f"变更标题：{title}")
    parts.append(f"变更类型：{change_type or '未提供'}")
    parts.append(f"变更等级：{change_grade or '未提供'}")
    parts.append(f"责任部门：{department or '未提供'}")
    parts.append("")

    parts.append("【申请变更原因】")
    parts.append(reason_text or "（未填写）")
    parts.append("")
    parts.append("【变更计划内容】")
    parts.append(plan_text or "（未填写）")
    parts.append("")
    parts.append("【预计效果】")
    parts.append(effect_text or "（未填写）")
    parts.append("")
    parts.append("【变更风险评估及建议措施】")
    parts.append(risk_text or "（未填写）")
    parts.append("")

    if knowledge_md:
        parts.append("【参考法规】")
        parts.append(knowledge_md)
        parts.append("")

    if include_fewshot:
        parts.append("【参考示例】（示例仅示范输出格式，不代表本次审核结论）")
        for i, ex in enumerate(FEWSHOT_EXAMPLES, 1):
            parts.append(f"—— 示例{i}：{ex['scenario']} ——")
            parts.append(f"变更编号：{ex['input']['change_no']}")
            parts.append(f"变更标题：{ex['input']['title']}")
            parts.append(f"输出：{ex['output']}")
        parts.append("")

    return "\n".join(parts)
