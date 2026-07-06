"""工单相关 MCP Tools：查询用户、查询工单、操作工单。"""

from __future__ import annotations

import uuid

from fastmcp.tools.tool import ToolResult

from app.modules.equipment.mcp_tools._helpers import (
    _resolve_work_order,
    _user_to_dict,
    _wo_to_dict,
    resolve_user,
)
from app.modules.equipment.repository.work_order import (
    get_user_work_orders,
)
from app.modules.equipment.service import (
    complete_work_order,
    start_work_order,
)
from app.platform.identity.models import User
from app.platform.identity.repository import UserRepository
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp

# ─────────────────────────────────────────────────────────────
# Tool 1: 查询用户身份
# ─────────────────────────────────────────────────────────────


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
