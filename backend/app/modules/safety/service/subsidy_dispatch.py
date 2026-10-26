"""监护补贴月报私发 — 每月 1 日 08:30 上一自然月补贴 Excel → 各部门分管安全员 DM。

2026-10-26 用户拍板（参考 2026-10-02 消防月报/速递卡那次的私发名单）：

- **统计范围**：台账三部门（提炼工程四/五/六部，``subsidy_dept_ledgers``）各生成
  一份上一自然月监护补贴 Excel（口径与 Agent 生成工具一致：级别以台账登记为准、
  未登级别暂按 A 证计入并进待核对、同日重叠去重、B 证 0.5 系数折算实发合计）；
  当月无计入记录的部门跳过（不空发）。
- **收件名单**：DEPARTMENT_CONFIG（``feishu/dept_config.py`` 人工维护权威名单）
  的 ``safety_officer`` —— 四部杨昆、五部蔡嘉旺、六部陈美丽；部门未配置安全员
  时该部门跳过并记 unresolved。
- **身份链路**：与中控日报私发同款 ``feishu.mention.resolve_open_ids``
  （identity → 邮箱 batch_get_id / user_id 反查 → **安全应用作用域 open_id**，
  2026-09-30 真机已验证三人可解析），卡片 ``send_user_card``、Excel
  ``send_file_to_chat(receive_id_type="open_id")`` 直发。
- **失败语义**：台账拉取失败向上抛（调度器补发窗口 23:30 前自动重试整任务）；
  单人发送失败只计数不抛（避免整任务重试造成已收人重复收文件）。
- **开关**：SAFETY_SUBSIDY_MONTHLY_DM_ENABLED（env > DB app_config 30s TTL >
  默认 true——用户明确要求按月自动发送；关闭即跳过）。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.modules.safety.app_config.store import store as _app_config_store
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
)
from app.modules.safety.service.subsidy_plan import ReviewNotes

logger = logging.getLogger(__name__)

# B 证折算系数与 Agent 生成工具一致（subsidy_tools._B_CERT_RATE）
_B_CERT_RATE = 0.5
# 无证/未登级别暂计口径（与 subsidy_tools/_UNCERTIFIED_LEVEL 一致）
_UNCERTIFIED_LEVEL = "A证"


def dispatch_enabled() -> bool:
    """月报私发开关（默认开：用户 2026-10-26 拍板按月自动发送）。

    读取链：env > DB 活行（app_config，30s TTL）> 默认 true。
    """
    return _app_config_store.get_bool("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", True)


def previous_month(today: date | None = None) -> tuple[int, int]:
    """今天所在月的上一完整自然月（1 日触发 → 上月 1 日~月末）。"""
    t = today or date.today()
    return (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)


def dept_safety_officer(department: str) -> str:
    """部门 → DEPARTMENT_CONFIG 分管安全员姓名（未配置返回空串）。"""
    return (DEPARTMENT_CONFIG.get(department, {}).get("safety_officer") or "").strip()


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
    result = SubsidyService.calculate(plan.records, year=year, month=month)
    title = f"{source.department} {year}年{month}月 监护补贴统计"
    excel_bytes = SubsidyService.export_excel(
        result.details,
        result.summaries,
        title=title,
        department=source.department,
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


def build_summary_card(source: Any, year: int, month: int, summary: dict[str, Any]) -> tuple[str, str]:
    """单部门月报摘要卡（文件前置解读），返回 (title, markdown 正文)。"""
    title = f"📊 监护补贴月报 · {source.department}"
    content = (
        f"**{source.department}** ｜ {year}年{month}月监护补贴统计\n"
        f"台账计入 **{summary['matched']}** 条 ｜ 监护人 **{summary['guardians']}** 名\n"
        f"补贴总额 **{summary['amount']:.2f} 元**（B证按{_B_CERT_RATE}系数折算后实发合计）\n"
        f"待核对 {summary['unmatched']} 条（{summary['unmatched_people']} 人未登级别，"
        f"已暂按A证计入）、跳过 {summary['skipped']} 条\n"
        f"证书级别以台账登记为准；明细见随后的 Excel（第二页为待核对/跳过说明）。"
    )
    return title, content


async def run_monthly_subsidy_dispatch(
    year: int | None = None, month: int | None = None
) -> dict[str, int] | None:
    """月报私发入口（scheduler-ready，独立 session；year/month 缺省取上一自然月）。

    Returns:
        {"sent", "skipped_empty", "skipped_disabled", "errors", "unresolved"}
        —— sent=文件+摘要卡均送达的部门数；skipped_empty=当月无记录部门数；
        errors=发送失败部门数；unresolved=安全员未解析到 union_id 的部门数；
        开关关闭时返回 None。
    """
    if not dispatch_enabled():
        logger.info("监护补贴月报私发已关闭 (SAFETY_SUBSIDY_MONTHLY_DM_ENABLED=false)")
        return None
    if year is None or month is None:
        year, month = previous_month()

    # ── ① 三部门台账拉取（失败上抛 → 调度器补发窗口整任务重试）──
    dept_payload: list[tuple[Any, bytes, str, dict[str, Any]]] = []
    skipped_empty = 0
    for source in LEDGER_SOURCES:
        rows = await fetch_ledger_rows(source)
        built = build_monthly_excel(rows, source, year, month)
        if built is None:
            skipped_empty += 1
            logger.info("%s %d-%02d 无计入记录，跳过月报", source.department, year, month)
            continue
        dept_payload.append((source, *built))
    if not dept_payload:
        logger.info("监护补贴月报：三部门当月均无记录，无私发")
        return {"sent": 0, "skipped_empty": skipped_empty, "errors": 0, "unresolved": 0}

    # ── ② 收件人 union_id 解析（姓名 → 邮箱 → batch_get_id，与消防私发同链）──
    officers = {
        source.department: dept_safety_officer(source.department)
        for source, *_ in dept_payload
    }
    names = {n for n in officers.values() if n}
    name_to_open_id = await resolve_open_ids(names)
    missing = names - set(name_to_open_id)
    if missing:
        logger.warning("分管安全员未解析 open_id（该部门月报跳过）: %s", "、".join(sorted(missing)))

    # ── ③ 逐部门私发：摘要卡 + Excel（先卡后文件）──
    sent = errors = unresolved = 0
    for source, excel_bytes, file_name, summary in dept_payload:
        dept = source.department
        officer = officers.get(dept, "")
        uid = name_to_open_id.get(officer, "") if officer else ""
        if not uid:
            unresolved += 1
            logger.warning("分管安全员未解析 open_id，月报未发: dept=%s officer=%s", dept, officer or "(未配置)")
            continue
        try:
            title, content = build_summary_card(source, year, month, summary)
            card_ok = await send_user_card(
                open_id=uid, title=title, content=content,
                id_type="open_id", header_template="blue",
            )
            file_ok = await send_file_to_chat(
                uid, excel_bytes, file_name, receive_id_type="open_id"
            )
            if file_ok:
                sent += 1
                logger.info(
                    "监护补贴月报私发成功: dept=%s → %s (card=%s) %s",
                    dept, officer, bool(card_ok), file_name,
                )
            else:
                errors += 1
                logger.warning("监护补贴月报文件发送失败: dept=%s → %s", dept, officer)
        except Exception:
            errors += 1
            logger.exception("监护补贴月报私发异常: dept=%s → %s", dept, officer)

    logger.info(
        "监护补贴月报私发完成: %d-%02d sent=%d skipped_empty=%d errors=%d unresolved=%d",
        year, month, sent, skipped_empty, errors, unresolved,
    )
    return {"sent": sent, "skipped_empty": skipped_empty, "errors": errors, "unresolved": unresolved}


__all__ = [
    "run_monthly_subsidy_dispatch",
    "dispatch_enabled",
    "previous_month",
    "dept_safety_officer",
    "build_monthly_excel",
    "build_summary_card",
]
