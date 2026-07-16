"""Inspection repository: data access for routes, tasks, photos."""

import uuid
from datetime import date, datetime

from sqlalchemy import String, and_, case, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import time as app_time
from app.modules.equipment.deps import EquipmentAccessContext
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
from app.modules.equipment.service.data_scope import apply_equipment_scope


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
    ctx: EquipmentAccessContext,
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
    count_stmt = apply_equipment_scope(
        count_stmt, ctx, InspectionRoute.created_by, "user_id"
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
    stmt = apply_equipment_scope(
        stmt, ctx, InspectionRoute.created_by, "user_id"
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
    today = app_time.now().strftime("%Y%m%d")
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


async def get_task_by_no(
    db: AsyncSession, task_no: str
) -> InspectionTask | None:
    """根据任务编号（如 IT-20260630-0001）查找任务。"""
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
            InspectionTask.task_no == task_no,
            InspectionTask.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_tasks(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
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
                # 线路巡检：通过路线-地点-设备链匹配
                and_(
                    InspectionTask.route_id.isnot(None),
                    InspectionTask.route_id.in_(
                        select(RouteLocation.route_id)
                        .join(
                            RouteLocationEquipment,
                            RouteLocationEquipment.route_location_id == RouteLocation.id,
                        )
                        .where(
                            RouteLocationEquipment.equipment_id == equipment_id,
                            RouteLocationEquipment.is_deleted == False,  # noqa: E712
                            RouteLocation.is_deleted == False,  # noqa: E712
                        )
                    ),
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
    count_stmt = apply_equipment_scope(
        count_stmt, ctx, InspectionTask.created_by, "user_id"
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
    stmt = apply_equipment_scope(stmt, ctx, InspectionTask.created_by, "user_id")
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


async def get_stale_completed_tasks(
    db: AsyncSession, cutoff: datetime,
) -> list[InspectionTask]:
    """Return tasks eligible for auto-close.

    Conditions: status='已完成', overall_result='正常',
    completed_at <= cutoff, is_deleted=False.
    """
    stmt = (
        select(InspectionTask)
        .where(
            InspectionTask.status == "已完成",
            InspectionTask.overall_result == "正常",
            InspectionTask.completed_at <= cutoff,
            InspectionTask.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionTask.completed_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


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


async def get_equipment_nos_by_ids(
    db: AsyncSession, equipment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """根据设备ID列表批量获取设备编号映射"""
    if not equipment_ids:
        return {}
    stmt = select(Equipment.id, Equipment.equipment_no).where(
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
    now = app_time.now()
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


# ═══════════ 数据分析聚合查询 ═══════════


async def get_trend_data(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    from_date: date,
    to_date: date,
) -> list[dict]:
    """参数趋势时序：每检查项一条序列，每日期一个数据点。

    时间轴用记录自身 created_at（读数提交时刻，恒有值），
    不依赖任务 completed_at（任务未整体完成时为 NULL，会漏掉在检数据）。
    """
    from app.modules.equipment.models.inspection_template import (
        InspectionRecord,
        InspectionTemplateItem,
    )

    rec_date = func.date(InspectionRecord.created_at)
    subq = (
        select(
            InspectionRecord.template_item_id,
            rec_date.label("date"),
            func.max(InspectionRecord.numeric_value).label("value"),
            func.max(InspectionRecord.result).label("result"),
        )
        .where(
            InspectionRecord.equipment_id == equipment_id,
            # item_ids 为空时不过滤，返回该设备全部数值型参数（默认全选）
            *([InspectionRecord.template_item_id.in_(item_ids)] if item_ids else []),
            InspectionRecord.numeric_value.isnot(None),
            InspectionRecord.is_deleted == False,  # noqa: E712
            rec_date >= from_date,
            rec_date <= to_date,
        )
        .group_by(InspectionRecord.template_item_id, rec_date)
        .subquery()
    )

    stmt = (
        select(
            InspectionTemplateItem.id,
            InspectionTemplateItem.item_name,
            InspectionTemplateItem.unit,
            subq.c.date,
            subq.c.value,
            subq.c.result,
        )
        .join(subq, InspectionTemplateItem.id == subq.c.template_item_id)
        .where(InspectionTemplateItem.is_deleted == False)  # noqa: E712
        .order_by(InspectionTemplateItem.sort_order, subq.c.date)
    )

    rows = (await db.execute(stmt)).all()

    series_map: dict[uuid.UUID, dict] = {}
    for row in rows:
        tid = row.id
        if tid not in series_map:
            series_map[tid] = {
                "template_item_id": str(tid),
                "item_name": row.item_name,
                "unit": row.unit or "",
                "data_points": [],
            }
        series_map[tid]["data_points"].append({
            "date": str(row.date),
            "value": row.value,
            "result": row.result,
        })

    return list(series_map.values())


async def get_anomaly_stats(
    db: AsyncSession,
    from_date: date,
    to_date: date,
    ctx: EquipmentAccessContext,
) -> dict:
    """异常热力统计：设备排行、检查项排行、月度趋势。"""
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.inspection import InspectionTask
    from app.modules.equipment.models.inspection_template import (
        InspectionRecord,
        InspectionTemplateItem,
    )

    base_q = (
        select(
            InspectionRecord.equipment_id,
            InspectionRecord.template_item_id,
            InspectionRecord.result,
            func.date(InspectionTask.completed_at).label("date"),
        )
        .join(InspectionTask, InspectionRecord.task_id == InspectionTask.id)
        # outer join：超管路径不丢弃无设备记录;数据范围过滤在下方按部门收口
        .join(Equipment, InspectionRecord.equipment_id == Equipment.id, isouter=True)
        .where(
            InspectionRecord.is_deleted == False,  # noqa: E712
            InspectionTask.is_deleted == False,    # noqa: E712
            InspectionTask.completed_at >= from_date,
            InspectionTask.completed_at <= to_date,
        )
    )
    # 按设备部门过滤(超管放行);无部门设备对非超管天然不可见
    base_q = apply_equipment_scope(
        base_q, ctx, Equipment.department_id, "department_id"
    )
    base = base_q.subquery()

    # 设备排行 TOP10
    eq_stmt = (
        select(
            base.c.equipment_id,
            Equipment.name,
            Equipment.equipment_no,
            func.count().label("total"),
            func.sum(case((base.c.result == "异常", 1), else_=0)).label("abnormal"),
        )
        .join(Equipment, base.c.equipment_id == Equipment.id)
        .group_by(base.c.equipment_id, Equipment.name, Equipment.equipment_no)
        .having(func.count() >= 1)
        .order_by(func.sum(case((base.c.result == "异常", 1), else_=0)).desc())
        .limit(10)
    )
    eq_rows = (await db.execute(eq_stmt)).all()
    equipment_ranking = [
        {
            "equipment_id": str(r.equipment_id),
            "equipment_name": r.name or "",
            "equipment_no": r.equipment_no or "",
            "total_count": r.total,
            "abnormal_count": r.abnormal or 0,
            "anomaly_rate": round((r.abnormal or 0) / r.total * 100, 1) if r.total else 0,
        }
        for r in eq_rows
    ]

    # 检查项排行 TOP10
    item_stmt = (
        select(
            InspectionTemplateItem.id,
            InspectionTemplateItem.item_name,
            func.count().label("total"),
            func.sum(case((base.c.result == "异常", 1), else_=0)).label("abnormal"),
        )
        .join(
            InspectionTemplateItem,
            base.c.template_item_id == InspectionTemplateItem.id,
        )
        .group_by(InspectionTemplateItem.id, InspectionTemplateItem.item_name)
        .having(func.count() >= 1)
        .order_by(func.sum(case((base.c.result == "异常", 1), else_=0)).desc())
        .limit(10)
    )
    item_rows = (await db.execute(item_stmt)).all()
    item_ranking = [
        {
            "template_item_id": str(r.id),
            "item_name": r.item_name,
            "template_name": "",
            "total_count": r.total,
            "abnormal_count": r.abnormal or 0,
            "anomaly_rate": round((r.abnormal or 0) / r.total * 100, 1) if r.total else 0,
        }
        for r in item_rows
    ]

    # 月度趋势
    month_stmt = (
        select(
            func.to_char(func.date_trunc("month", base.c.date), "YYYY-MM").label("month"),
            func.count().label("total"),
            func.sum(case((base.c.result == "正常", 1), else_=0)).label("normal"),
            func.sum(case((base.c.result == "异常", 1), else_=0)).label("abnormal"),
            func.sum(case((base.c.result == "跳过", 1), else_=0)).label("skip"),
        )
        .group_by(text("month"))
        .order_by(text("month"))
    )
    month_rows = (await db.execute(month_stmt)).all()
    monthly_trend = [
        {
            "month": r.month,
            "normal": r.normal or 0,
            "abnormal": r.abnormal or 0,
            "skip": r.skip or 0,
            "total": r.total,
        }
        for r in month_rows
    ]

    # 设备×检查项 矩阵（热力图/雷达/仪表盘共用数据源）
    matrix_stmt = (
        select(
            base.c.equipment_id,
            Equipment.name.label("equipment_name"),
            Equipment.equipment_no,
            base.c.template_item_id,
            InspectionTemplateItem.item_name,
            func.count().label("total"),
            func.sum(case((base.c.result == "异常", 1), else_=0)).label("abnormal"),
        )
        .join(Equipment, base.c.equipment_id == Equipment.id)
        .join(
            InspectionTemplateItem,
            base.c.template_item_id == InspectionTemplateItem.id,
        )
        .group_by(
            base.c.equipment_id,
            Equipment.name,
            Equipment.equipment_no,
            base.c.template_item_id,
            InspectionTemplateItem.item_name,
        )
        .having(func.count() >= 1)
        # ponytail: 全部设备×检查项，不截断（用户要求）。若某厂矩阵过大再加 having/limit。
    )
    matrix_rows = (await db.execute(matrix_stmt)).all()
    matrix = [
        {
            "equipment_id": str(r.equipment_id),
            "equipment_name": r.equipment_name or "",
            "equipment_no": r.equipment_no or "",
            "template_item_id": str(r.template_item_id),
            "item_name": r.item_name or "",
            "total_count": r.total,
            "abnormal_count": r.abnormal or 0,
            "anomaly_rate": round((r.abnormal or 0) / r.total * 100, 1) if r.total else 0,
        }
        for r in matrix_rows
    ]

    return {
        "equipment_ranking": equipment_ranking,
        "item_ranking": item_ranking,
        "monthly_trend": monthly_trend,
        "matrix": matrix,
    }


async def get_analytics_equipment_list(
    db: AsyncSession,
    keyword: str | None = None,
    ctx: EquipmentAccessContext | None = None,
) -> list[dict]:
    """可选设备列表：只返回有数值型检查项且有巡检记录的设备。"""
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.inspection import InspectionTask
    from app.modules.equipment.models.inspection_template import (
        InspectionRecord,
        InspectionTemplateItem,
    )

    eq_stmt = (
        select(
            Equipment.id,
            Equipment.name,
            Equipment.equipment_no,
            func.max(InspectionTask.completed_at).label("latest"),
        )
        .select_from(Equipment)
        .join(InspectionRecord, Equipment.id == InspectionRecord.equipment_id)
        .join(
            InspectionTemplateItem,
            InspectionRecord.template_item_id == InspectionTemplateItem.id,
        )
        .join(InspectionTask, InspectionRecord.task_id == InspectionTask.id)
        .where(
            InspectionRecord.numeric_value.isnot(None),
            InspectionTemplateItem.data_type == "numeric",
            InspectionRecord.is_deleted == False,   # noqa: E712
            InspectionTemplateItem.is_deleted == False,  # noqa: E712
            InspectionTask.is_deleted == False,     # noqa: E712
        )
    )
    if keyword:
        eq_stmt = eq_stmt.where(
            Equipment.name.ilike(f"%{keyword}%")
            | Equipment.equipment_no.ilike(f"%{keyword}%")
        )
    # 按设备部门过滤数据范围(ctx 为空时不过滤,兼容内部无上下文调用)
    if ctx is not None:
        eq_stmt = apply_equipment_scope(
            eq_stmt, ctx, Equipment.department_id, "department_id"
        )
    eq_stmt = eq_stmt.group_by(Equipment.id, Equipment.name, Equipment.equipment_no)

    rows = (await db.execute(eq_stmt)).all()

    equipments = [
        {
            "equipment_id": str(r.id),
            "equipment_name": r.name,
            "equipment_no": r.equipment_no or "",
            "numeric_item_count": 0,  # 由调用方填充
            "latest_inspection_date": str(r.latest.date()) if r.latest else "",
        }
        for r in rows
    ]

    # 补充每台设备的数值型检查项数量
    for eq in equipments:
        count_stmt = (
            select(func.count())
            .select_from(InspectionRecord)
            .join(
                InspectionTemplateItem,
                InspectionRecord.template_item_id == InspectionTemplateItem.id,
            )
            .where(
                InspectionRecord.equipment_id == uuid.UUID(eq["equipment_id"]),
                InspectionRecord.numeric_value.isnot(None),
                InspectionTemplateItem.data_type == "numeric",
                InspectionRecord.is_deleted == False,   # noqa: E712
                InspectionTemplateItem.is_deleted == False,  # noqa: E712
            )
        )
        eq["numeric_item_count"] = (await db.execute(count_stmt)).scalar() or 0

    return equipments


async def get_linkage_stats(
    db: AsyncSession,
    from_date: date,
    to_date: date,
    ctx: EquipmentAccessContext,
) -> dict:
    """巡检-维修联动：按月统计巡检异常数 与 各类型工单量。"""
    from app.modules.equipment.models.equipment import Equipment
    from app.modules.equipment.models.inspection import InspectionTask
    from app.modules.equipment.models.inspection_template import InspectionRecord
    from app.modules.equipment.models.work_order import WorkOrder

    # 巡检异常/月（复用 anomaly 的 base 口径：按任务 completed_at 归月）
    anomaly_base_q = (
        select(
            InspectionRecord.result,
            func.date(InspectionTask.completed_at).label("date"),
        )
        .join(InspectionTask, InspectionRecord.task_id == InspectionTask.id)
        # outer join：超管路径不丢弃无设备记录
        .join(Equipment, InspectionRecord.equipment_id == Equipment.id, isouter=True)
        .where(
            InspectionRecord.is_deleted == False,  # noqa: E712
            InspectionTask.is_deleted == False,    # noqa: E712
            InspectionTask.completed_at >= from_date,
            InspectionTask.completed_at <= to_date,
        )
    )
    anomaly_base_q = apply_equipment_scope(
        anomaly_base_q, ctx, Equipment.department_id, "department_id"
    )
    anomaly_base = anomaly_base_q.subquery()
    anomaly_stmt = (
        select(
            func.to_char(func.date_trunc("month", anomaly_base.c.date), "YYYY-MM").label("month"),
            func.sum(case((anomaly_base.c.result == "异常", 1), else_=0)).label("count"),
        )
        .group_by(text("month"))
        .order_by(text("month"))
    )
    anomaly_rows = (await db.execute(anomaly_stmt)).all()
    anomaly = [{"month": r.month, "count": r.count or 0} for r in anomaly_rows]

    # 工单量/月/类型（按报修时间 reported_at 归月）
    wo_stmt = (
        select(
            func.to_char(func.date_trunc("month", WorkOrder.reported_at), "YYYY-MM").label("month"),
            WorkOrder.order_type,
            func.count().label("count"),
        )
        # 工单无 department_id,经 equipment_id 关联设备部门(WorkOrder.equipment_id 非空)
        .join(Equipment, WorkOrder.equipment_id == Equipment.id)
        .where(
            WorkOrder.is_deleted == False,  # noqa: E712
            WorkOrder.order_type.notin_(["计划维护", "日常维护"]),
            WorkOrder.reported_at >= from_date,
            WorkOrder.reported_at <= to_date,
        )
        .group_by(text("month"), WorkOrder.order_type)
        .order_by(text("month"))
    )
    wo_stmt = apply_equipment_scope(
        wo_stmt, ctx, Equipment.department_id, "department_id"
    )
    wo_rows = (await db.execute(wo_stmt)).all()
    work_orders = [
        {"month": r.month, "order_type": r.order_type, "count": r.count}
        for r in wo_rows
    ]

    return {"anomaly": anomaly, "work_orders": work_orders}
