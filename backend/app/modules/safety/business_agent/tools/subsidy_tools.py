"""监护补贴统计（平台作业票数据源）Agent 工具。

替换旧 4 个工具（import_subsidy_records / fetch_subsidy_bitable /
calculate_guardian_subsidy / export_subsidy_report 及文件/bitable 解析辅助）为
分步确认的 2 个新工具：

- ``preview_guardian_subsidy``（**只读**，TOOL_KIND=False，直接执行）：
  按目标月 ±1 月窗口从平台拉 8 类标准作业票 → Parser 归一化 → 证书映射查询 →
  ``SubsidyPlanBuilder.build`` → 返回预览 dict（票数/监护人/待核对/跳过/候选部门），
  附一句「确认计算」话术，无任何副作用。
- ``generate_guardian_subsidy``（**写入**，TOOL_KIND=True，requires_approval=True）：
  以相同入参幂等重拉重算 → ``SubsidyService.calculate`` →
  ``export_excel(review_notes=...)`` → 经 ``feishu.chat_sender.send_file_to_chat``
  回传当前飞书会话（``ctx.deps.chat_id``）；web 渠道（chat_id=None）返回降级提示 +
  base64 兜底。

核心计算/整理逻辑均在 ``service/subsidy_plan.py`` 与 ``service/subsidy.py``，
本文件只做参数适配/拉数/编排/降级，不写业务规则。
"""

from __future__ import annotations

import base64
import logging
from datetime import date, timedelta
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.feishu.chat_sender import send_file_to_chat
from app.modules.safety.service.subsidy import SubsidyService, b_cert_adjusted_total
from app.modules.safety.service.subsidy_plan import (
    ReviewNotes,
    SubsidyPlan,
    SubsidyPlanBuilder,
    build_certificate_map,
)
from app.modules.safety.workticket_review.client import WorkTicketPlatformClient
from app.modules.safety.workticket_review.parser import WorkTicket, WorkTicketParser

logger = logging.getLogger(__name__)

# B 证补贴系数（与既有 export_excel 默认值一致；费率调整属制度变更，不在本 ticket 范围）
_B_CERT_RATE = 0.5


# ═══════════════════════════════════════════════════════════════════
# 公共辅助（无副作用；窗口/错误处理两工具共用）
# ═══════════════════════════════════════════════════════════════════


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """月份平移（delta 可为负），返回 (年, 月)。"""
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def _window_dates(year: int, month: int) -> tuple[date, date]:
    """目标月 ±1 月窗口（如 2026-08 → 2026-07-01 ~ 2026-09-30）。"""
    start_year, start_month = _shift_month(year, month, -1)
    end_year, end_month = _shift_month(year, month, +1)
    plus_year, plus_month = _shift_month(end_year, end_month, +1)
    end = date(plus_year, plus_month, 1) - timedelta(days=1)
    return date(start_year, start_month, 1), end


def _validate_params(year: int, month: int) -> dict[str, Any] | None:
    """年月参数校验；非法返回 error dict，合法返回 None。"""
    if not isinstance(year, int) or not isinstance(month, int):
        return {"error": "年份/月份参数必须为整数。", "error_type": "invalid_params"}
    if month < 1 or month > 12:
        return {"error": f"月份参数不合法：{month}（应为 1-12）。", "error_type": "invalid_params"}
    if year < 2000 or year > 2100:
        return {"error": f"年份参数不合法：{year}。", "error_type": "invalid_params"}
    return None


def _platform_error(exc: Exception) -> dict[str, Any]:
    """把平台拉取异常归类为降级 dict（见 backend-design 风险 7.1 / 7.2）。"""
    text = str(exc)
    if any(k in text for k in ("凭据", "token", "鉴权", "未配置")):
        return {
            "error": "平台鉴权失败：平台凭据失效或未配置，请检查 SAFETY_PLATFORM_* 或联系管理员。",
            "error_type": "auth_failed",
            "detail": text,
        }
    return {
        "error": "平台拉取失败，请稍后重试或联系管理员。",
        "error_type": "platform_fetch_error",
        "detail": text,
    }


async def _fetch_and_parse(year: int, month: int) -> tuple[list[WorkTicket] | None, dict[str, Any] | None]:
    """窗口拉数 + Parser 归一化；失败返回 (None, error_dict)。

    - 拉取：``WorkTicketPlatformClient.list_tickets_for_date_range``（8 类票
      all-list + detail 富化 + pid 去重，见 workticket_review/client.py）。
    - 解析：``WorkTicketParser.normalize``（含 guardian / apply_unit，不污染
      missing 列表——缺失诊断由 SubsidyPlanBuilder 负责）。
    """
    try:
        async with WorkTicketPlatformClient() as client:
            raw_records = await client.list_tickets_for_date_range(
                *_window_dates(year, month)
            )
    except Exception as exc:
        logger.warning("平台作业票拉取失败 year=%s month=%s err=%s", year, month, exc)
        return None, _platform_error(exc)

    parser = WorkTicketParser()
    tickets: list[WorkTicket] = []
    for record in raw_records:
        tickets.append(parser.normalize(record, record.get("type", "")))
    return tickets, None


async def _build_plan(
    db: Any, tickets: list[WorkTicket], dept_keyword: str, year: int, month: int
) -> SubsidyPlan:
    """证书映射查询 + 纯函数整理（is_void/缺时间/部门/监护人/证书/类型规则全在 builder）。"""
    cert_map = await build_certificate_map(db)
    return SubsidyPlanBuilder.build(tickets, cert_map, dept_keyword, year, month)


def _confirm_suggestion(
    dept_keyword: str, year: int, month: int, plan: SubsidyPlan, need_selection: bool
) -> str:
    """一句话话术：Agent 引述给用户确认（含「确认计算」指令示例）。"""
    levels = {r.guardian_name: r.guardian_level for r in plan.records}
    a_cert = sum(1 for v in levels.values() if v == "A证")
    b_cert = sum(1 for v in levels.values() if v == "B证")
    text = (
        f"以上为「{dept_keyword}」{year}年{month}月监护补贴预览："
        f"窗口拉取 {plan.total_tickets} 张作业票，{plan.matched_tickets} 张计入补贴"
        f"（监护人 {len(levels)} 名：A证 {a_cert} 名、B证 {b_cert} 名），"
        f"待核对 {plan.unmatched_tickets} 张（{len(plan.unmatched)} 人未匹配证书），"
        f"跳过 {plan.skipped_tickets} 张（目标域内）。"
    )
    if need_selection:
        text += "当前部门关键词未命中，请从候选部门中选择或换更精准的部门词后重试。"
    else:
        text += "确认无误请回复「确认计算」；如需调整，请告知新的部门或月份。"
    return text


# ═══════════════════════════════════════════════════════════════════
# 工具 1：preview_guardian_subsidy（只读）
# ═══════════════════════════════════════════════════════════════════


async def preview_guardian_subsidy(
    ctx: RunContext[SafetyDeps],
    dept_keyword: str,
    year: int,
    month: int,
) -> dict[str, Any]:
    """监护补贴预览：从平台作业票拉数 → 整理 → 返回清单请用户确认（**只读，无副作用**）。

    适用场景：用户提出"整理/统计某部门某月的监护人补贴"（如"整理环保部8月份的
    监护人补贴"）时，先调用本工具预览，**不要**直接生成 Excel。工具返回
    ``confirm_suggestion`` 含「确认计算」话术，可直接引导用户确认。

    Args:
        dept_keyword: 部门关键词（**包含匹配**，如"环保"可命中"环保部"；无需全称）
        year: 统计年份（如 2026）
        month: 统计月份（1-12，如 8；按作业**开始时间**归集）

    Returns:
        dict（预览结构）：
            - total_fetched: 窗口命中作业票总数（目标月 ±1 月窗口拉回）
            - domain_tickets: 目标部门+目标月命中且非作废的票数
            - matched_records / matched_tickets: 计入补贴的票数
            - guardian_names: 去重后的监护人名单
            - guardians: [{name, level, ticket_count}] 监护人 + A/B 证级别 + 票数
            - a_cert_count / b_cert_count: A 证 / B 证监护人数
            - unmatched: [{name, ticket_count, operation_types}] 证书未匹配（不计金额）
            - skipped: [{ticket_no, ticket_type, reason}] 跳过票（**目标域内**：
              目标部门+目标月的作废/缺时间/无监护人/未知类型，非目标域票不在其中）
            - departments: 窗口内出现过的作业申请单位（部门匹配不到时作候选清单）
            - need_department_selection: 部门关键词未命中且窗口有票时为 True
            - hint: 空票/部门不命中时的提示文案
            - confirm_suggestion: 一句话确认话术（含「确认计算」指令示例）
            - stats: {total_records, guardian_count, a_cert_count, b_cert_count, total_amount}
        失败时返回 {"error": ..., "error_type": "platform_fetch_error"|"auth_failed"|"invalid_params"}
    """
    dept_keyword = (dept_keyword or "").strip()
    if not dept_keyword:
        return {
            "error": "部门关键词不能为空，请提供部门名称（如「环保部」或「环保」）。",
            "error_type": "invalid_params",
        }
    err = _validate_params(year, month)
    if err:
        return err

    tickets, err = await _fetch_and_parse(year, month)
    if err:
        return err
    assert tickets is not None  # err 为 None 时必有拉取结果

    plan = await _build_plan(ctx.deps.db, tickets, dept_keyword, year, month)

    # ── 监护人聚合（去重 + 级别 + 票数） ──
    guardians: dict[str, dict[str, Any]] = {}
    for r in plan.records:
        g = guardians.setdefault(
            r.guardian_name,
            {"name": r.guardian_name, "level": r.guardian_level or "", "ticket_count": 0},
        )
        g["ticket_count"] += 1

    a_cert = sum(1 for g in guardians.values() if g["level"] == "A证")
    b_cert = sum(1 for g in guardians.values() if g["level"] == "B证")
    departments = sorted(plan.departments)
    keyword = dept_keyword.lower()
    matched_depts = [d for d in departments if keyword in d.lower()]

    hint: str | None = None
    need_selection = False
    if plan.total_tickets == 0:
        hint = "目标窗口未拉到作业票，请确认部门关键词/月份是否正确，或平台是否有数据。"
    elif not matched_depts:
        need_selection = True
        hint = "未按部门关键词匹配到作业票，请从候选部门中选择，或换更精准的部门词。"
    elif plan.matched_tickets == 0:
        hint = "该部门在目标月份没有可计入补贴的记录（可能均被跳过或待核对），请查看 skipped / unmatched 明细。"

    return {
        "total_fetched": plan.total_tickets,
        "domain_tickets": plan.domain_tickets,
        "matched_records": plan.matched_tickets,
        "matched_tickets": plan.matched_tickets,
        "guardian_names": sorted(guardians.keys()),
        "guardians": [guardians[n] for n in sorted(guardians)],
        "a_cert_count": a_cert,
        "b_cert_count": b_cert,
        "unmatched": [
            {
                "name": u.name,
                "ticket_count": u.ticket_count,
                "operation_types": u.operation_types,
            }
            for u in plan.unmatched
        ],
        "skipped": [
            {"ticket_no": s.ticket_no, "ticket_type": s.ticket_type, "reason": s.reason}
            for s in plan.skipped
        ],
        "departments": departments,
        "need_department_selection": need_selection,
        "hint": hint,
        "confirm_suggestion": _confirm_suggestion(dept_keyword, year, month, plan, need_selection),
        "stats": {
            "total_records": len(plan.records),
            "guardian_count": len(guardians),
            "a_cert_count": a_cert,
            "b_cert_count": b_cert,
            "total_amount": 0.0,  # 预览不计算金额；金额以 generate 结果为准
        },
    }


# ═══════════════════════════════════════════════════════════════════
# 工具 2：generate_guardian_subsidy（写入，requires_approval）
# ═══════════════════════════════════════════════════════════════════


async def generate_guardian_subsidy(
    ctx: RunContext[SafetyDeps],
    dept_keyword: str,
    year: int,
    month: int,
    filename: str | None = None,
) -> dict[str, Any]:
    """监护补贴生成：重拉平台作业票 → 重算 → 生成 Excel → 回传当前飞书会话（**写入，需确认**）。

    用户对预览明确确认（如回复「确认计算」）后调用。本工具以相同入参**幂等重拉重算**
    （与 preview 同窗口），Excel 主表 + 「待核对/跳过说明」第二页：
    - 主表：按监护人+作业类型拆分补贴，公司模板原样复现；
    - 第二页：证书未匹配监护人（不计入补贴）+ 跳过票（票号+原因）。

    文件通过 ``ctx.deps.chat_id`` 回传当前会话；web 渠道（chat_id=None）返回降级提示
    并附 ``file_content_base64`` 兜底（不发送）。

    Args:
        dept_keyword: 部门关键词（包含匹配，如"环保"→"环保部"）
        year: 统计年份（如 2026）
        month: 统计月份（1-12；按作业开始时间归集）
        filename: 可选，文件名（建议 .xlsx 结尾；缺省按「部门 年月 监护补贴统计.xlsx」生成）

    Returns:
        dict：
            - 成功: {"sent": True, "file_name", "summary": {total_amount, guardian_count,
              matched_count, unmatched_count, skipped_count}, "message": 文字摘要}
              （total_amount = B证按 0.5 系数折算后实发合计，与 Excel K 列口径一致）
            - 发送失败: {"sent": False, "message", "file_name", "file_content_base64", "summary"}
            - chat_id 为空: {"sent": False, "degraded": True, "message", "file_name",
              "file_content_base64"}
            - 拉取失败/无票/无匹配: {"error", "error_type", ...}
    """
    dept_keyword = (dept_keyword or "").strip()
    if not dept_keyword:
        return {
            "error": "部门关键词不能为空，请提供部门名称（如「环保部」或「环保」）。",
            "error_type": "invalid_params",
        }
    err = _validate_params(year, month)
    if err:
        return err

    tickets, err = await _fetch_and_parse(year, month)
    if err:
        return err
    assert tickets is not None  # err 为 None 时必有拉取结果

    plan = await _build_plan(ctx.deps.db, tickets, dept_keyword, year, month)

    if plan.total_tickets == 0:
        return {
            "error": "目标窗口未拉到作业票，无法生成补贴 Excel。请确认部门关键词/月份是否正确，或平台是否有数据。",
            "error_type": "no_tickets",
        }

    keyword = dept_keyword.lower()
    matched_depts = [d for d in sorted(plan.departments) if keyword in d.lower()]
    if plan.matched_tickets == 0:
        extra: dict[str, Any] = {"departments": sorted(plan.departments)}
        if not matched_depts:
            extra["hint"] = "部门关键词未匹配到作业票，请先用 preview_guardian_subsidy 查看候选部门后重试。"
        else:
            extra["hint"] = "该部门在目标月份没有可计入补贴的记录（全部被跳过或待核对），请先用 preview_guardian_subsidy 查看明细。"
        return {"error": "没有可计入补贴的作业票，未生成 Excel。", "error_type": "no_matched_records", **extra}

    # ── 标题/部门名：从命中的申请单位取（确定性：排序后取第一个），回退关键词 ──
    department = matched_depts[0] if matched_depts else dept_keyword
    title = f"{department} {year}年{month}月 监护补贴统计"
    file_name = (filename or "").strip() or f"{title}.xlsx"
    if not file_name.lower().endswith((".xlsx", ".xls")):
        file_name += ".xlsx"

    # ── 幂等重算（plan.records 已按开始时间过滤目标月；calculate 再过滤一次兜底）──
    result = SubsidyService.calculate(plan.records, year=year, month=month)
    excel_bytes = SubsidyService.export_excel(
        result.details,
        result.summaries,
        title=title,
        department=department,
        b_cert_rate=_B_CERT_RATE,
        review_notes=ReviewNotes(unmatched=plan.unmatched, skipped=plan.skipped),
    )

    # P-1：摘要金额 = B 证按 0.5 系数折算后实发合计（与 Excel K 列口径一致，
    # 见 service/subsidy.py 的 b_cert_adjusted_total）。
    adjusted_total = b_cert_adjusted_total(result.details, _B_CERT_RATE)
    summary = {
        "total_amount": adjusted_total,
        "guardian_count": result.stats.guardian_count,
        "matched_count": plan.matched_tickets,
        "unmatched_count": plan.unmatched_tickets,
        "skipped_count": plan.skipped_tickets,
    }

    # ── web 渠道降级（chat_id 为空）：不发送，返回 base64 兜底 ──
    if not ctx.deps.chat_id:
        return {
            "sent": False,
            "degraded": True,
            "message": "当前渠道无法回传文件，请在飞书会话中使用此功能。",
            "file_name": file_name,
            "file_content_base64": base64.b64encode(excel_bytes).decode(),
        }

    ok = await send_file_to_chat(ctx.deps.chat_id, excel_bytes, file_name)
    if not ok:
        return {
            "sent": False,
            "message": "Excel 已生成但发送失败，请稍后重试或联系管理员。",
            "file_name": file_name,
            "file_content_base64": base64.b64encode(excel_bytes).decode(),
            "summary": summary,
        }

    message = (
        f"已生成《{title}》并发送到当前会话。"
        f"统计：{plan.matched_tickets} 张票、{summary['guardian_count']} 名监护人、"
        f"补贴总额 {summary['total_amount']:.2f} 元"
        f"（B证按{_B_CERT_RATE}系数折算后实发合计，Excel K 列口径）；"
        f"待核对 {summary['unmatched_count']} 张、跳过 {summary['skipped_count']} 张"
        f"（目标域内，详见 Excel 第二页「待核对-跳过说明」）。"
    )
    return {"sent": True, "file_name": file_name, "summary": summary, "message": message}


__all__ = ["preview_guardian_subsidy", "generate_guardian_subsidy"]
