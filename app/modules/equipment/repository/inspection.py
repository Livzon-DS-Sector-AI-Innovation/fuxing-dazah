"""Inspection repository: data access for routes, tasks, photos."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.equipment.models.equipment import Equipment
from app.modules.equipment.models.inspection import (
    InspectionPhoto,
    InspectionRoute,
    InspectionRouteEquipment,
    InspectionRouteSchedule,
    InspectionTask,
)
from app.modules.equipment.models.inspection_route_location import (
    RouteEquipmentTemplate,
    RouteLocation,
    RouteLocationEquipment,
)
from app.modules.equipment.models.inspection_template import (
    InspectionRecord,
)


# ═══════════ 路线 ═══════════
async def create_route(
    db: AsyncSession, data: dict
) -> InspectionRoute:
    # 清理同 name 的已软删除记录，避免重复添加→删除→添加→删除时违反唯一约束
    name = data.get("name")
    if name:
        deleted_result = await db.execute(
            select(InspectionRoute).where(
                InspectionRoute.name == name,
                InspectionRoute.is_deleted == True,  # noqa: E712
            )
        )
        for old in deleted_result.scalars().all():
            await db.delete(old)

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
            selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments)
            .selectinload(RouteLocationEquipment.templates_rel)
            .selectinload(RouteEquipmentTemplate.template),
            selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.location),
            selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments)
            .selectinload(RouteLocationEquipment.equipment),
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
    location_id: uuid.UUID | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionRoute], int]:
    conditions = [InspectionRoute.is_deleted == False]  # noqa: E712
    if is_active is not None:
        conditions.append(InspectionRoute.is_active == is_active)
    if location_id:
        conditions.append(
            InspectionRoute.id.in_(
                select(RouteLocation.route_id).where(
                    RouteLocation.location_id == location_id,
                    RouteLocation.is_deleted == False,  # noqa: E712
                )
            )
        )
    if keyword:
        conditions.append(InspectionRoute.name.ilike(f"%{keyword}%"))

    count_stmt = select(func.count(InspectionRoute.id)).where(
        and_(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(InspectionRoute)
        .options(
            selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments),
        )
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
    # 用 eager re-fetch 替代 db.refresh
    result = await db.execute(
        select(InspectionRoute)
        .options(
            selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments)
            .selectinload(RouteLocationEquipment.equipment),
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
    # 获取该路线所有记录（含已软删除的），避免重复添加→删除→添加时违反唯一约束
    all_result = await db.execute(
        select(InspectionRouteEquipment).where(
            InspectionRouteEquipment.route_id == route_id,
        )
    )
    all_records = list(all_result.scalars().all())

    # 按 equipment_id 分组：活跃记录 和 已删除记录
    active_by_id: dict[uuid.UUID, InspectionRouteEquipment] = {}
    deleted_by_id: dict[uuid.UUID, InspectionRouteEquipment] = {}
    for r in all_records:
        if r.is_deleted:
            # 同一 pair 可能有多条已删除记录（历史 bug 残留），只保留一条
            if r.equipment_id not in deleted_by_id:
                deleted_by_id[r.equipment_id] = r
        else:
            active_by_id[r.equipment_id] = r

    new_ids = {item["equipment_id"] for item in items}
    active_ids = set(active_by_id.keys())

    # 删除：活跃但新 items 中没有的记录 → 软删除
    to_delete_ids = active_ids - new_ids
    if to_delete_ids:
        # 先物理删除该 route 下这些 equipment 的**所有** is_deleted=true 记录
        # （可能有多条历史残留），避免后续软删除时违反唯一约束
        from sqlalchemy import delete

        await db.execute(
            delete(InspectionRouteEquipment).where(
                InspectionRouteEquipment.route_id == route_id,
                InspectionRouteEquipment.equipment_id.in_(to_delete_ids),
                InspectionRouteEquipment.is_deleted == True,  # noqa: E712
            )
        )
        # 现在安全：不再有同 pair 的 is_deleted=true 记录
        for eq_id in to_delete_ids:
            active_by_id[eq_id].is_deleted = True

    # 新增/恢复/更新
    result: list[InspectionRouteEquipment] = []
    for item in items:
        eq_id = item["equipment_id"]
        if eq_id in active_by_id:
            # 已存在活跃记录：更新 sort_order
            existing = active_by_id[eq_id]
            existing.sort_order = item.get("sort_order", existing.sort_order)
            result.append(existing)
        elif eq_id in deleted_by_id:
            # 存在已软删除的旧记录：恢复它
            restored = deleted_by_id[eq_id]
            restored.is_deleted = False
            restored.sort_order = item.get("sort_order", restored.sort_order)
            result.append(restored)
        else:
            # 全新记录
            re_ = InspectionRouteEquipment(
                route_id=route_id,
                equipment_id=eq_id,
                sort_order=item.get("sort_order", 0),
            )
            db.add(re_)
            result.append(re_)

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
            selectinload(InspectionTask.route)
            .selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments),
            selectinload(InspectionTask.equipment),
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
            selectinload(InspectionTask.route)
            .selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments),
            selectinload(InspectionTask.equipment),
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
    exclude_status: str | None = None,
    route_id: uuid.UUID | None = None,
    assigned_to: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    planned_time_from: datetime | None = None,
    planned_time_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionTask], int]:
    conditions = [InspectionTask.is_deleted == False]  # noqa: E712
    if status:
        conditions.append(InspectionTask.status == status)
    if exclude_status:
        conditions.append(InspectionTask.status != exclude_status)
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
    if planned_time_from:
        conditions.append(InspectionTask.planned_time >= planned_time_from)
    if planned_time_to:
        conditions.append(InspectionTask.planned_time <= planned_time_to)

    count_stmt = select(func.count(InspectionTask.id)).where(
        and_(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(InspectionTask)
        .options(
            selectinload(InspectionTask.route)
            .selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments),
            selectinload(InspectionTask.equipment),
            selectinload(InspectionTask.assignee),
        )
        .where(and_(*conditions))
        .order_by(
            InspectionTask.planned_time.desc(),
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
async def soft_delete_records_by_task_equipment(
    db: AsyncSession, task_id: uuid.UUID, equipment_id: uuid.UUID
) -> None:
    """软删除某任务+设备的已有巡检记录（用于重新提交时替换旧数据）"""
    from sqlalchemy import update

    stmt = (
        update(InspectionRecord)
        .where(
            InspectionRecord.task_id == task_id,
            InspectionRecord.equipment_id == equipment_id,
            InspectionRecord.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    await db.execute(stmt)


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


# ═══════════ 线路地点配置（新） ═══════════


async def set_route_locations(
    db: AsyncSession, route_id: uuid.UUID, items: list[dict]
) -> list[RouteLocation]:
    """全量替换路线的地点→设备→模板配置"""
    existing_locs = (await db.execute(
        select(RouteLocation).where(RouteLocation.route_id == route_id)
    )).scalars().all()
    existing_loc_ids = {r.id for r in existing_locs}
    existing_by_loc_id: dict[uuid.UUID, RouteLocation] = {}
    for r in existing_locs:
        if r.location_id not in existing_by_loc_id or not r.is_deleted:
            existing_by_loc_id[r.location_id] = r

    new_loc_ids = set()

    for loc_item in items:
        location_id = loc_item["location_id"]
        sort_order = loc_item.get("sort_order", 0)
        equipments_data = loc_item.get("equipments", [])

        loc = existing_by_loc_id.get(location_id)
        if loc and not loc.is_deleted:
            # 现有活跃记录：更新 sort_order
            loc.sort_order = sort_order
        elif loc and loc.is_deleted:
            # 恢复软删除记录
            loc.is_deleted = False
            loc.sort_order = sort_order
        else:
            # 全新记录：先 flush 以生成 ID，再处理设备
            loc = RouteLocation(
                route_id=route_id,
                location_id=location_id,
                sort_order=sort_order,
            )
            db.add(loc)
            await db.flush()

        new_loc_ids.add(loc.id)

        # 处理该地点下的设备→模板
        await _set_location_equipments(db, loc, equipments_data)

    # 软删除不再需要的地点
    to_delete = {r.id for r in existing_locs if r.id not in new_loc_ids}
    for r in existing_locs:
        if r.id in to_delete and not r.is_deleted:
            r.is_deleted = True

    await db.flush()

    # Eager re-fetch
    result = list((await db.execute(
        select(RouteLocation)
        .options(
            selectinload(RouteLocation.equipments).selectinload(
                RouteLocationEquipment.templates_rel
            ).selectinload(RouteEquipmentTemplate.template),
            selectinload(RouteLocation.equipments).selectinload(
                RouteLocationEquipment.equipment
            ),
            selectinload(RouteLocation.location),
        )
        .where(
            RouteLocation.id.in_(new_loc_ids),
            RouteLocation.is_deleted == False,  # noqa: E712
        )
        .order_by(RouteLocation.sort_order)
    )).scalars().all())
    return result


async def _set_location_equipments(
    db: AsyncSession, route_location: RouteLocation, equipments: list[dict]
) -> None:
    """替换某个地点下的设备→模板配置"""
    loc_id = route_location.id
    existing_eqs = (await db.execute(
        select(RouteLocationEquipment).where(
            RouteLocationEquipment.route_location_id == loc_id,
        )
    )).scalars().all()
    existing_by_eq_id: dict[uuid.UUID, RouteLocationEquipment] = {}
    for r in existing_eqs:
        if r.equipment_id not in existing_by_eq_id or not r.is_deleted:
            existing_by_eq_id[r.equipment_id] = r

    new_eq_ids = set()

    for eq_item in equipments:
        equipment_id = eq_item["equipment_id"]
        sort_order = eq_item.get("sort_order", 0)
        template_ids = eq_item.get("template_ids", [])

        eq = existing_by_eq_id.get(equipment_id)
        if eq and not eq.is_deleted:
            eq.sort_order = sort_order
        elif eq and eq.is_deleted:
            eq.is_deleted = False
            eq.sort_order = sort_order
        else:
            eq = RouteLocationEquipment(
                route_location_id=loc_id,
                equipment_id=equipment_id,
                sort_order=sort_order,
            )
            db.add(eq)
            await db.flush()

        new_eq_ids.add(eq.equipment_id)
        await _set_equipment_templates(db, eq, template_ids)

    for eq_id, eq in existing_by_eq_id.items():
        if eq_id not in new_eq_ids and not eq.is_deleted:
            eq.is_deleted = True


async def _set_equipment_templates(
    db: AsyncSession, route_equipment: RouteLocationEquipment, template_ids: list
) -> None:
    """替换某个设备的模板绑定"""
    existing = (await db.execute(
        select(RouteEquipmentTemplate).where(
            RouteEquipmentTemplate.route_equipment_id == route_equipment.id,
        )
    )).scalars().all()
    existing_by_tid: dict[uuid.UUID, RouteEquipmentTemplate] = {}
    for r in existing:
        if r.template_id not in existing_by_tid or not r.is_deleted:
            existing_by_tid[r.template_id] = r

    new_tids = set(template_ids)

    for tid in template_ids:
        t = existing_by_tid.get(tid)
        if t and t.is_deleted:
            t.is_deleted = False
        elif not t:
            db.add(RouteEquipmentTemplate(
                route_equipment_id=route_equipment.id,
                template_id=tid,
            ))

    for tid, t in existing_by_tid.items():
        if tid not in new_tids and not t.is_deleted:
            t.is_deleted = True


# ═══════════ 路线定时任务 ═══════════

async def create_schedule(
    db: AsyncSession, data: dict
) -> InspectionRouteSchedule:
    route_id = data.get("route_id")
    cron_expr = data.get("cron_expression")
    assigned_to = data.get("assigned_to")

    # 幂等：已存在活跃记录时直接返回
    if route_id and cron_expr:
        active_cond = [
            InspectionRouteSchedule.route_id == route_id,
            InspectionRouteSchedule.cron_expression == cron_expr,
            InspectionRouteSchedule.is_deleted == False,  # noqa: E712
        ]
        if assigned_to is not None:
            active_cond.append(
                InspectionRouteSchedule.assigned_to == assigned_to,
            )
        active_result = await db.execute(
            select(InspectionRouteSchedule).where(and_(*active_cond)).limit(1)
        )
        existing = active_result.scalar_one_or_none()
        if existing is not None:
            return existing

        # 清理同参数的已软删除记录
        dup_cond = [
            InspectionRouteSchedule.route_id == route_id,
            InspectionRouteSchedule.cron_expression == cron_expr,
            InspectionRouteSchedule.is_deleted == True,  # noqa: E712
        ]
        if assigned_to is not None:
            dup_cond.append(
                InspectionRouteSchedule.assigned_to == assigned_to,
            )
        else:
            dup_cond.append(
                InspectionRouteSchedule.assigned_to.is_(None),
            )
        deleted_result = await db.execute(
            select(InspectionRouteSchedule).where(and_(*dup_cond))
        )
        for old in deleted_result.scalars().all():
            await db.delete(old)
        await db.flush()

    schedule = InspectionRouteSchedule(**data)
    db.add(schedule)
    await db.flush()
    return schedule


async def get_schedules_by_route(
    db: AsyncSession, route_id: uuid.UUID
) -> list[InspectionRouteSchedule]:
    result = await db.execute(
        select(InspectionRouteSchedule)
        .where(
            InspectionRouteSchedule.route_id == route_id,
            InspectionRouteSchedule.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionRouteSchedule.created_at)
    )
    return list(result.scalars().all())


async def get_schedule_by_id(
    db: AsyncSession, schedule_id: uuid.UUID
) -> InspectionRouteSchedule | None:
    result = await db.execute(
        select(InspectionRouteSchedule).where(
            InspectionRouteSchedule.id == schedule_id,
            InspectionRouteSchedule.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def update_schedule(
    db: AsyncSession, schedule_id: uuid.UUID, data: dict,
    schedule: InspectionRouteSchedule | None = None,
) -> InspectionRouteSchedule | None:
    if schedule is None:
        schedule = await get_schedule_by_id(db, schedule_id)
    if not schedule:
        return None
    for key, value in data.items():
        if key == "assigned_to":
            schedule.assigned_to = value  # allow clearing to None
        elif value is not None:
            setattr(schedule, key, value)
    await db.flush()
    # Re-fetch to get server-generated onupdate values (e.g. updated_at)
    result = await db.execute(
        select(InspectionRouteSchedule).where(
            InspectionRouteSchedule.id == schedule_id,
            InspectionRouteSchedule.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def delete_schedule(
    db: AsyncSession, schedule_id: uuid.UUID
) -> bool:
    schedule = await get_schedule_by_id(db, schedule_id)
    if not schedule:
        return False
    schedule.is_deleted = True
    await db.flush()
    return True


async def get_due_schedules(
    db: AsyncSession,
) -> list[InspectionRouteSchedule]:
    """Find enabled schedules with active routes where next_trigger_at <= now."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(InspectionRouteSchedule)
        .join(InspectionRoute)
        .where(
            InspectionRouteSchedule.is_active == True,    # noqa: E712
            InspectionRouteSchedule.is_deleted == False,  # noqa: E712
            InspectionRouteSchedule.next_trigger_at <= now,
            InspectionRoute.is_active == True,            # noqa: E712
            InspectionRoute.is_deleted == False,          # noqa: E712
        )
    )
    return list(result.scalars().all())
