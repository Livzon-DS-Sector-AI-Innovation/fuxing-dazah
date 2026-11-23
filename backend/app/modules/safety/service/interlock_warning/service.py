"""编排：节奏锚 / 轮次 / 收件人聚合 / 发送 —— 唯一测试接缝。

节奏：每 GAP_DAYS 天一轮。每日 9:00 任务触发本函数，Redis 锚
safety:interlock_red:last_sent（值=上一轮执行日）gap<GAP_DAYS 即跳过；
首轮无锚即发，此后自动隔天对齐。锚在每轮执行后写入（与红色记录多寡解耦）。
Redis 不可用 → 本轮跳过（fail-closed 宁漏勿扰）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from . import cards
from .records import (
    ROLE_APPLICANT,
    ROLE_PROCESS_OWNER,
    ROLE_SAFETY_OWNER,
    RedRecord,
    filter_red_records,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Recipient:
    """一位收件人（同人一卡）：名下红色记录 + 其在每条中的角色。"""

    open_id: str
    name: str
    entries: tuple[tuple[RedRecord, tuple[str, ...]], ...] = field(default=())

_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

GAP_DAYS = 2
ANCHOR_KEY = "safety:interlock_red:last_sent"
ROUND_KEY_PREFIX = "safety:interlock_red:round:"

FetchFn = Callable[[], Awaitable[list[dict[str, Any]]]]
SendFn = Callable[..., Awaitable[Any]]


def bj_today() -> date:
    return datetime.now(_TZ_SHANGHAI).date()


async def _fetch_rows() -> list[dict[str, Any]]:
    """默认拉取全表（测试 monkeypatch 点；49 行小表全量+客户端过滤）。"""
    from app.modules.safety.service.bitable_direct import reader as bd_reader

    client = bd_reader.resolve_client("interlock_change", "approval")
    return await bd_reader.fetch_all_records(client)


async def _get_redis() -> Any:
    from app.core.redis import get_redis

    return await get_redis()


async def _send_dm(open_id: str, title: str, content: str, **kw: Any) -> Any:
    """默认发送（测试钉 notification.send_user_card 即可拦截）。"""
    from app.modules.safety.feishu import notification

    return await notification.send_user_card(open_id, title, content, **kw)


async def run_interlock_red_warning(
    *,
    dry_run: bool = False,
    fetch: FetchFn | None = None,
    redis: Any = None,
    send: SendFn | None = None,
    now: date | None = None,
) -> dict[str, Any]:
    """红色预警提醒一轮（接缝入口）。

    - dry_run：真拉取真构建，打印收件人+卡面，不发送、不写任何 Redis 键
    - fetch/redis/send：测试替身注入；缺省走模块级默认绑定
    - now：测试注入「今日」
    返回 stats（skipped_gap/skipped_redis 或完整计数）。
    """
    today = now or bj_today()
    if not dry_run:
        try:
            client = redis if redis is not None else await _get_redis()
            anchor = await client.get(ANCHOR_KEY)
        except Exception:
            logger.exception("interlock_red: Redis 不可用，本轮跳过（fail-closed）")
            return {"skipped_redis": True}
        if isinstance(anchor, str):
            try:
                gap = (today - date.fromisoformat(anchor)).days
            except ValueError:
                gap = None
            if gap is not None and gap < GAP_DAYS:
                logger.info(
                    "interlock_red: 距上轮 %s 天 < %d 天，本轮跳过（上轮 %s）",
                    gap, GAP_DAYS, anchor,
                )
                return {"skipped_gap": True, "last_sent": anchor}
    else:
        client = redis
    return await _execute_round(today, fetch=fetch, redis=client, send=send, dry_run=dry_run)


async def _execute_round(
    today: date,
    *,
    fetch: FetchFn | None,
    redis: Any,
    send: SendFn | None,
    dry_run: bool,
) -> dict[str, Any]:
    fetch_fn = fetch or _fetch_rows
    rows = await fetch_fn()
    reds = filter_red_records(rows, today=today)
    recipients, no_recipient = _aggregate_recipients(reds)
    record_url = _resolve_record_url()

    rounds: dict[str, int | None] = {}
    for rec in reds:
        rounds[rec.record_id] = await _peek_round(redis, rec.record_id)

    send_fn = send or _send_dm
    stats: dict[str, Any] = {
        "red": len(reds),
        "recipients": len(recipients),
        "sent": 0,
        "failed": 0,
        "skipped_no_recipient": no_recipient,
        "dry_run": dry_run,
    }
    sent_ok_records: set[str] = set()
    for person in recipients:
        title, content = cards.build_warning_card(
            person.name, person.entries, rounds=rounds, record_url=record_url
        )
        if dry_run:
            print(f"[dry_run] → {person.name}（{person.open_id}）\n{content}\n")
            continue
        ok = await send_fn(person.open_id, title, content, header_template="red")
        if ok:
            stats["sent"] += 1
            sent_ok_records.update(rec.record_id for rec, _ in person.entries)
        else:
            stats["failed"] += 1
            logger.warning(
                "interlock_red: 私发失败 %s（%s）", person.name, person.open_id
            )

    if not dry_run:
        # 轮次：仅当该记录本轮 ≥1 卡成功才计数（与卡面「第N次」一致）
        for rec in reds:
            if rec.record_id in sent_ok_records:
                try:
                    await redis.incr(ROUND_KEY_PREFIX + rec.record_id)
                except Exception:
                    logger.exception(
                        "interlock_red: 轮次 INCR 失败 %s（不致命）", rec.record_id
                    )
        await _cleanup_stale_round_keys(redis, {rec.record_id for rec in reds})
        try:
            await redis.set(ANCHOR_KEY, today.isoformat())
        except Exception:
            logger.exception("interlock_red: 节奏锚写入失败（下轮可能提前，注意观察）")
    return stats


def _resolve_record_url() -> Callable[[str], str] | None:
    """按 bitable_config 实际连接生成台账直链构造器（DB/registry 挂 → None 回落常量版）。"""
    try:
        from app.modules.safety.bitable_config.store import store

        view = store.get_connection("interlock_change", "approval")
        if view.app_token and view.table_id:
            return cards.record_url_builder(view.app_token, view.table_id)
    except Exception:
        logger.exception("interlock_red: 台账连接解析失败，卡面链接回落默认常量")
    return None


def _aggregate_recipients(
    reds: list,
) -> tuple[list[Recipient], int]:
    """三角色按 open_id 聚合去重（同人一卡、角色并列）；→ (收件人列表, 无收件人记录数)。"""
    no_recipient = 0
    by_open_id: dict[str, dict[str, Any]] = {}

    def _add(persons: tuple[tuple[str, str], ...], role: str, rec: Any) -> None:
        for name, open_id in persons:
            slot = by_open_id.setdefault(open_id, {"name": name, "entries": {}})
            entry = slot["entries"].setdefault(rec.record_id, {"rec": rec, "roles": []})
            if role not in entry["roles"]:
                entry["roles"].append(role)

    for rec in reds:
        _add(rec.applicants, ROLE_APPLICANT, rec)
        _add(rec.process_owners, ROLE_PROCESS_OWNER, rec)
        _add(rec.safety_owners, ROLE_SAFETY_OWNER, rec)
        if not (rec.applicants or rec.process_owners or rec.safety_owners):
            no_recipient += 1
            logger.warning(
                "interlock_red: 记录 %s 三角色（发起人/工艺/安全负责人）全空，跳过提醒",
                rec.code or rec.record_id,
            )

    recipients = [
        Recipient(
            open_id=open_id,
            name=slot["name"],
            entries=tuple(
                (entry["rec"], tuple(entry["roles"]))
                for entry in slot["entries"].values()
            ),
        )
        for open_id, slot in by_open_id.items()
    ]
    return recipients, no_recipient


async def _peek_round(redis: Any, record_id: str) -> int | None:
    """展示用轮次 = 当前计数值+1（首条=1）；无 Redis/异常 → None（卡面省略第N次）。"""
    if redis is None:
        return None
    try:
        value = await redis.get(ROUND_KEY_PREFIX + record_id)
        return int(value) + 1 if value else 1
    except Exception:
        return None


async def _cleanup_stale_round_keys(redis: Any, live_ids: set[str]) -> None:
    """记录已退出红色 → 清残留轮次键（否则重新变红会带着旧轮次计数）。"""
    if redis is None:
        return
    try:
        stale = [
            key
            async for key in redis.scan_iter(match=ROUND_KEY_PREFIX + "*")
            if key[len(ROUND_KEY_PREFIX):] not in live_ids
        ]
        if stale:
            await redis.delete(*stale)
            logger.info("interlock_red: 清理非红残留轮次键 %s 条", len(stale))
    except Exception:
        logger.exception("interlock_red: 轮次残留键清理失败（不致命）")
