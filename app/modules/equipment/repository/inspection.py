"""Inspection repository: data access for routes, tasks, photos."""

import uuid
from datetime import date, datetime

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.equipment.models.equipment import Equipment
from app.modules.equipment.models.inspection import (
    InspectionPhoto,
    InspectionRoute,
    InspectionRouteEquipment,
    InspectionTask,
)
from app.modules.equipment.models.inspection_template import (
    InspectionRecord,
)


# ═══════════ 路线 ═══════════
async def create_route(
    db: AsyncSession, data: dict
) -> InspectionRoute:
    route = InspectionRoute(**data)
    db.add(route)
    await db.flush()
    await db.refresh(route)
    return route


async def get_route_by_id(
    db: AsyncSession, route_id: uuid.UUID
) -> InspectionRoute | None:
    stmt = (
        select(InspectionRoute)
        .options(
            selectinload(InspectionRoute.equipments_rel).selectinload(
                InspectionRouteEquipment.equipment
            )
        )
        .where(
            InspectionRoute.id == route_id,
            InspectionRoute.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_routes(
    db: AsyncSession,
    is_active: bool | None = None,
    area: str | None = None,
    period_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionRoute], int]:
    conditions = [InspectionRoute.is_deleted == False]  # noqa: E712
    if is_active is not None:
        conditions.append(InspectionRoute.is_active == is_active)
    if area:
        conditions.append(InspectionRoute.area == area)
    if period_type:
        conditions.append(InspectionRoute.period_type == period_type)
    if keyword:
        conditions.append(InspectionRoute.name.ilike(f"%{keyword}%"))

    count_stmt = select(func.count(InspectionRoute.id)).where(
        and_(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(InspectionRoute)
        .options(selectinload(InspectionRoute.equipments_rel))
        .where(and_(*conditions))
        .order_by(InspectionRoute.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def update_route(
    db: AsyncSession, route_id: uuid.UUID, data: dict
) -> InspectionRoute | None:
    route = await get_route_by_id(db, route_id)
    if not route:
        return None
    for k, v in data.items():
        setattr(route, k, v)
    await db.flush()
    # 用 eager re-fetch 替代 db.refresh，避免 expire 已加载的 equipments_rel 关系
    result = await db.execute(
        select(InspectionRoute)
        .options(
            selectinload(InspectionRoute.equipments_rel).selectinload(
                InspectionRouteEquipment.equipment
            )
        )
        .where(
            InspectionRoute.id == route_id,
            InspectionRoute.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one()


async def delete_route(db: AsyncSession, route_id: uuid.UUID) -> bool:
    route = await get_route_by_id(db, route_id)
    if not route:
        return False
    route.is_deleted = True
    await db.flush()
    return True


async def set_route_equipments(
    db: AsyncSession, route_id: uuid.UUID, items: list[dict]
) -> list[InspectionRouteEquipment]:
    # 获取当前活跃记录
    old_result = await db.execute(
        select(InspectionRouteEquipment).where(
            InspectionRouteEquipment.route_id == route_id,
            InspectionRouteEquipment.is_deleted == False,  # noqa: E712
        )
    )
    old_records = list(old_result.scalars().all())
    old_ids = {r.equipment_id for r in old_records}
    old_by_id = {r.equipment_id: r for r in old_records}

    new_ids = {item["equipment_id"] for item in items}

    # 删除：旧有但新 items 中没有的记录
    to_delete_ids = old_ids - new_ids
    for r in old_records:
        if r.equipment_id in to_delete_ids:
            r.is_deleted = True

    # 新增：新 items 中有但旧记录中没有的设备
    to_add_ids = new_ids - old_ids
    result: list[InspectionRouteEquipment] = []
    for item in items:
        if item["equipment_id"] in to_add_ids:
            re_ = InspectionRouteEquipment(
                route_id=route_id,
                equipment_id=item["equipment_id"],
                sort_order=item.get("sort_order", 0),
            )
            db.add(re_)
            result.append(re_)
        else:
            # 已存在：更新 sort_order
            existing = old_by_id.get(item["equipment_id"])
            if existing:
                existing.sort_order = item.get("sort_order", existing.sort_order)
                result.append(existing)

    await db.flush()
    return result


async def get_route_equipments(
    db: AsyncSession, route_id: uuid.UUID
) -> list[InspectionRouteEquipment]:
    stmt = (
        select(InspectionRouteEquipment)
        .options(selectinload(InspectionRouteEquipment.equipment))
        .where(
            InspectionRouteEquipment.route_id == route_id,
            InspectionRouteEquipment.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionRouteEquipment.sort_order)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ═══════════ 任务 ═══════════
async def get_max_task_no(db: AsyncSession) -> str | None:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"IT-{today}-"
    stmt = (
        select(InspectionTask.task_no)
        .where(InspectionTask.task_no.like(f"{prefix}%"))
        .order_by(InspectionTask.task_no.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_task(
    db: AsyncSession, data: dict
) -> InspectionTask:
    task = InspectionTask(**data)
    db.add(task)
    await db.flush()
    # eager re-fetch 加载关联，避免 _task_to_response 访问关系时 MissingGreenlet
    result = await db.execute(
        select(InspectionTask)
        .options(
            selectinload(InspectionTask.route).selectinload(InspectionRoute.equipments_rel),
            selectinload(InspectionTask.equipment),
            selectinload(InspectionTask.template),
            selectinload(InspectionTask.assignee),
        )
        .where(InspectionTask.id == task.id)
    )
    return result.scalar_one()


async def get_task_by_id(
    db: AsyncSession, task_id: uuid.UUID
) -> InspectionTask | None:
    stmt = (
        select(InspectionTask)
        .options(
            selectinload(InspectionTask.route).selectinload(InspectionRoute.equipments_rel),
            selectinload(InspectionTask.equipment),
            selectinload(InspectionTask.template),
            selectinload(InspectionTask.assignee),
        )
        .where(
            InspectionTask.id == task_id,
            InspectionTask.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_tasks(
    db: AsyncSession,
    status: str | None = None,
    route_id: uuid.UUID | None = None,
    assigned_to: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    planned_date_from: date | None = None,
    planned_date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionTask], int]:
    conditions = [InspectionTask.is_deleted == False]  # noqa: E712
    if status:
        conditions.append(InspectionTask.status == status)
    if route_id:
        conditions.append(InspectionTask.route_id == route_id)
    if assigned_to:
        conditions.append(InspectionTask.assigned_to == assigned_to)
    if equipment_id:
        conditions.append(
            or_(
                InspectionTask.equipment_id == equipment_id,
                cast(InspectionTask.equipment_ids, String).like(
                    f'%"{equipment_id}"%'
                ),
            )
        )
    if planned_date_from:
        conditions.append(InspectionTask.planned_date >= planned_date_from)
    if planned_date_to:
        conditions.append(InspectionTask.planned_date <= planned_date_to)

    count_stmt = select(func.count(InspectionTask.id)).where(
        and_(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(InspectionTask)
        .options(
            selectinload(InspectionTask.route).selectinload(InspectionRoute.equipments_rel),
            selectinload(InspectionTask.equipment),
            selectinload(InspectionTask.template),
            selectinload(InspectionTask.assignee),
        )
        .where(and_(*conditions))
        .order_by(
            InspectionTask.planned_date.desc(),
            InspectionTask.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_task_equipment_completed_ids(
    db: AsyncSession, task_id: uuid.UUID
) -> set[uuid.UUID]:
    stmt = (
        select(InspectionRecord.equipment_id)
        .where(
            InspectionRecord.task_id == task_id,
            InspectionRecord.is_deleted == False,  # noqa: E712
        )
        .distinct()
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


# ═══════════ 巡检记录 ═══════════
async def create_inspection_records(
    db: AsyncSession, records_data: list[dict]
) -> list[InspectionRecord]:
    objs = [InspectionRecord(**r) for r in records_data]
    db.add_all(objs)
    await db.flush()
    return objs


async def get_records_by_task(
    db: AsyncSession, task_id: uuid.UUID
) -> list[InspectionRecord]:
    stmt = (
        select(InspectionRecord)
        .options(selectinload(InspectionRecord.template_item))
        .where(
            InspectionRecord.task_id == task_id,
            InspectionRecord.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionRecord.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ═══════════ 照片 ═══════════
async def create_photo(
    db: AsyncSession, data: dict
) -> InspectionPhoto:
    # equipment_id 为 None 时（线路巡检照片）不传入构造
    if data.get("equipment_id") is None:
        data = {k: v for k, v in data.items() if k != "equipment_id" or v is not None}
    photo = InspectionPhoto(**data)
    db.add(photo)
    await db.flush()
    await db.refresh(photo)
    return photo


async def get_photos_by_task(
    db: AsyncSession, task_id: uuid.UUID
) -> list[InspectionPhoto]:
    stmt = (
        select(InspectionPhoto)
        .where(
            InspectionPhoto.task_id == task_id,
            InspectionPhoto.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionPhoto.uploaded_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_photos_by_task_and_equipment(
    db: AsyncSession, task_id: uuid.UUID, equipment_id: uuid.UUID
) -> list[InspectionPhoto]:
    stmt = (
        select(InspectionPhoto)
        .where(
            InspectionPhoto.task_id == task_id,
            InspectionPhoto.equipment_id == equipment_id,
            InspectionPhoto.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionPhoto.uploaded_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_photo_by_id(
    db: AsyncSession, photo_id: uuid.UUID
) -> InspectionPhoto | None:
    stmt = select(InspectionPhoto).where(
        InspectionPhoto.id == photo_id,
        InspectionPhoto.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def delete_photo(db: AsyncSession, photo_id: uuid.UUID) -> bool:
    photo = await get_photo_by_id(db, photo_id)
    if not photo:
        return False
    photo.is_deleted = True
    await db.flush()
    return True


async def count_photos_by_task(
    db: AsyncSession, task_id: uuid.UUID
) -> int:
    stmt = select(func.count(InspectionPhoto.id)).where(
        InspectionPhoto.task_id == task_id,
        InspectionPhoto.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_equipment_names_by_ids(
    db: AsyncSession, equipment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """根据设备ID列表批量获取设备名称映射"""
    if not equipment_ids:
        return {}
    stmt = select(Equipment.id, Equipment.name).where(
        Equipment.id.in_(equipment_ids),
        Equipment.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result.all()}
