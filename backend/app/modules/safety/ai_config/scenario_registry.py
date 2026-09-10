"""AI 场景注册表 — 27 个 AI 调用场景的代码唯一事实源（backend-design §2）。

本文件是：

1. **场景元数据唯一事实源**：``_AI_SCENARIO_FUNCTIONS`` 从二期
   ``service/ai_config.py`` 迁入本文件（防 service↔ai_config 双向 import），
   ``SCENARIO_REGISTRY``（scenario -> ScenarioInfo）由它单向构造，禁止手抄口径；
2. **运行时 fallback 来源**：DB 缺行 = 默认开启（``enabled=True``、
   ``model_profile=None`` 按 model_type 派生），未注册场景默认放行。

绑定白名单按 **model_type** 推导：text → {text, text_backup}、vision → {vision}；
但 ``embedding``/``rerank`` 在 ``_AI_SCENARIO_FUNCTIONS`` 里 model_type 记为
``"text"``（实际是固定 pipeline），必须在注册数据里显式**覆写**
``allowed_profiles=("embedding",)/("rerank",)``（否则白名单会误导出
text/text_backup）。``default_profile`` = 白名单首元素。

``drill_report_generation`` 已废弃（``deprecated=True``），保留可配。

本模块零副作用导入（不 import service/、knowledge/、feishu/、models），
migration 与断言测试可安全引用。
"""

from __future__ import annotations

from dataclasses import dataclass

# 场景 id → (中文标签, 一句话说明, model_type, channel)
# 标签对照前端 src/types/safety/ai-audit.ts 的 AI_AUDIT_SCENARIO_LABELS；
# model_type 默认 text，视觉类（法规/报告扫描件 OCR 等）标 vision；
# channel 为业务域合理取值，不一定与真实触发链路完全一致。
# 兼容层：service/ai_config.py 从此 re-export（外部 import 契约不变）。
_AI_SCENARIO_FUNCTIONS: dict[str, tuple[str, str, str, str]] = {
    "hazard_identification": ("隐患识别", "隐患登记后 AI 识别、分类并给出整改建议", "text", "mixed"),
    "hazard_id_bitable": ("危险源辨识", "危险源辨识 Bitable 事件流驱动的 7 步 AI 辨识", "text", "feishu"),
    "rectification_review": ("整改初审", "隐患整改方案与证据的 AI 初审", "text", "mixed"),
    "agent_chat": ("助手对话", "安全 AI 助手多轮对话", "text", "feishu"),
    "knowledge_chat": ("知识库问答", "安全法规知识库自然语言问答", "text", "web"),
    "graph_build": ("图谱构建", "法规/知识库实体关系图谱构建", "text", "system"),
    "regulation_crawl": ("法规筛选", "外部法规/标准抓取后的 AI 筛选归并", "text", "system"),
    "drill_plan_generation": ("演练预案生成", "应急演练标准化预案 AI 生成", "text", "mixed"),
    "drill_report_generation": ("演练报告生成", "演练报告 AI 生成（已废弃，保留兼容）", "text", "system"),
    "drill_issue_parsing": ("演练问题解析", "演练记录问题项 AI 解析", "text", "feishu"),
    "drill_plan_parsing": ("演练计划解析", "演练计划字段 AI 解析", "text", "feishu"),
    "drill_eval_parsing": ("演练评估解析", "演练评估结论 AI 解析（旧人工链路，已废弃，保留兼容）", "text", "feishu"),
    "drill_eval_generation": ("演练评估表生成", "演练评估表 docx AI 自动生成", "text", "mixed"),
    "embedding": ("向量嵌入", "知识库文本向量化嵌入", "text", "system"),
    "rerank": ("相关性重排", "RAG 检索结果相关性重排", "text", "system"),
    "memory_extraction": ("记忆提取", "Agent 长期记忆抽取", "text", "system"),
    "daily_report_analysis": ("日报AI分析", "特殊作业日报风险与次日预警 AI 分析", "text", "system"),
    "ehs_change_review": ("EHS变更审核", "EHS 变更合规性 AI 审核", "text", "mixed"),
    "contractor_admission_review": ("相关方准入审核", "承包商/相关方准入 AI 审核", "text", "mixed"),
    "urs_review": ("URS 智能审核", "设备采购 URS AI 合规审核", "text", "web"),
    "msds_extraction": ("MSDS提取", "危化品 MSDS 关键信息 AI 提取", "text", "mixed"),
    "sop_generation": ("操规AI补全", "安全操作规程 AI 编制补全", "text", "web"),
    "sop_review": ("操规AI审核", "安全操作规程 AI 审核校验", "text", "web"),
    "regulation_ocr": ("法规扫描件OCR", "法规/标准扫描件视觉 OCR 还原全文", "vision", "system"),
    "oh_exam_report_parsing": ("体检AI解析", "职业健康体检报告 AI 解析（指标/结论/适配判定）", "vision", "feishu"),
    "oh_transfer_hazard_diff": ("转岗危害差异", "转岗/离岗前后危害因素差异 AI 分析", "text", "feishu"),
    "fire_alarm_analysis": ("消防报警分析", "消防报警逐条/日报/周报 AI 汇总分析", "text", "system"),
    "central_alarm_analysis": ("中控报警分析", "中控报警逐条/日报 AI 汇总分析", "text", "system"),
}

# 已废弃但保留可配的场景（deprecated=True）；其余均为 False
_DEPRECATED_SCENARIOS: frozenset[str] = frozenset({"drill_report_generation", "drill_eval_parsing"})

# 内部管道场景：model_type 记为 "text"，但绑定白名单为固定各自 profile
# （不允许绑定其它，运行时校验）——显式覆写派生规则
_ALLOWED_PROFILES_OVERRIDES: dict[str, tuple[str, ...]] = {
    "embedding": ("embedding",),
    "rerank": ("rerank",),
}

SCENARIO_UNKNOWN = "unknown"

# model_type 文本值（embedding/rerank 在 dict 中为 "text"，由覆写字段兜住）
ModelType = str


@dataclass(frozen=True)
class ScenarioInfo:
    """单个 AI 调用场景（scenario 是稳定 key，DB 只能改值不能新增场景）。

    ``allowed_profiles`` 为 None 时由 ``model_type`` 派生（text→{text,text_backup}、
    vision→{vision}）；embedding/rerank 在注册数据里显式覆写为各自固定 profile。
    """

    scenario: str
    label: str                       # 中文标签（如 隐患识别）
    description: str                 # 一句话说明（原 tuple[1]）
    model_type: ModelType            # text / vision（embedding/rerank 按特例覆写）
    channel: str                     # web / feishu / system / mixed
    deprecated: bool = False         # drill_report_generation=True（已废弃，保留可配）
    allowed_profiles: tuple[str, ...] | None = None  # None → 由 model_type 派生


def _derive_allowed_profiles(model_type: str) -> tuple[str, ...]:
    """按 model_type 派生绑定白名单（不含 embedding/rerank 特例，它们有显式覆写）。"""
    if model_type == "vision":
        return ("vision",)
    return ("text", "text_backup")


# ── 注册数据构造（单向导出自 _AI_SCENARIO_FUNCTIONS，禁止手抄口径） ──
_SCENARIO_DEPRECATED = _DEPRECATED_SCENARIOS

_SCENARIO_INFOS: tuple[ScenarioInfo, ...] = tuple(
    ScenarioInfo(
        scenario=sid,
        label=label,
        description=description,
        model_type=model_type,
        channel=channel,
        deprecated=sid in _SCENARIO_DEPRECATED,
        allowed_profiles=_ALLOWED_PROFILES_OVERRIDES.get(sid),
    )
    for sid, (label, description, model_type, channel) in _AI_SCENARIO_FUNCTIONS.items()
)

SCENARIO_REGISTRY: dict[str, ScenarioInfo] = {s.scenario: s for s in _SCENARIO_INFOS}

# 构造断言：scenario 唯一 / 不含 "unknown" / deprecated 集合与预置一致 /
# 白名单非空且 default（首元素）∈ 白名单
assert len(SCENARIO_REGISTRY) == len(_SCENARIO_INFOS), "AI 场景注册表存在重复 scenario"
assert SCENARIO_UNKNOWN not in SCENARIO_REGISTRY, (
    f"SCENARIO_UNKNOWN（{SCENARIO_UNKNOWN}）不得注册进场景注册表"
)
assert {s.scenario for s in _SCENARIO_INFOS if s.deprecated} == set(_SCENARIO_DEPRECATED), (
    "deprecated 场景集合与预置不一致"
)
for _info in _SCENARIO_INFOS:
    _allowed = (
        _info.allowed_profiles
        if _info.allowed_profiles is not None
        else _derive_allowed_profiles(_info.model_type)
    )
    assert len(_allowed) > 0, f"AI 场景 {_info.scenario} 白名单为空"
    assert _info.scenario not in _ALLOWED_PROFILES_OVERRIDES or _info.allowed_profiles is not None, (
        f"AI 场景 {_info.scenario} 缺少白名单覆写"
    )


def get_scenario(scenario: str) -> ScenarioInfo | None:
    """未知场景返回 None（不抛）；熔断层据此默认放行。"""
    return SCENARIO_REGISTRY.get(scenario)


def get_scenario_info(scenario: str) -> ScenarioInfo:
    """未知场景抛 ValueError（消息以「未知场景」开头，与 scheduler 404 惯例一致）。"""
    info = SCENARIO_REGISTRY.get(scenario)
    if info is None:
        raise ValueError(f"未知场景: {scenario}")
    return info


def iter_scenarios() -> tuple[ScenarioInfo, ...]:
    """遍历全部注册场景（含 deprecated），供全量视图/断言测试。"""
    return _SCENARIO_INFOS


def allowed_profiles_for(scenario: str) -> tuple[str, ...]:
    """某场景绑定白名单（写路径校验 + 前端下拉来源）。

    派生规则：``model_type=text`` → ("text","text_backup")；``vision`` →
    ("vision",)；embedding/rerank 走注册表显式覆写（固定各自 profile）。
    """
    info = get_scenario_info(scenario)
    if info.allowed_profiles is not None:
        return info.allowed_profiles
    return _derive_allowed_profiles(info.model_type)


def default_profile_for(scenario: str) -> str:
    """某场景默认生效 profile（绑定 null 时 = 白名单首元素）。

    text → text、vision → vision、embedding → embedding、rerank → rerank。
    """
    return allowed_profiles_for(scenario)[0]


__all__ = [
    "SCENARIO_REGISTRY",
    "SCENARIO_UNKNOWN",
    "ScenarioInfo",
    "_AI_SCENARIO_FUNCTIONS",
    "get_scenario",
    "get_scenario_info",
    "iter_scenarios",
    "allowed_profiles_for",
    "default_profile_for",
]
