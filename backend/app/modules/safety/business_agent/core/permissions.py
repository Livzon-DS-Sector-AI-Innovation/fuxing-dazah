"""业务 Agent 权限策略（硬护栏之一）。

「数据管人、策略管权限」的拆分：
- **谁是什么角色** → 数据：``agent_user_roles`` 表（feishu_user_id → role），运维可维护。
- **每个角色能调哪些工具** → 策略：本文件的 ``ROLE_TOOL_POLICY`` 代码常量，deny-by-default。

授权在**工具执行层**强制（executor 调用工具前先 ``check``），不是提示词软约束。
agent.md 里的「能力清单」只是给模型的引导；能不能真正调用某工具，以本文件为准。

工具名必须与 ``tools/registry.py`` 中注册的工具名一致。
"""

from __future__ import annotations

# ── 角色 ─────────────────────────────────────────────────────────
ROLE_SAFETY_ADMIN = "safety_admin"  # 安全管理员：全部能力
ROLE_DEPT_LEADER = "dept_leader"  # 部门负责人：查询 + 建隐患 + 派整改
ROLE_INSPECTOR = "inspector"  # 检查人员：查询 + 建隐患
ROLE_VIEWER = "viewer"  # 只读：仅查询

# ── 工具名（与 tools/registry.py 保持一致）─────────────────────────
# 只读
TOOL_QUERY_HAZARDS = "query_hazards"
TOOL_QUERY_HAZARD_STATS = "query_hazard_stats"
TOOL_QUERY_CONTRACTOR_ADMISSIONS = "query_contractor_admissions"
TOOL_KNOWLEDGE_SEARCH = "knowledge_search"
TOOL_WEB_SEARCH = "web_search"
TOOL_QUERY_LATEST_REGULATIONS = "query_latest_regulations"
TOOL_QUERY_AI_AUDITS = "query_ai_audits"  # 审计数据含 prompt 全文，仅 safety_admin
TOOL_QUERY_AI_CONFIG = "query_ai_config"  # AI 配置（模型与场景清单，脱敏）
TOOL_QUERY_SCHEDULER_TASKS = "query_scheduler_tasks"  # 定时任务清单
TOOL_QUERY_BITABLE_CONFIG = "query_bitable_config"  # Bitable 连接/映射配置（app_token 脱敏）
TOOL_QUERY_SPECIAL_OP_RECORDS = "query_special_op_records"  # 特殊作业判定明细（本地同步库）
TOOL_QUERY_KEY_RISK_OPS = "query_key_risk_ops"  # 关键风险作业明细（本地同步库）
TOOL_QUERY_EHS_CHANGES = "query_ehs_changes"  # EHS 变更明细（本地同步库）
TOOL_QUERY_WORK_TICKET_REVIEWS = "query_work_ticket_reviews"  # 作业票审核记录与违规明细
TOOL_QUERY_HAZARD_IDENTIFICATIONS = "query_hazard_identifications"  # 危险源辨识明细
TOOL_QUERY_DRILL_PLANS = "query_drill_plans"
TOOL_QUERY_DRILL_RECORDS = "query_drill_records"
TOOL_QUERY_MSDS_DOCUMENTS = "query_msds_documents"
TOOL_QUERY_MSDS_COLLECTIONS = "query_msds_collections"
# 写入
TOOL_GENERATE_DRILL_PLAN = "generate_drill_plan"
TOOL_SYNC_DRILL_TO_FEISHU = "sync_drill_plan_to_feishu"
TOOL_GENERATE_DAILY_REPORT = "generate_daily_report"
TOOL_GENERATE_SUPERVISION_BULLETIN = "generate_supervision_bulletin"
# 隐患直读多维表格模式（轮询 AI 分析 / 轮询整改审核 / 发送督办通报）
TOOL_POLL_HAZARD_AI_ANALYSIS = "poll_hazard_ai_analysis"
TOOL_POLL_HAZARD_RECTIFICATION_REVIEW = "poll_hazard_rectification_review"
TOOL_SEND_HAZARD_SUPERVISION_BULLETIN = "send_hazard_supervision_bulletin"
# URS 智能审核
TOOL_QUERY_URS_RECORDS = "query_urs_records"
TOOL_QUERY_URS_REVIEW_DETAIL = "query_urs_review_detail"
TOOL_EXPORT_URS_PDF = "generate_urs_report_pdf"
TOOL_CREATE_URS_REVIEW = "create_urs_review"
TOOL_PARSE_URS_DOCUMENT = "parse_urs_document"
TOOL_RUN_URS_ASSESSMENT = "run_urs_assessment"
TOOL_UPDATE_URS_ITEM = "update_urs_item"
TOOL_CONFIRM_URS_ASSESSMENT = "confirm_urs_assessment"
TOOL_SUBMIT_URS_APPEAL = "submit_urs_appeal"
# 操规 AI 审核
TOOL_RUN_REGULATION_AI_REVIEW = "run_regulation_ai_review"
# 职业健康（只读）
TOOL_QUERY_OH_PERSONS = "query_oh_persons"
TOOL_QUERY_OH_EXAMS = "query_oh_exams"
TOOL_QUERY_OH_POSITIONS = "query_oh_positions"
TOOL_QUERY_OH_HAZARD_FACTORS = "query_oh_hazard_factors"
TOOL_QUERY_OH_FOLLOWUPS = "query_oh_followups"
TOOL_QUERY_OH_APPLICATIONS = "query_oh_applications"
TOOL_QUERY_OH_HAZARD_ENUMS = "query_oh_hazard_enums"
# 职业健康（写入）
TOOL_TRIGGER_OH_EXAM_PARSE = "trigger_oh_exam_parse"
TOOL_CREATE_OH_FOLLOWUP = "create_oh_followup"
TOOL_CLOSE_OH_FOLLOWUP = "close_oh_followup"
TOOL_ANALYZE_OH_TRANSFER = "analyze_oh_transfer"
TOOL_OVERRIDE_OH_CONCLUSION = (
    "override_oh_conclusion"  # 结论覆盖属合规判定，仅 safety_admin
)
# 消防报警分析
TOOL_QUERY_FIRE_ALARMS = "query_fire_alarms"
TOOL_GENERATE_FIRE_ALARM_DAILY_REPORT = "generate_fire_alarm_daily_report"
TOOL_GENERATE_FIRE_ALARM_WEEKLY_REPORT = "generate_fire_alarm_weekly_report"
# 中控报警分析
TOOL_QUERY_CENTRAL_ALARMS = "query_central_alarms"
TOOL_GENERATE_CENTRAL_ALARM_DAILY_REPORT = "generate_central_alarm_daily_report"
# 持证到期预警（只读）
TOOL_QUERY_CERT_WARNINGS = "query_cert_warnings"
# 持证到期预警（写入）
TOOL_RENEW_PERSON_CERTIFICATE = "renew_person_certificate"
# 危化品库存（只读）
TOOL_QUERY_CHEMICAL_INVENTORY = "query_chemical_inventory"
TOOL_ANALYZE_CHEMICAL_RISK = "analyze_chemical_risk"
# 监护补贴统计（平台作业票数据源；只读预览 + 写入生成，涉及持证台账/补贴金额，仅
# safety_admin 与 dept_leader——部门安环人员主场景；inspector/viewer 不授予）
TOOL_PREVIEW_GUARDIAN_SUBSIDY = "preview_guardian_subsidy"
TOOL_GENERATE_GUARDIAN_SUBSIDY = "generate_guardian_subsidy"

# ── 办公（office_*）权限点 ──────────────────────────────────────
# 只读办公工具对所有已登录角色开放；写入工具后续 ticket 再按角色矩阵填充。
TOOL_OFFICE_SEARCH_FILES = "office_search_files"
TOOL_OFFICE_READ_DOCX = "office_read_docx"
TOOL_OFFICE_READ_SHEET = "office_read_sheet"
TOOL_OFFICE_READ_BASE = "office_read_base"
TOOL_OFFICE_READ_DRIVE_FILE = "office_read_drive_file"
# 写入
TOOL_OFFICE_CREATE_DOCX = "office_create_docx"
TOOL_OFFICE_CREATE_SHEET = "office_create_sheet"
TOOL_OFFICE_WRITE_SHEET = "office_write_sheet"
TOOL_OFFICE_CREATE_BASE = "office_create_base"
TOOL_OFFICE_CREATE_SLIDES = "office_create_slides"
TOOL_OFFICE_GENERATE_DOCX_PDF = "office_generate_docx_pdf"
TOOL_OFFICE_UPLOAD_FILE = "office_upload_file"
TOOL_OFFICE_SET_PERMISSION = "office_set_permission"
TOOL_OFFICE_ROLLBACK_FILE = "rollback_office_file"

OFFICE_READ_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_OFFICE_SEARCH_FILES,
        TOOL_OFFICE_READ_DOCX,
        TOOL_OFFICE_READ_SHEET,
        TOOL_OFFICE_READ_BASE,
        TOOL_OFFICE_READ_DRIVE_FILE,
    }
)
OFFICE_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_OFFICE_CREATE_DOCX,
        TOOL_OFFICE_CREATE_SHEET,
        TOOL_OFFICE_WRITE_SHEET,
        TOOL_OFFICE_CREATE_BASE,
        TOOL_OFFICE_CREATE_SLIDES,
        TOOL_OFFICE_GENERATE_DOCX_PDF,
        TOOL_OFFICE_UPLOAD_FILE,
    }
)
# 高危办公写工具：仅 safety_admin（dept_leader 不授予）
OFFICE_DANGEROUS_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_OFFICE_SET_PERMISSION,
        TOOL_OFFICE_ROLLBACK_FILE,
    }
)

# 只读工具集合（便于按角色批量授予；不含 query_ai_audits——最小权限）
_READ_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_QUERY_HAZARDS,
        TOOL_QUERY_HAZARD_STATS,
        TOOL_QUERY_CONTRACTOR_ADMISSIONS,
        TOOL_KNOWLEDGE_SEARCH,
        TOOL_WEB_SEARCH,
        TOOL_QUERY_LATEST_REGULATIONS,
        TOOL_QUERY_AI_CONFIG,
        TOOL_QUERY_SCHEDULER_TASKS,
        TOOL_QUERY_BITABLE_CONFIG,
        TOOL_QUERY_DRILL_PLANS,
        TOOL_QUERY_DRILL_RECORDS,
        TOOL_QUERY_MSDS_DOCUMENTS,
        TOOL_QUERY_MSDS_COLLECTIONS,
        TOOL_GENERATE_DAILY_REPORT,
        TOOL_GENERATE_SUPERVISION_BULLETIN,
        TOOL_QUERY_URS_RECORDS,
        TOOL_QUERY_URS_REVIEW_DETAIL,
        TOOL_QUERY_FIRE_ALARMS,
        TOOL_QUERY_CENTRAL_ALARMS,
        TOOL_QUERY_CERT_WARNINGS,
        TOOL_QUERY_CHEMICAL_INVENTORY,
        TOOL_ANALYZE_CHEMICAL_RISK,
        TOOL_QUERY_SPECIAL_OP_RECORDS,
        TOOL_QUERY_KEY_RISK_OPS,
        TOOL_QUERY_EHS_CHANGES,
        TOOL_QUERY_WORK_TICKET_REVIEWS,
        TOOL_QUERY_HAZARD_IDENTIFICATIONS,
    }
)

# 职业健康只读工具集合（敏感健康信息，全角色可查；不含写工具）
_OH_READ_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_QUERY_OH_PERSONS,
        TOOL_QUERY_OH_EXAMS,
        TOOL_QUERY_OH_POSITIONS,
        TOOL_QUERY_OH_HAZARD_FACTORS,
        TOOL_QUERY_OH_FOLLOWUPS,
        TOOL_QUERY_OH_APPLICATIONS,
        TOOL_QUERY_OH_HAZARD_ENUMS,
    }
)

# 职业健康写工具集合（dept_leader 可触发解析/随访/转岗分析，不可覆盖 AI 结论）
_OH_WRITE_TOOLS_DEPT_LEADER: frozenset[str] = frozenset(
    {
        TOOL_TRIGGER_OH_EXAM_PARSE,
        TOOL_CREATE_OH_FOLLOWUP,
        TOOL_CLOSE_OH_FOLLOWUP,
        TOOL_ANALYZE_OH_TRANSFER,
    }
)

# 消防报警分析写工具集合（生成日报/周报：触发 AI 分析并回写记录，需用户确认；仅 admin/leader）
_FIRE_ALARM_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_GENERATE_FIRE_ALARM_DAILY_REPORT,
        TOOL_GENERATE_FIRE_ALARM_WEEKLY_REPORT,
    }
)

# 中控报警分析写工具集合（生成日报：触发 AI 分析并回写记录，需用户确认；仅 admin/leader）
_CENTRAL_ALARM_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_GENERATE_CENTRAL_ALARM_DAILY_REPORT,
    }
)

# 监护补贴工具集合（预览 + 生成；仅 admin/leader 授予）
_GUARDIAN_SUBSIDY_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_PREVIEW_GUARDIAN_SUBSIDY,
        TOOL_GENERATE_GUARDIAN_SUBSIDY,
    }
)

# 隐患直读模式：轮询工具集合（触发 AI 分析并写回多维表格，需用户确认；admin/leader）
_HAZARD_POLL_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_POLL_HAZARD_AI_ANALYSIS,
        TOOL_POLL_HAZARD_RECTIFICATION_REVIEW,
    }
)

# 隐患直读模式：督办通报推送（向群发消息，需用户确认；admin/leader）
_HAZARD_BULLETIN_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_SEND_HAZARD_SUPERVISION_BULLETIN,
    }
)

# ── 角色 → 允许工具（deny-by-default：未列出的角色/工具一律拒绝）──────
ROLE_TOOL_POLICY: dict[str, frozenset[str]] = {
    ROLE_SAFETY_ADMIN: _READ_TOOLS
    | {
        TOOL_QUERY_AI_AUDITS,
        TOOL_GENERATE_DRILL_PLAN,
        TOOL_SYNC_DRILL_TO_FEISHU,
        TOOL_EXPORT_URS_PDF,
        TOOL_CREATE_URS_REVIEW,
        TOOL_PARSE_URS_DOCUMENT,
        TOOL_RUN_URS_ASSESSMENT,
        TOOL_UPDATE_URS_ITEM,
        TOOL_CONFIRM_URS_ASSESSMENT,
        TOOL_SUBMIT_URS_APPEAL,
        TOOL_RUN_REGULATION_AI_REVIEW,
    }
    | OFFICE_READ_TOOLS
    | OFFICE_WRITE_TOOLS
    | OFFICE_DANGEROUS_TOOLS
    | _OH_READ_TOOLS
    | _OH_WRITE_TOOLS_DEPT_LEADER
    | {TOOL_OVERRIDE_OH_CONCLUSION}
    | {TOOL_RENEW_PERSON_CERTIFICATE}
    | _FIRE_ALARM_WRITE_TOOLS
    | _CENTRAL_ALARM_WRITE_TOOLS
    | _GUARDIAN_SUBSIDY_TOOLS
    | _HAZARD_POLL_WRITE_TOOLS
    | _HAZARD_BULLETIN_WRITE_TOOLS,
    ROLE_DEPT_LEADER: _READ_TOOLS
    | {
        TOOL_GENERATE_DRILL_PLAN,
        TOOL_SYNC_DRILL_TO_FEISHU,
        TOOL_EXPORT_URS_PDF,
        TOOL_CREATE_URS_REVIEW,
        TOOL_PARSE_URS_DOCUMENT,
        TOOL_UPDATE_URS_ITEM,
        TOOL_SUBMIT_URS_APPEAL,
        TOOL_RUN_REGULATION_AI_REVIEW,
    }
    | OFFICE_READ_TOOLS
    | OFFICE_WRITE_TOOLS
    | _OH_READ_TOOLS
    | _OH_WRITE_TOOLS_DEPT_LEADER
    | _FIRE_ALARM_WRITE_TOOLS
    | _CENTRAL_ALARM_WRITE_TOOLS
    | _GUARDIAN_SUBSIDY_TOOLS
    | _HAZARD_POLL_WRITE_TOOLS
    | _HAZARD_BULLETIN_WRITE_TOOLS,
    ROLE_INSPECTOR: _READ_TOOLS
    | {TOOL_CREATE_URS_REVIEW}
    | OFFICE_READ_TOOLS
    | _OH_READ_TOOLS,
    ROLE_VIEWER: _READ_TOOLS | OFFICE_READ_TOOLS | _OH_READ_TOOLS,
}

# 所有已知角色（用于校验 agent_user_roles.role 合法性）
KNOWN_ROLES: frozenset[str] = frozenset(ROLE_TOOL_POLICY.keys())


def allowed_tools(role: str | None) -> frozenset[str]:
    """返回该角色被允许调用的工具集合；未知/空角色返回空集（deny-by-default）。"""
    if not role:
        return frozenset()
    return ROLE_TOOL_POLICY.get(role, frozenset())


def check(role: str | None, tool_name: str) -> bool:
    """该角色是否被允许调用该工具。未知角色/工具一律 False。"""
    return tool_name in allowed_tools(role)
