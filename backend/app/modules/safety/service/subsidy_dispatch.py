"""监护补贴月报私发 — 每月 1 日 08:30 上一自然月补贴 Excel → 各部门收件人 DM。

2026-11-02 扩面拍板（首跑 sent=0 事故 + 用户纠偏「月报不能只有台账三部门」）：

- **统计范围（全部门双源）**：
  - 台账部门（提炼工程四/五/六部，``subsidy_dept_ledgers``）——四/六部 base
    按月分表，``fetch_ledger_rows(source, year, month)`` 按 (年,月) 路由子表
    （2026-11-01 首跑钉死 9 月表致 10 月「假空跳」的根因修复）；
  - **其余全部部门 → 平台作业票路线**（目标月 ±1 月窗口拉票 → Parser 归一化 →
    按监护人所在部门归集，与 Agent 工具 ``generate_guardian_subsidy`` 同链），
    逐部门出 Excel；台账三部门从平台结果中排除（**台账为准防双算**）；
  - 当月无计入记录的部门跳过（不空发）。
- **收件名单**：**补贴业务专属名单**（``SUBSIDY_DM_OVERRIDES``，支持一部门多人：
  四部林锴彬、五部蔡嘉旺+陈卫强(2026-11-02 增)、六部孙长宽）优先；未覆盖部门
  回退 DEPARTMENT_CONFIG ``safety_officer``。**不改全局分管安全员名单**——消防
  私发/隐患督办@提及等其他消费方仍按原名单。
- **open_id 解析三层链**（identity 空表家族根治，与催办收件人同思路）：
  ① ``bitable_id_mapper`` 静态映射（安全应用作用域）→ ② 本地回退表
  （``_SUBSIDY_OPEN_ID_FALLBACK``）→ ③ ``resolve_open_ids``（identity → 邮箱
  batch_get_id）。解析不到的收件人跳过并计 unresolved（**高声量 WARNING**，
  不再静默）。
- **失败语义**：构建阶段（拉台账/拉票/出 Excel）失败向上抛 → 调度器补发窗口
  23:30 前整任务重试（此时尚未发送任何文件，重试安全）；发送阶段单人失败只
  计数不抛（避免整任务重试造成已收人重复收文件）。
- **开关**：SAFETY_SUBSIDY_MONTHLY_DM_ENABLED（env > DB app_config 30s TTL >
  默认 true；关闭即跳过返回 None）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.feishu.bitable_id_mapper import get_bitable_open_id
from app.modules.safety.feishu.chat_sender import send_file_to_chat
from app.modules.safety.feishu.dept_config import DEPARTMENT_CONFIG
from app.modules.safety.feishu.mention import resolve_open_ids
from app.modules.safety.feishu.notification import send_user_card
from app.modules.safety.service.subsidy import (
    SubsidyService,
    b_cert_adjusted_total,
)
from app.modules.safety.service.subsidy_dept_ledgers import (
    LEDGER_SOURCES,
    build_ledger_plan,
    fetch_ledger_rows,
    match_ledger_source,
)
from app.modules.safety.service.subsidy_plan import (
    ReviewNotes,
    SubsidyPlan,
    SubsidyPlanBuilder,
    build_certificate_map,
    build_guardian_department_map,
)
from app.modules.safety.workticket_review.client import WorkTicketPlatformClient
from app.modules.safety.workticket_review.parser import WorkTicketParser

logger = logging.getLogger(__name__)

# B 证折算系数与 Agent 生成工具一致（subsidy_tools._B_CERT_RATE）
_B_CERT_RATE = 0.5
# 无证/未登级别暂计口径（与 subsidy_tools/_UNCERTIFIED_LEVEL 一致）
_UNCERTIFIED_LEVEL = "A证"

# 数据源标签（摘要卡话术与 payload 记录用）
SOURCE_LEDGER = "dept_ledger"
SOURCE_PLATFORM = "platform_ticket"


def dispatch_enabled() -> bool:
    """月报私发开关（默认开：用户 2026-10-26 拍板按月自动发送）。

    读取链：env > DB 活行（app_config，30s TTL）> 默认 true。
    """
    return _app_config_store.get_bool("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", True)


def previous_month(today: date | None = None) -> tuple[int, int]:
    """今天所在月的上一完整自然月（1 日触发 → 上月 1 日~月末）。"""
    t = today or date.today()
    return (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)


# 补贴业务专属收件人：部门 → 姓名元组（一部门可多人）。
# 2026-10-26 拍板四部林锴彬/六部孙长宽；2026-11-02 五部增陈卫强（蔡嘉旺保留）。
# 只作用于月报私发，不改 DEPARTMENT_CONFIG 全局分管安全员名单；
# 未覆盖部门回退该部门 safety_officer。
SUBSIDY_DM_OVERRIDES: dict[str, tuple[str, ...]] = {
    "提炼工程四部": ("林锴彬",),
    "提炼工程五部": ("蔡嘉旺", "陈卫强"),
    "提炼工程六部": ("孙长宽",),
}


def subsidy_recipients(department: str) -> tuple[str, ...]:
    """补贴月报收件人（可多人）：业务专属名单优先，未覆盖回退 safety_officer。"""
    overrides = SUBSIDY_DM_OVERRIDES.get(department)
    if overrides:
        return tuple(n for n in overrides if n.strip())
    officer = (DEPARTMENT_CONFIG.get(department, {}).get("safety_officer") or "").strip()
    return (officer,) if officer else ()


# 静态映射兜不到的收件人直配（安全应用作用域 open_id）。
# 陈卫强：2026-11-02 自「特殊作业日报表」发起人/实操考核人人员字段直取（多条一致）。
_SUBSIDY_OPEN_ID_FALLBACK: dict[str, str] = {
    "陈卫强": "ou_455f4a47607e0d7575d203d7e80f105a",
}


async def resolve_recipient_open_ids(names: set[str]) -> dict[str, str]:
    """收件人姓名 → 安全应用 open_id，三层链：

    ① ``bitable_id_mapper`` 静态映射（bitable_open_ids.json，催办收件人同源）
    → ② 本地回退表 ``_SUBSIDY_OPEN_ID_FALLBACK``
    → ③ ``resolve_open_ids``（identity → 邮箱 → batch_get_id）。

    解析不到的姓名不出现在返回值，调用方按 unresolved 处理。
    """
    out: dict[str, str] = {}
    pending: set[str] = set()
    for name in {n.strip() for n in names if n and n.strip()}:
        oid = get_bitable_open_id(name=name) or _SUBSIDY_OPEN_ID_FALLBACK.get(name)
        if oid:
            out[name] = oid
        else:
            pending.add(name)
    if pending:
        out.update(await resolve_open_ids(pending))
    return out


# ═══════════════════════════════════════════════════════════════════
# 单部门 Excel / 摘要卡（台账与平台两路共用）
# ═══════════════════════════════════════════════════════════════════


@dataclass
class DeptPayload:
    """一个部门的月报载荷（构建阶段产物，发送阶段消费）。"""

    department: str
    source: str                 # SOURCE_LEDGER / SOURCE_PLATFORM
    excel_bytes: bytes
    file_name: str
    summary: dict[str, Any]


def _export_plan(
    department: str, plan: SubsidyPlan, year: int, month: int
) -> tuple[bytes, str, dict[str, Any]]:
    """补贴计划 → (Excel 字节, 文件名, 摘要)；口径镜像 Agent 生成工具。"""
    result = SubsidyService.calculate(plan.records, year=year, month=month)
    title = f"{department} {year}年{month}月 监护补贴统计"
    excel_bytes = SubsidyService.export_excel(
        result.details,
        result.summaries,
        title=title,
        department=department,
        b_cert_rate=_B_CERT_RATE,
        review_notes=ReviewNotes(
            unmatched=plan.unmatched,
            skipped=plan.skipped,
            unmatched_counted=_UNCERTIFIED_LEVEL is not None,
        ),
    )
    summary = {
        "matched": plan.matched_tickets,
        "guardians": result.stats.guardian_count,
        "amount": b_cert_adjusted_total(result.details, _B_CERT_RATE),
        "unmatched": plan.unmatched_tickets,
        "skipped": plan.skipped_tickets,
        "unmatched_people": len(plan.unmatched),
    }
    return excel_bytes, f"{title}.xlsx", summary


def build_monthly_excel(
    source_rows: list[dict[str, Any]],
    source: Any,
    year: int,
    month: int,
) -> tuple[bytes, str, dict[str, Any]] | None:
    """单部门台账行 → (Excel 字节, 文件名, 摘要)；无计入记录返回 None（跳过不空发）。

    纯函数（不碰网络/DB），口径镜像 Agent 生成工具 generate_guardian_subsidy：
    calculate → export_excel(review_notes) → b_cert_adjusted_total。
    """
    plan = build_ledger_plan(
        source, source_rows, year, month, uncertified_level=_UNCERTIFIED_LEVEL
    )
    if plan.matched_tickets == 0:
        return None
    return _export_plan(source.department, plan, year, month)


def build_platform_excel(
    plan: SubsidyPlan, department: str, year: int, month: int
) -> tuple[bytes, str, dict[str, Any]] | None:
    """平台票路线单部门计划 → (Excel, 文件名, 摘要)；无计入返回 None。"""
    if plan.matched_tickets == 0:
        return None
    return _export_plan(department, plan, year, month)


def build_summary_card(
    department: str, year: int, month: int,
    summary: dict[str, Any], source: str = SOURCE_LEDGER,
) -> tuple[str, str]:
    """单部门月报摘要卡（文件前置解读），返回 (title, markdown 正文)。"""
    title = f"📊 监护补贴月报 · {department}"
    if source == SOURCE_PLATFORM:
        head = f"**{department}** ｜ {year}年{month}月监护补贴统计（平台作业票）"
        tail = (
            "按监护人所在部门归集；未登级别者已暂按A证计入（进待核对），"
            "级别以监护人证书台账为准；明细见随后的 Excel（第二页为待核对/跳过说明）。"
        )
        matched_label = "作业票计入"
    else:
        head = f"**{department}** ｜ {year}年{month}月监护补贴统计"
        tail = (
            "证书级别以台账登记为准；明细见随后的 Excel（第二页为待核对/跳过说明）。"
        )
        matched_label = "台账计入"
    content = (
        f"{head}\n"
        f"{matched_label} **{summary['matched']}** 条 ｜ 监护人 **{summary['guardians']}** 名\n"
        f"补贴总额 **{summary['amount']:.2f} 元**（B证按{_B_CERT_RATE}系数折算后实发合计）\n"
        f"待核对 {summary['unmatched']} 条（{summary['unmatched_people']} 人未登级别，"
        f"已暂按A证计入）、跳过 {summary['skipped']} 条\n"
        f"{tail}"
    )
    return title, content


# ═══════════════════════════════════════════════════════════════════
# 平台票路线（其余部门；与 subsidy_tools 同链但不依赖工具层）
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


async def _fetch_platform_tickets(year: int, month: int) -> list[Any]:
    """平台作业票窗口拉取 + Parser 归一化（失败上抛 → 调度器重试）。"""
    async with WorkTicketPlatformClient() as client:
        raw_records = await client.list_tickets_for_date_range(
            *_window_dates(year, month)
        )
    parser = WorkTicketParser()
    return [parser.normalize(r, r.get("type", "")) for r in raw_records]


def _is_ledger_department(department: str) -> bool:
    """部门名是否命中台账源（含别名），命中则从平台路线排除（防双算）。"""
    return match_ledger_source(department) is not None


async def build_platform_payloads(
    year: int, month: int
) -> tuple[list[DeptPayload], int]:
    """平台票路线：逐部门出 Excel；返回 (payloads, skipped_empty)。

    部门清单 = 空关键词计划的归集部门全集（含窗口内非目标月，出 Excel 时
    自然判空跳过）− 台账三部门（别名匹配排除）。
    """
    from app.core.database import async_session_factory

    tickets = await _fetch_platform_tickets(year, month)
    async with async_session_factory() as db:
        cert_map = await build_certificate_map(db)
        guardian_depts = await build_guardian_department_map(db)

    plan_all = SubsidyPlanBuilder.build(
        tickets, cert_map, "", year, month,
        guardian_departments=guardian_depts,
        uncertified_level=_UNCERTIFIED_LEVEL,
    )
    targets = sorted(
        d for d in plan_all.departments
        if d and not _is_ledger_department(d)
    )

    payloads: list[DeptPayload] = []
    skipped_empty = 0
    for dept in targets:
        plan = SubsidyPlanBuilder.build(
            tickets, cert_map, dept, year, month,
            guardian_departments=guardian_depts,
            uncertified_level=_UNCERTIFIED_LEVEL,
        )
        built = build_platform_excel(plan, dept, year, month)
        if built is None:
            skipped_empty += 1
            logger.info("%s %d-%02d 平台票无计入记录，跳过月报", dept, year, month)
            continue
        excel_bytes, file_name, summary = built
        payloads.append(DeptPayload(
            department=dept, source=SOURCE_PLATFORM,
            excel_bytes=excel_bytes, file_name=file_name, summary=summary,
        ))
    logger.info(
        "平台票路线: 窗口 %d 张票，归集部门 %d 个（台账部门已排除），计入 %d 个 / 空跳 %d 个",
        len(tickets), len(plan_all.departments), len(payloads), skipped_empty,
    )
    return payloads, skipped_empty


# ═══════════════════════════════════════════════════════════════════
# 月报入口
# ═══════════════════════════════════════════════════════════════════


async def run_monthly_subsidy_dispatch(
    year: int | None = None, month: int | None = None
) -> dict[str, int] | None:
    """月报私发入口（scheduler-ready；year/month 缺省取上一自然月）。

    Returns:
        {"sent", "skipped_empty", "errors", "unresolved"}
        —— sent=全部收件人均送达的部门数；skipped_empty=当月无记录部门数
        （台账+平台两路合计）；errors=存在发送失败收件人的部门数；
        unresolved=存在未解析收件人的部门数；开关关闭时返回 None。
    """
    if not dispatch_enabled():
        logger.info("监护补贴月报私发已关闭 (SAFETY_SUBSIDY_MONTHLY_DM_ENABLED=false)")
        return None
    if year is None or month is None:
        year, month = previous_month()

    # ── ① 构建阶段：台账三部门 + 平台票其余部门（失败上抛 → 尚未发件，重试安全）──
    payloads: list[DeptPayload] = []
    skipped_empty = 0
    for source in LEDGER_SOURCES:
        rows = await fetch_ledger_rows(source, year=year, month=month)
        built = build_monthly_excel(rows, source, year, month)
        if built is None:
            skipped_empty += 1
            logger.info("%s %d-%02d 无计入记录，跳过月报", source.department, year, month)
            continue
        excel_bytes, file_name, summary = built
        payloads.append(DeptPayload(
            department=source.department, source=SOURCE_LEDGER,
            excel_bytes=excel_bytes, file_name=file_name, summary=summary,
        ))

    platform_payloads, platform_skipped = await build_platform_payloads(year, month)
    payloads.extend(platform_payloads)
    skipped_empty += platform_skipped

    if not payloads:
        logger.info("监护补贴月报：全部部门当月均无记录，无私发")
        return {"sent": 0, "skipped_empty": skipped_empty, "errors": 0, "unresolved": 0}

    # ── ② 收件人 open_id 解析（三层链：静态映射 → 本地回退 → identity）──
    recipients_by_dept = {
        p.department: subsidy_recipients(p.department) for p in payloads
    }
    all_names = {n for names in recipients_by_dept.values() for n in names}
    name_to_open_id = await resolve_recipient_open_ids(all_names)
    missing = all_names - set(name_to_open_id)
    if missing:
        logger.warning(
            "月报收件人未解析 open_id（对应部门跳过该收件人）: %s", "、".join(sorted(missing))
        )

    # ── ③ 发送阶段：逐部门逐收件人（摘要卡 + Excel）；单人失败只计数不抛 ──
    sent = errors = unresolved = 0
    for p in payloads:
        dept = p.department
        names = recipients_by_dept.get(dept, ())
        uids: list[tuple[str, str]] = []
        dept_unresolved = False
        for n in names:
            oid = name_to_open_id.get(n, "")
            if oid:
                uids.append((n, oid))
            else:
                dept_unresolved = True
                logger.warning(
                    "月报收件人未解析 open_id，跳过该收件人: dept=%s officer=%s", dept, n or "(未配置)"
                )
        if not uids:
            unresolved += 1
            continue

        dept_ok = True
        for name, uid in uids:
            try:
                title, content = build_summary_card(
                    dept, year, month, p.summary, source=p.source
                )
                card_ok = await send_user_card(
                    open_id=uid, title=title, content=content,
                    id_type="open_id", header_template="blue",
                )
                file_ok = await send_file_to_chat(
                    uid, p.excel_bytes, p.file_name, receive_id_type="open_id"
                )
                if file_ok:
                    logger.info(
                        "监护补贴月报私发成功: dept=%s → %s (card=%s) %s",
                        dept, name, bool(card_ok), p.file_name,
                    )
                else:
                    dept_ok = False
                    logger.warning("监护补贴月报文件发送失败: dept=%s → %s", dept, name)
            except Exception:
                dept_ok = False
                logger.exception("监护补贴月报私发异常: dept=%s → %s", dept, name)

        if dept_unresolved:
            unresolved += 1
        if dept_ok and not dept_unresolved:
            sent += 1
        elif not dept_ok:
            errors += 1

    if unresolved or errors:
        logger.warning(
            "监护补贴月报存在未达项: unresolved_depts=%d error_depts=%d（名单见上方日志）",
            unresolved, errors,
        )
    logger.info(
        "监护补贴月报私发完成: %d-%02d sent=%d skipped_empty=%d errors=%d unresolved=%d",
        year, month, sent, skipped_empty, errors, unresolved,
    )
    return {"sent": sent, "skipped_empty": skipped_empty, "errors": errors, "unresolved": unresolved}


__all__ = [
    "run_monthly_subsidy_dispatch",
    "dispatch_enabled",
    "previous_month",
    "subsidy_recipients",
    "resolve_recipient_open_ids",
    "build_platform_payloads",
    "SUBSIDY_DM_OVERRIDES",
    "build_monthly_excel",
    "build_platform_excel",
    "build_summary_card",
    "SOURCE_LEDGER",
    "SOURCE_PLATFORM",
]
