"""生产模块数据读写。只负责查询与持久化，不做业务判断。"""

import uuid
from typing import Any, Literal

from sqlalchemy import Row, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import (
    Batch,
    BatchIntermediateConsumption,
    BatchIntermediateOutput,
    IntermediateType,
    NodeExecution,
    NodeExecutionEquipment,
    NodeFieldDef,
    NodeFieldValue,
    ProcessRoute,
    Product,
    RouteEdge,
    RouteNode,
    RouteNodeIntermediate,
)

# 注意：BatchLink 的读取只发生在下方递归 CTE 中，无需单独查询函数

# ── 产品 ──


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> Product | None:
    stmt = select(Product).where(Product.id == product_id, Product.is_deleted == False)  # noqa: E712
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_product_by_name(db: AsyncSession, name: str) -> Product | None:
    stmt = select(Product).where(
        Product.product_name == name, Product.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_products(
    db: AsyncSession, keyword: str | None, page: int, page_size: int
) -> tuple[list[Product], int]:
    stmt = select(Product).where(Product.is_deleted == False)  # noqa: E712
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            Product.product_code.ilike(pattern) | Product.product_name.ilike(pattern)
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(Product.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars())
    return items, total


# ── 路线（模板图） ──


async def get_route(db: AsyncSession, route_id: uuid.UUID) -> ProcessRoute | None:
    stmt = select(ProcessRoute).where(
        ProcessRoute.id == route_id, ProcessRoute.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_routes(
    db: AsyncSession, product_id: uuid.UUID | None, page: int, page_size: int
) -> tuple[list[ProcessRoute], int]:
    stmt = select(ProcessRoute).where(ProcessRoute.is_deleted == False)  # noqa: E712
    if product_id:
        stmt = stmt.where(ProcessRoute.product_id == product_id)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = (
        stmt.order_by(ProcessRoute.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(stmt)).scalars()), total


async def next_route_version(db: AsyncSession, product_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.max(ProcessRoute.version), 0)).where(
        ProcessRoute.product_id == product_id,
        ProcessRoute.is_deleted == False,  # noqa: E712
    )
    return int((await db.execute(stmt)).scalar_one()) + 1


async def get_route_nodes(db: AsyncSession, route_id: uuid.UUID) -> list[RouteNode]:
    stmt = (
        select(RouteNode)
        .where(RouteNode.route_id == route_id, RouteNode.is_deleted == False)  # noqa: E712
        .order_by(RouteNode.sort_order, RouteNode.node_code)
    )
    return list((await db.execute(stmt)).scalars())


async def get_route_edges(db: AsyncSession, route_id: uuid.UUID) -> list[RouteEdge]:
    stmt = select(RouteEdge).where(
        RouteEdge.route_id == route_id, RouteEdge.is_deleted == False  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_edge(db: AsyncSession, edge_id: uuid.UUID) -> RouteEdge | None:
    stmt = select(RouteEdge).where(
        RouteEdge.id == edge_id, RouteEdge.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_field_defs_by_nodes(
    db: AsyncSession, node_ids: list[uuid.UUID]
) -> list[NodeFieldDef]:
    if not node_ids:
        return []
    stmt = (
        select(NodeFieldDef)
        .where(NodeFieldDef.node_id.in_(node_ids), NodeFieldDef.is_deleted == False)  # noqa: E712
        .order_by(NodeFieldDef.sort_order)
    )
    return list((await db.execute(stmt)).scalars())


async def soft_delete_route_graph(db: AsyncSession, route_id: uuid.UUID) -> None:
    """整图替换前软删除路线现有节点、边、字段定义、中间体绑定。"""
    nodes = await get_route_nodes(db, route_id)
    node_ids = [n.id for n in nodes]
    for n in nodes:
        n.is_deleted = True
    for e in await get_route_edges(db, route_id):
        e.is_deleted = True
    for f in await get_field_defs_by_nodes(db, node_ids):
        f.is_deleted = True
    im_stmt = select(RouteNodeIntermediate).where(
        RouteNodeIntermediate.node_id.in_(node_ids),
        RouteNodeIntermediate.is_deleted == False,  # noqa: E712
    )
    im_list = list((await db.execute(im_stmt)).scalars())
    for im in im_list:
        im.is_deleted = True
    await db.flush()


# ── 批次 ──


async def get_batch(db: AsyncSession, batch_id: uuid.UUID) -> Batch | None:
    stmt = select(Batch).where(Batch.id == batch_id, Batch.is_deleted == False)  # noqa: E712
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_batch_by_no(db: AsyncSession, batch_no: str) -> Batch | None:
    stmt = select(Batch).where(
        Batch.batch_no == batch_no, Batch.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_batches_by_ids(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> list[Batch]:
    if not batch_ids:
        return []
    stmt = select(Batch).where(Batch.id.in_(batch_ids), Batch.is_deleted == False)  # noqa: E712
    return list((await db.execute(stmt)).scalars())


async def list_batches(
    db: AsyncSession,
    product_id: uuid.UUID | None,
    status: str | None,
    keyword: str | None,
    page: int,
    page_size: int,
    order_by: str = "created_at",
    order: str = "desc",
) -> tuple[list[Batch], int]:
    stmt = select(Batch).where(Batch.is_deleted == False)  # noqa: E712
    if product_id:
        stmt = stmt.where(Batch.product_id == product_id)
    if status:
        stmt = stmt.where(Batch.status == status)
    if keyword:
        stmt = stmt.where(Batch.batch_no.ilike(f"%{keyword}%"))
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    sort_col = {"batch_no": Batch.batch_no, "created_at": Batch.created_at}.get(
        order_by, Batch.created_at
    )
    stmt = (
        stmt.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(stmt)).scalars()), total


async def count_unfinished_batches(db: AsyncSession, product_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(Batch)
        .where(
            Batch.product_id == product_id,
            Batch.status.in_(("pending", "in_progress")),
            Batch.is_deleted == False,  # noqa: E712
        )
    )
    return (await db.execute(stmt)).scalar_one()


# ── 执行 ──


async def get_execution(
    db: AsyncSession, execution_id: uuid.UUID
) -> NodeExecution | None:
    stmt = select(NodeExecution).where(
        NodeExecution.id == execution_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_executions(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[NodeExecution]:
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id == batch_id,
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.started_at)
    )
    return list((await db.execute(stmt)).scalars())


async def list_executions_by_batches(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> list[NodeExecution]:
    if not batch_ids:
        return []
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id.in_(batch_ids),
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.started_at)
    )
    return list((await db.execute(stmt)).scalars())


async def count_executions(db: AsyncSession, batch_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return int((await db.execute(stmt)).scalar_one())


async def max_execution_seq(
    db: AsyncSession, batch_id: uuid.UUID, node_id: uuid.UUID
) -> int:
    stmt = select(func.coalesce(func.max(NodeExecution.execution_seq), 0)).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.node_id == node_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return int((await db.execute(stmt)).scalar_one())


async def has_in_progress_execution(
    db: AsyncSession, batch_id: uuid.UUID, node_id: uuid.UUID
) -> bool:
    stmt = select(func.count()).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.node_id == node_id,
        NodeExecution.status == "in_progress",
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return int((await db.execute(stmt)).scalar_one()) > 0


async def completed_node_ids(
    db: AsyncSession, batch_id: uuid.UUID
) -> set[uuid.UUID]:
    stmt = select(NodeExecution.node_id).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.status == "completed",
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return set((await db.execute(stmt)).scalars())


async def get_field_values_by_executions(
    db: AsyncSession, execution_ids: list[uuid.UUID]
) -> list[NodeFieldValue]:
    if not execution_ids:
        return []
    stmt = select(NodeFieldValue).where(
        NodeFieldValue.execution_id.in_(execution_ids),
        NodeFieldValue.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_equipments_by_executions(
    db: AsyncSession, execution_ids: list[uuid.UUID]
) -> list[NodeExecutionEquipment]:
    if not execution_ids:
        return []
    stmt = select(NodeExecutionEquipment).where(
        NodeExecutionEquipment.execution_id.in_(execution_ids),
        NodeExecutionEquipment.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_nodes_by_ids(
    db: AsyncSession, node_ids: list[uuid.UUID]
) -> list[RouteNode]:
    if not node_ids:
        return []
    stmt = select(RouteNode).where(
        RouteNode.id.in_(node_ids), RouteNode.is_deleted == False  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def list_executions_by_node(
    db: AsyncSession,
    node_id: uuid.UUID,
    status: str | None,
    page: int,
    page_size: int,
    order_by: str = "started_at",
    order: str = "desc",
) -> tuple[list[NodeExecution], int]:
    stmt = select(NodeExecution).where(
        NodeExecution.node_id == node_id,
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    if status:
        stmt = stmt.where(NodeExecution.status == status)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    if order_by == "batch_no":
        # 批号在 batches 表上，仅排序时 join（无外键约束，按 batch_id 关联）
        stmt = stmt.join(Batch, Batch.id == NodeExecution.batch_id)
    sort_col = {
        "batch_no": Batch.batch_no,
        "started_at": NodeExecution.started_at,
    }.get(order_by, NodeExecution.started_at)
    stmt = (
        stmt.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.execute(stmt)).scalars()), int(total)


# ── 谱系与溯源 ──


_TRACE_UP_SQL = text(
    """
WITH RECURSIVE up AS (
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, ARRAY[l.child_batch_id] AS path, 1 AS depth
    FROM production.batch_links l
    WHERE l.child_batch_id = :bid AND l.is_deleted = false
    UNION ALL
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, up.path || l.child_batch_id, up.depth + 1
    FROM production.batch_links l
    JOIN up ON l.child_batch_id = up.parent_batch_id
    WHERE l.is_deleted = false
      AND NOT (l.parent_batch_id = ANY(up.path))
      AND up.depth < 20
)
SELECT parent_batch_id, child_batch_id, edge_id, allocated_qty, is_deviation FROM up
"""
)

_TRACE_DOWN_SQL = text(
    """
WITH RECURSIVE down AS (
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, ARRAY[l.parent_batch_id] AS path, 1 AS depth
    FROM production.batch_links l
    WHERE l.parent_batch_id = :bid AND l.is_deleted = false
    UNION ALL
    SELECT l.parent_batch_id, l.child_batch_id, l.edge_id, l.allocated_qty,
           l.is_deviation, down.path || l.parent_batch_id, down.depth + 1
    FROM production.batch_links l
    JOIN down ON l.parent_batch_id = down.child_batch_id
    WHERE l.is_deleted = false
      AND NOT (l.child_batch_id = ANY(down.path))
      AND down.depth < 20
)
SELECT parent_batch_id, child_batch_id, edge_id, allocated_qty, is_deviation FROM down
"""
)


async def trace_links(
    db: AsyncSession, batch_id: uuid.UUID, direction: Literal["up", "down"]
) -> list[Row[Any]]:
    """沿 batch_links 递归上溯/下溯，返回谱系边行（防环、深度上限 20）。"""
    sql = _TRACE_UP_SQL if direction == "up" else _TRACE_DOWN_SQL
    result = await db.execute(sql, {"bid": batch_id})
    return list(result.all())


# ── 中间体 ──


async def get_intermediate_type(
    db: AsyncSession, type_id: uuid.UUID
) -> IntermediateType | None:
    stmt = select(IntermediateType).where(
        IntermediateType.id == type_id, IntermediateType.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_intermediate_type_by_code(
    db: AsyncSession, code: str
) -> IntermediateType | None:
    stmt = select(IntermediateType).where(
        IntermediateType.code == code, IntermediateType.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_intermediate_types(
    db: AsyncSession, keyword: str | None, page: int, page_size: int
) -> tuple[list[IntermediateType], int]:
    stmt = select(IntermediateType).where(
        IntermediateType.is_deleted == False  # noqa: E712
    )
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            IntermediateType.code.ilike(pattern)
            | IntermediateType.name.ilike(pattern)
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(IntermediateType.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    return list((await db.execute(stmt)).scalars()), total


async def list_intermediate_types_all(
    db: AsyncSession,
) -> list[IntermediateType]:
    stmt = select(IntermediateType).where(
        IntermediateType.is_deleted == False  # noqa: E712
    ).order_by(IntermediateType.code)
    return list((await db.execute(stmt)).scalars())


async def get_node_intermediates(
    db: AsyncSession, node_ids: list[uuid.UUID]
) -> list[RouteNodeIntermediate]:
    """按节点批量查询中间体绑定。"""
    if not node_ids:
        return []
    stmt = select(RouteNodeIntermediate).where(
        RouteNodeIntermediate.node_id.in_(node_ids),
        RouteNodeIntermediate.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_node_intermediates_by_direction(
    db: AsyncSession, node_id: uuid.UUID, direction: str
) -> list[RouteNodeIntermediate]:
    stmt = select(RouteNodeIntermediate).where(
        RouteNodeIntermediate.node_id == node_id,
        RouteNodeIntermediate.direction == direction,
        RouteNodeIntermediate.is_deleted == False,  # noqa: E712
    ).order_by(RouteNodeIntermediate.sort_order)
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_output(
    db: AsyncSession, output_id: uuid.UUID
) -> BatchIntermediateOutput | None:
    stmt = select(BatchIntermediateOutput).where(
        BatchIntermediateOutput.id == output_id,
        BatchIntermediateOutput.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_intermediate_outputs_by_batch(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[BatchIntermediateOutput]:
    stmt = (
        select(BatchIntermediateOutput)
        .where(
            BatchIntermediateOutput.batch_id == batch_id,
            BatchIntermediateOutput.is_deleted == False,  # noqa: E712
        )
        .order_by(BatchIntermediateOutput.created_at)
    )
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_outputs_by_executions(
    db: AsyncSession, execution_ids: list[uuid.UUID]
) -> list[BatchIntermediateOutput]:
    if not execution_ids:
        return []
    stmt = select(BatchIntermediateOutput).where(
        BatchIntermediateOutput.execution_id.in_(execution_ids),
        BatchIntermediateOutput.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_consumptions_by_batch(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[BatchIntermediateConsumption]:
    stmt = (
        select(BatchIntermediateConsumption)
        .where(
            BatchIntermediateConsumption.batch_id == batch_id,
            BatchIntermediateConsumption.is_deleted == False,  # noqa: E712
        )
        .order_by(BatchIntermediateConsumption.created_at)
    )
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_consumptions_by_executions(
    db: AsyncSession, execution_ids: list[uuid.UUID]
) -> list[BatchIntermediateConsumption]:
    if not execution_ids:
        return []
    stmt = select(BatchIntermediateConsumption).where(
        BatchIntermediateConsumption.execution_id.in_(execution_ids),
        BatchIntermediateConsumption.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_consumptions_by_output(
    db: AsyncSession, output_id: uuid.UUID
) -> list[BatchIntermediateConsumption]:
    """下游溯源：谁消耗了该产出。"""
    stmt = select(BatchIntermediateConsumption).where(
        BatchIntermediateConsumption.output_id == output_id,
        BatchIntermediateConsumption.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())
