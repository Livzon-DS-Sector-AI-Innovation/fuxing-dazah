"""设备模块飞书卡片回调 — 验收卡片按钮处理与平台注册。

业务逻辑原驻平台层 event_handler.py，迁入本模块后：
- handle_work_order_verify：处理验收卡片 approve/reject 按钮
- register_feishu_callbacks：应用启动时向平台注册（见 main.py 接线）
"""

import logging
import uuid as _uuid
from typing import Any

from sqlalchemy import select as sa_select

from app.core.database import async_session_factory
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import WorkOrder
from app.modules.equipment.schemas import WorkOrderVerify
from app.modules.equipment.service import verify_work_order
from app.platform.identity.models import User
from app.platform.integrations.feishu.event_handler import (
    register_card_action_handler,
)
from app.platform.integrations.feishu.notification import send_user_card

logger = logging.getLogger(__name__)


async def handle_work_order_verify(
    payload: dict[str, Any], user_id: str,
) -> None:
    """处理验收卡片按钮点击（approve/reject）。"""
    action = payload.get("action")
    work_order_id = payload.get("work_order_id")

    if action == "approve":
        result = "合格"
    elif action == "reject":
        result = "不合格"
    else:
        logger.error("无效的卡片 action: %s", payload)
        return

    if not work_order_id:
        logger.error("卡片回调缺少 work_order_id: %s", payload)
        return

    async with async_session_factory() as db:
        # 查找操作用户
        user = None
        if user_id:
            user_result = await db.execute(
                sa_select(User).where(
                    User.feishu_user_id == user_id,
                    User.is_deleted == False,  # noqa: E712
                )
            )
            user = user_result.scalar_one_or_none()

        if not user:
            logger.warning("卡片回调：未找到飞书用户 %s", user_id)
            return

        # 查找工单 — FOR UPDATE 防并发重复验收
        wo = (
            await db.execute(
                sa_select(WorkOrder)
                .where(
                    WorkOrder.id == _uuid.UUID(work_order_id),
                    WorkOrder.is_deleted == False,  # noqa: E712
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not wo:
            if user.feishu_user_id:
                await send_user_card(
                    open_id=user.feishu_user_id,
                    title="❌ 工单不存在",
                    receive_id_type="user_id",
                    content=f"工单 {work_order_id} 不存在或已删除。",
                )
            return

        if wo.status != "待验收":
            if user.feishu_user_id:
                await send_user_card(
                    open_id=user.feishu_user_id,
                    title="⚠️ 无法验收",
                    receive_id_type="user_id",
                    content=(
                        f"工单 **{wo.work_order_no}** 当前状态为「{wo.status}」，"
                        "只有「待验收」的工单才能验收。"
                    ),
                )
            return

        label = "验收通过" if result == "合格" else "退回"
        try:
            verify_data = WorkOrderVerify(
                result=result,
                remark=f"通过飞书卡片{label}",
            )
            ctx = EquipmentAccessContext(user=user, data_scope="all")
            await verify_work_order(db, wo.id, ctx, verify_data)
            await db.commit()
        except Exception as e:
            logger.exception("飞书卡片验收失败: %s", e)
            if user.feishu_user_id:
                await send_user_card(
                    open_id=user.feishu_user_id,
                    title="❌ 操作失败",
                    receive_id_type="user_id",
                    content=f"验收操作失败：{e}",
                )
            return

        # ponytail: 操作反馈，只发关键信息
        eq_name = wo.equipment.name if wo.equipment else ""
        if user.feishu_user_id:
            await send_user_card(
                open_id=user.feishu_user_id,
                title=f"✅ {label}",
                receive_id_type="user_id",
                content=(
                    f"工单 **{wo.work_order_no}**（{eq_name}）\n"
                    f"已{label}"
                ),
            )


def register_feishu_callbacks() -> None:
    """应用启动时调用，注册设备模块的飞书卡片回调。"""
    register_card_action_handler("approve", handle_work_order_verify)
    register_card_action_handler("reject", handle_work_order_verify)
