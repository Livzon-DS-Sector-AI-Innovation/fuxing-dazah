"""Work order service: state machine, business logic."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models import WorkOrder
from app.modules.equipment.schemas import (
    WorkOrderComplete,
    WorkOrderCreate,
    WorkOrderUpdate,
    WorkOrderVerify,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "待处理": ["执行中", "已关闭"],
    "执行中": ["待验收", "已完成", "已关闭"],
    "待验收": ["已完成", "执行中", "已关闭"],
    "已完成": ["已关闭"],
    "已关闭": [],
}


async def generate_work_order_no(db: AsyncSession) -> str:
    """生成工单号：WO-{yyyyMMdd}-{seq:04d}"""
    max_no = await repo.get_max_work_order_no(db)
    today = datetime.now().strftime("%Y%m%d")
    if max_no:
        seq_str = max_no.split("-")[-1]
        seq = int(seq_str) + 1
    else:
        seq = 1
    return f"WO-{today}-{seq:04d}"


def _validate_transition(current: str, target: str) -> None:
    """校验状态转换是否合法"""
    allowed = _VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise AppException(
            message=f"状态不允许从 '{current}' 转换到 '{target}'"
        )


async def _get_work_order(
    db: AsyncSession, work_order_id: uuid.UUID
) -> WorkOrder:
    """获取工单，不存在则抛异常"""
    wo = await repo.get_work_order_by_id(db, work_order_id)
    if not wo:
        raise NotFoundException("工单", str(work_order_id))
    return wo


async def _update_equipment_status(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    status: str,
) -> None:
    """直接更新设备状态（模块内使用）"""
    equipment = await repo.get_equipment_by_id(db, equipment_id)
    if equipment:
        equipment.status = status
        await db.flush()


async def _try_restore_equipment_status(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> None:
    """检查设备是否所有故障维修工单已关闭，是则恢复设备为正常"""
    open_count = await repo.count_open_fault_work_orders(db, equipment_id)
    if open_count == 0:
        equipment = await repo.get_equipment_by_id(db, equipment_id)
        if equipment and equipment.status == "维修中":
            equipment.status = "在用"
            await db.flush()


async def create_work_order(
    db: AsyncSession,
    data: WorkOrderCreate,
    reporter_id: uuid.UUID,
) -> WorkOrder:
    """创建维修工单"""
    equipment = await repo.get_equipment_by_id(db, data.equipment_id)
    if not equipment:
        raise NotFoundException("设备", str(data.equipment_id))

    # 校验设备状态
    if equipment.status in ("停用", "报废"):
        raise AppException(
            message=f"设备当前状态为 '{equipment.status}'，不能创建工单"
        )

    original_status = equipment.status

    for attempt in range(_MAX_RETRIES):
        wo_no = await generate_work_order_no(db)

        wo_data = data.model_dump()
        wo_data["work_order_no"] = wo_no
        wo_data["reporter_id"] = reporter_id
        wo_data["status"] = "待处理"
        wo_data["original_equipment_status"] = original_status

        try:
            work_order = await repo.create_work_order(db, wo_data)
            # 仅"故障维修"类型的工单才自动改设备状态为维修中
            if data.order_type == "故障维修":
                await _update_equipment_status(db, data.equipment_id, "维修中")
            # eager re-fetch，避免返回对象触发懒加载 MissingGreenlet
            result = await repo.get_work_order_by_id(db, work_order.id)
            # 飞书通知设备责任人（异步，非关键路径）
            if equipment.responsible_person_id:
                asyncio.ensure_future(_notify_new_work_order(
                    responsible_person_id=equipment.responsible_person_id,
                    work_order_no=wo_no,
                    equipment_name=equipment.name,
                    order_type=data.order_type,
                    priority=data.priority,
                ))
            return result
        except IntegrityError:
            if attempt < _MAX_RETRIES - 1:
                await db.rollback()
                continue
            raise AppException(message="工单号生成失败，请重试")

    raise AppException(message="工单号生成失败，请重试")


async def update_work_order(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    data: WorkOrderUpdate,
) -> WorkOrder:
    """更新工单信息"""
    wo = await _get_work_order(db, work_order_id)

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise AppException(message="没有需要更新的字段")

    for field, value in update_data.items():
        setattr(wo, field, value)

    await db.flush()
    return await repo.get_work_order_by_id(db, wo.id)


async def assign_work_order(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    assignee_id: uuid.UUID,
) -> WorkOrder:
    """指派维修人（不改变工单状态，仅记录指派人）"""
    wo = await _get_work_order(db, work_order_id)

    wo.assignee_id = assignee_id
    wo.assigned_at = datetime.now(UTC)
    await db.flush()
    wo = await repo.get_work_order_by_id(db, wo.id)

    # 飞书通知被指派人
    equipment = wo.equipment
    asyncio.ensure_future(_notify_assignment(
        assignee_id=assignee_id,
        work_order_no=wo.work_order_no,
        equipment_name=equipment.name if equipment else "",
        order_type=wo.order_type,
        priority=wo.priority,
    ))

    return wo


async def start_work_order(
    db: AsyncSession,
    work_order_id: uuid.UUID,
) -> WorkOrder:
    """开始执行"""
    wo = await _get_work_order(db, work_order_id)
    _validate_transition(wo.status, "执行中")

    wo.status = "执行中"
    wo.started_at = datetime.now(UTC)
    await db.flush()
    return await repo.get_work_order_by_id(db, wo.id)


async def complete_work_order(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    data: WorkOrderComplete,
) -> WorkOrder:
    """提交完成"""
    wo = await _get_work_order(db, work_order_id)

    is_repair = wo.order_type in ("故障维修", "校准", "异常处理")
    target = "待验收" if is_repair else "已完成"
    _validate_transition(wo.status, target)

    now = datetime.now(UTC)
    wo.status = target
    wo.completed_at = now
    wo.repair_detail = data.repair_detail

    # 计算耗时
    if wo.started_at:
        delta = now - wo.started_at
        wo.actual_duration = int(delta.total_seconds() / 60)

    await db.flush()

    # 计划维护工单完成时，联动更新维护计划日期
    if wo.order_type == "计划维护" and wo.maintenance_plan_id:
        await _update_maintenance_plan_on_completion(
            db, wo.maintenance_plan_id
        )

    # 待验收时，飞书通知责任人确认验收
    if target == "待验收":
        responsible = wo.responsible_person
        equipment = wo.equipment
        feishu_uid = (
            getattr(responsible, "feishu_user_id", None)
            if responsible else None
        )
        if feishu_uid:
            # 收集图片存储路径（直接传 DB 中 file_path，notification 层无需反推）
            img_paths: list[str] = []
            for img in (wo.images or []):
                img_paths.append(img.file_path)
            asyncio.ensure_future(_notify_verification(
                feishu_user_id=feishu_uid,
                work_order_no=wo.work_order_no,
                equipment_name=equipment.name if equipment else "",
                assignee_name=wo.assignee.name if wo.assignee else "",
                priority=wo.priority,
                repair_detail=wo.repair_detail or "",
                work_order_id=str(wo.id),
                image_paths=img_paths,
            ))

    return await repo.get_work_order_by_id(db, wo.id)


async def _update_maintenance_plan_on_completion(
    db: AsyncSession,
    maintenance_plan_id: uuid.UUID,
) -> None:
    """计划维护工单完成时，自动推进维护计划的日期。

    仅对设备级计划生效；分类级计划的日期由 scheduler 统一管理。
    """
    from datetime import date as date_type

    from app.modules.equipment.service.maintenance_plan import (
        _calculate_next_maintenance_date,
    )

    plan = await repo.get_maintenance_plan_by_id(db, maintenance_plan_id)
    if not plan:
        return

    # 分类级计划不在此推进日期——不同设备完成时间各异，
    # 由 scheduler 的 generate_due_work_orders 统一管理周期
    if plan.category_id:
        return

    today = date_type.today()
    plan.last_maintenance_date = today
    plan.next_maintenance_date = _calculate_next_maintenance_date(
        today, plan.frequency, plan.frequency_unit
    )
    # last_generated_date 保持旧值，让 scheduler 下个周期自然触发
    await db.flush()


async def _notify_verification(
    feishu_user_id: str,
    work_order_no: str,
    equipment_name: str,
    assignee_name: str,
    priority: str,
    repair_detail: str = "",
    work_order_id: str = "",
    image_paths: list[str] | None = None,
) -> None:
    """工单进入待验收时，飞书通知责任人确认验收。

    发送交互卡片包含：维修描述、现场照片、验收通过/退回按钮。
    非关键路径：发送失败只记日志，不影响主流程。
    """
    try:
        from app.modules.equipment.feishu.notification import send_verification_card

        ok = await send_verification_card(
            feishu_user_id=feishu_user_id,
            work_order_no=work_order_no,
            equipment_name=equipment_name,
            assignee_name=assignee_name,
            priority=priority,
            repair_detail=repair_detail,
            work_order_id=work_order_id,
            image_paths=image_paths or [],
        )
        if ok:
            logger.info(
                "验收通知已发送: %s -> %s", work_order_no, feishu_user_id,
            )
        else:
            logger.warning(
                "验收通知发送失败: %s -> %s", work_order_no, feishu_user_id,
            )
    except Exception:
        logger.exception(
            "验收通知异常: %s -> %s", work_order_no, feishu_user_id,
        )


async def _notify_new_work_order(
    responsible_person_id: uuid.UUID,
    work_order_no: str,
    equipment_name: str,
    order_type: str,
    priority: str,
) -> None:
    """新建工单时飞书通知设备责任人。

    非关键路径：发送失败只记日志，不影响主流程。
    """
    try:
        from sqlalchemy import select as sa_select

        from app.core.database import async_session_factory
        from app.modules.equipment.feishu.notification import send_user_card
        from app.platform.identity.models import User

        async with async_session_factory() as session:
            result = await session.execute(
                sa_select(User).where(
                    User.id == responsible_person_id,
                    User.is_deleted == False,  # noqa: E712
                )
            )
            user = result.scalar_one_or_none()

        if not user or not user.feishu_user_id:
            logger.info(
                "工单 %s 责任人 %s 无飞书账号，跳过通知",
                work_order_no, responsible_person_id,
            )
            return

        title = f"🔔 新工单 - {work_order_no}"
        lines = [
            f"**工单编号：**{work_order_no}",
            f"**关联设备：**{equipment_name}",
            f"**工单类型：**{order_type}",
            f"**优先级：**{priority}",
            "",
            "请及时处理。",
        ]
        content = "\n".join(lines)

        ok = await send_user_card(
            open_id=user.feishu_user_id,
            title=title,
            content=content,
        )
        if ok:
            logger.info(
                "新建工单通知已发送: %s -> %s",
                work_order_no, user.feishu_user_id,
            )
        else:
            logger.warning(
                "新建工单通知发送失败: %s", work_order_no,
            )
    except Exception:
        logger.exception(
            "新建工单通知异常: %s", work_order_no,
        )


async def _notify_assignment(
    assignee_id: uuid.UUID,
    work_order_no: str,
    equipment_name: str,
    order_type: str,
    priority: str,
) -> None:
    """指派维修人后飞书通知被指派人。

    非关键路径：发送失败只记日志，不影响主流程。
    """
    try:
        from sqlalchemy import select as sa_select

        from app.core.database import async_session_factory
        from app.modules.equipment.feishu.notification import send_user_card
        from app.platform.identity.models import User

        async with async_session_factory() as session:
            result = await session.execute(
                sa_select(User).where(
                    User.id == assignee_id,
                    User.is_deleted == False,  # noqa: E712
                )
            )
            user = result.scalar_one_or_none()

        if not user or not user.feishu_user_id:
            logger.info(
                "工单 %s 被指派人 %s 无飞书账号，跳过通知",
                work_order_no, assignee_id,
            )
            return

        title = f"📋 新任务指派 - {work_order_no}"
        lines = [
            f"**工单编号：**{work_order_no}",
            f"**关联设备：**{equipment_name}",
            f"**工单类型：**{order_type}",
            f"**优先级：**{priority}",
            "",
            "你已被指派为该工单的维修人，请及时处理。",
        ]
        content = "\n".join(lines)

        ok = await send_user_card(
            open_id=user.feishu_user_id,
            title=title,
            content=content,
        )
        if ok:
            logger.info(
                "指派通知已发送: %s -> %s",
                work_order_no, user.feishu_user_id,
            )
        else:
            logger.warning(
                "指派通知发送失败: %s", work_order_no,
            )
    except Exception:
        logger.exception(
            "指派通知异常: %s", work_order_no,
        )


async def _notify_rejection(
    feishu_user_id: str,
    work_order_no: str,
    equipment_name: str,
    remark: str = "",
) -> None:
    """验收退回时飞书通知维修人重新处理。

    非关键路径：发送失败只记日志，不影响主流程。
    """
    try:
        from app.modules.equipment.feishu.notification import send_user_card

        title = f"↩️ 工单退回 - {work_order_no}"
        lines = [
            f"**工单编号：**{work_order_no}",
            f"**关联设备：**{equipment_name}",
            "",
            "验收不通过，已被退回重修，请重新处理。",
        ]
        if remark:
            lines.append(f"**退回原因：**{remark}")
        content = "\n".join(lines)

        ok = await send_user_card(
            open_id=feishu_user_id,
            title=title,
            content=content,
        )
        if ok:
            logger.info(
                "退回通知已发送: %s -> %s", work_order_no, feishu_user_id,
            )
        else:
            logger.warning(
                "退回通知发送失败: %s", work_order_no,
            )
    except Exception:
        logger.exception(
            "退回通知异常: %s", work_order_no,
        )


async def verify_work_order(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    verifier_id: uuid.UUID,
    data: WorkOrderVerify,
) -> WorkOrder:
    """验收工单"""
    wo = await _get_work_order(db, work_order_id)
    if wo.order_type not in ("故障维修", "校准", "异常处理"):
        raise AppException(message=f"工单类型 '{wo.order_type}' 不支持验收")

    wo.verified_by = verifier_id
    wo.verified_at = datetime.now(UTC)
    wo.verification_result = data.result
    wo.verification_remark = data.remark

    if data.result == "合格":
        _validate_transition(wo.status, "已完成")
        wo.status = "已完成"
    else:
        # 打回重修
        _validate_transition(wo.status, "执行中")
        wo.status = "执行中"
        wo.started_at = None
        wo.completed_at = None
        wo.actual_duration = None

    await db.flush()
    wo = await repo.get_work_order_by_id(db, wo.id)

    # 退回时飞书通知维修人
    if data.result == "不合格" and wo.assignee:
        assignee = wo.assignee
        feishu_uid = getattr(assignee, "feishu_user_id", None)
        if feishu_uid:
            asyncio.ensure_future(_notify_rejection(
                feishu_user_id=feishu_uid,
                work_order_no=wo.work_order_no,
                equipment_name=wo.equipment.name if wo.equipment else "",
                remark=data.remark or "",
            ))

    return wo


async def close_work_order(
    db: AsyncSession,
    work_order_id: uuid.UUID,
) -> WorkOrder:
    """关闭工单"""
    wo = await _get_work_order(db, work_order_id)
    _validate_transition(wo.status, "已关闭")

    wo.status = "已关闭"
    await db.flush()

    # 仅故障维修类型触发设备状态恢复检查
    if wo.order_type == "故障维修":
        await _try_restore_equipment_status(db, wo.equipment_id)

    # eager re-fetch
    return await repo.get_work_order_by_id(db, wo.id)


async def get_work_orders(
    db: AsyncSession,
    status: str | None = None,
    equipment_id: uuid.UUID | None = None,
    priority: str | None = None,
    order_type: str | None = None,
    exclude_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[WorkOrder], int]:
    """获取工单列表"""
    return await repo.get_work_orders(
        db,
        status=status,
        equipment_id=equipment_id,
        priority=priority,
        order_type=order_type,
        exclude_status=exclude_status,
        page=page,
        page_size=page_size,
    )


async def get_work_order_statistics(
    db: AsyncSession,
    exclude_status: str | None = None,
) -> dict[str, object]:
    """获取工单统计"""
    return await repo.get_work_order_statistics(
        db, exclude_status=exclude_status,
    )


async def get_work_order_by_id(
    db: AsyncSession,
    work_order_id: uuid.UUID,
) -> WorkOrder:
    """获取工单"""
    return await _get_work_order(db, work_order_id)


async def claim_work_order(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    user_id: uuid.UUID,
) -> WorkOrder:
    """维修人员自主抢单（不改变工单状态，仅记录指派人）"""
    wo = await _get_work_order(db, work_order_id)

    if wo.status != "待处理":
        raise AppException(message="该工单已不可抢单")
    if wo.assignee_id is not None:
        raise AppException(message="该工单已被其他人接单")

    wo.assignee_id = user_id
    wo.assigned_at = datetime.now(UTC)
    await db.flush()
    return await repo.get_work_order_by_id(db, wo.id)


async def consume_materials(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    items: list[dict[str, Any]],
) -> list[Any]:
    """工单领料"""
    wo = await _get_work_order(db, work_order_id)

    if wo.status in ("已完成", "已关闭"):
        raise AppException(message="工单已完成或已关闭，不能领料")

    from app.modules.equipment.service.spare_part import (
        get_spare_part_by_id,
        get_stock_by_spare_part_id,
        outbound_stock,
    )

    total_cost = 0.0
    transactions = []

    for item in items:
        spare_part = await get_spare_part_by_id(db, item["spare_part_id"])
        stock = await get_stock_by_spare_part_id(db, item["spare_part_id"])

        if not stock or stock.current_qty < item["quantity"]:
            raise AppException(
                message=f"备件 '{spare_part.name}' 库存不足"
            )

        # 扣减库存
        await outbound_stock(db, item["spare_part_id"], item["quantity"])

        # 创建流水记录
        transaction = await repo.create_material_consumption(
            db,
            {
                "spare_part_id": item["spare_part_id"],
                "work_order_id": work_order_id,
                "transaction_type": "出库",
                "quantity": -item["quantity"],
                "remark": f"工单 {wo.work_order_no} 领料",
            },
        )
        transactions.append(transaction)

        # 累加费用
        if spare_part.unit_price:
            total_cost += spare_part.unit_price * item["quantity"]

    # 更新工单备件费用
    current_cost = wo.spare_parts_cost or 0.0
    wo.spare_parts_cost = current_cost + total_cost
    await db.flush()

    return transactions
