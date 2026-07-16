"""设备查询相关 MCP Tools：模糊查询设备信息。"""

from __future__ import annotations

import uuid
from typing import Any

from fastmcp.tools.base import ToolResult

from app.modules.equipment.deps import (
    EquipmentAccessContext,
    build_access_context,
)
from app.modules.equipment.mcp_tools._helpers import _resolve_equipment
from app.modules.equipment.repository.equipment import (
    get_department_info,
    get_equipments,
)
from app.modules.equipment.service.data_scope import verify_write_ownership
from app.modules.equipment.service.status_log import record_status_change
from app.platform.identity.mcp_tools import resolve_user
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp


def _md_cell(value: str) -> str:
    """转义 Markdown 表格单元格中的竖线，避免破坏表格结构。"""
    return value.replace("|", "\\|")


@mcp.tool()
async def search_equipments(
    name: str,
    operator_id: str,
    limit: int = 20,
) -> ToolResult:
    """
    根据模糊的设备名称查询设备信息，返回 Markdown 格式的设备列表。

    Agent 只需提供一个模糊的设备名称关键词，工具会对设备编号和设备名称
    做模糊匹配，返回含【设备编号、设备名称、设备位置、归属部门】的列表，
    供 Agent 展示给用户或据此选定确切的设备编号后再执行其他操作。

    结果按 operator_id 对应的用户数据权限过滤，只返回用户所属部门的设备。

    Args:
        name: 模糊的设备名称或设备编号关键词
        operator_id: 实际操作人的 user_id 或姓名（按此用户的部门权限过滤）
        limit: 最多返回的设备数量，默认 20
    """
    if not name or not name.strip():
        return ToolResult(
            content="请提供设备名称关键词后再查询。",
            structured_content={"error": "name 不能为空", "result": [], "total": 0},
            is_error=True,
        )

    keyword = name.strip()
    db = get_db()

    # 解析操作人身份，通过权限系统获取真实数据范围（超管 scope="all" 则不过滤）
    try:
        user = await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    ctx = await build_access_context(db, user, resource="asset")
    equipments, total = await get_equipments(
        db, ctx, keyword=keyword, page=1, page_size=limit
    )

    if not equipments:
        return ToolResult(
            content=f"未找到匹配「{keyword}」的设备。",
            structured_content={"result": [], "total": 0},
        )

    # 解析归属部门名称（缓存，避免同部门重复查询）
    dept_name_cache: dict[uuid.UUID, str] = {}
    for eq in equipments:
        if eq.department_id and eq.department_id not in dept_name_cache:
            info = await get_department_info(db, eq.department_id)
            dept_name_cache[eq.department_id] = info["name"] if info else ""

    result: list[dict[str, Any]] = []
    for eq in equipments:
        location = eq.location.name if eq.location else ""
        department = dept_name_cache.get(eq.department_id, "") if eq.department_id else ""
        result.append(
            {
                "equipment_no": eq.equipment_no,
                "name": eq.name,
                "location": location,
                "department": department,
                "status": eq.status,
                "running_status": eq.running_status,
            }
        )

    lines = [f"找到 {len(result)} 台匹配「{keyword}」的设备（共 {total} 台）：", ""]
    lines.append("| 设备编号 | 设备名称 | 设备位置 | 归属部门 | 运行状态 | 设备状态 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in result:
        lines.append(
            f"| {_md_cell(item['equipment_no'])} "
            f"| {_md_cell(item['name'])} "
            f"| {_md_cell(item['location']) or '未设置'} "
            f"| {_md_cell(item['department']) or '未设置'} "
            f"| {_md_cell(item['running_status'])} "
            f"| {_md_cell(item['status'])} |"
        )
    if total > len(result):
        lines.append("")
        lines.append(f"结果较多，仅显示前 {limit} 台，请提供更精确的名称以缩小范围。")

    return ToolResult(
        content="\n".join(lines),
        structured_content={"result": result, "total": total},
    )


@mcp.tool()
async def update_equipment_running_status(
    equipment: str,
    running_status: str,
    operator_id: str,
) -> ToolResult:
    """
    修改设备的运行状态（开机/停机），并记录到状态变更历史。

    Agent 在用户要求开机或停机时调用此工具。
    会校验运行状态值、解析操作人身份、记录状态变更日志。

    Args:
        equipment: 设备编号（如 EQ-001）或设备 UUID
        running_status: 目标运行状态，仅支持：开机 / 停机
        operator_id: 实际操作人的 user_id 或姓名
    """
    if running_status not in ("开机", "停机"):
        return ToolResult(
            content=f"无效的运行状态「{running_status}」，可选值：开机 / 停机。",
            structured_content={"error": f"无效运行状态：{running_status}"},
            is_error=True,
        )

    db = get_db()

    try:
        user = await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    try:
        eq = await _resolve_equipment(db, equipment)
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

    eq_name = eq.name
    eq_no = eq.equipment_no
    old_running_status = eq.running_status

    # 构建访问上下文（MCP 工具中用户身份已校验，scope=all 委托服务层决策）
    ctx = EquipmentAccessContext(user=user, data_scope="all")
    await verify_write_ownership(ctx, eq, field="department_id")

    if old_running_status == running_status:
        return ToolResult(
            content=f"设备 {eq_name}（{eq_no}）当前已是「{running_status}」状态，无需重复操作。",
            structured_content={
                "success": True,
                "equipment_no": eq_no,
                "equipment_name": eq_name,
                "old_running_status": old_running_status,
                "new_running_status": running_status,
                "unchanged": True,
            },
        )

    eq.running_status = running_status

    await record_status_change(
        db,
        eq.id,
        old_running_status,
        running_status,
        source="manual",
        operator_id=user.id,
        log_type="running",
    )

    await db.commit()

    return ToolResult(
        content=f"设备 {eq_name}（{eq_no}）运行状态已变更：{old_running_status} → {running_status}",
        structured_content={
            "success": True,
            "equipment_no": eq_no,
            "equipment_name": eq_name,
            "old_running_status": old_running_status,
            "new_running_status": running_status,
            "unchanged": False,
        },
    )
