"""Work order service: state machine, business logic."""

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
    if equipment.status not in ("在用", "备用"):
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
            # 设备状态改为维修中
            await _update_equipment_status(db, data.equipment_id, "维修中")
            # eager re-fetch，避免返回对象触发懒加载 MissingGreenlet
            return await repo.get_work_order_by_id(db, work_order.id)
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
    await db.refresh(wo)
    return wo


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
    await db.refresh(wo)
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
    await db.refresh(wo)
    return wo


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
    await db.refresh(wo)
    return wo


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
    await db.refresh(wo)
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

    # 恢复设备到创建工单前的原始状态
    restore_status = wo.original_equipment_status or "在用"
    await _update_equipment_status(db, wo.equipment_id, restore_status)

    await db.refresh(wo)
    return wo


async def get_work_orders(
    db: AsyncSession,
    status: str | None = None,
    equipment_id: uuid.UUID | None = None,
    priority: str | None = None,
    order_type: str | None = None,
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
        page=page,
        page_size=page_size,
    )


async def get_work_order_statistics(db: AsyncSession) -> dict[str, object]:
    """获取工单统计"""
    return await repo.get_work_order_statistics(db)


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
    await db.refresh(wo)
    return wo


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
