"""链6：复训到期扫描单轮——培训表「下次复训日期」30 天窗口（含已逾期）。

提醒为确定性文本（非 AI 内容，不受链5推送开关管控）；出口配置键
SAFETY_TB_RETRAINING_DUE_CHAT_ID（真实群发送随启用批接入，当前为占位
记录），未配置时仅日志——域页 retraining_due_30d 统计卡兜底可见。
口径差异：本提醒 30 天窗口**含已逾期行**（催办语义），域页统计卡只计
未来 0-30 天，有逾期行时两边数字会不同（各自口径，非 bug）。
消费方：scheduled.py FIXED_TIME 日任务（08:20 北京）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior.common import BJ_TZ, Opener, bj_today

logger = logging.getLogger(__name__)

DUE_CHAT_KEY = "SAFETY_TB_RETRAINING_DUE_CHAT_ID"
_WINDOW_DAYS = 30

_READ_FIELDS = ("培训名称", "状态", "下次复训日期", "组织部门")


def build_digest(rows: list[dict[str, Any]], today: date) -> str:
    """到期清单 → 提醒文本（确定性生成，按剩余天数升序=最急在前）。"""
    lines = [f"【复训到期提醒】{today.isoformat()}（30 天窗口共 {len(rows)} 项）"]
    for r in rows:
        due: date = r["due"]
        name: str = r["name"]
        if due < today:
            lines.append(f"- {name}：已逾期 {(today - due).days} 天（复训日 {due}）")
        else:
            lines.append(f"- {name}：剩余 {(due - today).days} 天（复训日 {due}）")
    return "\n".join(lines)


async def run_retraining_due_round(
    *,
    opener: Opener | None = None,
    today: date | None = None,
    send_digest: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """单轮扫描：窗口内到期行 → 汇总提醒（无到期不发送）。"""
    open_client = opener or bd_reader.resolve_client
    try:
        training_client = open_client("training_behavior", "training")
    except BitableConfigError as exc:
        logger.info("复训到期扫描跳过（域未接入）: %s", exc)
        return {"status": "not_connected", "due": 0}

    today = today or bj_today()
    records = await training_client.list_all_records(
        field_names=list(_READ_FIELDS), strict=True
    )
    hits: list[dict[str, Any]] = []
    for record in records:
        fields = record.get("fields") or {}
        if bd_fields.select(fields, "状态") == "已取消":
            continue
        dt = bd_fields.datetime_ms(fields, "下次复训日期")
        if dt is None:
            continue
        due = dt.astimezone(BJ_TZ).date()
        if (due - today).days > _WINDOW_DAYS:
            continue  # 窗口外（未来 >30 天）；已逾期为负数天然命中
        hits.append({
            "name": bd_fields.text(fields, "培训名称") or "（未命名培训）",
            "due": due,
        })
    hits.sort(key=lambda r: r["due"])
    overdue = sum(1 for r in hits if r["due"] < today)

    if not hits:
        return {"status": "ok", "due": 0, "overdue": 0}

    digest = build_digest(hits, today)
    sender = send_digest or _default_send_digest
    try:
        await sender(digest)
    except Exception as exc:  # 发送失败不影响统计口径
        logger.warning("复训到期提醒发送失败: %s", exc)
    return {"status": "ok", "due": len(hits), "overdue": overdue}


async def _default_send_digest(text: str) -> None:
    """发送出口：目标群未配置时仅日志（域页统计卡兜底可见）。"""
    from app.modules.safety.app_config.store import store

    chat_id = store.get_str(DUE_CHAT_KEY, None)
    if not chat_id:
        logger.info("复训到期提醒（%s 未配置仅日志）:\n%s", DUE_CHAT_KEY, text)
        return
    # 真实群发送随启用批接入（复用既有 chat_sender 通道）
    logger.info(
            "复训到期提醒出口为占位（未实发，chat=%s；真实发送随启用批接入）",
            chat_id,
        )
