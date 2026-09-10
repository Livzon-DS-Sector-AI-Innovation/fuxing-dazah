"""工具按需加载 —— 按用户意图动态选择工具子集，减少 tool definitions 开销。

# DEPRECATED: S4 prompt 分节组装后，tool_catalog 节提示模型可见工具，不再需要关键词选子集。保留兼容期。
现状：18 个工具全量注册，每轮 ~3,500 tokens 的固定 tool definitions 开销。
优化后：平均 5-7 个工具，~1,200 tokens。关键词匹配零 AI 调用开销。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── 工具分组（工具名列表）─────────────────────────────────────────
# 必须与 registry.py 中的 TOOL_KIND 保持一致

TOOL_GROUPS: dict[str, list[str]] = {
    "hazard": [
        "query_hazards", "query_hazard_stats",
    ],
    "knowledge": [
        "knowledge_search", "web_search", "query_latest_regulations",
    ],
    "contractor_admission": ["query_contractor_admissions"],
    "drill": [
        "query_drill_plans", "query_drill_records",
        "generate_drill_plan", "sync_drill_plan_to_feishu",
    ],
    "audit": ["query_ai_audits"],
    "daily_report": [
        "generate_daily_report",
        "office_create_docx",
    ],
    "fire_alarm": [
        "query_fire_alarms",
        "generate_fire_alarm_daily_report", "generate_fire_alarm_weekly_report",
    ],
    "central_alarm": [
        "query_central_alarms",
        "generate_central_alarm_daily_report",
    ],
    "cert_warning": [
        "query_cert_warnings",
        "renew_person_certificate",
    ],
    "oh": [
        "query_oh_persons", "query_oh_exams", "query_oh_positions",
        "query_oh_hazard_factors", "query_oh_followups", "query_oh_applications",
        "query_oh_hazard_enums",
        "trigger_oh_exam_parse", "create_oh_followup", "close_oh_followup",
        "analyze_oh_transfer", "override_oh_conclusion",
    ],
    "msds": [
        "query_msds_documents", "query_msds_collections",
    ],
    "office": [
        "office_search_files", "office_read_docx", "office_read_sheet",
        "office_read_base", "office_read_drive_file",
    ],
    "urs": [
        "query_urs_records", "query_urs_review_detail",
        "create_urs_review", "parse_urs_document", "run_urs_assessment",
        "update_urs_item", "confirm_urs_assessment", "submit_urs_appeal",
    ],
    "chemical_inventory": [
        "query_chemical_inventory", "analyze_chemical_risk",
    ],
    "guardian_subsidy": [
        "preview_guardian_subsidy", "generate_guardian_subsidy",
    ],
    # 已同步本地库的明细查询
    "special_op": ["query_special_op_records"],
    "key_risk_op": ["query_key_risk_ops"],
    "ehs_change": ["query_ehs_changes"],
    "work_ticket": ["query_work_ticket_reviews"],
    "hazard_id": ["query_hazard_identifications"],
}

# ── 意图关键词（中文）─────────────────────────────────────────────

INTENT_KEYWORDS: dict[str, list[str]] = {
    "hazard": [
        "隐患", "整改", "缺陷", "堵头", "泄漏", "防爆",
        "危险源", "风险", "关闭",
    ],
    "knowledge": [
        "法规", "标准", "规范", "条款", "规定", "制度",
        "GB", "AQ", "HG", "SH", "TSG", "GB/T", "AQ/T",
    ],
    "contractor_admission": ["准入", "承包商", "相关方", "劳务派遣", "外包单位"],
    "drill": ["演练", "应急", "预案", "逃生", "疏散"],
    "audit": ["审计", "AI调用", "token", "调用记录"],
    "daily_report": ["日报", "报表", "特殊作业", "次日预警", "计划外", "17点", "17点日报"],
    "fire_alarm": ["消防报警", "消防", "火警", "报警器"],
    "central_alarm": ["中控报警", "中控", "报警记录"],
    "cert_warning": ["持证", "证书", "换证", "复审", "资质到期", "证件到期"],
    "oh": ["职业健康", "体检", "随访", "职业病", "岗位危害", "转岗", "离岗"],
    "msds": ["MSDS", "化学品安全技术说明", "安全数据单"],
    "office": [
        "文档", "云文档", "docx", "表格", "电子表格", "sheet",
        "多维表格", "base", "幻灯片", "slides", "知识库", "wiki",
        "上传", "文件", "下载", "管理制度", "制度",
    ],
    "urs": ["URS", "用户需求", "设备采购", "采购评审", "智能审核", "适用性评估", "风险画像", "采购审核"],
    "chemical_inventory": ["危化品", "库存", "超量", "混存", "禁忌", "易制毒", "易制爆", "现场物料总量", "化学品"],
    "guardian_subsidy": [
        "监护人补贴", "监护补贴", "特殊作业补贴", "作业票补贴", "补贴",
    ],
    # 已同步本地库的明细查询（"特殊作业"同时命中 daily_report 组，两组工具合并激活）
    "special_op": [
        "作业判定", "特殊作业记录", "特殊作业明细", "动火作业", "受限空间",
        "高处作业", "吊装", "临时用电", "盲板", "动土", "断路", "计划外作业",
    ],
    "key_risk_op": ["关键风险作业", "关键作业"],
    "ehs_change": ["EHS变更", "EHS 变更", "变更管理", "变更台账"],
    "work_ticket": ["作业票审核", "作业票违规", "作业票", "票审核", "违规"],
    "hazard_id": ["危险源辨识", "辨识记录", "LEC", "JHA"],
}

# ── 始终激活的工具（基础能力，任何意图都带）────────────────────
_ALWAYS_INCLUDE = {"knowledge_search"}


def select_tool_names(user_message: str) -> list[str]:
    """根据用户消息意图返回推荐的活跃工具名列表。

    规则：
    1. 关键词匹配 → 按 INTENT_KEYWORDS 打分
    2. 始终包含 knowledge_search（基础能力）
    3. 无匹配时返回 None（调用方使用全量工具作为回退）

    Returns:
        工具名列表；空列表或匹配数为 0 时返回 None（表示全量回退）。
    """
    if not user_message or not user_message.strip():
        return None

    # 纯办公链接/token 交给 executor 全量回退，不做关键词收窄
    if has_office_reference(user_message):
        logger.debug("tool_selector: office link/token → fallback to all tools")
        return None

    msg_lower = user_message.lower()
    matched: set[str] = set()

    for group, keywords in INTENT_KEYWORDS.items():
        if any(kw.lower() in msg_lower for kw in keywords):
            matched.add(group)

    if not matched:
        logger.debug("tool_selector: no intent matched → fallback to all tools")
        return None

    # 收拢工具名
    tool_names: set[str] = set(_ALWAYS_INCLUDE)
    for g in matched:
        tool_names.update(TOOL_GROUPS.get(g, []))

    result = sorted(tool_names)
    logger.debug(
        "tool_selector: matched groups=%s → %d tools: %s",
        sorted(matched), len(result), result,
    )
    return result


# ── office 链接/token 命中检测 ────────────────────────────────────
# executor 在命中飞书办公链接或显式 token 时绕过子集选择，直接使用全量 Agent，
# 避免 augment_office_query 注入的提示（含“文档/表格”等词）反而把工具收窄。

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

    命中时调用方应回退全量工具（``get_agent_for_tools(None)``），
    而不是用关键词子集把办公读写工具摘除。
    """
    if not user_message:
        return False
    return bool(
        _OFFICE_LINK_RE.search(user_message)
        or _OFFICE_TOKEN_REFERENCE_RE.search(user_message)
    )
