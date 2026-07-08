"""MCP Tools 共享辅助函数。

提供设备/工单/模板解析、ORM→字典转换等。
用户解析相关已移至 app.platform.identity.mcp_tools。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models.inspection_route_location import (
    RouteEquipmentTemplate,
    RouteLocation,
    RouteLocationEquipment,
)
from app.modules.equipment.models.inspection_template import (
    InspectionTemplateItem,
)
from app.modules.equipment.repository.equipment import (
    get_equipment_by_id,
    get_equipment_by_no,
)
from app.modules.equipment.repository.inspection_template import (
    get_inspection_template_by_id,
    get_inspection_template_by_name,
)
from app.modules.equipment.repository.work_order import (
    get_work_order_by_no,
)
from app.modules.equipment.service import (
    get_work_order_by_id,
)


def _wo_to_dict(wo: Any) -> dict[str, Any]:
    """WorkOrder ORM → 字典"""
    image_count = len(wo.images) if wo.images is not None else 0
    return {
        "id": str(wo.id),
        "work_order_no": wo.work_order_no,
        "order_type": wo.order_type,
        "status": wo.status,
        "priority": wo.priority,
        "equipment_name": wo.equipment.name if wo.equipment else "",
        "equipment_no": wo.equipment.equipment_no if wo.equipment else "",
        "fault_description": wo.fault_description or "",
        "repair_detail": wo.repair_detail or "",
        "assignee_name": wo.assignee.name if wo.assignee else "",
        "reporter_name": wo.reporter.name if wo.reporter else "",
        "responsible_person_name": wo.responsible_person.name if wo.responsible_person else "",
        "created_at": wo.created_at.isoformat() if wo.created_at else "",
        "started_at": wo.started_at.isoformat() if wo.started_at else "",
        "completed_at": wo.completed_at.isoformat() if wo.completed_at else "",
        "image_count": image_count,
    }


def _it_to_dict(task: Any) -> dict[str, Any]:
    """InspectionTask ORM → 字典"""
    route = task.route
    eq_count = 0
    if route and route.locations_rel:
        for loc in route.locations_rel:
            eq_count += len([e for e in (loc.equipments or []) if not e.is_deleted])
    elif task.equipment_ids or task.equipment_id:
        eq_ids = list(task.equipment_ids or [])
        if task.equipment_id and str(task.equipment_id) not in eq_ids:
            eq_ids.append(str(task.equipment_id))
        eq_count = len(eq_ids)

    return {
        "id": str(task.id),
        "task_no": task.task_no,
        "plan_type": task.plan_type,
        "status": task.status,
        "route_name": task.route.name if task.route else "",
        "route_id": str(task.route.id) if task.route else "",
        "equipment_name": task.equipment.name if task.equipment else "",
        "equipment_ids": [str(eid) for eid in task.equipment_ids] if task.equipment_ids else [],
        "equipment_count": eq_count,
        "planned_time": task.planned_time.isoformat() if task.planned_time else "",
        "overall_result": task.overall_result or "",
        "assignee_name": task.assignee.name if task.assignee else "",
        "created_at": task.created_at.isoformat() if task.created_at else "",
    }


async def _get_template_item_map(
    db: AsyncSession, task: Any, equipment_id: uuid.UUID | None = None
) -> dict[str, str]:
    """根据任务类型获取模板检查项的 item_name → template_item_id 映射。

    线路巡检：从路线 → 地点 → 设备 → 模板绑定获取（可能多个模板合并）
    设备巡检：从 task.equipment_templates 或 task.template_ids 获取

    若提供 equipment_id，线路巡检只查该设备绑定的模板项；
    不提供则查整条路线所有设备的模板项（兼容旧调用方）。
    """
    name_to_id: dict[str, str] = {}

    if task.route_id:
        # 线路巡检：从路线地点设备绑定获取模板项
        loc_stmt = select(RouteLocation).where(
            RouteLocation.route_id == task.route_id,
            RouteLocation.is_deleted == False,  # noqa: E712
        )
        locs = (await db.execute(loc_stmt)).scalars().all()

        seen_tids: set[uuid.UUID] = set()
        for loc in locs:
            eq_stmt = select(RouteLocationEquipment).where(
                RouteLocationEquipment.route_location_id == loc.id,
                RouteLocationEquipment.is_deleted == False,  # noqa: E712
            )
            if equipment_id is not None:
                eq_stmt = eq_stmt.where(
                    RouteLocationEquipment.equipment_id == equipment_id
                )
            eqs = (await db.execute(eq_stmt)).scalars().all()
            for eq in eqs:
                tpl_stmt = select(RouteEquipmentTemplate).where(
                    RouteEquipmentTemplate.route_equipment_id == eq.id,
                    RouteEquipmentTemplate.is_deleted == False,  # noqa: E712
                )
                tpls = (await db.execute(tpl_stmt)).scalars().all()
                for tpl in tpls:
                    if tpl.template_id not in seen_tids:
                        seen_tids.add(tpl.template_id)
                        item_stmt = select(InspectionTemplateItem).where(
                            InspectionTemplateItem.template_id == tpl.template_id,
                            InspectionTemplateItem.is_deleted == False,  # noqa: E712
                        )
                        items = (await db.execute(item_stmt)).scalars().all()
                        for item_ in items:
                            existing = name_to_id.get(item_.item_name)
                            if existing is None:
                                name_to_id[item_.item_name] = str(item_.id)
                            elif existing != str(item_.id):
                                name_to_id[item_.item_name] = ""

    elif task.equipment_templates:
        seen_tids: set[uuid.UUID] = set()
        for tpl_ids in task.equipment_templates.values():
            for tid_str in tpl_ids:
                tid = uuid.UUID(tid_str) if isinstance(tid_str, str) else tid_str
                if tid not in seen_tids:
                    seen_tids.add(tid)
        for tid in seen_tids:
            item_stmt = select(InspectionTemplateItem).where(
                InspectionTemplateItem.template_id == tid,
                InspectionTemplateItem.is_deleted == False,  # noqa: E712
            )
            items = (await db.execute(item_stmt)).scalars().all()
            for item_ in items:
                existing = name_to_id.get(item_.item_name)
                if existing is None:
                    name_to_id[item_.item_name] = str(item_.id)
                elif existing != str(item_.id):
                    name_to_id[item_.item_name] = ""

    elif task.template_ids:
        for tid_str in task.template_ids:
            tid = uuid.UUID(tid_str) if isinstance(tid_str, str) else tid_str
            item_stmt = select(InspectionTemplateItem).where(
                InspectionTemplateItem.template_id == tid,
                InspectionTemplateItem.is_deleted == False,  # noqa: E712
            )
            items = (await db.execute(item_stmt)).scalars().all()
            for item_ in items:
                existing = name_to_id.get(item_.item_name)
                if existing is None:
                    name_to_id[item_.item_name] = str(item_.id)
                elif existing != str(item_.id):
                    name_to_id[item_.item_name] = ""

    return name_to_id


async def _resolve_equipment(db: AsyncSession, identifier: str) -> Any:
    """将设备编号或 UUID 解析为 Equipment 对象。"""
    equipment = await get_equipment_by_no(db, identifier)
    if equipment:
        return equipment
    try:
        eid = uuid.UUID(identifier)
        equipment = await get_equipment_by_id(db, eid)
        if equipment:
            return equipment
    except ValueError:
        pass
    raise ValueError(f"未找到设备「{identifier}」，请提供有效的设备编号或 UUID。")


async def _resolve_work_order(db: AsyncSession, identifier: str) -> Any:
    """将工单编号或 UUID 解析为 WorkOrder 对象。"""
    wo = await get_work_order_by_no(db, identifier)
    if wo:
        return wo
    try:
        wo_uuid = uuid.UUID(identifier)
        wo = await get_work_order_by_id(db, wo_uuid)
        if wo:
            return wo
    except ValueError:
        pass
    raise ValueError(f"未找到工单「{identifier}」，请提供有效的工单编号（如 WO-20260616-0001）或 UUID。")


async def _resolve_template(db: AsyncSession, identifier: str) -> Any:
    """将模板名称或 UUID 解析为 InspectionTemplate 对象。"""
    template = await get_inspection_template_by_name(db, identifier)
    if template:
        return template
    try:
        tid = uuid.UUID(identifier)
        template = await get_inspection_template_by_id(db, tid)
        if template:
            return template
    except ValueError:
        pass
    raise ValueError(f"未找到模板「{identifier}」，请提供有效的模板名称或 UUID。")


