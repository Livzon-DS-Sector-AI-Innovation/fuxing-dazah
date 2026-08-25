"""产品工艺目录查询 — 列出系统内产品、已发布的工艺路线及各路线节点流程。"""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastmcp.tools.base import ToolResult
from sqlalchemy import select

from app.modules.production.models import ProcessRoute, Product, RouteNode
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("production")


@mcp.tool()
async def query_product_catalog() -> ToolResult:
    """查询系统当前有哪些产品、每个产品的已发布工艺路线及各路线的节点流程。

    产品 → 工艺路线（仅 published，已发布）→ 工序节点（按流程顺序）逐级组织，
    以 Markdown 表格输出，适用于 Agent 了解可生产的产品与工艺结构。

    Returns:
        产品工艺目录（Markdown）
    """
    db = get_db()
    products_stmt = (
        select(Product)
        .where(Product.is_deleted == False)  # noqa: E712
        .order_by(Product.product_name)
    )
    products = list((await db.execute(products_stmt)).scalars())

    if not products:
        return ToolResult(content="系统中暂无产品。")

    # 批量查询所有产品的已发布路线
    product_ids = [p.id for p in products]
    routes_stmt = (
        select(ProcessRoute)
        .where(
            ProcessRoute.product_id.in_(product_ids),
            ProcessRoute.status == "published",
            ProcessRoute.is_deleted == False,  # noqa: E712
        )
        .order_by(ProcessRoute.route_name)
    )
    all_routes = list((await db.execute(routes_stmt)).scalars())
    routes_by_product: dict[uuid.UUID, list[ProcessRoute]] = defaultdict(list)
    for r in all_routes:
        routes_by_product[r.product_id].append(r)

    # 批量查询所有路线的节点
    route_ids = [r.id for r in all_routes]
    nodes_stmt = (
        select(RouteNode)
        .where(
            RouteNode.route_id.in_(route_ids),
            RouteNode.is_deleted == False,  # noqa: E712
        )
        .order_by(RouteNode.route_id, RouteNode.sort_order, RouteNode.node_code)
    )
    all_nodes = list((await db.execute(nodes_stmt)).scalars())
    nodes_by_route: dict[uuid.UUID, list[RouteNode]] = defaultdict(list)
    for n in all_nodes:
        nodes_by_route[n.route_id].append(n)

    lines = ["## 产品工艺目录\n"]

    for product in products:
        header = f"### {product.product_name}"
        if product.product_code:
            header += f"（{product.product_code}）"
        lines.append(header)
        lines.append(f"默认单位：{product.unit}\n")

        routes = routes_by_product.get(product.id, [])

        if not routes:
            lines.append("暂无已发布的工艺路线。\n")
            continue

        for route in routes:
            lines.append(f"**{route.route_name}**（已发布）\n")
            nodes = nodes_by_route.get(route.id, [])

            if not nodes:
                lines.append("该路线暂无节点。\n")
                continue

            lines.append("| 序号 | 工序 | 编码 | 工段 |")
            lines.append("|------|------|------|------|")
            for i, node in enumerate(nodes, 1):
                lines.append(
                    f"| {i} | {node.name} | `{node.node_code}` | {node.stage_name or '—'} |"
                )
            lines.append("")

    return ToolResult(content="\n".join(lines))
