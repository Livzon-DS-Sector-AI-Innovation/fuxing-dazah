"""备件相关 MCP Tools：查询备件库存。"""

from __future__ import annotations

from fastmcp.tools.base import ToolResult
from sqlalchemy import or_, select

from app.modules.equipment.models.spare_part import SparePart, SparePartStock
from app.platform.identity.mcp_tools import resolve_user
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp


@mcp.tool()
async def search_spare_parts(
    keyword: str,
    operator_id: str,
) -> ToolResult:
    """
    根据关键词模糊搜索备件库存信息。

    支持按备件编号或名称模糊匹配，返回匹配备件的基本信息和当前库存。
    Agent 在帮用户提交维护工单、需要填写消耗备件时，先调用此工具查询可用备件。

    Args:
        keyword: 备件编号或名称的关键词（支持模糊搜索）
        operator_id: 实际操作人的 user_id 或姓名
    """
    if not keyword or not keyword.strip():
        return ToolResult(
            content="搜索关键词不能为空，请提供备件编号或名称的关键词。",
            structured_content={"error": "keyword 不能为空"},
            is_error=True,
        )

    db = get_db()
    try:
        await resolve_user(db, operator_id)
    except ValueError as e:
        return ToolResult(
            content=str(e),
            structured_content={"error": str(e)},
            is_error=True,
        )

    pattern = f"%{keyword.strip()}%"
    query = (
        select(SparePart)
        .where(
            SparePart.is_deleted == False,  # noqa: E712
            SparePart.is_active == True,  # noqa: E712
            or_(
                SparePart.code.ilike(pattern),
                SparePart.name.ilike(pattern),
            ),
        )
        .order_by(SparePart.code)
        .limit(20)
    )
    result = await db.execute(query)
    parts = list(result.scalars().all())

    if not parts:
        return ToolResult(
            content=f"未找到与「{keyword.strip()}」匹配的备件。请尝试其他关键词或确认备件编号。",
            structured_content={"result": [], "total": 0},
        )

    # 批量查库存
    ids = [sp.id for sp in parts]
    stock_q = (
        select(
            SparePartStock.spare_part_id,
            SparePartStock.current_qty,
        )
        .where(
            SparePartStock.spare_part_id.in_(ids),
            SparePartStock.is_deleted == False,  # noqa: E712
        )
    )
    stock_result = await db.execute(stock_q)
    stock_map = {row.spare_part_id: row.current_qty for row in stock_result}

    items = []
    for sp in parts:
        items.append({
            "code": sp.code,
            "name": sp.name,
            "specification": sp.specification or "",
            "current_qty": stock_map.get(sp.id, 0),
        })

    lines = [f"找到 {len(items)} 个备件："]
    for item in items:
        lines.append(
            f"  {item['code']} {item['name']}"
            f"（{item['specification']}）库存：{item['current_qty']}"
        )

    return ToolResult(
        content="\n".join(lines),
        structured_content={"result": items, "total": len(items)},
    )
