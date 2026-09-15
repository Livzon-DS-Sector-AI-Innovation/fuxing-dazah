"""出入库计划单服务：状态机与业务校验（库存变更只发生在生成登记时）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.warehouse import repository
from app.modules.warehouse.models import WarehouseMovementPlan
from app.modules.warehouse.schemas import PlanCreate
from app.modules.warehouse.service import _generate_no
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User

_PLAN_NO_PREFIX = {"inbound": "IP", "outbound": "OP"}


async def create_plan(db: AsyncSession, payload: PlanCreate, user: User) -> WarehouseMovementPlan:
    material = await repository.get_material(db, UUID(payload.material_id))
    if not material:
        raise NotFoundException("物料", payload.material_id)
    location = await repository.get_location(db, UUID(payload.location_id))
    if not location:
        raise NotFoundException("库位", payload.location_id)

    plan = WarehouseMovementPlan(
        plan_no=_generate_no(_PLAN_NO_PREFIX[payload.direction]),
        direction=payload.direction,
        source_type=payload.source_type,
        material_id=material.id,
        material_code=material.code,
        material_name=material.name,
        batch_no=payload.batch_no.strip(),
        quantity=Decimal(str(payload.quantity)),
        location_id=location.id,
        location_code=location.code,
        location_name=location.name,
        planned_date=payload.planned_date,
        status="planned",
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(plan)
    await db.flush()
    await record_audit_log(
        db,
        action=f"warehouse.plan.{payload.direction}.create",
        user=user,
        resource_type="warehouse_movement_plan",
        resource_id=plan.id,
        new_value={
            "plan_no": plan.plan_no,
            "material": material.code,
            "quantity": float(plan.quantity),
            "location": location.code,
        },
    )
    return plan


async def get_plan(db: AsyncSession, plan_id: UUID) -> WarehouseMovementPlan:
    plan = await repository.get_plan(db, plan_id)
    if not plan:
        raise NotFoundException("出入库计划单", str(plan_id))
    return plan


async def start_plan(db: AsyncSession, plan_id: UUID, user: User) -> WarehouseMovementPlan:
    plan = await get_plan(db, plan_id)
    if plan.status != "planned":
        raise AppException(status_code=400, message=f"仅待执行计划可开始，当前状态: {plan.status}")
    plan.status = "in_progress"
    plan.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.plan.start",
        user=user,
        resource_type="warehouse_movement_plan",
        resource_id=plan.id,
        new_value={"plan_no": plan.plan_no, "status": plan.status},
    )
    return plan


async def cancel_plan(db: AsyncSession, plan_id: UUID, reason: str, user: User) -> WarehouseMovementPlan:
    plan = await get_plan(db, plan_id)
    if plan.status == "completed":
        raise AppException(status_code=400, message="已完成的计划单不可取消")
    if plan.status == "cancelled":
        raise AppException(status_code=400, message="该计划单已取消")
    plan.status = "cancelled"
    plan.cancel_reason = reason
    plan.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.plan.cancel",
        user=user,
        resource_type="warehouse_movement_plan",
        resource_id=plan.id,
        new_value={"plan_no": plan.plan_no, "status": plan.status, "reason": reason},
    )
    return plan


async def generate_plan_movement(
    db: AsyncSession,
    plan_id: UUID,
    payload: Any,
    user: User,
) -> tuple[WarehouseMovementPlan, Any]:
    """从执行中计划单生成出入库登记：复用既有 createMovement 事务逻辑，
    成功后计划单置 completed 并回填 movement_id。"""
    from app.modules.warehouse.schemas import MovementCreate
    from app.modules.warehouse.service import create_movement

    plan = await get_plan(db, plan_id)
    if plan.status != "in_progress":
        raise AppException(
            status_code=400,
            message=f"仅执行中的计划可生成登记，当前状态: {plan.status}",
        )

    quantity = float(payload.quantity) if payload is not None and payload.quantity else float(plan.quantity)
    occurred_at = payload.occurred_at if payload is not None and payload.occurred_at else None
    remark = payload.remark if payload is not None and payload.remark else plan.remark

    movement = await create_movement(
        db,
        MovementCreate(
            direction=plan.direction,
            source_type=plan.source_type,
            material_id=str(plan.material_id),
            batch_no=plan.batch_no,
            quantity=quantity,
            location_id=str(plan.location_id),
            occurred_at=occurred_at,
            expiry_date=None,
            remark=remark,
        ),
        user,
    )
    plan.status = "completed"
    plan.movement_id = movement.id
    plan.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.plan.complete",
        user=user,
        resource_type="warehouse_movement_plan",
        resource_id=plan.id,
        new_value={"plan_no": plan.plan_no, "movement_no": movement.movement_no},
    )
    return plan, movement


async def list_plans(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    direction: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    planned_before: date | None = None,
) -> tuple[list[WarehouseMovementPlan], int]:
    return await repository.list_plans(
        db,
        page=page,
        page_size=page_size,
        direction=direction,
        status=status,
        keyword=keyword,
        planned_before=planned_before,
    )
