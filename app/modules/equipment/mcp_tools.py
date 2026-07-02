"""Equipment 模块暴露给 AI Agent 的 MCP Tools。

工具函数通过 @mcp.tool() 装饰器注册到全局 FastMCP 实例。
每个 tool 的 docstring 即为 Agent 可读的中文使用说明。

设计原则：
- tool 函数只做参数校验和 user 解析，业务逻辑通过 service 层完成
- 所有写操作必须提供 operator_id，声明替谁操作
- 不直接操作 ORM model 或 repository
"""

from __future__ import annotations

import uuid
from typing import Any

from fastmcp.tools.tool import ToolResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
from app.modules.equipment.repository.inspection import (
    get_equipment_names_by_ids,
    get_equipment_nos_by_ids,
    get_task_by_no,
    get_task_equipment_completed_ids,
)
from app.modules.equipment.repository.inspection_template import (
    get_inspection_template_by_id,
    get_inspection_template_by_name,
)
from app.modules.equipment.repository.work_order import (
    get_user_work_orders,
    get_work_order_by_no,
)
from app.modules.equipment.service import (
    complete_work_order,
    get_work_order_by_id,
    start_work_order,
)
from app.modules.equipment.service.inspection import (
    close_task as close_inspection_task,
)
from app.modules.equipment.service.inspection import (
    complete_task as complete_inspection_task,
)
from app.modules.equipment.service.inspection import (
    get_task_by_id as get_inspection_task_by_id,
)
from app.modules.equipment.service.inspection import (
    get_tasks as get_inspection_tasks,
)
from app.modules.equipment.service.inspection import (
    start_task as start_inspection_task,
)
from app.modules.equipment.service.inspection import (
    submit_equipment_check,
)
from app.platform.identity.models import User
from app.platform.identity.repository import UserRepository
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp


async def resolve_user(db: AsyncSession, operator_id: str) -> User:
    """将 operator_id 解析为 User 对象。"""
    try:
        uid = uuid.UUID(operator_id)
        user = await db.get(User, uid)
        if user and not user.is_deleted:
            return user
    except ValueError:
        pass

    repo = UserRepository()
    user = await repo.get_by_feishu_user_id(db, operator_id)
    if user:
        return user

    users, total = await repo.list_all(db, keyword=operator_id, limit=10)
    if total == 1:
        return users[0]
    if total > 1:
        raise ValueError(f"找到多个匹配用户（{total}人），请提供更精确的 user_id")

    raise ValueError(f"未找到用户：{operator_id}")


def _wo_to_dict(wo: Any) -> dict[str, Any]:
    """WorkOrder ORM → 字典"""
    return {
        "id": str(wo.id),
        "work_order_no": wo.work_order_no,
        "order_type": wo.order_type,
        "status": wo.status,
        "priority": wo.priority,
        "equipment_name": wo.equipment.name if wo.equipment else "",
        "fault_description": wo.fault_description or "",
        "assignee_name": wo.assignee.name if wo.assignee else "",
        "reporter_name": wo.reporter.name if wo.reporter else "",
        "created_at": wo.created_at.isoformat() if wo.created_at else "",
        "started_at": wo.started_at.isoformat() if wo.started_at else "",
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
                                # 同名检查项来自不同模板，标记为冲突
                                # agent 必须用 template_item_id 提交，不能用 item_name
                                name_to_id[item_.item_name] = ""

    elif task.equipment_templates:
        # 新方式：从设备-模板映射聚合所有唯一模板
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
                    # 同名来自不同模板，标记冲突
                    name_to_id[item_.item_name] = ""

    elif task.template_ids:
        # 兼容旧数据：从 task.template_ids JSON 列表获取
        for tid_str in task.template_ids:
            tid = uuid.UUID(tid_str) if isinstance(tid_str, str) else tid_str
            item_stmt = select(InspectionTemplateItem).where(
                InspectionTemplateItem.template_id == tid,
                InspectionTemplateItem.is_deleted == False,  # noqa: E712
            )
            items = (await db.execute(item_stmt)).scalars().all()
            for item_ in items:
                # 同名检查项去重；同名不同ID标记冲突
                existing = name_to_id.get(item_.item_name)
                if existing is None:
                    name_to_id[item_.item_name] = str(item_.id)
                elif existing != str(item_.id):
                    name_to_id[item_.item_name] = ""

    return name_to_id


# ─────────────────────────────────────────────────────────────
# 解析器辅助函数：支持人类可读标识 + UUID 双模式
# ─────────────────────────────────────────────────────────────


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
        wo = await get_work_order_by_id(db, wo_uuid)  # service layer, data_scope=all
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


# ─────────────────────────────────────────────────────────────
# Tool 1: 查询用户身份
# ─────────────────────────────────────────────────────────────


def _user_to_dict(u: User) -> dict[str, Any]:
    """User ORM → 字典"""
    return {
        "id": str(u.id),
        "name": u.name,
        "employee_no": u.employee_no or "",
        "department": u.department or "",
        "position": u.position or "",
        "email": u.email or "",
        "mobile": u.mobile or "",
        "feishu_user_id": u.feishu_user_id or "",
    }


@mcp.tool()
async def query_user(keyword: str) -> ToolResult:
    """
    根据姓名或 user_id 查询系统用户信息。

    查询优先级：
    1. 先尝试按 UUID 精确匹配
    2. 再尝试按飞书 user_id（union_id）精确匹配
    3. 最后按姓名模糊搜索

    适用于 Agent 在替用户操作前，需要先确认用户身份和 user_id 的场景。

    Args:
        keyword: 用户 UUID、飞书 user_id（union_id）、姓名（支持模糊匹配）或工号
    """
    db = get_db()
    repo = UserRepository()

    # 1) 尝试 UUID 精确匹配
    try:
        uid = uuid.UUID(keyword)
        user = await db.get(User, uid)
        if user and not user.is_deleted:
            u = _user_to_dict(user)
            return ToolResult(
                content=f"找到用户：{u['name']}（工号{u['employee_no']}）· {u['department']} · {u['position']}",
                structured_content={"users": [u]},
            )
    except ValueError:
        pass

    # 2) 尝试飞书 user_id 精确匹配
    user = await repo.get_by_feishu_user_id(db, keyword)
    if user:
        u = _user_to_dict(user)
        return ToolResult(
            content=f"找到用户：{u['name']}（工号{u['employee_no']}）· {u['department']} · {u['position']}",
            structured_content={"users": [u]},
        )

    # 3) 按姓名模糊搜索
    users, _total = await repo.list_all(db, keyword=keyword, limit=20)
    user_list = [_user_to_dict(u) for u in users]
    if not user_list:
        return ToolResult(
            content=f"未找到匹配「{keyword}」的用户。",
            structured_content={"users": []},
        )
    if len(user_list) == 1:
        u = user_list[0]
        return ToolResult(
            content=f"找到用户：{u['name']}（工号{u['employee_no']}）· {u['department']} · {u['position']}",
            structured_content={"users": user_list},
        )
    lines = [f"找到 {len(user_list)} 个匹配「{keyword}」的用户："]
    for u in user_list:
        lines.append(f"- {u['name']}（工号{u['employee_no']}）· {u['department']} · {u['position']}")
    return ToolResult(content="\n".join(lines), structured_content={"users": user_list})


# ─────────────────────────────────────────────────────────────
# Tool 2: 查询用户维护工单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def list_work_orders(
    operator_id: str,
    status: str | None = None,
) -> ToolResult:
    """
    查询指定用户的维护工单列表。
    适用的业务场景：设备部人员想知道自己当前有哪些工单需要处理，
    Agent 替其查看工单列表，可按工单状态过滤。

    Args:
        operator_id: 实际操作人的 user_id 或姓名（替谁查）
        status: 工单状态过滤，可选值：待处理 / 执行中 / 待验收 / 已完成 / 已关闭。
                 不传则返回所有未关闭的工单。
    """
    db = get_db()
    try:
        user = await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    work_orders = await get_user_work_orders(db, user.id)

    if status:
        valid_statuses = {"待处理", "执行中", "待验收", "已完成", "已关闭"}
        if status not in valid_statuses:
            return ToolResult(
                content=f"无效的工单状态「{status}」，可选值：待处理 / 执行中 / 待验收 / 已完成 / 已关闭。",
                structured_content={"error": f"无效状态：{status}"},
                is_error=True,
            )
        work_orders = [wo for wo in work_orders if wo.status == status]

    result = [_wo_to_dict(wo) for wo in work_orders]
    if not result:
        return ToolResult(
            content=f"{user.name} 当前没有{'「' + status + '」状态的' if status else '待处理的'}工单。",
            structured_content={"result": [], "total": 0},
        )
    lines = [f"{user.name} 共有 {len(result)} 个工单："]
    for wo in result:
        lines.append(f"  [{wo['status']}] {wo['work_order_no']}（{wo['order_type']} · {wo['equipment_name']}）")
    return ToolResult(
        content="\n".join(lines),
        structured_content={"result": result, "total": len(result)},
    )


# ─────────────────────────────────────────────────────────────
# Tool 3: 开始/完成工单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def operate_work_order(
    work_order: str,
    action: str,
    operator_id: str,
    repair_detail: str | None = None,
) -> ToolResult:
    """
    对维护工单执行状态流转操作：开始维修 或 完成维修。

    Args:
        work_order: 工单编号（如 WO-20260616-0001）或工单 UUID
        action: 操作类型，可选值 start / complete
        operator_id: 实际操作人的 user_id 或姓名
        repair_detail: 维修过程描述，action=complete 时必需
    """
    db = get_db()
    try:
        user = await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    if action not in ("start", "complete"):
        return ToolResult(
            content=f"无效的操作类型「{action}」，可选值：start（开始维修）、complete（完成维修）。",
            structured_content={"error": f"无效操作：{action}"},
            is_error=True,
        )

    try:
        wo = await _resolve_work_order(db, work_order)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    from app.modules.equipment.deps import EquipmentAccessContext

    ctx = EquipmentAccessContext(user=user, data_scope="all")
    eq_name = wo.equipment.name if wo.equipment else "未知设备"

    if action == "start":
        result = await start_work_order(db, wo.id, ctx)
        await db.commit()
        return ToolResult(
            content=f"工单 {result.work_order_no} 已开始维修（{eq_name}），状态：待处理 → {result.status}",
            structured_content={
                "success": True,
                "work_order_no": result.work_order_no,
                "old_status": "待处理",
                "new_status": result.status,
            },
        )

    if not repair_detail or not repair_detail.strip():
        return ToolResult(
            content="完成工单时需要提供 repair_detail（维修过程描述），请描述维修过程后重试。",
            structured_content={"error": "缺少 repair_detail"},
            is_error=True,
        )

    from app.modules.equipment.schemas.work_order import WorkOrderComplete

    data = WorkOrderComplete(repair_detail=repair_detail.strip())
    result = await complete_work_order(db, wo.id, data, ctx)
    await db.commit()
    return ToolResult(
        content=f"工单 {result.work_order_no} 维修完成（{eq_name}），状态：执行中 → {result.status}",
        structured_content={
            "success": True,
            "work_order_no": result.work_order_no,
            "old_status": "执行中",
            "new_status": result.status,
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 4: 提交巡检表单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def submit_inspection(
    task_no: str,
    equipment: str,
    operator_id: str,
    check_items: list[dict[str, Any]],
    images: list[str] | None = None,
) -> ToolResult:
    """
    提交设备巡检表单，逐项记录检查结果，同时上传巡检照片。

    支持线路巡检和设备巡检两种模式：
    - 设备巡检：直接使用 task 上绑定的 template_ids 查找检查项
    - 线路巡检：从路线 → 地点 → 设备的模板绑定中查找检查项（自动合并多模板）

    如果所有设备都已提交，自动完成该巡检任务。

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        equipment: 设备编号（如 EQ-001）或 UUID
        operator_id: 实际操作人的 user_id 或姓名
        check_items: 检查项列表，每项包含：
            - item_name: 检查项目名称（必需）
            - result: 检查结果，可选值：正常 / 异常 / 跳过（必需）
            - actual_value: 实测值（可选）
            - remark: 备注（可选）
        images: 巡检照片的 base64 编码列表（可选，不含 data:image/xxx;base64, 前缀）
    """
    db = get_db()
    try:
        await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    task = await get_task_by_no(db, task_no)
    if not task:
        return ToolResult(
            content=f"未找到任务「{task_no}」，请检查任务编号是否正确。",
            structured_content={"error": f"任务不存在：{task_no}"},
            is_error=True,
        )

    try:
        eq = await _resolve_equipment(db, equipment)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)
    equipment_uuid = eq.id

    task_uuid = task.id

    # 校验 check_items
    valid_results = {"正常", "异常", "跳过"}
    for item in check_items:
        item_name = item.get("item_name", "")
        result = item.get("result", "")
        if not item_name:
            return ToolResult(
                content="提交失败：每个检查项必须提供 item_name。",
                structured_content={"error": "缺少 item_name"},
                is_error=True,
            )
        if result not in valid_results:
            return ToolResult(
                content=f"提交失败：检查项「{item_name}」的结果值「{result}」无效，可选值：正常 / 异常 / 跳过。",
                structured_content={"error": f"无效的检查结果：{item_name}={result}"},
                is_error=True,
            )
        if result == "异常" and not item.get("actual_value") and not item.get("remark"):
            return ToolResult(
                content=f"提交失败：检查项「{item_name}」结果为【异常】，必须填写实际值（actual_value）或备注（remark）。",
                structured_content={"error": f"异常项缺少 actual_value/remark：{item_name}"},
                is_error=True,
            )

    # 加载模板项映射（支持线路巡检多模板，按设备过滤）
    name_to_id = await _get_template_item_map(db, task, equipment_uuid)

    if not name_to_id:
        if task.route_id:
            msg = "该路线尚未配置设备检查模板，请先在系统中配置模板后再提交。"
        else:
            msg = "该任务未绑定检查模板，请先在系统中配置模板后再提交。"
        return ToolResult(content=msg, structured_content={"error": msg}, is_error=True)

    # 构建 name ↔ id 双向映射（排除冲突标记 ""）
    id_to_name = {v: k for k, v in name_to_id.items() if v}

    # 构建 records
    records: list[dict[str, Any]] = []
    for item in check_items:
        rec: dict[str, Any] = {
            "result": item["result"],
            "actual_value": item.get("actual_value", ""),
            "remark": item.get("remark", ""),
        }
        tid = item.get("template_item_id")
        if tid:
            # 校验 template_item_id 是否有效
            if tid not in id_to_name:
                available = "、".join([k for k, v in name_to_id.items() if v][:10])
                return ToolResult(
                    content=f"提交失败：template_item_id「{tid}」无效，数据库中没有此检查项。\n"
                            f"请使用 get_inspection_check_items 获取正确的 template_item_id。\n"
                            f"可用检查项：{available}",
                    structured_content={
                        "error": f"无效的 template_item_id：{tid}",
                        "available": [k for k, v in name_to_id.items() if v][:10],
                    },
                    is_error=True,
                )
            rec["template_item_id"] = tid
        else:
            item_name = item["item_name"]
            mapped_id = name_to_id.get(item_name)
            if mapped_id is None:
                # 检查项名称不在映射中
                available = "、".join([k for k in name_to_id if name_to_id[k]][:10])
                return ToolResult(
                    content=f"提交失败：未找到检查项「{item_name}」。\n"
                            f"可用检查项：{available}\n"
                            f"请确认检查项名称与模板完全一致。",
                    structured_content={"error": f"未知检查项：{item_name}", "available": [k for k in name_to_id if name_to_id[k]][:10]},
                    is_error=True,
                )
            if not mapped_id:
                # mapped_id == "" → 同名检查项存在于多个模板中，必须用 template_item_id
                return ToolResult(
                    content=f"提交失败：检查项「{item_name}」在多个模板中存在，无法通过名称定位。\n"
                            f"请使用 get_inspection_check_items 获取正确的 template_item_id，"
                            f"并在提交时提供 template_item_id 而非 item_name。",
                    structured_content={
                        "error": f"检查项名称冲突：{item_name}",
                        "hint": "使用 template_item_id 替代 item_name",
                    },
                    is_error=True,
                )
            rec["template_item_id"] = mapped_id
        records.append(rec)

    # 提交
    try:
        submitted = await submit_equipment_check(db, task_uuid, equipment_uuid, records)
    except Exception as e:
        return ToolResult(
            content=f"提交失败：系统内部错误。\n详情：{e}",
            structured_content={"error": str(e)},
            is_error=True,
        )

    # 显式提交事务（BaseHTTPMiddleware + SSE 场景下中间件的 commit 可能不执行）
    await db.commit()

    # 上传巡检照片（非关键，失败不回滚巡检记录）
    photo_count = 0
    if images:
        from app.modules.equipment.service.inspection import save_photo_from_base64

        for img_b64 in images:
            try:
                await save_photo_from_base64(db, task_uuid, equipment_uuid, img_b64)
                photo_count += 1
            except Exception:
                await db.rollback()
        if photo_count:
            await db.commit()

    # 重新查询任务状态
    task_after = await get_inspection_task_by_id(db, task_uuid)
    all_done = task_after.status == "已完成"

    # 构建自然语言 content
    lines = [
        f"任务 {task.task_no} · 设备 {eq.equipment_no}（{eq.name}）提交成功！",
        f"已记录 {len(submitted)} 项检查结果",
    ]
    if photo_count:
        lines.append(f"已上传 {photo_count} 张巡检照片")
    if all_done:
        lines.append("所有设备均已提交，巡检任务已完成！")
    else:
        lines.append("还有待检设备，请继续巡检。")
    content = "\n".join(lines)

    return ToolResult(
        content=content,
        structured_content={
            "success": True,
            "task_no": task.task_no,
            "equipment_no": eq.equipment_no,
            "submitted_count": len(submitted),
            "photo_count": photo_count,
            "all_done": all_done,
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 5: 查询巡检任务
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def list_inspection_tasks(
    operator_id: str,
    status: str | None = None,
) -> ToolResult:
    """
    查询指定用户的巡检任务列表。

    Args:
        operator_id: 实际操作人的 user_id 或姓名（替谁查）
        status: 任务状态过滤，可选值：待执行 / 执行中 / 已完成 / 已关闭。
                 不传则只返回待处理的任务（待执行 + 执行中）。
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    from app.modules.equipment.deps import EquipmentAccessContext

    ctx = EquipmentAccessContext(user=user, data_scope="all")

    if status:
        valid_statuses = {"待执行", "执行中", "已完成", "已关闭"}
        if status not in valid_statuses:
            raise ValueError(
                f"无效的任务状态 '{status}'，可选值：{' / '.join(valid_statuses)}"
            )

    tasks, _total = await get_inspection_tasks(
        db,
        ctx,
        assigned_to=user.id,
        status=status,
        page=1,
        page_size=100,
    )
    # 默认只返回待处理的任务
    if not status:
        tasks = [t for t in tasks if t.status in ("待执行", "执行中")]
    result = [_it_to_dict(t) for t in tasks]

    # 补充多设备任务的 equipment_name 和 equipment_no
    need_enrich: list[dict[str, Any]] = []
    all_eq_ids: set[uuid.UUID] = set()
    for r in result:
        if not r["equipment_name"] and r.get("equipment_ids"):
            need_enrich.append(r)
            for eid_str in r["equipment_ids"]:
                all_eq_ids.add(uuid.UUID(eid_str))

    if need_enrich:
        name_map = await get_equipment_names_by_ids(db, list(all_eq_ids))
        no_map = await get_equipment_nos_by_ids(db, list(all_eq_ids))
        for r in need_enrich:
            names = [
                name_map.get(uuid.UUID(eid), eid[:8] + "…")
                for eid in r["equipment_ids"]
            ]
            nos = [
                no_map.get(uuid.UUID(eid), "")
                for eid in r["equipment_ids"]
            ]
            if names:
                r["equipment_name"] = "、".join(names[:3])
                if len(names) > 3:
                    r["equipment_name"] += f" 等{len(names)}台"
            if nos:
                r["equipment_no"] = "、".join(n for n in nos[:3] if n)
                if len(nos) > 3:
                    r["equipment_no"] += f" 等{len(nos)}台"

    # 构建自然语言 content
    if not result:
        content = f"{user.name} 当前没有待处理的巡检任务。"
    else:
        lines = [f"{user.name} 共有 {len(result)} 个巡检任务："]
        for t in result:
            eq_label = t["equipment_name"] or t.get("equipment_no", "") or f"{t['equipment_count']}台设备"
            route_label = f"路线「{t['route_name']}」" if t["route_name"] else ""
            lines.append(
                f"- [{t['status']}] {t['task_no']} "
                f"({t['plan_type']}{' · ' + route_label if route_label else ''} · {eq_label})"
            )
        content = "\n".join(lines)

    return ToolResult(
        content=content,
        structured_content={"result": result, "total": len(result)},
    )


# ─────────────────────────────────────────────────────────────
# Tool 6: 修改巡检任务状态
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def update_inspection_task(
    task_no: str,
    action: str,
    operator_id: str,
    remark: str | None = None,
) -> ToolResult:
    """
    修改巡检任务状态：开始执行、完成、或关闭任务。

    - action="start"：任务从"待执行"变为"执行中"
    - action="complete"：任务从"执行中"变为"已完成"（设备巡检和线路巡检均支持）
    - action="close"：任务变为"已关闭"

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        action: 操作类型，可选值 start / complete / close
        operator_id: 实际操作人的 user_id 或姓名
        remark: 备注说明，action=close 时作为关闭原因
    """
    db = get_db()
    try:
        user = await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    if action not in ("start", "complete", "close"):
        return ToolResult(
            content=f"无效的操作类型「{action}」，可选值：start（开始执行）、complete（完成）、close（关闭）。",
            structured_content={"error": f"无效操作：{action}"},
            is_error=True,
        )

    task = await get_task_by_no(db, task_no)
    if not task:
        return ToolResult(
            content=f"未找到任务「{task_no}」，请检查任务编号是否正确。",
            structured_content={"error": f"任务不存在：{task_no}"},
            is_error=True,
        )

    from app.modules.equipment.deps import EquipmentAccessContext

    ctx = EquipmentAccessContext(user=user, data_scope="all")
    task_uuid = task.id
    old_status = task.status
    route_label = f"（路线「{task.route.name}」）" if task.route else ""

    if action == "start":
        result = await start_inspection_task(db, task_uuid, ctx)
        content = f"任务 {result.task_no} 已开始执行{route_label}，状态：{old_status} → {result.status}"
    elif action == "complete":
        result = await complete_inspection_task(db, task_uuid, ctx)
        content = f"任务 {result.task_no} 已完成{route_label}，状态：{old_status} → {result.status}"
    else:
        result = await close_inspection_task(db, task_uuid, remark=remark)
        reason = f"，原因：{remark}" if remark else ""
        content = f"任务 {result.task_no} 已关闭{route_label}{reason}，状态：{old_status} → {result.status}"

    # 显式提交事务（BaseHTTPMiddleware + SSE 场景下中间件的 commit 可能不执行）
    await db.commit()

    return ToolResult(
        content=content,
        structured_content={
            "success": True,
            "task_no": result.task_no,
            "old_status": old_status,
            "new_status": result.status,
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 7: 查询巡检任务进度
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def get_inspection_task_progress(
    task_no: str,
    operator_id: str,
) -> ToolResult:
    """
    查询巡检任务中每台设备的检查进度：哪些已提交、哪些待检。

    Agent 可据此告诉用户「任务 X 共 N 台设备，已完成 M 台，还剩 A、B、C 待检」。
    适用于用户说了"我要提交巡检"但不知道当前进度时，Agent 主动查询并引导。

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        operator_id: 实际操作人的 user_id 或姓名
    """
    db = get_db()
    await resolve_user(db, operator_id)

    task = await get_task_by_no(db, task_no)
    if not task:
        raise ValueError(f"未找到任务：{task_no}")
    task_uuid = task.id

    # 收集任务涉及的所有设备（线路巡检 vs 设备巡检）
    equipments: list[dict[str, Any]] = []

    if task.route_id:
        # 线路巡检：从路线 → 地点 → 设备
        loc_stmt = select(RouteLocation).where(
            RouteLocation.route_id == task.route_id,
            RouteLocation.is_deleted == False,  # noqa: E712
        ).options(
            selectinload(RouteLocation.location),
        ).order_by(RouteLocation.sort_order)
        locs = (await db.execute(loc_stmt)).scalars().all()

        for loc in locs:
            eq_stmt = select(RouteLocationEquipment).where(
                RouteLocationEquipment.route_location_id == loc.id,
                RouteLocationEquipment.is_deleted == False,  # noqa: E712
            ).options(
                selectinload(RouteLocationEquipment.equipment),
            ).order_by(RouteLocationEquipment.sort_order)
            eqs = (await db.execute(eq_stmt)).scalars().all()
            for eq in eqs:
                equipments.append({
                    "equipment_id": str(eq.equipment_id),
                    "equipment_name": eq.equipment.name if eq.equipment else "",
                    "equipment_no": eq.equipment.equipment_no if eq.equipment else "",
                    "location_name": loc.location.name if loc.location else "",
                    "sort_order": eq.sort_order,
                })
    elif task.equipment_ids or task.equipment_id:
        # 设备巡检：合并 equipment_ids（多设备）和 equipment_id（单设备兼容）
        eq_ids: list[str] = list(task.equipment_ids or [])
        if task.equipment_id:
            eid_str = str(task.equipment_id)
            if eid_str not in eq_ids:
                eq_ids.append(eid_str)

        name_map = await get_equipment_names_by_ids(
            db, [uuid.UUID(eid) for eid in eq_ids]
        )
        no_map = await get_equipment_nos_by_ids(
            db, [uuid.UUID(eid) for eid in eq_ids]
        )
        for eid_str in eq_ids:
            equipments.append({
                "equipment_id": eid_str,
                "equipment_name": name_map.get(uuid.UUID(eid_str), ""),
                "equipment_no": no_map.get(uuid.UUID(eid_str), ""),
                "location_name": "",
                "sort_order": 0,
            })

    # 获取已完成检查的设备 ID
    completed_ids = await get_task_equipment_completed_ids(db, task_uuid)
    completed_set = {str(cid) for cid in completed_ids}

    # 标记每台设备的检查状态
    for eq in equipments:
        eq["checked"] = eq["equipment_id"] in completed_set

    pending = [eq for eq in equipments if not eq["checked"]]
    checked = [eq for eq in equipments if eq["checked"]]

    # 构建自然语言 content
    route_label = f" · 路线「{task.route.name}」" if task.route else ""
    lines = [
        f"任务 {task.task_no}（{task.plan_type}{route_label}）",
        f"进度：{len(checked)}/{len(equipments)} 已完成，{len(pending)} 台待检",
    ]
    if pending:
        lines.append("待检设备：")
        for eq in pending:
            loc = f"（{eq['location_name']}）" if eq.get("location_name") else ""
            no = f" {eq['equipment_no']}" if eq.get("equipment_no") else ""
            lines.append(f"  - {eq['equipment_name']}{no}{loc}  [{eq['equipment_id']}]")
    if checked:
        lines.append("已检设备：")
        for eq in checked:
            no = f" {eq['equipment_no']}" if eq.get("equipment_no") else ""
            lines.append(f"  - {eq['equipment_name']}{no}  [{eq['equipment_id']}]")
    content = "\n".join(lines)

    return ToolResult(
        content=content,
        structured_content={
            "task_id": str(task.id),
            "task_no": task.task_no,
            "plan_type": task.plan_type,
            "status": task.status,
            "route_name": task.route.name if task.route else "",
            "total_equipments": len(equipments),
            "checked_count": len(checked),
            "pending_count": len(pending),
            "equipments": equipments,
            "pending_equipments": pending,
            "checked_equipments": checked,
        },
    )


# ─────────────────────────────────────────────────────────────
# Tool 8: 查询设备巡检检查项模板
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def get_inspection_check_items(
    task_no: str,
    equipment: str,
    operator_id: str,
) -> ToolResult:
    """
    查询巡检任务中某台设备需要检查的模板项列表（含检查项名称和预期值）。

    Agent 据此告诉用户「请检查以下项目：温度（标准25±2℃）、压力（标准<0.5MPa）...」，
    并在用户发送照片后，将检查项列表传给视觉模型进行分析。

    支持线路巡检（路线→地点→设备→模板链）和设备巡检（equipment_templates映射）。

    Args:
        task_no: 巡检任务编号（如 IT-20260630-0001）
        equipment: 设备编号（如 EQ-001）或 UUID
        operator_id: 实际操作人的 user_id 或姓名
    """
    db = get_db()
    try:
        await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    task = await get_task_by_no(db, task_no)
    if not task:
        return ToolResult(
            content=f"未找到任务「{task_no}」，请检查任务编号是否正确。",
            structured_content={"error": f"任务不存在：{task_no}"},
            is_error=True,
        )

    try:
        eq = await _resolve_equipment(db, equipment)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    # 复用 AI service 的检查项获取逻辑（支持线路巡检多模板合并）
    from app.modules.equipment.service.ai.service import _get_inspection_items

    items, tpl_names = await _get_inspection_items(db, task, eq.id)

    item_dicts = [
        {
            "template_item_id": str(item.id),
            "item_name": item.item_name,
            "expected_result": item.expected_result or "",
            "sort_order": item.sort_order,
            "template_name": tpl_names.get(item.id, ""),
        }
        for item in items
    ]

    # 构建自然语言 content
    if not item_dicts:
        content = f"设备 {eq.equipment_no}（{eq.name}）没有配置检查项。请先在系统中为此设备绑定巡检模板。"
    else:
        lines = [
            f"设备 {eq.equipment_no}（{eq.name}）的检查项（共 {len(item_dicts)} 项）：",
        ]
        for item in item_dicts:
            std = f"（标准：{item['expected_result']}）" if item["expected_result"] else ""
            tpl = f" [{item['template_name']}]" if item["template_name"] else ""
            lines.append(f"{item['sort_order'] + 1}. {item['item_name']}{std}{tpl}")
        content = "\n".join(lines)

    return ToolResult(
        content=content,
        structured_content={
            "task_no": task.task_no,
            "equipment_no": eq.equipment_no,
            "items": item_dicts,
        },
    )
