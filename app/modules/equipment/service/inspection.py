"""Inspection service: business logic for routes, tasks, photos."""

import os
import uuid
from datetime import UTC, date, datetime

from fastapi import UploadFile
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models.inspection import (
    InspectionPhoto,
    InspectionRoute,
    InspectionTask,
)
from app.modules.equipment.models.inspection_template import InspectionRecord
from app.modules.equipment.models.work_order import WorkOrder

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
    area: str | None = None,
    period_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionRoute], int]:
    return await repo.get_routes(
        db,
        is_active=is_active,
        area=area,
        period_type=period_type,
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


async def set_route_equipments(
    db: AsyncSession, route_id: uuid.UUID, items: list[dict]
) -> list:
    await get_route_by_id(db, route_id)
    return await repo.set_route_equipments(db, route_id, items)


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
        # 线路巡检时，如果未提供模板，则从路线的默认模板获取
        if not data.get("template_id"):
            route = await get_route_by_id(db, data["route_id"])
            if route.template_id:
                data["template_id"] = str(route.template_id)
            else:
                raise AppException(message="所选路线未配置默认检查模板，请手动选择模板")
    else:
        # 设备巡检：至少需要提供一个设备
        if not has_equipment:
            raise AppException(message="设备巡检至少需要选择一台设备")
        if not data.get("template_id"):
            raise AppException(message="设备巡检必须选择检查模板")

    # JSON 列无法直接序列化 UUID 对象，需提前转为字符串
    if data.get("equipment_ids"):
        data["equipment_ids"] = [str(uid) for uid in data["equipment_ids"]]

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
    route_id: uuid.UUID | None = None,
    assigned_to: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    planned_date_from: date | None = None,
    planned_date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionTask], int]:
    return await repo.get_tasks(
        db,
        status=status,
        route_id=route_id,
        assigned_to=assigned_to,
        equipment_id=equipment_id,
        planned_date_from=planned_date_from,
        planned_date_to=planned_date_to,
        page=page,
        page_size=page_size,
    )


async def get_task_by_id(
    db: AsyncSession, task_id: uuid.UUID
) -> InspectionTask:
    return await _get_task(db, task_id)


async def _refetch_task(db: AsyncSession, task_id: uuid.UUID) -> InspectionTask:
    """eager re-fetch 任务及关联，避免 MissingGreenlet"""
    from app.modules.equipment.models.inspection import InspectionRoute as IRoute

    result = await db.execute(
        select(InspectionTask)
        .options(
            selectinload(InspectionTask.route).selectinload(IRoute.equipments_rel),
            selectinload(InspectionTask.equipment),
            selectinload(InspectionTask.template),
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

    if task.plan_type == "线路巡检":
        raise AppException(
            message="线路巡检任务请使用线路巡检提交接口完成"
        )

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
    await db.flush()

    # 设备状态改为维修中
    equipment.status = "维修中"
    await db.flush()

    # 发送飞书通知（非关键路径）
    responsible_open_id: str | None = None
    if responsible_user_id:
        from app.platform.identity.models import User

        user_result = await db.execute(
            select(User.feishu_open_id).where(User.id == responsible_user_id)
        )
        responsible_open_id = user_result.scalar_one_or_none()

    from app.modules.equipment.service.inspection_notification import (
        send_work_order_notification,
    )

    await send_work_order_notification(wo, equipment, task, responsible_open_id)

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

    filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.normpath(os.path.join(_UPLOAD_DIR, filename))
    if not file_path.startswith(os.path.normpath(_UPLOAD_DIR)):
        raise AppException(message="非法文件路径")

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    photo_data = {
        "task_id": str(task_id),
        "equipment_id": str(equipment_id) if equipment_id else None,
        "file_name": file.filename or "unknown",
        "file_path": file_path,
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
    if os.path.exists(photo.file_path):
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
        conditions.append(ITask.planned_date >= date_from)
    if date_to:
        conditions.append(ITask.planned_date <= date_to)
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

    stmt = (
        select(ITask)
        .options(
            selectinload(ITask.route).selectinload(InspectionRoute.equipments_rel),
            selectinload(ITask.equipment),
            selectinload(ITask.template),
            selectinload(ITask.assignee),
        )
        .where(and_(*conditions))
        .order_by(ITask.planned_date.desc(), ITask.created_at.desc())
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
