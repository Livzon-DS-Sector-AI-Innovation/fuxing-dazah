"""「安全速递」总卡：每日一张，各报告推送时滚动追加格子（飞书 PATCH 更新）。

设计（2026-09-15 与需求方确认）：
- 一张总卡发到安全AI创新交流群，每个日报占一个「格子」：彩色标签 + 报告名 +
  概览统计 + 右侧图标，格子内嵌默认收起的「查看详情」折叠面板（点击展开明细）
- 存储：Redis hash ``safety:daily_digest:{date}``（field=报告 key，TTL 7 天），
  卡片 message_id 存 ``safety:daily_digest:card:{date}``
- 滚动更新：首个报告创建卡片，后续报告把新格子加进同一张卡（PATCH 全量重建）
- 顺序固定（CELL_ORDER），当天未产生的报告自动缺席
- 任何异常只告警返回 False——总卡失败绝不影响报告自身的推送
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.redis import get_redis
from app.modules.safety.feishu.notification import (
    build_card_dict,
    send_group_card,
    update_card,
)

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def digest_enabled() -> bool:
    """总卡开关（默认开启；置 false 各报告只发自己的卡片，不汇总）。"""
    raw = (os.getenv("SAFETY_DAILY_DIGEST_ENABLED") or "").strip().lower()
    return not raw or raw in _TRUE


# 发送目标：安全AI创新交流群（可用环境变量覆盖）
DIGEST_CHAT_ID = os.getenv(
    "SAFETY_DAILY_DIGEST_CHAT_ID", "oc_f05532603bd7682fc520929c01aca88d",
)

_KEY = "safety:daily_digest:{date}"
_MSG_KEY = "safety:daily_digest:card:{date}"
_TTL_SECONDS = 7 * 86400
# 单格明细字符上限：7 格 × 1.6K + 结构 ≈ 15KB，留足 30KB 消息上限余量
_DETAIL_MAX_CHARS = 1600

# 格子固定展示顺序（当天缺席的报告跳过）
CELL_ORDER: list[str] = [
    "special_op", "workticket", "fire_alarm", "central_alarm",
    "chemical_daily", "chemical_weekly", "hazard_bulletin",
]


@dataclass
class DigestCell:
    """一个日报格子的内容。"""

    tag_color: str      # text_tag 颜色枚举（red/blue/orange/indigo/yellow/green...）
    tag_text: str       # 标签文字（如「消防报警」）
    title: str          # 报告名（如「消防报警日报」）
    stats: str          # 概览统计行（markdown，核心数字加粗）
    zone: str           # 一句话重点（灰字，可空）
    detail: str         # 详情 markdown（超长自动截断）


# 同日多报告并发推送时串行化「读格子 → 建卡 → PATCH」（单进程内足够）
_lock = asyncio.Lock()


def _bj_today() -> date:
    """北京时间今天（调度任务都在 UTC+8 语义下运行）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _digest_key(d: date) -> str:
    return _KEY.format(date=d.isoformat())


def _cap_detail(text: str, limit: int = _DETAIL_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…（明细过长已截断）"


async def upsert_daily_digest(
    report_date: date,
    key: str,
    cell: DigestCell,
    *,
    chat_id: str | None = None,
    store: Any = None,
    sender: Any = None,
    updater: Any = None,
) -> bool:
    """保存格子并创建/更新当日总卡。

    Args:
        report_date: 报告日期（北京时间日）
        key: 报告标识（CELL_ORDER 之一）
        cell: 格子内容
        chat_id / store / sender / updater: 测试与覆盖用接缝
            （默认真实 Redis / send_group_card / update_card）

    Returns:
        True 表示总卡已包含该格子；False 表示失败（只告警，不抛异常）
    """
    if not digest_enabled():
        return False
    store = store if store is not None else await get_redis()
    sender = sender if sender is not None else send_group_card
    updater = updater if updater is not None else update_card
    chat = chat_id or DIGEST_CHAT_ID
    try:
        payload = asdict(cell)
        payload["detail"] = _cap_detail(payload["detail"])
        async with _lock:
            await store.hset(
                _digest_key(report_date), key, json.dumps(payload, ensure_ascii=False),
            )
            await store.expire(_digest_key(report_date), _TTL_SECONDS)
            cells = await _load_cells(store, report_date)
            card, title, subtitle, greeting = await _build_card(report_date, cells)
            msg_id_key = _MSG_KEY.format(date=report_date.isoformat())
            msg_id = await store.get(msg_id_key)
            updated = False
            if msg_id:
                updated = await updater(msg_id, card)
                if not updated:
                    logger.warning("安全速递总卡 PATCH 失败，转重建: %s", msg_id)
            if not updated:
                # sender 内部会把 greeting 作为首个元素重拼，这里剥掉已含的问候元素
                new_id = await sender(
                    chat_id=chat,
                    title=title,
                    content=greeting,
                    elements=card["body"]["elements"][1:],
                    header_template="blue",
                    subtitle=subtitle,
                )
                if not new_id:
                    logger.warning("安全速递总卡创建失败: date=%s", report_date)
                    return False
                await store.set(msg_id_key, new_id, ex=_TTL_SECONDS)
            return True
    except Exception:
        logger.warning("安全速递总卡更新异常（不影响报告推送）", exc_info=True)
        return False


async def _load_cells(store: Any, report_date: date) -> dict[str, dict[str, Any]]:
    raw = await store.hgetall(_digest_key(report_date))
    cells: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if key not in CELL_ORDER:
            continue
        try:
            cells[key] = json.loads(value)
        except (TypeError, ValueError):
            logger.warning("安全速递格子数据损坏，跳过: %s", key)
    return cells


async def _build_card(
    report_date: date,
    cells: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str, str, str]:
    """构建总卡；超 25KB 时逐级收缩明细再超限则只留概览。"""
    title = f"📌 安全速递 | {report_date.isoformat()}"
    subtitle = f"今日已汇总 {len(cells)} 项安全动态"
    greeting = "Hi，今日安全动态汇总，点各条目的「查看详情」展开明细："

    for detail_limit in (_DETAIL_MAX_CHARS, 400, 0):
        elements = await _build_elements(cells, detail_limit)
        card = build_card_dict(title, greeting, "blue", elements, subtitle=subtitle)
        size = len(json.dumps(card, ensure_ascii=False).encode("utf-8"))
        if size <= 25_000:
            return card, title, subtitle, greeting
        logger.warning("安全速递总卡 %d 字节超限，明细收缩至 %d 字符重试", size, detail_limit)
    return card, title, subtitle, greeting


async def _build_elements(
    cells: dict[str, dict[str, Any]],
    detail_limit: int,
) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for key in CELL_ORDER:
        cell = cells.get(key)
        if not cell:
            continue
        elements.append(await _cell_element(cell, detail_limit))
    if not elements:
        elements.append({"tag": "markdown", "content": "_今日暂无安全动态_"})
    return elements


async def _cell_element(
    cell: dict[str, Any],
    detail_limit: int,
) -> dict[str, Any]:
    """一个日报格子：灰底概览卡 + 内嵌「查看详情」折叠面板（不带图片）。"""
    overview = [
        f"<text_tag color='{cell['tag_color']}'>{cell['tag_text']}</text_tag>"
        f" **{cell['title']}**",
        cell["stats"],
    ]
    if cell.get("zone"):
        overview.append(f"<font color='grey'>{cell['zone']}</font>")

    detail = cell["detail"]
    if detail_limit and len(detail) > detail_limit:
        detail = detail[:detail_limit].rstrip() + "\n…（明细过长已截断）"
    panel: dict[str, Any] | None = None
    if detail:
        panel = {
            "tag": "collapsible_panel",
            "expanded": False,
            "border": {"color": "grey", "corner_radius": "5px"},
            "margin": "6px 0px 0px 0px",
            "header": {"title": {"tag": "plain_text", "content": "📄 查看详情"}},
            "elements": [{"tag": "markdown", "content": detail}],
        }

    left_elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": "\n".join(overview)}
    ]
    if panel is not None:
        left_elements.append(panel)

    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "grey",
        "margin": "0px 0px 8px 0px",
        "columns": [{
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_align": "center",
            "padding": "8px 4px 8px 12px",
            "elements": left_elements,
        }],
    }
