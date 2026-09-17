"""效期到期自动冻结（分期D Ticket 04）。

每日 00:15 FIXED_TIME 任务扫描 ``expiry_date <= 今日 且 status='normal'`` 的
库存行，批量置 frozen 并写状态流转日志（operator 为空=系统），随后发飞书卡片
到 ``WAREHOUSE_ALERT_CHAT_ID``（未配置则跳过通知，不影响冻结本身）。

幂等性：只扫 normal 行，已冻结/待检行天然跳过，重复执行不会重复变更。
窗口守卫复用快照窗口（00:00-06:00，同 snapshot/intelligence 模块——
FIXED_TIME 任务在窗口外重启会误触发，宁夏仓实测教训）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseStock, WarehouseStockStatusLog

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

AUTO_FREEZE_REASON = "效期到期自动冻结"


async def freeze_expired_stocks(
    db: AsyncSession, *, today: date | None = None
) -> list[dict[str, Any]]:
    """冻结全部已过期且仍为 normal 的库存行，返回变更明细（不 commit，由调用方决定）。"""
    today = today or datetime.now(CN_TZ).date()
    stmt = select(WarehouseStock).where(
        WarehouseStock.is_deleted == False,  # noqa: E712
        WarehouseStock.status == "normal",
        WarehouseStock.expiry_date <= today,
    )
    rows = list((await db.execute(stmt)).scalars().all())
    changed: list[dict[str, Any]] = []
    for stock in rows:
        stock.status = "frozen"
        db.add(
            WarehouseStockStatusLog(
                stock_id=stock.id,
                old_status="normal",
                new_status="frozen",
                reason=AUTO_FREEZE_REASON,
                operator_id=None,
            )
        )
        changed.append(
            {
                "stock_id": str(stock.id),
                "material_code": stock.material_code,
                "material_name": stock.material_name,
                "batch_no": stock.batch_no,
                "location_name": stock.location_name,
                "expiry_date": stock.expiry_date.isoformat() if stock.expiry_date else "",
                "quantity": float(stock.quantity),
            }
        )
    if changed:
        logger.info("效期自动冻结：%d 行置 frozen", len(changed))
    return changed


def build_freeze_card(changed: list[dict[str, Any]]) -> dict[str, Any]:
    """构建效期冻结通知卡片（飞书 JSON 2.0，与 gateway 卡片同构）。"""
    from app.modules.warehouse.agent.cards import build_card

    lines = "\n".join(
        f"- **{row['material_code']}** {row['material_name']} · 批次 {row['batch_no'] or '-'}"
        f" · {row['location_name'] or '-'} · 数量 {row['quantity']}"
        f" · 效期 {row['expiry_date'] or '-'}"
        for row in changed[:20]
    )
    more = f"\n- …等共 {len(changed)} 行" if len(changed) > 20 else ""
    markdown = (
        f"以下 **{len(changed)}** 行库存已过效期，系统已自动冻结（frozen）：\n{lines}{more}\n"
        "如需恢复请走「解冻」流程（frozen→normal）并复检效期。"
    )
    return build_card(
        title="效期到期自动冻结提醒",
        template="red",
        elements=[{"tag": "markdown", "content": markdown}],
    )


async def notify_expired_freeze(
    changed: list[dict[str, Any]], *, dry_run: bool | None = None
) -> bool:
    """发送冻结通知到配置群；未配置 chat_id 或无变更时跳过，失败不抛异常。"""
    if not changed:
        return False
    chat_id = get_settings().WAREHOUSE_ALERT_CHAT_ID.strip()
    if not chat_id:
        logger.info(
            "效期冻结通知跳过：WAREHOUSE_ALERT_CHAT_ID 未配置（本次冻结 %d 行）", len(changed)
        )
        return False

    card = build_freeze_card(changed)
    message_id = await notification.send_card(chat_id, card, dry_run=dry_run)
    if message_id:
        logger.info("效期冻结通知已发送: chat_id=%s message_id=%s", chat_id, message_id)
        return True
    logger.warning("效期冻结通知发送失败: chat_id=%s", chat_id)
    return False
