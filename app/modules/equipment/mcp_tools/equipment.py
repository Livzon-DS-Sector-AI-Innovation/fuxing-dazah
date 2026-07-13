"""设备查询相关 MCP Tools：模糊查询设备信息。"""

from __future__ import annotations

import uuid
from typing import Any

from fastmcp.tools.base import ToolResult

from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.repository.equipment import (
    get_department_info,
    get_equipments,
)
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp


def _md_cell(value: str) -> str:
    """转义 Markdown 表格单元格中的竖线，避免破坏表格结构。"""
    return value.replace("|", "\\|") if value else value


@mcp.tool()
async def search_equipments(name: str, limit: int = 20) -> ToolResult:
    """
    根据模糊的设备名称查询设备信息，返回 Markdown 格式的设备列表。

    Agent 只需提供一个模糊的设备名称关键词，工具会对设备编号和设备名称
    做模糊匹配，返回含【设备编号、设备名称、设备位置、归属部门】的列表，
    供 Agent 展示给用户或据此选定确切的设备编号后再执行其他操作。

    Args:
        name: 模糊的设备名称或设备编号关键词
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

    # 全局查询：data_scope="all" 时 apply_equipment_scope 直接返回，不访问 ctx.user
    ctx = EquipmentAccessContext(user=None, data_scope="all")  # type: ignore[arg-type]
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
            }
        )

    lines = [f"找到 {len(result)} 台匹配「{keyword}」的设备（共 {total} 台）：", ""]
    lines.append("| 设备编号 | 设备名称 | 设备位置 | 归属部门 |")
    lines.append("| --- | --- | --- | --- |")
    for item in result:
        lines.append(
            f"| {_md_cell(item['equipment_no'])} "
            f"| {_md_cell(item['name'])} "
            f"| {_md_cell(item['location']) or '未设置'} "
            f"| {_md_cell(item['department']) or '未设置'} |"
        )
    if total > len(result):
        lines.append("")
        lines.append(f"结果较多，仅显示前 {limit} 台，请提供更精确的名称以缩小范围。")

    return ToolResult(
        content="\n".join(lines),
        structured_content={"result": result, "total": total},
    )
