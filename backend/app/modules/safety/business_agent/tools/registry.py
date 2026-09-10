"""工具注册表。

将所有工具按名注册，区分只读/写入。executor 据此做权限校验和确认流控制。
工具名必须与 ``permissions.py`` 中的常量一致。
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent

from app.modules.safety.business_agent.core.pipeline import execute_tool

# ── 办公（office_*）──
from app.modules.safety.business_agent.tools.office_tools import (
    office_create_base,
    office_create_docx,
    office_create_sheet,
    office_create_slides,
    office_generate_docx_pdf,
    office_read_base,
    office_read_docx,
    office_read_drive_file,
    office_read_sheet,
    office_search_files,
    office_set_permission,
    office_upload_file,
    office_write_sheet,
    rollback_office_file,
)

# ── 只读 ──
from app.modules.safety.business_agent.tools.read_tools import (
    analyze_chemical_risk,
    knowledge_search,
    query_ai_audits,
    query_ai_config,
    query_bitable_config,
    query_central_alarms,
    query_cert_warnings,
    query_chemical_inventory,
    query_contractor_admissions,
    query_drill_plans,
    query_drill_records,
    query_ehs_changes,
    query_fire_alarms,
    query_hazard_identifications,
    query_hazard_stats,
    query_hazards,
    query_key_risk_ops,
    query_latest_regulations,
    query_msds_collections,
    query_msds_documents,
    query_oh_applications,
    query_oh_exams,
    query_oh_followups,
    query_oh_hazard_enums,
    query_oh_hazard_factors,
    query_oh_persons,
    query_oh_positions,
    query_scheduler_tasks,
    query_special_op_records,
    query_work_ticket_reviews,
    web_search,
)

# ── 监护补贴统计（平台作业票数据源）──
from app.modules.safety.business_agent.tools.subsidy_tools import (
    generate_guardian_subsidy,
    preview_guardian_subsidy,
)

# ── URS 智能审核 ──
from app.modules.safety.business_agent.tools.urs_tools import (
    confirm_urs_assessment,
    create_urs_review,
    generate_urs_report_pdf,
    parse_urs_document,
    query_urs_records,
    query_urs_review_detail,
    run_urs_assessment,
    submit_urs_appeal,
    update_urs_item,
)

# ── 写入 ──
from app.modules.safety.business_agent.tools.write_tools import (
    analyze_oh_transfer,
    close_oh_followup,
    create_oh_followup,
    generate_central_alarm_daily_report,
    generate_daily_report,
    generate_drill_plan,
    generate_fire_alarm_daily_report,
    generate_fire_alarm_weekly_report,
    generate_supervision_bulletin,
    override_oh_conclusion,
    poll_hazard_ai_analysis,
    poll_hazard_rectification_review,
    renew_person_certificate,
    run_regulation_ai_review,
    send_hazard_supervision_bulletin,
    sync_drill_plan_to_feishu,
    trigger_oh_exam_parse,
)

_OFFICE_READ_FUNCS: list[Callable[..., Any]] = [
    office_search_files,
    office_read_docx,
    office_read_sheet,
    office_read_base,
    office_read_drive_file,
]
_OFFICE_WRITE_FUNCS: list[Callable[..., Any]] = [
    office_create_docx,
    office_create_sheet,
    office_write_sheet,
    office_create_base,
    office_create_slides,
    office_generate_docx_pdf,
    office_upload_file,
    office_set_permission,
    rollback_office_file,
]

logger = logging.getLogger(__name__)

# 工具名 → 是否写入（executor.py 据此决定是否需要 DeferredToolRequests 处理）
TOOL_KIND: dict[str, bool] = {
    # 只读
    "query_hazards": False,
    "query_hazard_stats": False,
    "query_central_alarms": False,
    "query_contractor_admissions": False,
    "knowledge_search": False,
    "web_search": False,
    "query_latest_regulations": False,
    "query_ai_audits": False,
    "query_ai_config": False,
    "query_bitable_config": False,
    "query_scheduler_tasks": False,
    "query_drill_plans": False,
    "query_drill_records": False,
    "query_msds_documents": False,
    "query_msds_collections": False,
    # 职业健康（只读）
    "query_oh_persons": False,
    "query_oh_exams": False,
    "query_oh_positions": False,
    "query_oh_hazard_factors": False,
    "query_oh_followups": False,
    "query_oh_applications": False,
    "query_oh_hazard_enums": False,
    # 消防报警分析（只读）
    "query_fire_alarms": False,
    # 持证到期预警（只读）
    "query_cert_warnings": False,
    # 危化品库存（只读）
    "query_chemical_inventory": False,
    "analyze_chemical_risk": False,
    # 已同步本地库的明细查询（只读）
    "query_special_op_records": False,
    "query_key_risk_ops": False,
    "query_ehs_changes": False,
    "query_work_ticket_reviews": False,
    "query_hazard_identifications": False,
    # 写入
    "generate_drill_plan": True,
    "sync_drill_plan_to_feishu": True,
    "generate_daily_report": False,
    "generate_supervision_bulletin": False,
    # URS 智能审核
    "query_urs_records": False,
    "query_urs_review_detail": False,
    # 生成 PDF 文件（写盘，需用户确认）
    "generate_urs_report_pdf": True,
    "create_urs_review": True,
    "parse_urs_document": True,
    "run_urs_assessment": True,
    "update_urs_item": True,
    "confirm_urs_assessment": True,
    "submit_urs_appeal": True,
    # 操规 AI 审核（触发后台审核，写入状态/内容，需用户确认）
    "run_regulation_ai_review": True,
    # 职业健康（写入，需用户确认）
    "trigger_oh_exam_parse": True,
    "create_oh_followup": True,
    "close_oh_followup": True,
    "analyze_oh_transfer": True,
    "override_oh_conclusion": True,
    # 持证到期预警（写入，需用户确认）
    "renew_person_certificate": True,
    # 消防报警分析（写入：触发 AI 分析，需用户确认）
    "generate_fire_alarm_daily_report": True,
    "generate_fire_alarm_weekly_report": True,
    # 中控报警分析（写入：触发 AI 分析，需用户确认）
    "generate_central_alarm_daily_report": True,
    # 隐患直读多维表格模式（写入：调用 AI 并写回多维表格 / 推群，需用户确认）
    "poll_hazard_ai_analysis": True,
    "poll_hazard_rectification_review": True,
    "send_hazard_supervision_bulletin": True,
    # 监护补贴统计（只读：预览；写入：生成 Excel 并回传文件，需用户确认）
    "preview_guardian_subsidy": False,
    "generate_guardian_subsidy": True,
    # ── 办公（office_*）：只读 ──
    "office_search_files": False,
    "office_read_docx": False,
    "office_read_sheet": False,
    "office_read_base": False,
    "office_read_drive_file": False,
    # ── 办公（office_*）：写入（走 DeferredToolRequests 人审）──
    "office_create_docx": True,
    "office_create_sheet": True,
    "office_write_sheet": True,
    "office_create_base": True,
    "office_create_slides": True,
    "office_generate_docx_pdf": True,
    "office_upload_file": True,
    "office_set_permission": True,
    "rollback_office_file": True,
}


def _all_read_funcs() -> list[Callable[..., Any]]:
    return [
        query_hazards,
        query_hazard_stats,
        query_central_alarms,
        query_contractor_admissions,
        knowledge_search,
        web_search,
        query_latest_regulations,
        query_ai_audits,
        query_ai_config,
        query_bitable_config,
        query_scheduler_tasks,
        query_drill_plans,
        query_drill_records,
        query_msds_documents,
        query_msds_collections,
        query_oh_persons,
        query_oh_exams,
        query_oh_positions,
        query_oh_hazard_factors,
        query_oh_followups,
        query_oh_applications,
        query_oh_hazard_enums,
        query_fire_alarms,
        query_cert_warnings,
        query_chemical_inventory,
        analyze_chemical_risk,
        query_special_op_records,
        query_key_risk_ops,
        query_ehs_changes,
        query_work_ticket_reviews,
        query_hazard_identifications,
        generate_daily_report,
        generate_supervision_bulletin,
        query_urs_records,
        query_urs_review_detail,
        preview_guardian_subsidy,
    ] + _OFFICE_READ_FUNCS


def _all_write_funcs() -> list[Callable[..., Any]]:
    return [
        generate_drill_plan,
        generate_central_alarm_daily_report,
        generate_fire_alarm_daily_report,
        generate_fire_alarm_weekly_report,
        sync_drill_plan_to_feishu,
        generate_urs_report_pdf,
        create_urs_review,
        parse_urs_document,
        run_urs_assessment,
        update_urs_item,
        confirm_urs_assessment,
        submit_urs_appeal,
        run_regulation_ai_review,
        trigger_oh_exam_parse,
        create_oh_followup,
        close_oh_followup,
        analyze_oh_transfer,
        override_oh_conclusion,
        renew_person_certificate,
        generate_guardian_subsidy,
        poll_hazard_ai_analysis,
        poll_hazard_rectification_review,
        send_hazard_supervision_bulletin,
    ] + _OFFICE_WRITE_FUNCS


def _wrap_tool(func: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    """为工具函数套统一管道（保留 Pydantic AI 的 docstring/schema 反射）。

    wrap 后的工具函数签名不变（仍 ``async def(ctx, **kwargs)``），内部调
    ``core.pipeline.execute_tool``。显式回填 ``__name__``/``__doc__``/``__annotations__``
    确保 Pydantic AI 仍能从 docstring 提参数 schema、从 ``__name__`` 取工具名
    （与现状 ``func.__name__`` 一致）。
    """

    @functools.wraps(func)
    async def wrapper(ctx: Any, **kwargs: Any) -> Any:
        return await execute_tool(ctx, tool_name, kwargs, func)

    # 显式回填元数据，保证 Pydantic AI schema 反射正常
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    wrapper.__annotations__ = func.__annotations__
    return wrapper


def register_all_tools(agent: Agent) -> None:
    """将所有工具函数注册到给定的 Pydantic AI Agent 实例。

    所有工具注册前先 wrap（统一管道）；写工具额外传 ``requires_approval=True``。
    """
    # 只读（带 RunContext）
    for func in _all_read_funcs():
        agent.tool(_wrap_tool(func, func.__name__))
    # 写入（带 RunContext + requires_approval）
    for func in _all_write_funcs():
        agent.tool(_wrap_tool(func, func.__name__), requires_approval=True)


# ── 函数名 → 函数对象映射（供 register_tools_subset 使用）─────────

_FUNC_BY_NAME: dict[str, Callable[..., Any]] = {
    f.__name__: f for f in _all_read_funcs() + _all_write_funcs()
}


def register_tools_subset(agent: Agent, tool_names: list[str]) -> None:
    """仅注册指定名称的工具到 Agent 实例。

    与 register_all_tools 的注册方式完全一致（读工具 plain、
    写工具 requires_approval=True），但只注册 tool_names 中列出的。
    不在 _FUNC_BY_NAME 中的名称静默跳过。
    """
    for name in tool_names:
        func = _FUNC_BY_NAME.get(name)
        if func is None:
            logger.warning("register_tools_subset: unknown tool %r, skipped", name)
            continue
        is_write = TOOL_KIND.get(name, False)
        agent.tool(_wrap_tool(func, name), requires_approval=is_write)
