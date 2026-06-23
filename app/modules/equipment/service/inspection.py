"""Inspection service: business logic for routes, tasks, photos."""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from datetime import timezone as dt_timezone

from croniter import croniter  # type: ignore[import-untyped]
from fastapi import UploadFile
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, NotFoundException
from app.core.storage import delete_object, upload_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.equipment import repository as repo
from app.modules.equipment.models.inspection import (
    InspectionPhoto,
    InspectionRoute,
    InspectionRouteSchedule,
    InspectionTask,
)
from app.modules.equipment.models.inspection_route_location import (
    RouteLocation,
)
from app.modules.equipment.models.inspection_template import InspectionRecord
from app.modules.equipment.models.work_order import WorkOrder
from app.modules.equipment.schemas.inspection import (
    InspectionScheduleResponse,
)

_UPLOAD_DIR = "uploads/inspection"
_MAX_RETRIES = 3
os.makedirs(_UPLOAD_DIR, exist_ok=True)

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "待执行": ["执行中", "已关闭"],
    "执行中": ["已完成", "已关闭"],
    "已完成": ["已关闭"],
    "已关闭": [],
}


# ═══════════ 路线 ═══════════
async def create_route(
    db: AsyncSession, data: dict
) -> InspectionRoute:
    return await repo.create_route(db, data)


async def get_route_by_id(
    db: AsyncSession, route_id: uuid.UUID
) -> InspectionRoute:
    route = await repo.get_route_by_id(db, route_id)
    if not route:
        raise NotFoundException("巡检路线", str(route_id))
    return route


async def get_routes(
    db: AsyncSession,
    is_active: bool | None = None,
    location_id: uuid.UUID | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionRoute], int]:
    return await repo.get_routes(
        db,
        is_active=is_active,
        location_id=location_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


async def update_route(
    db: AsyncSession, route_id: uuid.UUID, data: dict
) -> InspectionRoute:
    route = await repo.update_route(db, route_id, data)
    if not route:
        raise NotFoundException("巡检路线", str(route_id))
    return route


async def delete_route(
    db: AsyncSession, route_id: uuid.UUID
) -> bool:
    if not await repo.delete_route(db, route_id):
        raise NotFoundException("巡检路线", str(route_id))
    return True


async def set_route_locations(
    db: AsyncSession, route_id: uuid.UUID, items: list[dict]
) -> list[RouteLocation]:
    await get_route_by_id(db, route_id)
    return await repo.set_route_locations(db, route_id, items)


# ═══════════ 任务 ═══════════
async def _generate_task_no(db: AsyncSession) -> str:
    today = datetime.now().strftime("%Y%m%d")
    max_no = await repo.get_max_task_no(db)
    if max_no:
        seq = int(max_no.split("-")[-1]) + 1
    else:
        seq = 1
    return f"IT-{today}-{seq:04d}"


async def _get_task(
    db: AsyncSession, task_id: uuid.UUID
) -> InspectionTask:
    task = await repo.get_task_by_id(db, task_id)
    if not task:
        raise NotFoundException("巡检任务", str(task_id))
    return task


def _validate_transition(current: str, target: str) -> None:
    allowed = _VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise AppException(
            message=f"状态不允许从 '{current}' 转换到 '{target}'"
        )


async def create_task(
    db: AsyncSession, data: dict
) -> InspectionTask:
    plan_type = data.get("plan_type", "设备巡检")
    has_route = data.get("route_id")
    has_equipment = data.get("equipment_id") or data.get("equipment_ids")

    if plan_type == "线路巡检":
        if not has_route:
            raise AppException(message="线路巡检必须选择巡检路线")
        # 线路巡检时，模板从路线地点下各设备的绑定获取，无需单独提供
    else:
        # 设备巡检：至少需要提供一个设备
        if not has_equipment:
            raise AppException(message="设备巡检至少需要选择一台设备")

        equipment_templates = data.get("equipment_templates")
        template_ids = data.get("template_ids")

        if equipment_templates:
            # 新方式：逐设备绑定模板
            equipment_ids = data.get("equipment_ids", [])
            eq_id_set = {str(eid) for eid in equipment_ids}
            # 校验 equipment_templates 的 key 都在 equipment_ids 中
            for eq_id in equipment_templates:
                if eq_id not in eq_id_set:
                    raise AppException(
                        message=f"设备 {eq_id} 不在已选择的设备列表中"
                    )
            # 校验每个已选设备都绑定了至少一个模板
            for eq_id in eq_id_set:
                if eq_id not in equipment_templates or not equipment_templates[eq_id]:
                    raise AppException(
                        message="每台已选设备必须绑定至少一个检查模板"
                    )
            # 将 UUID 转为字符串存储
            data["equipment_templates"] = {
                str(k): [str(tid) for tid in v]
                for k, v in equipment_templates.items()
            }
        elif template_ids:
            # 兼容旧方式：扁平模板列表（所有模板应用于所有设备）
            pass
        else:
            raise AppException(message="设备巡检必须选择检查模板")

    # JSON 列无法直接序列化 UUID 对象，需提前转为字符串
    if data.get("equipment_ids"):
        data["equipment_ids"] = [str(uid) for uid in data["equipment_ids"]]
    if data.get("template_ids"):
        data["template_ids"] = [str(uid) for uid in data["template_ids"]]

    for attempt in range(_MAX_RETRIES):
        task_no = await _generate_task_no(db)
        data["task_no"] = task_no
        data["status"] = "待执行"
        try:
            return await repo.create_task(db, data)
        except IntegrityError:
            if attempt < _MAX_RETRIES - 1:
                await db.rollback()
                continue
            raise AppException(message="任务号生成失败，请重试")
    raise AppException(message="任务号生成失败")


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
    return await repo.get_tasks(
        db,
        status=status,
        exclude_status=exclude_status,
        route_id=route_id,
        assigned_to=assigned_to,
        equipment_id=equipment_id,
        planned_time_from=planned_time_from,
        planned_time_to=planned_time_to,
        page=page,
        page_size=page_size,
    )


async def get_task_by_id(
    db: AsyncSession, task_id: uuid.UUID
) -> InspectionTask:
    return await _get_task(db, task_id)


async def _refetch_task(db: AsyncSession, task_id: uuid.UUID) -> InspectionTask:
    """eager re-fetch 任务及关联，避免 MissingGreenlet

    线路巡检需要加载到 RouteLocation.equipments → Equipment 和
    RouteLocation.location，确保通知服务和后续逻辑不触发懒加载。
    """
    from app.modules.equipment.models.inspection_route_location import (
        RouteLocation,
        RouteLocationEquipment,
    )

    result = await db.execute(
        select(InspectionTask)
        .options(
            selectinload(InspectionTask.route)
            .selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments)
            .selectinload(RouteLocationEquipment.equipment),
            selectinload(InspectionTask.route)
            .selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.location),
            selectinload(InspectionTask.equipment),
            selectinload(InspectionTask.assignee),
        )
        .where(InspectionTask.id == task_id)
    )
    return result.scalar_one()


async def start_task(
    db: AsyncSession, task_id: uuid.UUID
) -> InspectionTask:
    task = await _get_task(db, task_id)
    _validate_transition(task.status, "执行中")
    task.status = "执行中"
    task.started_at = datetime.now(UTC)
    await db.flush()
    refreshed = await _refetch_task(db, task_id)

    # 发送飞书通知（非关键路径，失败不影响主流程）
    from app.modules.equipment.service.inspection_notification import (
        send_inspection_start_notification,
    )

    await send_inspection_start_notification(refreshed, db)

    return refreshed


async def complete_task(
    db: AsyncSession, task_id: uuid.UUID
) -> InspectionTask:
    task = await _get_task(db, task_id)
    _validate_transition(task.status, "已完成")

    records = await repo.get_records_by_task(db, task_id)
    has_abnormal = any(r.result == "异常" for r in records)
    task.overall_result = "异常" if has_abnormal else "正常"
    task.status = "已完成"
    task.completed_at = datetime.now(UTC)
    await db.flush()
    return await _refetch_task(db, task_id)


async def submit_route_check(
    db: AsyncSession,
    task_id: uuid.UUID,
    overall_result: str,
    route_summary: str | None = None,
) -> InspectionTask:
    """线路巡检提交：设置总体结果和现场描述，完成任务"""
    task = await _get_task(db, task_id)
    if task.status != "执行中":
        raise AppException(message="任务未在'执行中'状态，不能提交")
    if task.plan_type != "线路巡检":
        raise AppException(message="仅线路巡检任务支持此操作")

    task.overall_result = overall_result
    task.route_summary = route_summary
    task.status = "已完成"
    task.completed_at = datetime.now(UTC)
    await db.flush()
    return await _refetch_task(db, task_id)


async def close_task(
    db: AsyncSession, task_id: uuid.UUID, remark: str | None = None
) -> InspectionTask:
    task = await _get_task(db, task_id)
    _validate_transition(task.status, "已关闭")

    # 检查是否有未处理的关联工单
    pending_wos = await repo.get_pending_work_orders_by_inspection_task(
        db, task_id
    )
    if pending_wos:
        wo_list = [
            {
                "id": str(wo.id),
                "work_order_no": wo.work_order_no,
                "equipment_name": wo.equipment.name if wo.equipment else None,
                "status": wo.status,
                "priority": wo.priority,
            }
            for wo in pending_wos
        ]
        raise AppException(
            message=(
                f"存在 {len(pending_wos)} 个未处理的异常工单，"
                f"请先处理后再关闭巡检"
            ),
            detail={"pending_work_orders": wo_list},
        )

    task.status = "已关闭"
    task.closed_at = datetime.now(UTC)
    task.closure_remark = remark
    await db.flush()
    return await _refetch_task(db, task_id)


# ═══════════ 巡检执行 ═══════════
async def _create_anomaly_work_order(
    db: AsyncSession,
    task: InspectionTask,
    equipment_id: uuid.UUID,
    abnormal_records: list[InspectionRecord],
    template_item_map: dict[uuid.UUID, str],
) -> WorkOrder | None:
    """为巡检异常自动创建工单。

    Returns:
        创建的工单，或 None（设备不存在或已有未关闭工单时）。
    """
    from app.modules.equipment.models.work_order import WorkOrder as WOModel

    # 获取设备信息
    equipment = await repo.get_equipment_by_id(db, equipment_id)
    if not equipment:
        return None

    # 去重：检查是否已有未关闭工单
    if await repo.exists_unclosed_work_order(db, task.id, equipment_id):
        return None

    # 获取工单责任人：优先使用设备独立设置的负责人，否则由部门负责人推导
    responsible_user_id: uuid.UUID | None = equipment.responsible_person_id
    if not responsible_user_id and equipment.department_id:
        dept_info = await repo.get_department_info(db, equipment.department_id)
        if dept_info:
            responsible_user_id = dept_info.get("leader_id")

    # 构建异常描述
    desc_parts: list[str] = []
    for r in abnormal_records:
        item_name = template_item_map.get(r.template_item_id, "未知检查项")
        remark = r.remark or ""
        desc_parts.append(f"{item_name}—{remark}" if remark else item_name)
    fault_description = "巡检发现异常：" + "；".join(desc_parts)

    # 生成工单号
    wo_no = await repo.get_max_work_order_no(db)
    today = datetime.now().strftime("%Y%m%d")
    if wo_no:
        seq = int(wo_no.split("-")[-1]) + 1
    else:
        seq = 1
    new_wo_no = f"WO-{today}-{seq:04d}"

    # 创建工单
    wo = WOModel(
        work_order_no=new_wo_no,
        equipment_id=equipment_id,
        order_type="异常处理",
        priority=equipment.importance,
        status="待处理",
        responsible_person_id=responsible_user_id,
        reporter_id=task.assigned_to,
        fault_description=fault_description,
        inspection_task_id=task.id,
        original_equipment_status=equipment.status,
    )
    db.add(wo)
    # 异常处理工单不自动改设备状态（问题可能只是仪表偏差，设备仍在运行）
    await db.flush()

    # 发送飞书通知（非关键路径）
    responsible_user_id_str: str | None = None
    if responsible_user_id:
        from app.platform.identity.models import User

        user_result = await db.execute(
            select(User.feishu_user_id).where(User.id == responsible_user_id)
        )
        responsible_user_id_str = user_result.scalar_one_or_none()

    from app.modules.equipment.service.inspection_notification import (
        send_work_order_notification,
    )

    await send_work_order_notification(
        wo, equipment, task, responsible_user_id_str,
    )

    return wo


async def submit_equipment_check(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    records: list[dict],
) -> list[InspectionRecord]:
    task = await _get_task(db, task_id)
    if task.status != "执行中":
        raise AppException(
            message="任务未在'执行中'状态，不能提交检查结果"
        )

    for r in records:
        r["task_id"] = str(task_id)
        r["equipment_id"] = str(equipment_id)

    # 校验：异常项必须填写实际值或备注
    for r in records:
        if r.get("result") == "异常" and not r.get("actual_value") and not r.get("remark"):
            raise AppException(message="检查项异常时必须填写实际值或备注")

    # 替换旧记录：先软删除同设备的已有记录，再创建新记录
    await repo.soft_delete_records_by_task_equipment(db, task_id, equipment_id)
    created_records = await repo.create_inspection_records(db, records)

    # 筛选异常记录
    abnormal = [r for r in created_records if r.result == "异常"]

    if abnormal:
        # 查询检查项名称（用于构建工单描述）
        item_ids = [r.template_item_id for r in abnormal]
        from app.modules.equipment.models.inspection_template import (
            InspectionTemplateItem,
        )

        item_result = await db.execute(
            select(
                InspectionTemplateItem.id,
                InspectionTemplateItem.item_name,
            ).where(InspectionTemplateItem.id.in_(item_ids))
        )
        template_item_map = {row.id: row.item_name for row in item_result.all()}

        # 重新获取 task（含 assignee 关系，用于工单 reporter_id）
        refreshed_task = await _refetch_task(db, task_id)

        await _create_anomaly_work_order(
            db, refreshed_task, equipment_id, abnormal, template_item_map
        )

    return created_records


async def skip_equipment_check(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    reason: str | None = None,
) -> list[InspectionRecord]:
    """跳过某台设备的巡检 — 为该设备所有检查项创建"跳过"记录。

    适用场景：设备停机维修中、无法接近检查等。

    先查该设备关联的模板检查项，为每项创建 result="跳过" 的记录。
    如果已有记录则覆盖（先删后建）。
    """
    from app.modules.equipment.service.ai.service import _get_inspection_items

    task = await _get_task(db, task_id)
    if task.status != "执行中":
        raise AppException(
            message="任务未在'执行中'状态，不能跳过设备检查"
        )

    # 获取该设备的检查项
    items = await _get_inspection_items(db, task, equipment_id)
    if not items:
        raise AppException(
            message="该设备没有关联检查项，无法跳过"
        )

    records = [
        {
            "task_id": str(task_id),
            "equipment_id": str(equipment_id),
            "template_item_id": str(item.id),
            "result": "跳过",
            "actual_value": "",
            "remark": reason or "现场无法检查",
        }
        for item in items
    ]

    # 先软删除已有记录，再创建新记录
    await repo.soft_delete_records_by_task_equipment(db, task_id, equipment_id)
    created = await repo.create_inspection_records(db, records)
    return created


# ═══════════ 照片 ═══════════
async def upload_photo(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID | None = None,
    file: UploadFile | None = None,
) -> InspectionPhoto:
    task = await _get_task(db, task_id)
    if task.status != "执行中":
        raise AppException(
            message="任务未在'执行中'状态，不能上传照片"
        )
    if file is None:
        raise AppException(message="请提供照片文件")

    content = await file.read()
    filename = f"{uuid.uuid4()}_{file.filename}"

    if minio_enabled():
        # MinIO 模式：上传到对象存储
        object_key = f"inspection/{filename}"
        upload_object(
            module="equipment",
            object_key=object_key,
            data=content,
            length=len(content),
            content_type=file.content_type or "image/jpeg",
        )
        stored_path = object_key
    else:
        # 本地文件系统模式（兼容旧部署）
        file_path = os.path.normpath(os.path.join(_UPLOAD_DIR, filename))
        if not file_path.startswith(os.path.normpath(_UPLOAD_DIR)):
            raise AppException(message="非法文件路径")
        with open(file_path, "wb") as f:
            f.write(content)
        stored_path = file_path

    photo_data = {
        "task_id": str(task_id),
        "equipment_id": str(equipment_id) if equipment_id else None,
        "file_name": file.filename or "unknown",
        "file_path": stored_path,
        "file_size": len(content),
    }
    return await repo.create_photo(db, photo_data)


async def get_task_photos(
    db: AsyncSession, task_id: uuid.UUID
) -> list[InspectionPhoto]:
    return await repo.get_photos_by_task(db, task_id)


async def delete_photo(
    db: AsyncSession, photo_id: uuid.UUID
) -> bool:
    photo = await repo.get_photo_by_id(db, photo_id)
    if not photo:
        raise NotFoundException("照片", str(photo_id))

    if minio_enabled():
        # MinIO 模式：从对象存储删除
        try:
            delete_object("equipment", photo.file_path)
        except Exception:
            # 删除 MinIO 文件失败不阻塞数据库操作
            pass
    elif os.path.exists(photo.file_path):
        os.remove(photo.file_path)

    return await repo.delete_photo(db, photo_id)


# ═══════════ 历史 ═══════════
async def get_history(
    db: AsyncSession,
    date_from: date | None = None,
    date_to: date | None = None,
    equipment_id: uuid.UUID | None = None,
    route_id: uuid.UUID | None = None,
    result: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionTask], int]:
    from app.modules.equipment.models.inspection import (
        InspectionTask as ITask,
    )

    conditions = [
        ITask.is_deleted == False,  # noqa: E712
        ITask.status.in_(["已完成", "已关闭"]),
    ]
    if date_from:
        conditions.append(ITask.planned_time >= date_from)
    if date_to:
        conditions.append(ITask.planned_time <= date_to)
    if equipment_id:
        conditions.append(
            or_(
                ITask.equipment_id == equipment_id,
                cast(ITask.equipment_ids, String).like(
                    f'%"{equipment_id}"%'
                ),
            )
        )
    if route_id:
        conditions.append(ITask.route_id == route_id)
    if result:
        conditions.append(ITask.overall_result == result)

    count_stmt = select(func.count(ITask.id)).where(and_(*conditions))
    total = (await db.execute(count_stmt)).scalar_one()

    from app.modules.equipment.models.inspection_route_location import (
        RouteLocation,
    )

    stmt = (
        select(ITask)
        .options(
            selectinload(ITask.route)
            .selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.equipments),
            selectinload(ITask.route)
            .selectinload(InspectionRoute.locations_rel)
            .selectinload(RouteLocation.location),
            selectinload(ITask.equipment),
            selectinload(ITask.assignee),
        )
        .where(and_(*conditions))
        .order_by(ITask.planned_time.desc(), ITask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result_set = await db.execute(stmt)
    return list(result_set.scalars().all()), total


async def get_task_detail(
    db: AsyncSession, task_id: uuid.UUID
) -> dict:
    task = await _get_task(db, task_id)
    records = await repo.get_records_by_task(db, task_id)
    photos = await repo.get_photos_by_task(db, task_id)
    return {"task": task, "records": records, "photos": photos}


# ═══════════ 定时任务 ═══════════

_CN_TZ = dt_timezone(timedelta(hours=8))


def compute_next_cron(
    expression: str, from_time: datetime | None = None,
) -> datetime:
    """Compute the next fire time for a cron expression.

    Raises ValueError if *expression* is not a valid cron string.
    """
    base = from_time or datetime.now(_CN_TZ)
    naive = base.replace(tzinfo=None)
    is_six = len(expression.split()) == 6
    cron = croniter(expression, naive, second_at_beginning=is_six)
    next_naive: datetime = cron.get_next(datetime)
    return next_naive.replace(tzinfo=_CN_TZ)


def _validate_cron(expression: str) -> None:
    """Raise AppException if cron expression is invalid."""
    try:
        is_six = len(expression.split()) == 6
        croniter(expression, second_at_beginning=is_six)
    except (ValueError, KeyError) as e:
        raise AppException(
            message=f"无效的 cron 表达式: {expression}",
            detail=str(e),
        ) from e


async def _batch_fetch_user_names(
    db: AsyncSession, user_ids: set[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Batch-fetch user names for a set of user IDs."""
    if not user_ids:
        return {}
    from app.platform.identity.models import User

    result = await db.execute(
        select(User.id, User.name).where(User.id.in_(user_ids))
    )
    return {row.id: row.name for row in result.all()}


async def create_schedule(
    db: AsyncSession, route_id: uuid.UUID, data: dict,
) -> InspectionRouteSchedule:
    await get_route_by_id(db, route_id)  # validate route exists
    _validate_cron(data["cron_expression"])
    data["route_id"] = str(route_id)
    data["assigned_to"] = str(data["assigned_to"])
    data["next_trigger_at"] = compute_next_cron(data["cron_expression"])
    return await repo.create_schedule(db, data)


async def get_schedules_by_route(
    db: AsyncSession, route_id: uuid.UUID,
) -> list[InspectionScheduleResponse]:
    schedules = await repo.get_schedules_by_route(db, route_id)

    # batch-fetch assignee names
    user_ids = {
        s.assigned_to
        for s in schedules
        if s.assigned_to is not None
    }
    name_map = await _batch_fetch_user_names(db, user_ids)

    result: list[InspectionScheduleResponse] = []
    for s in schedules:
        resp = InspectionScheduleResponse.model_validate(s)
        if s.assigned_to and s.assigned_to in name_map:
            resp.assignee_name = name_map[s.assigned_to]
        result.append(resp)
    return result


async def update_schedule(
    db: AsyncSession, schedule_id: uuid.UUID, data: dict,
) -> InspectionRouteSchedule:
    schedule = await repo.get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise NotFoundException("定时任务", str(schedule_id))
    if data.get("cron_expression"):
        _validate_cron(data["cron_expression"])
        data["next_trigger_at"] = compute_next_cron(data["cron_expression"])
    updated = await repo.update_schedule(db, schedule_id, data, schedule=schedule)
    assert updated is not None
    return updated


async def delete_schedule(
    db: AsyncSession, schedule_id: uuid.UUID,
) -> bool:
    if not await repo.delete_schedule(db, schedule_id):
        raise NotFoundException("定时任务", str(schedule_id))
    return True
