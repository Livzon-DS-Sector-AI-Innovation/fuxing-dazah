"""效期到期自动冻结（分期D Ticket 04 → V3.0 分期A Ticket 06 改造为先 Base 后镜像）。

每日 00:15 FIXED_TIME 任务扫描 ``expiry_date <= 今日 且 status='normal'`` 的
库存行，逐条**先写 Base（material_receipt.上一状态=不合格）再落本地 frozen**
（2B 定案；本地冻结标记仅展示镜像）。Base 写失败的条目跳过并记录，不回滚
已成功条目；本地不再单方面写状态。

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

from app.modules.warehouse import base_mirror
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseStock

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

AUTO_FREEZE_REASON = "效期到期自动冻结"


async def freeze_expired_stocks(
    db: AsyncSession, *, today: date | None = None
) -> dict[str, list[dict[str, Any]]]:
    """冻结全部已过期且仍为 normal 的库存行（先 Base 后本地，逐条容错）。

    返回 ``{"changed": [...变更明细], "skipped": [...跳过明细]}``（不 commit，
    由调用方决定）。Base 失败/定位失败的条目进 skipped，本地保持 normal，
    下轮扫描重试。
    """
    today = today or datetime.now(CN_TZ).date()
    stmt = select(WarehouseStock).where(
        WarehouseStock.is_deleted == False,  # noqa: E712
        WarehouseStock.status == "normal",
        WarehouseStock.expiry_date <= today,
    )
    rows = list((await db.execute(stmt)).scalars().all())
    changed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for stock in rows:
        detail = {
            "stock_id": str(stock.id),
            "material_code": stock.material_code,
            "material_name": stock.material_name,
            "batch_no": stock.batch_no,
            "location_name": stock.location_name,
            "expiry_date": stock.expiry_date.isoformat() if stock.expiry_date else "",
            "quantity": float(stock.quantity),
        }
        try:
            # 先写 Base 上一状态=不合格，成功后 helper 内落本地 frozen + 日志
            await base_mirror.apply_stock_status_base_first(
                db, stock, "frozen", reason=AUTO_FREEZE_REASON, operator_id=None
            )
        except base_mirror.BaseMirrorError as exc:
            logger.warning("效期冻结 Base 写失败，跳过该行: batch_no=%s err=%s", stock.batch_no, exc)
            skipped.append({**detail, "error": str(exc)})
            continue
        changed.append(detail)
    if changed:
        logger.info("效期自动冻结：%d 行先 Base 后本地置 frozen", len(changed))
    return {"changed": changed, "skipped": skipped}


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
    """发送冻结通知到配置群（DB→env 回退链，V3.0 分期A 替换 env 直读）。

    未配置目标或无变更时跳过，失败不抛异常。
    """
    if not changed:
        return False
    from app.modules.warehouse.ops_config.scheduler_store import scheduler_store

    chat_id = scheduler_store.get_alert_target() or ""
    if not chat_id:
        logger.info(
            "效期冻结通知跳过：告警目标未配置（本次冻结 %d 行）", len(changed)
        )
        return False

    card = build_freeze_card(changed)
    message_id = await notification.send_card(chat_id, card, dry_run=dry_run)
    if message_id:
        logger.info("效期冻结通知已发送: chat_id=%s message_id=%s", chat_id, message_id)
        return True
    logger.warning("效期冻结通知发送失败: chat_id=%s", chat_id)
    return False
