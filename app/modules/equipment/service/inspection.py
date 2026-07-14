"""Inspection service: business logic for routes, tasks, photos."""

import base64
import logging
import os
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from croniter import croniter  # type: ignore[import-untyped]
from fastapi import UploadFile
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import time as app_time
from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.core.storage import delete_object, upload_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.equipment import repository as repo
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.equipment import Equipment
from app.modules.equipment.models.inspection import (
    InspectionPhoto,
    InspectionRoute,
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
    InspectionTemplate,
    InspectionTemplateItem,
)
from app.modules.equipment.models.work_order import WorkOrder
from app.modules.equipment.schemas.inspection import (
    InspectionScheduleResponse,
)
from app.modules.equipment.service.data_scope import verify_write_ownership

logger = logging.getLogger(__name__)

_UPLOAD_DIR = "uploads/inspection"
_MAX_RETRIES = 3
os.makedirs(_UPLOAD_DIR, exist_ok=True)

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "待执行": ["执行中", "已关闭"],
    "执行中": ["已完成", "已关闭"],
    "已完成": ["已关闭"],
    "已关闭": [],
}


def _parse_numeric_value(s: str | None) -> Decimal | None:
    """严格解析数值型实测值：空→None；纯数字→Decimal；其余→抛 InvalidOperation。"""
    s = (s or "").strip()
    if not s:
        return None
    return Decimal(s)


# ═══════════ 路线 ═══════════
async def create_route(
    db: AsyncSession, data: dict[str, Any], ctx: EquipmentAccessContext
) -> InspectionRoute:
    data["created_by"] = ctx.user.id
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
    ctx: EquipmentAccessContext,
    is_active: bool | None = None,
    location_id: uuid.UUID | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InspectionRoute], int]:
    return await repo.get_routes(
        db,
        ctx=ctx,
        is_active=is_active,
        location_id=location_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


async def update_route(
    db: AsyncSession, route_id: uuid.UUID, data: dict[str, Any], ctx: EquipmentAccessContext
) -> InspectionRoute:
    route = await repo.get_route_by_id(db, route_id)
    if not route:
        raise NotFoundException("巡检路线", str(route_id))
    await verify_write_ownership(ctx, route, "created_by", "user_id")
    updated = await repo.update_route(db, route_id, data)
    if not updated:
        raise NotFoundException("巡检路线", str(route_id))
    return updated


async def delete_route(
    db: AsyncSession, route_id: uuid.UUID, ctx: EquipmentAccessContext
) -> bool:
    route = await repo.get_route_by_id(db, route_id)
    if not route:
        raise NotFoundException("巡检路线", str(route_id))
    await verify_write_ownership(ctx, route, "created_by", "user_id")
    if not await repo.delete_route(db, route_id):
        raise NotFoundException("巡检路线", str(route_id))
    return True


async def set_route_locations(
    db: AsyncSession,
    route_id: uuid.UUID,
    items: list[dict[str, Any]],
    ctx: EquipmentAccessContext,
) -> list[RouteLocation]:
    route = await get_route_by_id(db, route_id)
    await verify_write_ownership(ctx, route, "created_by", "user_id")
    return await repo.set_route_locations(db, route_id, items)


# ═══════════ 任务 ═══════════
async def _generate_task_no(db: AsyncSession) -> str:
    today = app_time.now().strftime("%Y%m%d")
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


async def get_inspection_items(
    db: AsyncSession, task: InspectionTask, equipment_id: uuid.UUID
) -> tuple[list[InspectionTemplateItem], dict[uuid.UUID, str]]:
    """获取巡检检查项 — 统一处理线路巡检和设备巡检的多模板合并。

    线路巡检：从 route → locations → equipment → templates 链获取
    设备巡检（新）：从 task.equipment_templates 按设备匹配
    设备巡检（旧）：从 task.template_ids 扁平列表（兼容）

    返回 (检查项列表, item_id → template_name 映射)。
    template_name 预收集避免调用方通过 relationship 懒加载触发 MissingGreenlet。
    """
    all_items: list[InspectionTemplateItem] = []
    template_ids: set[uuid.UUID] = set()
    item_template_names: dict[uuid.UUID, str] = {}

    if task.route_id:
        # 线路巡检：找到该设备在路线中的所有模板绑定
        loc_stmt = select(RouteLocation).where(
            RouteLocation.route_id == task.route_id,
            RouteLocation.is_deleted == False,  # noqa: E712
        )
        locs = (await db.execute(loc_stmt)).scalars().all()

        for loc in locs:
            eq_stmt = select(RouteLocationEquipment).where(
                RouteLocationEquipment.route_location_id == loc.id,
                RouteLocationEquipment.equipment_id == equipment_id,
                RouteLocationEquipment.is_deleted == False,  # noqa: E712
            )
            route_eqs = (await db.execute(eq_stmt)).scalars().all()
            for req in route_eqs:
                tpl_stmt = select(RouteEquipmentTemplate).where(
                    RouteEquipmentTemplate.route_equipment_id == req.id,
                    RouteEquipmentTemplate.is_deleted == False,  # noqa: E712
                )
                tpls = (await db.execute(tpl_stmt)).scalars().all()
                for tpl in tpls:
                    template_ids.add(tpl.template_id)

    elif task.equipment_templates:
        # 新方式：从设备-模板映射中获取该设备绑定的模板
        eq_id_str = str(equipment_id)
        tpl_ids = task.equipment_templates.get(eq_id_str, [])
        for tid_str in tpl_ids:
            template_ids.add(uuid.UUID(tid_str))

    elif task.template_ids:
        # 兼容旧数据：扁平模板列表（所有模板应用于所有设备）
        for tid_str in task.template_ids:
            tid = uuid.UUID(tid_str) if isinstance(tid_str, str) else tid_str
            template_ids.add(tid)

    for tid in template_ids:
        result = await db.execute(
            select(InspectionTemplate)
            .options(selectinload(InspectionTemplate.items))
            .where(
                InspectionTemplate.id == tid,
                InspectionTemplate.is_deleted == False,  # noqa: E712
            )
        )
        template = result.scalar_one_or_none()
        if template and template.items:
            tpl_name = template.name
            for item in sorted(template.items, key=lambda x: x.sort_order):
                # ponytail: 不去重 — 同名检查项来自不同模板时 agent 需要看到全部
                # 通过 template_item_id 区分，避免提交时定位到错误的检查项
                all_items.append(item)
                item_template_names[item.id] = tpl_name

    return all_items, item_template_names


def _validate_transition(current: str, target: str) -> None:
    allowed = _VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise AppException(
            message=f"状态不允许从 '{current}' 转换到 '{target}'"
        )


async def create_task(
    db: AsyncSession, data: dict[str, Any], ctx: EquipmentAccessContext
) -> InspectionTask:
    data["created_by"] = ctx.user.id
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
    return await repo.get_tasks(
        db,
        ctx=ctx,
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
    db: AsyncSession, task_id: uuid.UUID, ctx: EquipmentAccessContext
) -> InspectionTask:
    task = await _get_task(db, task_id)
    await verify_write_ownership(ctx, task, "created_by", "user_id")
    _validate_transition(task.status, "执行中")
    task.status = "执行中"
    task.started_at = app_time.now()
    await db.flush()
    refreshed = await _refetch_task(db, task_id)

    # 发送飞书通知（非关键路径，失败不影响主流程）
    from app.modules.equipment.service.inspection_notification import (
        send_inspection_start_notification,
    )

    await send_inspection_start_notification(refreshed, db)

    return refreshed


async def complete_task(
    db: AsyncSession, task_id: uuid.UUID, ctx: EquipmentAccessContext
) -> InspectionTask:
    task = await _get_task(db, task_id)
    await verify_write_ownership(ctx, task, "created_by", "user_id")
    _validate_transition(task.status, "已完成")

    records = await repo.get_records_by_task(db, task_id)
    has_abnormal = any(r.result == "异常" for r in records)
    task.overall_result = "异常" if has_abnormal else "正常"
    task.status = "已完成"
    task.completed_at = app_time.now()
    await db.flush()
    return await _refetch_task(db, task_id)


async def submit_route_check(
    db: AsyncSession,
    task_id: uuid.UUID,
    overall_result: str,
    route_summary: str | None = None,
    ctx: EquipmentAccessContext | None = None,
) -> InspectionTask:
    """线路巡检提交：设置总体结果和现场描述，完成任务"""
    task = await _get_task(db, task_id)
    if ctx:
        await verify_write_ownership(ctx, task, "created_by", "user_id")
    if task.status != "执行中":
        raise AppException(message="任务未在'执行中'状态，不能提交")
    if task.plan_type != "线路巡检":
        raise AppException(message="仅线路巡检任务支持此操作")

    task.overall_result = overall_result
    task.route_summary = route_summary
    task.status = "已完成"
    task.completed_at = app_time.now()
    await db.flush()
    return await _refetch_task(db, task_id)


async def close_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    remark: str | None = None,
    ctx: EquipmentAccessContext | None = None,
) -> InspectionTask:
    task = await _get_task(db, task_id)
    if ctx:
        await verify_write_ownership(ctx, task, "created_by", "user_id")
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
    task.closed_at = app_time.now()
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

    # 生成工单号 + 创建工单（含并发重试）
    wo: WOModel | None = None
    for attempt in range(_MAX_RETRIES):
        wo_no = await repo.get_max_work_order_no(db)
        today = app_time.now().strftime("%Y%m%d")
        if wo_no:
            seq = int(wo_no.split("-")[-1]) + 1
        else:
            seq = 1
        new_wo_no = f"WO-{today}-{seq:04d}"

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
        try:
            await db.flush()
            break
        except IntegrityError:
            if attempt < _MAX_RETRIES - 1:
                await db.rollback()
                continue
            raise

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

    assert wo is not None  # 循环内必赋值或抛异常，循环后 wo 一定存在
    await send_work_order_notification(
        wo, equipment, task, responsible_user_id_str,
    )

    return wo


async def submit_equipment_check(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    records: list[dict[str, Any]],
    ctx: EquipmentAccessContext | None = None,
) -> list[InspectionRecord]:
    task = await _get_task(db, task_id)
    if ctx:
        await verify_write_ownership(ctx, task, "created_by", "user_id")
    if task.status != "执行中":
        raise AppException(
            message="任务未在'执行中'状态，不能提交检查结果"
        )

    # 校验设备是否存在且属于此任务
    eq_result = await db.execute(
        select(Equipment).where(
            Equipment.id == equipment_id, Equipment.is_deleted == False  # noqa: E712
        )
    )
    if not eq_result.scalar_one_or_none():
        raise NotFoundException(resource="设备", resource_id=str(equipment_id))

    if task.route_id:
        # 线路巡检：校验设备在路线上
        rle_result = await db.execute(
            select(RouteLocationEquipment).join(RouteLocation).where(
                RouteLocation.route_id == task.route_id,
                RouteLocationEquipment.equipment_id == equipment_id,
                RouteLocationEquipment.is_deleted == False,  # noqa: E712
                RouteLocation.is_deleted == False,  # noqa: E712
            )
        )
        if not rle_result.scalar_one_or_none():
            raise AppException(
                message=f"设备 {equipment_id} 不属于此巡检路线，请确认设备ID是否正确"
            )
    elif task.equipment_ids:
        if str(equipment_id) not in task.equipment_ids:
            raise AppException(
                message=f"设备 {equipment_id} 不在此巡检任务中，请确认设备ID是否正确"
            )
    elif task.equipment_id and task.equipment_id != equipment_id:
        raise AppException(
            message=f"设备 {equipment_id} 不匹配此巡检任务的设备"
        )

    for r in records:
        r["task_id"] = str(task_id)
        r["equipment_id"] = str(equipment_id)

    # 校验：异常项必须填写实际值或备注
    for r in records:
        if (
            r.get("result") == "异常"
            and not r.get("actual_value")
            and not r.get("remark")
        ):
            raise AppException(message="检查项异常时必须填写实际值或备注")

    # 数值型检查项：严格解析 actual_value → numeric_value，脏值阻断
    from app.modules.equipment.models.inspection_template import (
        InspectionTemplateItem,
    )

    item_ids = [
        uuid.UUID(r["template_item_id"])
        if isinstance(r["template_item_id"], str)
        else r["template_item_id"]
        for r in records
        if r.get("template_item_id")
    ]
    type_result = await db.execute(
        select(
            InspectionTemplateItem.id,
            InspectionTemplateItem.item_name,
            InspectionTemplateItem.data_type,
            InspectionTemplateItem.unit,
        ).where(InspectionTemplateItem.id.in_(item_ids))
    )
    type_map = {
        row.id: (row.item_name, row.data_type, row.unit)
        for row in type_result.all()
    }

    for r in records:
        tid = r.get("template_item_id")
        if not tid:
            continue
        tid_uuid = uuid.UUID(tid) if isinstance(tid, str) else tid
        info = type_map.get(tid_uuid)
        if not info:
            continue
        item_name, data_type, unit = info
        if data_type != "numeric":
            continue
        try:
            r["numeric_value"] = _parse_numeric_value(r.get("actual_value"))
        except InvalidOperation:
            unit_hint = (
                f"（单位 {unit} 已在检查项配置中，无需重复填写）" if unit else ""
            )
            raise AppException(
                message=(
                    f"提交失败：检查项「{item_name}」的实测值"
                    f"「{r.get('actual_value')}」无法解析为数字，"
                    f"请填写纯数字{unit_hint}。"
                )
            )

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
    task = await _get_task(db, task_id)
    if task.status != "执行中":
        raise AppException(
            message="任务未在'执行中'状态，不能跳过设备检查"
        )

    # 获取该设备的检查项
    items, _ = await get_inspection_items(db, task, equipment_id)
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
    db: AsyncSession, photo_id: uuid.UUID, ctx: EquipmentAccessContext | None = None
) -> bool:
    photo = await repo.get_photo_by_id(db, photo_id)
    if not photo:
        raise NotFoundException("照片", str(photo_id))

    # 验证所有权：通过关联的巡检任务验证用户是否有写权限
    if ctx:
        task = await _get_task(db, photo.task_id)
        await verify_write_ownership(ctx, task, "created_by", "user_id")

    if minio_enabled():
        # MinIO 模式：从对象存储删除
        try:
            delete_object("equipment", photo.file_path)
        except Exception:
            # 删除 MinIO 文件失败不阻塞数据库操作，但记录日志方便排查
            logger.exception("删除 MinIO 文件失败: %s", photo.file_path)
    elif os.path.exists(photo.file_path):
        os.remove(photo.file_path)

    return await repo.delete_photo(db, photo_id)


async def save_photo_from_path(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    file_path: str,
) -> InspectionPhoto:
    """从本地文件路径保存巡检照片到 MinIO（或本地）和数据库。"""
    from pathlib import Path

    p = Path(file_path)
    if not p.exists():
        raise AppException(message=f"照片文件不存在: {file_path}")

    content = p.read_bytes()
    filename = f"{uuid.uuid4()}_{p.name}"

    if minio_enabled():
        object_key = f"inspection/{filename}"
        upload_object(
            module="equipment",
            object_key=object_key,
            data=content,
            length=len(content),
            content_type="image/jpeg",
        )
        stored_path = object_key
    else:
        file_dest = os.path.normpath(os.path.join(_UPLOAD_DIR, filename))
        if not file_dest.startswith(os.path.normpath(_UPLOAD_DIR)):
            raise AppException(message="非法文件路径")
        with open(file_dest, "wb") as f:
            f.write(content)
        stored_path = file_dest

    photo_data = {
        "task_id": str(task_id),
        "equipment_id": str(equipment_id),
        "file_name": p.name,
        "file_path": stored_path,
        "file_size": len(content),
    }
    return await repo.create_photo(db, photo_data)


async def save_photo_from_base64(
    db: AsyncSession,
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    image_b64: str,
    filename: str = "",
) -> InspectionPhoto:
    """从 base64 编码保存巡检照片到 MinIO（或本地）和数据库。"""
    max_size = 10 * 1024 * 1024  # 10 MB

    # Validate base64
    try:
        content = base64.b64decode(image_b64, validate=True)
    except Exception as e:
        raise AppException(message=f"图片 base64 解码失败：{e}")

    if len(content) > max_size:
        raise AppException(
            message=f"图片大小 {len(content) / 1024 / 1024:.1f}MB 超过上限 10MB"
        )

    if len(content) < 64:
        raise AppException(message="图片数据过小，可能不是有效图片")

    # Basic image format check (magic bytes)
    magic = content[:4]
    valid_magics = {
        b"\xff\xd8\xff": "jpg",       # JPEG
        b"\x89PNG": "png",             # PNG
        b"RIFF": "webp",              # WEBP
        b"BM": "bmp",                 # BMP
    }
    ext = "jpg"
    for magic_bytes, fmt in valid_magics.items():
        if magic.startswith(magic_bytes):
            ext = fmt
            break

    fname = filename or f"{uuid.uuid4()}.{ext}"

    if minio_enabled():
        object_key = f"inspection/{fname}"
        upload_object(
            module="equipment",
            object_key=object_key,
            data=content,
            length=len(content),
            content_type="image/jpeg",
        )
        stored_path = object_key
    else:
        file_dest = os.path.normpath(os.path.join(_UPLOAD_DIR, fname))
        if not file_dest.startswith(os.path.normpath(_UPLOAD_DIR)):
            raise AppException(message="非法文件路径")
        with open(file_dest, "wb") as f:
            f.write(content)
        stored_path = file_dest

    photo_data = {
        "task_id": str(task_id),
        "equipment_id": str(equipment_id),
        "file_name": fname,
        "file_path": stored_path,
        "file_size": len(content),
    }
    return await repo.create_photo(db, photo_data)


# ═══════════ 历史 ═══════════
async def get_history(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
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
    from app.modules.equipment.service.data_scope import apply_equipment_scope

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

    # Apply data scope filtering
    count_stmt = select(func.count(ITask.id)).where(and_(*conditions))
    count_stmt = apply_equipment_scope(count_stmt, ctx, ITask.created_by, "user_id")
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
    stmt = apply_equipment_scope(stmt, ctx, ITask.created_by, "user_id")
    result_set = await db.execute(stmt)
    return list(result_set.scalars().all()), total


async def get_task_detail(
    db: AsyncSession, task_id: uuid.UUID
) -> dict[str, Any]:
    task = await _get_task(db, task_id)
    records = await repo.get_records_by_task(db, task_id)
    photos = await repo.get_photos_by_task(db, task_id)
    return {"task": task, "records": records, "photos": photos}


# ═══════════ 定时任务 ═══════════


def compute_next_cron(
    expression: str, from_time: datetime | None = None,
) -> datetime:
    """Compute the next fire time for a cron expression.

    Raises ValueError if *expression* is not a valid cron string.
    """
    base = from_time or app_time.now()
    naive = base.replace(tzinfo=None)
    is_six = len(expression.split()) == 6
    cron = croniter(expression, naive, second_at_beginning=is_six)
    next_naive: datetime = cron.get_next(datetime)
    return next_naive.replace(tzinfo=app_time.APP_TZ)


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
    db: AsyncSession, route_id: uuid.UUID, data: dict[str, Any],
) -> InspectionRouteSchedule:
    await get_route_by_id(db, route_id)  # validate route exists
    _validate_cron(data["cron_expression"])
    # route_id / assigned_to 是真正的 UUID 列，直接存 UUID，不要 str()：
    # 否则新建返回对象的这两个字段是 str，与模型声明 Mapped[uuid.UUID]
    # 及幂等去重分支（re-fetch 出来是 UUID）类型不一致。
    data["route_id"] = route_id
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
    db: AsyncSession, schedule_id: uuid.UUID, data: dict[str, Any],
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


# ═══════════ 巡检数据分析 ═══════════

from app.modules.equipment.repository.inspection import (  # noqa: E402
    get_analytics_equipment_list,
    get_anomaly_stats,
    get_linkage_stats,
    get_trend_data,
)
from app.modules.equipment.schemas.inspection import (  # noqa: E402
    AnomalyMatrixCell,
    AnomalyMonthlyItem,
    AnomalyRankingItem,
    AnomalyResponse,
    EquipmentListItem,
    EquipmentListResponse,
    LinkagePoint,
    LinkageResponse,
    TrendDataPoint,
    TrendResponse,
    TrendSeries,
)


async def get_trend(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    from_date: date,
    to_date: date,
    ctx: EquipmentAccessContext,
) -> TrendResponse:
    """参数趋势分析"""
    from app.modules.equipment.repository.equipment import get_equipment_by_id

    eq = await get_equipment_by_id(db, equipment_id)
    # 单设备:按数据范围校验设备归属部门,越权直接 403(与列表过滤口径一致)
    if not ctx.is_unrestricted and (
        eq is None or eq.department_id not in ctx.visible_department_ids
    ):
        raise ForbiddenException("无权查看其他部门设备的巡检分析")
    rows = await get_trend_data(db, equipment_id, item_ids, from_date, to_date)

    series = []
    for s in rows:
        dps = [
            TrendDataPoint(
                date=date.fromisoformat(dp["date"]),
                value=dp["value"],
                result=dp["result"],
            )
            for dp in s["data_points"]
        ]
        series.append(
            TrendSeries(
                template_item_id=s["template_item_id"],
                item_name=s["item_name"],
                unit=s["unit"],
                data_points=dps,
            )
        )

    return TrendResponse(
        equipment_name=eq.name if eq else "",
        equipment_no=eq.equipment_no if eq else "",
        series=series,
    )


async def get_anomaly(
    db: AsyncSession,
    from_date: date,
    to_date: date,
    ctx: EquipmentAccessContext,
) -> AnomalyResponse:
    """异常热力分析"""
    data = await get_anomaly_stats(db, from_date, to_date, ctx)

    return AnomalyResponse(
        equipment_ranking=[
            AnomalyRankingItem(  # pyright: ignore[reportCallIssue]
                equipment_id=r["equipment_id"],
                equipment_name=r["equipment_name"],
                equipment_no=r.get("equipment_no", ""),
                total_count=r["total_count"],
                abnormal_count=r["abnormal_count"],
                anomaly_rate=r["anomaly_rate"],
            )
            for r in data["equipment_ranking"]
        ],
        item_ranking=[
            AnomalyRankingItem(  # pyright: ignore[reportCallIssue]
                template_item_id=r["template_item_id"],
                item_name=r["item_name"],
                template_name=r.get("template_name", ""),
                total_count=r["total_count"],
                abnormal_count=r["abnormal_count"],
                anomaly_rate=r["anomaly_rate"],
            )
            for r in data["item_ranking"]
        ],
        monthly_trend=[
            AnomalyMonthlyItem(
                month=r["month"],
                normal=r["normal"],
                abnormal=r["abnormal"],
                skip=r["skip"],
                total=r["total"],
            )
            for r in data["monthly_trend"]
        ],
        matrix=[
            AnomalyMatrixCell(
                equipment_id=r["equipment_id"],
                equipment_name=r["equipment_name"],
                equipment_no=r["equipment_no"],
                template_item_id=r["template_item_id"],
                item_name=r["item_name"],
                total_count=r["total_count"],
                abnormal_count=r["abnormal_count"],
                anomaly_rate=r["anomaly_rate"],
            )
            for r in data["matrix"]
        ],
    )


async def get_equipment_list(
    db: AsyncSession,
    keyword: str | None = None,
    ctx: EquipmentAccessContext | None = None,
) -> EquipmentListResponse:
    """可选设备列表"""
    data = await get_analytics_equipment_list(db, keyword, ctx)

    return EquipmentListResponse(
        equipments=[
            EquipmentListItem(
                equipment_id=r["equipment_id"],
                equipment_name=r["equipment_name"],
                equipment_no=r.get("equipment_no", ""),
                numeric_item_count=r["numeric_item_count"],
                latest_inspection_date=r.get("latest_inspection_date", ""),
            )
            for r in data
        ],
    )


async def get_linkage(
    db: AsyncSession,
    from_date: date,
    to_date: date,
    ctx: EquipmentAccessContext,
) -> LinkageResponse:
    """巡检-维修联动分析：按月叠加巡检异常数与各类型工单量。"""
    data = await get_linkage_stats(db, from_date, to_date, ctx)

    points = [
        LinkagePoint(month=r["month"], series="巡检异常", count=r["count"])
        for r in data["anomaly"]
    ]
    points += [
        LinkagePoint(month=r["month"], series=r["order_type"], count=r["count"])
        for r in data["work_orders"]
    ]

    return LinkageResponse(points=points)
