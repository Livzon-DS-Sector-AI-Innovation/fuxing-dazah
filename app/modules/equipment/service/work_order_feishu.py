"""Work order Feishu bot service: query and complete work orders via chat."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.equipment import repository as repo
from app.modules.equipment.feishu.notification import send_user_card
from app.modules.equipment.schemas import WorkOrderComplete
from app.modules.equipment.service.work_order import complete_work_order

logger = logging.getLogger(__name__)


async def _find_user_by_user_id(
    db: AsyncSession, user_id: str
):
    """根据飞书 user_id（租户级）查找系统用户。"""
    from app.platform.identity.models import User

    result = await db.execute(
        select(User).where(
            User.feishu_user_id == user_id,
            User.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_user_work_orders(
    user_id: str,
    open_id: str,
) -> None:
    """查询并发送用户的未关闭工单列表。"""
    async with async_session_factory() as db:
        user = await _find_user_by_user_id(db, user_id)
        if not user:
            await send_user_card(
                open_id=open_id,
                title="❌ 未找到用户",
                receive_id_type="open_id",
                content="未找到与您的飞书账号关联的系统用户。",
            )
            return

        work_orders = await repo.get_user_work_orders(db, user.id)

    if not work_orders:
        await send_user_card(
            open_id=open_id,
            title="📋 我的工单",
            receive_id_type="open_id",
            content="当前没有未关闭的工单。",
        )
        return

    lines = [f"**共 {len(work_orders)} 个未关闭工单**\n"]
    for i, wo in enumerate(work_orders, 1):
        eq_name = wo.equipment.name if wo.equipment else "未知设备"
        lines.append(
            f"{i}. **{wo.work_order_no}** | {wo.order_type} | {wo.status}\n"
            f"   设备: {eq_name}"
        )

    lines.append(
        "\n---\n"
        "发送「完成 工单号 描述」可提交完成执行中的工单\n"
        "例: `完成 WO-20260615-0001 更换了密封圈`"
    )

    await send_user_card(
        open_id=open_id,
        title="📋 我的工单",
        receive_id_type="open_id",
        content="\n".join(lines),
    )


async def complete_work_order_by_no(
    user_id: str,
    open_id: str,
    work_order_no: str,
    repair_detail: str | None = None,
) -> None:
    """通过工单号完成工单。"""
    async with async_session_factory() as db:
        user = await _find_user_by_user_id(db, user_id)
        if not user:
            await send_user_card(
                open_id=open_id,
                title="❌ 未找到用户",
                receive_id_type="open_id",
                content="未找到与您的飞书账号关联的系统用户。",
            )
            return

        wo = await repo.get_work_order_by_no(db, work_order_no)
        if not wo:
            await send_user_card(
                open_id=open_id,
                title="❌ 工单不存在",
                receive_id_type="open_id",
                content=f"未找到工单 **{work_order_no}**，请检查工单号。",
            )
            return

        # 校验状态：必须是执行中
        if wo.status != "执行中":
            await send_user_card(
                open_id=open_id,
                title="❌ 无法完成",
                receive_id_type="open_id",
                content=(
                    f"工单 **{work_order_no}** 当前状态为「{wo.status}」，\n"
                    "只有「执行中」的工单才能提交完成。"
                ),
            )
            return

        # 校验权限：必须是当前用户的工单
        if wo.assignee_id != user.id:
            await send_user_card(
                open_id=open_id,
                title="❌ 无权限",
                receive_id_type="open_id",
                content=(
                    f"工单 **{work_order_no}** 的执行人不是您，\n"
                    "只能完成指派给自己的工单。"
                ),
            )
            return

        detail = repair_detail or "通过飞书机器人完成"
        data = WorkOrderComplete(repair_detail=detail)

        try:
            completed_wo = await complete_work_order(db, wo.id, data)
            await db.commit()
        except Exception as e:
            logger.exception("完成工单失败: %s", e)
            await send_user_card(
                open_id=open_id,
                title="❌ 完成失败",
                receive_id_type="open_id",
                content=f"工单 **{work_order_no}** 完成失败：{e}",
            )
            return

    eq_name = completed_wo.equipment.name if completed_wo.equipment else "未知设备"
    await send_user_card(
        open_id=open_id,
        title="✅ 工单已完成",
        receive_id_type="open_id",
        content=(
            f"**{work_order_no}**\n"
            f"设备: {eq_name}\n"
            f"维修过程: {detail}"
        ),
    )
