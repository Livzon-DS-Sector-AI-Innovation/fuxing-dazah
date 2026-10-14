"""外来人员保险到期预警 — 报告组装与推送（安全速递格子）。

链路（照 hazard_direct/bulletin 模式）：
直读预报备审批表 → classify 三类口径 → DigestCell →
总卡开启时 upsert_daily_digest（并入当日「安全速递」总卡）；
总卡关闭时 send_digest_cell_card（同款版式独立群卡）。
推送时间：每周三 08:30（scheduler.py「外来人员保险预警」）。

无预警日也照发（需求方确认）：格子呈现「今日无到期/过期预警」，
同时持续曝光 ⚪ 在厂未填保险有效期清单，倒逼补录。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.service.visitor_insurance import warning
from app.modules.safety.service.visitor_insurance.reader import (
    VisitorNoticeReader,
    VisitorNoticeView,
    open_reader,
)

logger = logging.getLogger(__name__)

_DIGEST_KEY = "visitor_insurance"
_TAG_TEXT = "保险预警"
_TITLE = "外来人员保险到期预警"

_SEP = "━" * 18


def _bj_today() -> date:
    """北京时间今天（调度与报告日期统一 UTC+8 语义，与 daily_digest 一致）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _fmt(d: date | None) -> str:
    return d.isoformat() if d else "-"


def _work_line(g: warning.ExpiringGroup) -> str:
    work = g.work_content or "-"
    if g.work_scope:
        work = f"{work}（{g.work_scope}）"
    return work


def build_detail(result: warning.WarningResult) -> str:
    """折叠明细 markdown：三节固定结构，无命中的节保留标题并标注「今日无」。"""
    lines: list[str] = []

    lines.append(
        f"**扫描口径**：预报备已通过且在厂（进厂结束 ≥ 今日）；"
        f"共扫描 {result.total_notices} 条报备，在厂 {result.active_notices} 条"
    )
    lines.append("")

    expired_people = sum(g.people for g in result.expired)
    lines.append(f"{_SEP} 🔴 保险已过期（{len(result.expired)} 条 / {expired_people} 人）{_SEP}")
    if result.expired:
        for idx, g in enumerate(result.expired, 1):
            lines.append(
                f"**{idx}. {g.company}**（{g.people} 人）：{g.names or '-'}"
            )
            lines.append(
                f"作业：{_work_line(g)}｜保险已于 {_fmt(g.insurance_end)} 过期"
                f" **{abs(g.days_left)} 天**｜在厂至 {_fmt(g.entry_end)}"
            )
    else:
        lines.append("今日无")
    lines.append("")

    soon_people = sum(g.people for g in result.soon)
    lines.append(f"{_SEP} 🟡 3天内到期（{len(result.soon)} 条 / {soon_people} 人）{_SEP}")
    if result.soon:
        for idx, g in enumerate(result.soon, 1):
            lines.append(
                f"**{idx}. {g.company}**（{g.people} 人）：{g.names or '-'}"
            )
            lines.append(
                f"作业：{_work_line(g)}｜保险 {_fmt(g.insurance_end)} 到期"
                f"（剩 **{g.days_left} 天**）｜在厂至 {_fmt(g.entry_end)}"
            )
    elif result.next_expiry is not None:
        lines.append(
            f"今日无；在厂报备最近到期：{result.next_expiry_company} "
            f"{_fmt(result.next_expiry)}（剩 {(result.next_expiry - result.today).days} 天）"
        )
    else:
        lines.append("今日无")
    lines.append("")

    missing_people = sum(g.people for g in result.missing)
    missing_notices = sum(g.notices for g in result.missing)
    lines.append(
        f"{_SEP} ⚪ 在厂未填保险有效期"
        f"（{missing_notices} 条 / {missing_people} 人 / {len(result.missing)} 家单位）{_SEP}"
    )
    if result.missing:
        for g in result.missing:
            lines.append(
                f"- **{g.company}**：{g.notices} 条报备｜{g.people} 人｜"
                f"最晚在厂至 {_fmt(g.latest_entry_end)}"
            )
        lines.append("")
        lines.append("📌 请相关对接部门催收保险凭证，并在预报备表补录「保险有效期至」")
    else:
        lines.append("今日无（在厂报备均已填写保险有效期）")
    lines.append("")

    lines.append(f"{_SEP} 处置建议 {_SEP}")
    lines.append("🔴 已过期：暂停相关单位人员进厂作业，保险补齐后恢复")
    lines.append("🟡 临期：联系单位提前续保，并更新预报备表保险信息")

    return "\n".join(lines)


def build_cell(result: warning.WarningResult) -> Any:
    """口径结果 → 「安全速递」格子（颜色随命中级别：红>橙>蓝）。"""
    from app.modules.safety.feishu.daily_digest import DigestCell

    expired_people = sum(g.people for g in result.expired)
    soon_people = sum(g.people for g in result.soon)
    missing_people = sum(g.people for g in result.missing)
    missing_notices = sum(g.notices for g in result.missing)

    stats = (
        f"🔴 已过期 **{len(result.expired)}** 条/{expired_people} 人 ｜ "
        f"🟡 3天内到期 **{len(result.soon)}** 条/{soon_people} 人 ｜ "
        f"⚪ 在厂未填保险 **{missing_notices}** 条/{missing_people} 人"
    )

    if result.expired:
        worst = result.expired[0]
        zone = (
            f"最严重：{worst.company} 已过期 {abs(worst.days_left)} 天，"
            f"请立即暂停其进厂作业"
        )
        color = "red"
    elif result.soon:
        first = result.soon[0]
        zone = f"最近到期：{first.company} {_fmt(first.insurance_end)}（剩 {first.days_left} 天）"
        color = "orange"
    elif result.missing:
        top = result.missing[0]
        zone = f"今日无到期预警；未填保险最大单位：{top.company}（{top.people} 人）"
        color = "blue"
    else:
        zone = "今日无外来人员保险到期预警，在厂报备保险信息齐全"
        color = "green"

    return DigestCell(
        tag_color=color,
        tag_text=_TAG_TEXT,
        title=_TITLE,
        stats=stats,
        zone=zone[:100],
        detail=build_detail(result),
    )


async def build_warning_result(
    reader: VisitorNoticeReader | None = None,
    *,
    today: date | None = None,
) -> warning.WarningResult:
    """直读全量 → 口径计算（today 可注入，测试/补推固定日期用）。"""
    reader = reader or open_reader()
    views: list[VisitorNoticeView] = await reader.fetch_all()
    return warning.classify(views, today or _bj_today())


async def send_visitor_insurance_warning(
    chat_id: str | None = None,
    *,
    reader: VisitorNoticeReader | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """生成并推送保险预警（chat_id 仅在总卡关闭时作为独立群卡目标，默认速递群）。

    Returns:
        统计 dict（sent=bool + 三类计数），供调度日志与验收使用。
    """
    from app.modules.safety.feishu.daily_digest import (
        digest_enabled,
        send_digest_cell_card,
        upsert_daily_digest,
    )

    result = await build_warning_result(reader, today=today)
    cell = build_cell(result)
    report_date = result.today
    stats: dict[str, Any] = {
        "report_date": report_date.isoformat(),
        "expired": len(result.expired),
        "soon": len(result.soon),
        "missing_groups": len(result.missing),
        "missing_people": sum(g.people for g in result.missing),
        "total_notices": result.total_notices,
        "active_notices": result.active_notices,
    }

    try:
        if digest_enabled():
            ok = await upsert_daily_digest(report_date, _DIGEST_KEY, cell)
        else:
            ok = bool(await send_digest_cell_card(
                cell,
                chat_id=chat_id,
                title=f"📌 {_TITLE} | {report_date.isoformat()}",
            ))
    except Exception:
        # upsert/send 内部已吞异常返回 False，这里只可能收到构建期错误；
        # 无论哪种失败都上抛，交给调度器记 failed → 补发窗口内自动重试
        logger.exception("外来人员保险预警推送异常")
        raise

    if not ok:
        raise RuntimeError(f"外来人员保险预警推送失败（总卡/群卡未确认投递）: {stats}")
    stats["sent"] = True
    logger.info("外来人员保险预警已推送: %s", stats)
    return stats
