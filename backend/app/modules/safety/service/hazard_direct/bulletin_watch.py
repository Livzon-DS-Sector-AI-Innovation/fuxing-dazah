"""④ 督办通报值守轮询 — 周四 13:00-18:00 变化即刷新「安全速递」格子。

诉求（2026-10-15）：周四通报发出后，当日下午隐患状态若有变化（关闭 /
整改中 / 督办等级 / 进展更新 / 新增记录），速递格子要即时跟上，不等下周。

实现：值守窗口内每分钟重建通报内容（直读多维表格，strict 绕过查询缓存），
与当日速递格子现存 ``detail`` 逐字比对；有差异（或格子尚不存在，如 13:00
周任务失败）才投递——``upsert_daily_digest`` 是对当日总卡的原地 PATCH，
无变化不投递，避免无效请求与 sent_at 抖动。

窗口外跳过；总卡关闭（独立群卡模式）时值守会造成刷屏，同样跳过。
周任务仍是 13:00 的兜底首发（值守只管「变化增量」）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# 值守窗口：每周四 13:00（含）- 18:00（不含），北京时间
WATCH_DOW = 3  # 周四（weekday 口径：0=周一）
WATCH_START = time(13, 0)
WATCH_END = time(18, 0)

# 速递格子 key（与 bulletin.send_bulletin 投递用一致）
CELL_KEY = "hazard_bulletin"


def beijing_now() -> datetime:
    """当前北京时间（naive，UTC+8 语义与调度任务/daily_digest 对齐）。"""
    return datetime.now(UTC) + timedelta(hours=8)


def in_watch_window(now: datetime) -> bool:
    """是否处于周四 13:00-18:00 值守窗口（北京时间）。"""
    return now.weekday() == WATCH_DOW and WATCH_START <= now.time() < WATCH_END


async def run_bulletin_watch_once(
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """执行一轮值守检查。

    Returns:
        None：未动作（窗口外 / 总卡关闭 / 内容无变化）；
        投递结果 dict：检测到变化并已投递（``sent`` 表明成败）。
    """
    bj = now or beijing_now()
    if not in_watch_window(bj):
        return None

    from app.modules.safety.feishu.daily_digest import (
        cell_detail,
        digest_chat_id,
        digest_enabled,
    )
    if not digest_enabled():
        return None

    from app.modules.safety.service.hazard_direct.bulletin import (
        build_bulletin,
        deliver_bulletin,
    )

    content, stats = await build_bulletin()
    current = await cell_detail(bj.date(), CELL_KEY)
    if current == content:
        logger.debug("④ 值守轮询无变化 (total=%s)", stats.get("total"))
        return None

    delivered = await deliver_bulletin(content, stats, digest_chat_id())
    if delivered.get("sent"):
        logger.info("④ 值守轮询检测到变化，已刷新速递格子: %s", stats)
    else:
        logger.warning("④ 值守轮询刷新失败: %s", stats)
    return delivered


__all__ = ["CELL_KEY", "beijing_now", "in_watch_window", "run_bulletin_watch_once"]
