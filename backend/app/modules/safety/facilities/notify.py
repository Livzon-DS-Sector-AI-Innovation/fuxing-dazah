"""滚动批次卡 + 速递格子 + 逾期升级（facilities-p1 票 05）。

合并铁律（DESIGN §4.5）：绝不逐条发送。每部门至多一张进行中批次卡
（facility_notice_batches 部门唯一 open）——当日派发无进行中卡则新发，
有则新任务并入原卡原地 PATCH；闭环命中原地刷新进度；全闭环置绿归档
停更。PATCH 限流：每批次卡 5 分钟窗口内合并刷新（进程内时间戳；卡内容
恒从 DB 全量重建，延迟刷新不丢状态，下一触发点补刷）。

速递格子 key=facility_check（CELL_ORDER 已追加）：全厂口径 逾期/30 天内
到期/待闭环 + 逾期 Top + ⚪ 信息不全，倒逼补录。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.feishu.daily_digest import DigestCell, upsert_daily_digest
from app.modules.safety.feishu.notification import (
    build_card_dict,
    send_group_card,
    update_card,
)
from app.modules.safety.models import (
    FacilityCheckTask,
    FacilityNoticeBatch,
)

logger = logging.getLogger(__name__)

DIGEST_KEY = "facility_check"
# PATCH 限流窗口（秒）：事件风暴下防连环刷新卡片
PATCH_THROTTLE_SECONDS = 5 * 60
_LAST_REFRESH_AT: dict[str, float] = {}  # batch_id hex -> monotonic 时间戳


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def notice_chat_id() -> str:
    """批次卡目标群（默认=速递总卡群；env > DB 活行 > 代码默认）。"""
    return _app_config_store.get_str(
        "SAFETY_FACILITY_NOTICE_CHAT_ID",
        "oc_f05532603bd7682fc520929c01aca88d",
    )


def reset_throttle() -> None:
    """测试隔离用：清空限流窗口。"""
    _LAST_REFRESH_AT.clear()


def _at(open_id: str | None, name: str | None = None) -> str:
    """飞书卡片 markdown @mention（无 open_id 退化为纯文本姓名）。"""
    if open_id:
        return f'<at user_id="{open_id}"></at>'
    return name or ""


async def _visible_tasks(
    session: AsyncSession, department: str, open_batch_id: Any | None
) -> list[FacilityCheckTask]:
    """部门当前周期参与批次卡的任务。

    周期口径 = 未挂钩任务（batch_id 为空：本轮新派发/reopen 归队）+ 挂在
    本 open 批次上的任务（含本周期已闭环条目，供进度展示）。已归档批次的
    历史任务不进新卡（DESIGN §4.5「全闭环归档后新临期任务→新开一张批次卡」，
    卡不随周期无界膨胀、旧任务 batch_id 不被改写污染审计）。
    """
    stmt = select(FacilityCheckTask).where(
        FacilityCheckTask.department == department,
        FacilityCheckTask.is_deleted.is_(False),
        FacilityCheckTask.status != "cancelled",
        or_(
            FacilityCheckTask.batch_id.is_(None),
            *(
                [FacilityCheckTask.batch_id == open_batch_id]
                if open_batch_id is not None
                else []
            ),
        ),
    )
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


# 待办状态文案按台账类型（2026-10-20 拍板：消防器材到期=待更换；
# 其余台账接入时再定各自口径，默认待闭环）
_PENDING_TEXT: dict[str, str] = {"fire_equipment": "⏳ 待更换"}


def _task_line(task: FacilityCheckTask, today: date, record_url: str | None = None) -> str:
    remaining = (task.due_date - today).days
    if remaining < 0:
        remain_txt = f"逾期 {abs(remaining)} 天"
    else:
        remain_txt = f"剩 {remaining} 天"
    status_txt = (
        _PENDING_TEXT.get(task.biz_type, "⏳ 待闭环")
        if task.status != "closed" else "✅ 已闭环"
    )
    link = f"｜[📋记录]({record_url})" if record_url else ""
    return (
        f"- {task.equipment_no or task.ledger_key[:8]}｜{task.location or '-'}｜"
        f"{task.due_date.isoformat()}｜{remain_txt}｜{status_txt}{link}"
    )


# 租户域名（与 feishu/progress_card.py 记录直达链接同款拼法）
_FEISHU_BASE_URL = "https://j0eukrlohu.feishu.cn"


def record_urls_for(tasks: list[FacilityCheckTask]) -> dict[str, str]:
    """任务列表 → 记录直达链接（key=f"{biz_type}:{ledger_key}"）。

    按 biz_type 解析台账连接（store.get_connection 同步带 TTL 缓存）；
    连接未登记/不完整 → 该类任务无链接（明细行退化为无链接，不影响发卡）。
    """
    from app.modules.safety.bitable_config.store import store as _conn_store
    from app.modules.safety.facilities.ledger import BIZ_TO_KIND, DOMAIN

    urls: dict[str, str] = {}
    conns: dict[str, Any] = {}
    for t in tasks:
        bt = t.biz_type
        if bt not in conns:
            conn = _conn_store.get_connection(DOMAIN, BIZ_TO_KIND.get(bt, ""))
            conns[bt] = (
                conn if conn is not None and conn.app_token and conn.table_id else None
            )
        conn = conns[bt]
        if conn is None:
            continue
        urls[f"{bt}:{t.ledger_key}"] = (
            f"{_FEISHU_BASE_URL}/base/{conn.app_token}"
            f"?table={conn.table_id}&record={t.ledger_key}"
        )
    return urls


def build_batch_card(
    department: str,
    tasks: list[FacilityCheckTask],
    *,
    today: date,
    escalation_md: str = "",
    escalate_open_ids: list[str] | None = None,
    record_urls: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    """部门跟进提醒卡（全量重建）：头部合计 + 分组分区 + @责任人 + 表格指引。

    2026-10-20 拍板口径：标题=「设备设施跟进提醒」；头部只显示剩余合计
    （「{部门} 合计 N 件」），明细只列未完成项（已闭环不再展示）。
    返回 (card_dict, title)；全部闭环时置绿「✅ 全部完成」后归档。
    record_urls：明细行追加多维表格记录直达链接（record_urls_for 产出，
    缺省无链接——纯函数不触 store，测试/未配置场景友好）。
    """
    open_tasks = [t for t in tasks if t.status == "issued"]
    all_done = bool(tasks) and not open_tasks

    groups: dict[str, list[FacilityCheckTask]] = {}
    for t in open_tasks:
        groups.setdefault(t.group_key, []).append(t)

    title = f"🔧 {department} 设备设施跟进提醒"
    header_lines: list[str] = []
    if all_done:
        header_lines.append(f"## ✅ 全部完成｜{department}（累计 {len(tasks)} 件）")
        header_template = "green"
    else:
        header_lines.append(f"## {department} 合计 **{len(open_tasks)}** 件")
        header_template = "blue"
    if escalation_md:
        header_lines.append("")
        header_lines.append(escalation_md)

    detail_lines: list[str] = []
    links = record_urls or {}
    for group_key in sorted(groups):
        items = groups[group_key]
        detail_lines.append(f"**{group_key} {len(items)} 件**")
        detail_lines.extend(
            _task_line(t, today, links.get(f"{t.biz_type}:{t.ledger_key}"))
            for t in items
        )
        detail_lines.append("")

    mention_ids = {t.assignee_open_id for t in open_tasks if t.assignee_open_id}
    mention_ids.update(escalate_open_ids or [])
    tail: list[str] = []
    if mention_ids:
        tail.append("责任人：" + " ".join(sorted(_at(mid) for mid in mention_ids)))
    tail.append(
        "<font color='grey'>校验完成后请在多维表格中更新校验时间（下次/上次校验日期），"
        "任务将自动闭环；本卡随进度自动刷新</font>"
    )

    content = "\n".join(header_lines + tail)
    elements: list[dict[str, Any]] = [
        {
            "tag": "collapsible_panel",
            "expanded": not all_done,
            "border": {"color": "grey", "corner_radius": "5px"},
            "margin": "6px 0px 0px 0px",
            "header": {"title": {"tag": "plain_text", "content": "📋 分组明细"}},
            "elements": [{"tag": "markdown", "content": "\n".join(detail_lines)}],
        }
    ] if detail_lines else []
    card = build_card_dict(title, content, header_template, elements)
    return card, title


def _throttled(batch_id: Any, *, now: float | None) -> bool:
    if now is not None:  # 测试注入时钟
        key = str(batch_id)
        last = _LAST_REFRESH_AT.get(key)
        if last is not None and now - last < PATCH_THROTTLE_SECONDS:
            return True
        _LAST_REFRESH_AT[key] = now
        return False
    key = str(batch_id)
    last = _LAST_REFRESH_AT.get(key)
    mono = time.monotonic()
    if last is not None and mono - last < PATCH_THROTTLE_SECONDS:
        return True
    _LAST_REFRESH_AT[key] = mono
    return False


async def refresh_department_batch(
    session: AsyncSession,
    department: str,
    *,
    sender: Any = None,
    updater: Any = None,
    chat_id: str | None = None,
    now: float | None = None,
    today: date | None = None,
    escalation_md: str = "",
    escalate_open_ids: list[str] | None = None,
) -> dict[str, Any]:
    """部门滚动批次卡刷新（新发 / 原地 PATCH / 全闭环置绿归档）。

    Returns: {"action": "sent|patched|throttled|archived|noop", ...}
    失败只告警不抛（通知绝不阻塞派发/闭环主链路）。
    """
    today = today or _bj_today()
    sender = sender if sender is not None else send_group_card
    updater = updater if updater is not None else update_card
    chat = chat_id if chat_id is not None else notice_chat_id()

    batch = (
        await session.execute(
            select(FacilityNoticeBatch).where(
                FacilityNoticeBatch.department == department,
                FacilityNoticeBatch.status == "open",
                FacilityNoticeBatch.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    tasks = await _visible_tasks(
        session, department, batch.id if batch is not None else None
    )

    if not tasks:
        if batch is not None:  # 兜底：任务全没了（极端）→ 归档
            batch.status = "archived"
            _LAST_REFRESH_AT.pop(str(batch.id), None)
        return {"action": "noop"}

    open_n = sum(1 for t in tasks if t.status == "issued")
    card, title = build_batch_card(
        department, tasks, today=today,
        escalation_md=escalation_md, escalate_open_ids=escalate_open_ids,
        record_urls=record_urls_for(tasks),
    )

    # 已有进行中卡 → 限流后原地 PATCH；无 → 新发建批次
    if batch is not None:
        if _throttled(batch.id, now=now):
            return {"action": "throttled", "batch_id": str(batch.id)}
        if batch.card_message_id and await updater(batch.card_message_id, card):
            batch.open_count = open_n
            batch.total_count = len(tasks)
            batch.last_refreshed_at = datetime.now(UTC)
            action = "patched"
        else:
            # 旧卡已删（PATCH 失败）→ 降级重发新卡
            msg_id = await sender(
                chat_id=chat, title=title, content=card["body"]["elements"][0]["content"],
                elements=card["body"]["elements"][1:], header_template=card["header"]["template"],
            )
            if not msg_id:
                logger.warning("设施批次卡重发失败: dept=%s", department)
                return {"action": "failed"}
            batch.card_message_id = msg_id
            batch.open_count = open_n
            batch.total_count = len(tasks)
            batch.last_refreshed_at = datetime.now(UTC)
            action = "resent"
    else:
        msg_id = await sender(
            chat_id=chat, title=title, content=card["body"]["elements"][0]["content"],
            elements=card["body"]["elements"][1:], header_template=card["header"]["template"],
        )
        if not msg_id:
            logger.warning("设施批次卡发送失败: dept=%s", department)
            return {"action": "failed"}
        batch = FacilityNoticeBatch(
            department=department,
            card_message_id=msg_id,
            total_count=len(tasks),
            open_count=open_n,
            first_sent_at=datetime.now(UTC),
            last_refreshed_at=datetime.now(UTC),
        )
        session.add(batch)
        await session.flush()
        _throttled(batch.id, now=now)  # 新发同样起表：窗口内的后续刷新并入本次
        action = "sent"

    # 全闭环 → 置绿（本次刷新已带 ✅ 头）+ 归档停更；顺手清限流登记
    if open_n == 0:
        batch.status = "archived"
        _LAST_REFRESH_AT.pop(str(batch.id), None)
        action = "archived"

    # 批内任务补挂 batch_id（新派发并入原卡 / reopen 清链后重新归队）
    for t in tasks:
        if t.batch_id != batch.id:
            t.batch_id = batch.id
    return {"action": action, "batch_id": str(batch.id), "open": open_n, "total": len(tasks)}


# ── 派发/闭环通知钩子（dispatch 与 closure 的默认实装）──────────────


class NoopNotifier:
    """空通知（测试注入；生产缺省走真实钩子）。"""

    async def on_dispatched(
        self, session: AsyncSession, departments: list[str], *, today: date
    ) -> None:
        return None

    async def on_tasks_changed(
        self, session: AsyncSession, departments: list[str]
    ) -> None:
        return None


class FacilitiesNotifier(NoopNotifier):
    """真实通知钩子：派发后/闭环后按部门刷新滚动批次卡（限流防刷屏）。

    注意 session 事务边界归调用方——刷新只 mutate 批次行，随主事务落库。
    """

    def __init__(self, *, sender: Any = None, updater: Any = None, chat_id: str | None = None):
        self._sender = sender
        self._updater = updater
        self._chat_id = chat_id

    async def _refresh_many(self, session: AsyncSession, departments: list[str]) -> None:
        for dept in departments:
            try:
                await refresh_department_batch(
                    session, dept,
                    sender=self._sender, updater=self._updater, chat_id=self._chat_id,
                )
            except Exception:
                logger.warning("设施批次卡刷新失败（不影响主链路）: dept=%s", dept, exc_info=True)

    async def on_dispatched(
        self, session: AsyncSession, departments: list[str], *, today: date
    ) -> None:
        await self._refresh_many(session, departments)

    async def on_tasks_changed(
        self, session: AsyncSession, departments: list[str]
    ) -> None:
        await self._refresh_many(session, departments)


# ── 速递格子 facility_check ────────────────────────────────────────


def build_digest_cell_payload(
    *,
    open_total: int,
    overdue: int,
    due_30d: int,
    top_overdue: list[dict[str, Any]],
    incomplete: int,
    unresolved_owner: int,
) -> DigestCell:
    """全厂口径速递格子（分桶计数 + 逾期 Top + ⚪ 信息不全倒逼补录）。"""
    lines: list[str] = []
    if overdue:
        lines.append("**逾期 Top**（红档=逾期>7 天）：")
        for item in top_overdue[:5]:
            flag = "🔴" if item["over_days"] > 7 else "🟠"
            lines.append(
                f"- {flag} {item['department']}｜{item['equipment_no']}｜"
                f"{item['group_key']}｜逾期 {item['over_days']} 天"
            )
    else:
        lines.append("今日无逾期校验任务")
    if incomplete or unresolved_owner:
        lines.append("")
        lines.append(
            f"⚪ 台账信息不全 {incomplete} 行（缺编号/缺锚点，无法派任务）；"
            f"责任人解析失败 {unresolved_owner} 条"
        )
        lines.append("请在台账补录编号与校验日期（下次或上次+周期）")
    detail = "\n".join(lines)

    tone = "red" if overdue else ("orange" if open_total else "green")
    return DigestCell(
        tag_color=tone,
        tag_text="设施校验",
        title="设施校验任务速递",
        stats=(
            f"**待闭环 {open_total}** ｜ 逾期 **{overdue}** ｜ 30 天内到期 {due_30d}"
        ),
        zone="闭环口径：责任人在多维表格更新校验时间即自动闭环",
        detail=detail,
    )


async def push_digest_cell(
    cell: DigestCell,
    *,
    today: date | None = None,
    chat_id: str | None = None,
    store: Any = None,
    sender: Any = None,
    updater: Any = None,
) -> bool:
    """投递速递格子（upsert_daily_digest fail-open：失败不影响派发主链路）。"""
    today = today or _bj_today()
    try:
        return await upsert_daily_digest(
            today, DIGEST_KEY, cell,
            chat_id=chat_id, store=store, sender=sender, updater=updater,
        )
    except Exception:
        logger.warning("设施校验速递格子投递失败（不影响派发）", exc_info=True)
        return False


__all__ = [
    "DIGEST_KEY",
    "FacilitiesNotifier",
    "NoopNotifier",
    "build_batch_card",
    "build_digest_cell_payload",
    "notice_chat_id",
    "push_digest_cell",
    "refresh_department_batch",
    "reset_throttle",
]
