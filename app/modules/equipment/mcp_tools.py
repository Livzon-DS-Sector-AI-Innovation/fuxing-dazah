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
from app.modules.equipment.repository.work_order import get_user_work_orders
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
    elif task.equipment_ids:
        eq_count = len(task.equipment_ids)
    elif task.equipment_id:
        eq_count = 1

    return {
        "id": str(task.id),
        "task_no": task.task_no,
        "plan_type": task.plan_type,
        "status": task.status,
        "route_name": task.route.name if task.route else "",
        "route_id": str(task.route.id) if task.route else "",
        "equipment_name": task.equipment.name if task.equipment else "",
        "equipment_count": eq_count,
        "planned_time": task.planned_time.isoformat() if task.planned_time else "",
        "overall_result": task.overall_result or "",
        "assignee_name": task.assignee.name if task.assignee else "",
        "created_at": task.created_at.isoformat() if task.created_at else "",
    }


async def _get_template_item_map(
    db: AsyncSession, task: Any
) -> dict[str, str]:
    """根据任务类型获取模板检查项的 item_name → template_item_id 映射。

    线路巡检：从路线 → 地点 → 设备 → 模板绑定获取（可能多个模板合并）
    设备巡检：从 task.equipment_templates 或 task.template_ids 获取
    """
    name_to_id: dict[str, str] = {}

    if task.route_id:
        # 线路巡检：从路线地点设备绑定获取所有模板项
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
                            name_to_id[item_.item_name] = str(item_.id)

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
                if item_.item_name not in name_to_id:
                    name_to_id[item_.item_name] = str(item_.id)

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
                # 同名检查项去重
                if item_.item_name not in name_to_id:
                    name_to_id[item_.item_name] = str(item_.id)

    return name_to_id


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
async def query_user(keyword: str) -> list[dict[str, Any]]:
    """
    根据姓名或 user_id 查询系统用户信息。

    查询优先级：
    1. 先尝试按 UUID 精确匹配
    2. 再尝试按飞书 user_id（union_id）精确匹配
    3. 最后按姓名模糊搜索

    适用于 Agent 在替用户操作前，需要先确认用户身份和 user_id 的场景。
    返回匹配的用户列表，包含 id、姓名、部门、职位、工号等信息。

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
            return [_user_to_dict(user)]
    except ValueError:
        pass

    # 2) 尝试飞书 user_id 精确匹配
    user = await repo.get_by_feishu_user_id(db, keyword)
    if user:
        return [_user_to_dict(user)]

    # 3) 按姓名模糊搜索
    users, _total = await repo.list_all(db, keyword=keyword, limit=20)
    return [_user_to_dict(u) for u in users]


# ─────────────────────────────────────────────────────────────
# Tool 2: 查询用户维护工单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def list_work_orders(
    operator_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
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
    user = await resolve_user(db, operator_id)

    work_orders = await get_user_work_orders(db, user.id)

    if status:
        valid_statuses = {"待处理", "执行中", "待验收", "已完成", "已关闭"}
        if status not in valid_statuses:
            raise ValueError(
                f"无效的工单状态 '{status}'，可选值：{' / '.join(valid_statuses)}"
            )
        work_orders = [wo for wo in work_orders if wo.status == status]

    return [_wo_to_dict(wo) for wo in work_orders]


# ─────────────────────────────────────────────────────────────
# Tool 3: 开始/完成工单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def operate_work_order(
    work_order_id: str,
    action: str,
    operator_id: str,
    repair_detail: str | None = None,
) -> dict[str, Any]:
    """
    对维护工单执行状态流转操作：开始维修 或 完成维修。

    Args:
        work_order_id: 工单编号（如 WO-20260616-0001）或工单 UUID
        action: 操作类型，可选值 start / complete
        operator_id: 实际操作人的 user_id 或姓名
        repair_detail: 维修过程描述，action=complete 时必需
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    from app.modules.equipment.deps import EquipmentAccessContext

    ctx = EquipmentAccessContext(user=user, data_scope="all")

    if action not in ("start", "complete"):
        raise ValueError(f"无效的操作类型 '{action}'，可选值：start / complete")

    wo_uuid = uuid.UUID(work_order_id)
    wo = await get_work_order_by_id(db, wo_uuid)

    if action == "start":
        result = await start_work_order(db, wo.id, ctx)
        return {
            "success": True,
            "work_order_no": result.work_order_no,
            "old_status": "待处理",
            "new_status": result.status,
        }

    if not repair_detail or not repair_detail.strip():
        raise ValueError("完成工单时需要提供 repair_detail")

    from app.modules.equipment.schemas.work_order import WorkOrderComplete

    data = WorkOrderComplete(repair_detail=repair_detail.strip())
    result = await complete_work_order(db, wo.id, data, ctx)
    return {
        "success": True,
        "work_order_no": result.work_order_no,
        "old_status": "执行中",
        "new_status": result.status,
    }


# ─────────────────────────────────────────────────────────────
# Tool 4: 提交巡检表单
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def submit_inspection(
    task_id: str,
    equipment_id: str,
    operator_id: str,
    check_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    提交设备巡检表单，逐项记录检查结果。

    支持线路巡检和设备巡检两种模式：
    - 设备巡检：直接使用 task 上绑定的 template_ids 查找检查项
    - 线路巡检：从路线 → 地点 → 设备的模板绑定中查找检查项（自动合并多模板）

    如果所有设备都已提交，自动完成该巡检任务。

    Args:
        task_id: 巡检任务 ID（UUID 格式）
        equipment_id: 被检设备 ID（UUID 格式）
        operator_id: 实际操作人的 user_id 或姓名
        check_items: 检查项列表，每项包含：
            - item_name: 检查项目名称（必需）
            - result: 检查结果，可选值：正常 / 异常 / 跳过（必需）
            - actual_value: 实测值（可选）
            - remark: 备注（可选）
    """
    db = get_db()
    await resolve_user(db, operator_id)

    task_uuid = uuid.UUID(task_id)
    equipment_uuid = uuid.UUID(equipment_id)

    task = await get_inspection_task_by_id(db, task_uuid)

    # 校验 check_items
    valid_results = {"正常", "异常", "跳过"}
    for item in check_items:
        item_name = item.get("item_name", "")
        result = item.get("result", "")
        if not item_name:
            raise ValueError("每个检查项必须提供 item_name")
        if result not in valid_results:
            raise ValueError(
                f"检查项 '{item_name}' 的 result '{result}' 无效，"
                f"可选值：正常 / 异常 / 跳过"
            )
        # 异常项必须填写实际值或备注
        if result == "异常" and not item.get("actual_value") and not item.get("remark"):
            raise ValueError(
                f"检查项 '{item_name}' 结果为异常，必须填写 actual_value 或 remark"
            )

    # 加载模板项映射（支持线路巡检多模板）
    name_to_id = await _get_template_item_map(db, task)

    if not name_to_id:
        modes = []
        if task.route_id:
            modes.append("该路线尚未配置设备检查模板")
        else:
            modes.append("该任务未绑定检查模板")
        raise ValueError("、".join(modes) + "，请先在系统中配置")

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
            rec["template_item_id"] = tid
        else:
            item_name = item["item_name"]
            mapped_id = name_to_id.get(item_name)
            if mapped_id:
                rec["template_item_id"] = mapped_id
            else:
                available = "、".join(list(name_to_id.keys())[:10])
                raise ValueError(
                    f"未找到检查项 '{item_name}' 对应的模板项。"
                    f"请确认：1) 检查项名称与模板完全一致 "
                    f"2) 该设备已绑定包含此检查项的模板。可用项：{available}"
                )
        records.append(rec)

    # 提交
    submitted = await submit_equipment_check(db, task_uuid, equipment_uuid, records)

    # 重新查询任务状态
    task_after = await get_inspection_task_by_id(db, task_uuid)
    all_done = task_after.status == "已完成"

    return {
        "success": True,
        "task_no": task.task_no,
        "submitted_count": len(submitted),
        "all_done": all_done,
        "message": (
            f"已提交 {len(submitted)} 项检查结果，"
            + ("巡检任务已完成" if all_done else "还有待检设备")
        ),
    }


# ─────────────────────────────────────────────────────────────
# Tool 5: 查询巡检任务
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def list_inspection_tasks(
    operator_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """
    查询指定用户的巡检任务列表。

    Args:
        operator_id: 实际操作人的 user_id 或姓名（替谁查）
        status: 任务状态过滤，可选值：待执行 / 执行中 / 已完成 / 已关闭。
                 不传则返回所有状态。
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
    return [_it_to_dict(t) for t in tasks]


# ─────────────────────────────────────────────────────────────
# Tool 6: 修改巡检任务状态
# ─────────────────────────────────────────────────────────────


@mcp.tool()
async def update_inspection_task(
    task_id: str,
    action: str,
    operator_id: str,
    remark: str | None = None,
) -> dict[str, Any]:
    """
    修改巡检任务状态：开始执行、完成、或关闭任务。

    - action="start"：任务从"待执行"变为"执行中"
    - action="complete"：任务从"执行中"变为"已完成"（设备巡检和线路巡检均支持）
    - action="close"：任务变为"已关闭"

    Args:
        task_id: 巡检任务 ID（UUID 格式）
        action: 操作类型，可选值 start / complete / close
        operator_id: 实际操作人的 user_id 或姓名
        remark: 备注说明，action=close 时作为关闭原因
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    from app.modules.equipment.deps import EquipmentAccessContext

    ctx = EquipmentAccessContext(user=user, data_scope="all")

    if action not in ("start", "complete", "close"):
        raise ValueError(f"无效的操作类型 '{action}'，可选值：start / complete / close")

    task_uuid = uuid.UUID(task_id)

    task = await get_inspection_task_by_id(db, task_uuid)
    old_status = task.status

    if action == "start":
        result = await start_inspection_task(db, task_uuid, ctx)
    elif action == "complete":
        result = await complete_inspection_task(db, task_uuid, ctx)
    else:
        result = await close_inspection_task(db, task_uuid, remark=remark)

    return {
        "success": True,
        "task_no": result.task_no,
        "old_status": old_status,
        "new_status": result.status,
    }
