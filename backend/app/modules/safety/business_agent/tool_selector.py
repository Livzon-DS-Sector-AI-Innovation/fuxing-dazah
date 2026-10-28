"""工具按需加载 —— 按用户意图动态选择工具子集，减少 tool definitions 开销。

1-C 后口径：名册 67 个工具 = 常驻 37（registry.RESIDENT_TOOLS，默认 Agent 注册面）
+ 按需 30（urs/ops/office 低频写/证照/相关方/明细查询等，域命中时挂载）。
关键词命中 → 「核心兜底 + 命中域工具集」；未命中由调用方决定兜底（1-D：核心 15，
不再回退全量）。全量 schema 参考 scripts/measure_tool_schema.py 实测（88.7KB 基线）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── 工具分组（工具名列表）─────────────────────────────────────────
# 必须与 registry.py 中的 TOOL_KIND 保持一致

TOOL_GROUPS: dict[str, list[str]] = {
    "hazard": [
        "query_hazards", "query_hazard_stats",
        # 隐患直读模式：督办通报（只读生成 / 推群）。轮询触发收 ops 运维域（拍板②）。
        "generate_supervision_bulletin", "send_hazard_supervision_bulletin",
        # 1-D 域收敛：危险源辨识并入隐患域
        "query_hazard_identifications",
    ],
    "knowledge": [
        "knowledge_search", "web_search", "query_latest_regulations",
        "run_regulation_ai_review",
        # 2-B：技能加载通用工具归知识域（常驻只读，SOP 按需注入）
        "load_skill",
    ],
    "contractor_admission": ["query_contractor_admissions"],
    # 3.x 平台关联 F1：在册人员副台账 + 岗位字典（按需，常驻不动）
    "contractor_workers": ["query_contractor_workers", "query_org_posts"],
    "drill": [
        "query_drills",
        "generate_drill_plan", "sync_drill_plan_to_feishu",
    ],
    "ops": [
        # 运维域（按需，拍板②④）：隐患轮询补跑 + 管理调试查询（Web 后台均有页面）
        "poll_hazard_ai_analysis", "poll_hazard_rectification_review",
        "query_ai_audits",
        "query_ai_config", "query_bitable_config", "query_scheduler_tasks",
        "query_regulation_crawl_status",
    ],

    "alarm": [
        # 1-D 域收敛：消防+中控报警合一域（生成工具 1-C 已合一）
        "query_fire_alarms", "query_central_alarms",
        "generate_alarm_report",
    ],
    "cert_warning": [
        "query_cert_warnings",
        "renew_person_certificate",
    ],
    "oh": [
        "query_oh_persons", "query_oh_exams", "query_oh",
        "trigger_oh_exam_parse", "create_oh_followup", "close_oh_followup",
        "analyze_oh_transfer", "override_oh_conclusion",
    ],
    "chemical": [
        # 1-D 域收敛：危化品库存+MSDS 台账合一域
        "query_chemical_inventory", "analyze_chemical_risk", "query_msds",
        # 写《危险品日报表》数量（确认流；admin/dept_leader 才有权限）
        "update_chemical_inventory",
        # agent-query-p1：库存趋势派生面
        "query_chemical_trend",
    ],
    "office": [
        "office_search_files", "office_read_docx", "office_read_sheet",
        "office_read_base", "office_read_drive_file",
        # 写工具一并入组：用户「把结果导出成表格/文档」这类话里没有链接或 token，
        # 走不到 has_office_reference 全量回退，缺了它们同样会出现「未挂载」。
        "office_create_docx", "office_create_sheet", "office_write_sheet",
        "office_create_base", "office_create_slides", "office_generate_docx_pdf",
        "office_upload_file", "office_set_permission", "rollback_office_file",
    ],
    "urs": [
        "query_urs_records", "query_urs_review_detail",
        "create_urs_review", "parse_urs_document", "run_urs_assessment",
        "update_urs_item", "confirm_urs_assessment", "submit_urs_appeal",
        "generate_urs_report_pdf",
        # 2-D 委派元工具归 urs 域（开 SAFETY_AGENT_URS_DELEGATION 时路由改挂
        # 「核心集 + delegate」，9 个域工具由域子 Agent 持有）
        "delegate",
    ],
    "guardian_subsidy": [
        "preview_guardian_subsidy", "generate_guardian_subsidy",
    ],
    # 特殊作业域（1-D 收敛：日报/明细/关键作业合一——日报即特殊作业日报）
    "special_op": [
        "query_special_op_records", "query_key_risk_ops",
        "generate_daily_report", "office_create_docx",
    ],
    # 仓储查询域（2-E 消费侧：跨模块查库存/物料/流水/报表，按需挂载）
    "warehouse": [
        "query_stock", "query_material",
        "query_movements", "query_report",
    ],
    "ehs_change": ["query_ehs_changes"],
    # S1 体系标准核查（2026-10-21）：标准×运行数据四态判定
    "standard_check": ["query_standard_compliance"],
    "work_ticket": ["query_work_ticket_reviews", "screen_work_ticket_personnel"],
    # 遥测域（agent-query-p1：特种设备最新读数/报警，按需挂载）
    "telemetry": ["query_telemetry_latest", "query_telemetry_alarms"],
    # 设施管理域（agent-query-p1：三台账/校验任务/灭火器点检，按需挂载）
    "facilities": [
        "query_facility_ledgers", "query_facility_tasks",
        "query_facility_inspections",
    ],
    # 培训与行为管控域（agent-query-p1：违章档案/培训/草案/复训，按需挂载）
    "training": ["query_training_behavior"],
    # 外来人员保险域（agent-query-p1：预报备+三类保险预警，按需挂载）
    "visitor_insurance": ["query_visitor_insurance"],
    # 总览聚合域（agent-query-p1：驾驶舱 KPI 一句话总览，按需挂载）
    "overview": ["query_overview"],
}

# ── 意图关键词（中文）─────────────────────────────────────────────

INTENT_KEYWORDS: dict[str, list[str]] = {
    "standard_check": [
        "标准", "达标", "符合性", "绩效", "核查",
        "目标责任", "体系运行", "演练做了",
    ],
    "hazard": [
        "隐患", "整改", "缺陷", "堵头", "泄漏", "防爆",
        "危险源", "风险", "关闭",
        # 「督办通报」本身不含「隐患」二字，必须单独给词，否则这类问法收不到工具
        "督办", "通报",
        # 1-D 域收敛：危险源辨识关键词并入
        "辨识记录", "LEC", "JHA",
    ],
    "knowledge": [
        "法规", "标准", "规范", "条款", "规定", "制度",
        "GB", "AQ", "HG", "SH", "TSG", "GB/T", "AQ/T",
        "操规", "操作规程",
    ],
    "contractor_admission": ["准入", "承包商", "相关方", "劳务派遣", "外包单位"],
    "contractor_workers": [
        "在册", "花名册", "实名", "在场人员", "在厂人员", "外包",
        "岗位字典", "有哪些岗位", "岗位有哪些", "厂里岗位",
    ],
    "drill": ["演练", "应急", "预案", "逃生", "疏散"],
    "ops": [
        "审计", "AI调用", "token", "调用记录",
        "AI配置", "模型配置", "多维表格配置", "定时任务", "调度", "后台任务",
        # 轮询补跑（拍板②）：「轮询一下隐患AI分析」等话术命中 ops 而非仅 hazard
        "轮询", "补跑", "补上", "补一下", "采集状态", "采集监控",
    ],
    "alarm": ["消防报警", "消防", "火警", "报警器", "中控报警", "中控", "报警记录"],
    "cert_warning": ["持证", "证书", "换证", "复审", "资质到期", "证件到期"],
    "oh": ["职业健康", "体检", "随访", "职业病", "岗位危害", "接触危害", "职业危害", "危害因素", "转岗", "离岗"],

    "office": [
        "文档", "云文档", "docx", "表格", "电子表格", "sheet",
        "多维表格", "base", "幻灯片", "slides", "知识库", "wiki",
        "上传", "文件", "下载", "管理制度", "制度",
    ],
    "urs": ["URS", "用户需求", "设备采购", "采购评审", "智能审核", "适用性评估", "风险画像", "采购审核"],
    "chemical": [
        "危化品", "库存", "超量", "混存", "禁忌", "易制毒", "易制爆",
        "现场物料总量", "化学品", "MSDS", "化学品安全技术说明", "安全数据单",
        # agent-query-p1：趋势派生面
        "趋势", "环比", "异动",
    ],
    "guardian_subsidy": [
        "监护人补贴", "监护补贴", "特殊作业补贴", "作业票补贴", "补贴",
    ],
    # 特殊作业域（日报+明细+关键作业）：日报类话术直接挂 generate_daily_report
    "special_op": [
        "日报", "报表", "次日预警", "计划外", "17点", "17点日报",
        "特殊作业", "作业判定", "特殊作业记录", "特殊作业明细", "动火作业", "受限空间",
        "高处作业", "吊装", "临时用电", "盲板", "动土", "断路", "计划外作业",
        "关键风险作业", "关键作业",
    ],
    "warehouse": [
        "仓库", "仓储", "入库", "出库", "领用", "呆料", "复验期",
        "物料名称", "物料代码", "库存移动", "仓储报表",
    ],
    # agent-query-p1 补「变更」裸词：「最近有哪些变更」此前不命中规则层，
    # 掉进核心兜底 15（无 query_ehs_changes）必失败
    "ehs_change": ["EHS变更", "EHS 变更", "变更管理", "变更台账", "变更"],
    "work_ticket": [
        "作业票审核", "作业票违规", "作业票", "票审核", "违规",
        "外包人员", "承包商人员", "人员筛查", "实名",
    ],
    # 遥测域（agent-query-p1）：「特种设备报警」与设施域「特种设备台账」词面互不
    # 包含，两域同命中时多挂无害（模型按问题语义选工具）
    "telemetry": ["锅炉", "压力", "遥测", "抄表", "特种设备报警", "读数"],
    # 设施管理域（agent-query-p1）：「消防」裸词归报警域，「消防器材」才归设施
    "facilities": [
        "灭火器", "消防器材", "安全附件", "特种设备台账", "设施",
        "校验任务", "点检",
    ],
    # 培训与行为管控域（agent-query-p1）：「违规」归作业票域，「违章」归培训域
    "training": ["培训", "违章", "三违", "复训", "讲义", "课件"],
    # 外来人员保险域（agent-query-p1）
    "visitor_insurance": ["外来人员", "保险", "报备", "访客"],
    # 总览聚合域（agent-query-p1）
    "overview": ["总览", "整体情况", "概况", "安全状况"],
}

# ── 始终激活的工具（基础能力，任何意图都带）────────────────────
_ALWAYS_INCLUDE = {"knowledge_search"}


# ── 核心兜底集（1-D：置信不足/无匹配时挂载，永不回退全量）─────────
CORE_FALLBACK_TOOLS: frozenset[str] = frozenset({
    "knowledge_search", "web_search",
    "query_hazards", "query_hazard_stats",
    "query_latest_regulations", "query_special_op_records",
    "query_chemical_inventory", "query_fire_alarms", "query_central_alarms",
    "query_drills", "query_oh",
    "generate_daily_report", "generate_supervision_bulletin",
    "office_search_files", "office_read_docx",
})


@dataclass(frozen=True)
class RoutingDecision:
    """一次路由决策（写入 ai_call_audits.extra.routing 供持续调优）。"""

    tool_names: list[str]
    domains: tuple[str, ...] = ()
    path: str = "core_fallback"   # rule | embedding | office_reference | core_fallback
    confidence: float | None = None


def route_message(user_message: str | None) -> RoutingDecision:
    """两段式路由入口（规则层，同步）：快速路径 + 兜底核心 15，永不返回全量。

    - 办公链接/token → office 域工具集（不再全量回退）
    - 关键词命中 → 命中域工具集 ∪ knowledge_search
    - 无命中 → 核心兜底 15（生产链路请用 ``route_message_async``，嵌入层在此介入）
    - 任何内部异常 → 核心兜底 15（路由永不抛出、永不放大工具面）
    """
    try:
        return _route_rule(user_message)
    except Exception:
        logger.exception("route_message failed → core fallback")
        return RoutingDecision(sorted(CORE_FALLBACK_TOOLS))


async def route_message_async(user_message: str | None) -> RoutingDecision:
    """两段式路由完整入口（生产链路）：规则 → 嵌入相似度 → 核心兜底。

    规则层结果直接沿用（零嵌入成本）；规则 miss 时嵌入层分类 top 域
    （开关 SAFETY_AGENT_ROUTER_EMBEDDING，异常/低置信自动落核心兜底）。
    """
    decision = route_message(user_message)
    if decision.path != "core_fallback" or not user_message:
        return decision
    try:
        from app.modules.safety.business_agent import router_embedding

        hit = await router_embedding.classify(user_message)
    except Exception:
        logger.debug("embedding routing stage failed → keep core fallback",
                     exc_info=True)
        hit = None
    if hit is None:
        return decision
    domain, confidence = hit
    tools = sorted(_mountable_group_tools(domain) | set(_ALWAYS_INCLUDE))
    if domain == "urs" and _urs_delegation_enabled():
        # 2-D 委派式（嵌入层与规则层同口径）
        tools = sorted(_delegated_urs_tools())
    if not tools:
        return decision
    return RoutingDecision(
        tools, domains=(domain,), path="embedding", confidence=confidence,
    )


def _urs_delegation_enabled() -> bool:
    """URS 域委派试点开关（app_config，60s TTL；关 = 挂载式一键回退）。"""
    try:
        from app.modules.safety.app_config.store import store as app_config_store

        return app_config_store.get_bool("SAFETY_AGENT_URS_DELEGATION", False)
    except Exception:
        return False


def _delegated_urs_tools() -> set[str]:
    """2-D 委派式的挂载面：核心兜底集 + delegate（规则/嵌入两层共用）。"""
    return set(CORE_FALLBACK_TOOLS) | {"delegate"} | set(_ALWAYS_INCLUDE)


def _mountable_group_tools(group: str) -> set[str]:
    """域的可挂载工具集；delegate 元工具仅在委派开关开时可见（关 = 纯挂载式，
    模型看不到委派入口，一键回退干净）。"""
    tools = set(TOOL_GROUPS.get(group, []))
    if "delegate" in tools and not _urs_delegation_enabled():
        tools.discard("delegate")
    return tools


def _route_rule(user_message: str | None) -> RoutingDecision:
    if not user_message or not user_message.strip():
        return RoutingDecision(sorted(CORE_FALLBACK_TOOLS))

    # 办公链接/显式 token：挂 office 域全量读写（旧路径曾回退全量 76 工具）
    if has_office_reference(user_message):
        tools = sorted(set(TOOL_GROUPS["office"]) | set(_ALWAYS_INCLUDE))
        return RoutingDecision(
            tools, domains=("office",), path="office_reference",
        )

    msg_lower = user_message.lower()
    matched: set[str] = set()
    for group, keywords in INTENT_KEYWORDS.items():
        if any(kw.lower() in msg_lower for kw in keywords):
            matched.add(group)

    if not matched:
        # T10：此处将接入嵌入相似度层（开关 SAFETY_AGENT_ROUTER_EMBEDDING）
        return RoutingDecision(sorted(CORE_FALLBACK_TOOLS))

    tool_names: set[str] = set(_ALWAYS_INCLUDE)
    delegate_urs = "urs" in matched and _urs_delegation_enabled()
    for g in matched:
        if g == "urs" and delegate_urs:
            # 2-D 委派式：urs 域不挂 9 工具，改挂核心兜底集 + delegate
            # 元工具（域子 Agent 由 delegate 程序化运行，确认门在 orchestrator）
            tool_names |= _delegated_urs_tools()
        else:
            tool_names |= _mountable_group_tools(g)
    result = sorted(tool_names)
    logger.debug(
        "tool_selector: matched groups=%s → %d tools", sorted(matched), len(result),
    )
    return RoutingDecision(result, domains=tuple(sorted(matched)), path="rule")


def select_tool_names(user_message: str) -> list[str]:
    """兼容入口：返回路由决策的工具名列表（1-D 起永不返回 None）。"""
    return route_message(user_message).tool_names


# ── office 链接/token 命中检测 ────────────────────────────────────
# 1-D：命中时路由到 office 域工具集（14 个读写），不再回退全量 Agent。

_OFFICE_LINK_RE = re.compile(
    r"https?://[^\s<>)]+\.feishu\.cn/"
    r"(docx|docs|sheets?|base|wiki|slides|file)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_OFFICE_TOKEN_REFERENCE_RE = re.compile(
    r"(云文档|文档|电子表格|表格|多维表格|知识库|幻灯片|文件|docx|sheet|base|"
    r"wiki|slides|file)\s*(?:token|标识|id)?\s*[：:，,\s]+"
    r"(?P<token>[A-Za-z0-9_-]{6,})",
    re.IGNORECASE,
)


def has_office_reference(user_message: str) -> bool:
    """检测消息中是否包含飞书办公链接或显式文件 token。

    命中时路由挂 office 域全量读写工具（1-D：不再回退全量 Agent）。
    """
    if not user_message:
        return False
    return bool(
        _OFFICE_LINK_RE.search(user_message)
        or _OFFICE_TOKEN_REFERENCE_RE.search(user_message)
    )
