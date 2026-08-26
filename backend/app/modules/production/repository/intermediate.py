"""中间体数据查询。"""

import uuid
from typing import Any, Literal

from sqlalchemy import Row, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import (
    BatchIntermediateConsumption,
    BatchIntermediateOutput,
    IntermediateType,
    MixingContainer,
    NodeExecution,
    ProcessRoute,
    RouteNode,
    RouteNodeIntermediate,
)

__all__ = [
    "get_intermediate_type",
    "get_intermediate_type_by_code",
    "list_intermediate_types",
    "list_intermediate_types_all",
    "get_node_intermediates",
    "get_node_intermediates_by_direction",
    "get_intermediate_output",
    "get_intermediate_outputs_by_batch",
    "get_intermediate_outputs_by_executions",
    "get_intermediate_consumptions_by_batch",
    "get_intermediate_consumptions_by_executions",
    "get_consumptions_by_output",
    "get_consumptions_by_outputs",
    "get_intermediate_outputs_by_type",
    "get_intermediate_consumptions_by_type",
    "get_intermediate_types_by_ids",
    "get_intermediate_outputs_by_ids",
    "get_available_outputs",
    "get_non_archived_routes_by_intermediate_type",
    "get_intermediate_type_by_name",
    "get_mixing_container",
    "list_mixing_containers",
    "get_mixing_containers_by_ids",
    "get_mixing_containers_by_line",
    "get_outputs_by_container",
    "get_outputs_by_container_ids",
    "get_consumptions_by_container",
    "get_consumptions_by_container_ids",
    "get_material_links_by_batches",
]


async def get_intermediate_type(
    db: AsyncSession, type_id: uuid.UUID, *, include_deleted: bool = False,
) -> IntermediateType | None:
    stmt = select(IntermediateType).where(IntermediateType.id == type_id)
    if not include_deleted:
        stmt = stmt.where(IntermediateType.is_deleted == False)  # noqa: E712
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_intermediate_type_by_code(
    db: AsyncSession, code: str
) -> IntermediateType | None:
    stmt = select(IntermediateType).where(
        IntermediateType.code == code, IntermediateType.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_intermediate_types(
    db: AsyncSession, keyword: str | None, page: int, page_size: int,
    *, include_deleted: bool = False,
) -> tuple[list[IntermediateType], int]:
    stmt = select(IntermediateType)
    if not include_deleted:
        stmt = stmt.where(IntermediateType.is_deleted == False)  # noqa: E712
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


async def get_consumptions_by_outputs(
    db: AsyncSession, output_ids: list[uuid.UUID],
) -> list[BatchIntermediateConsumption]:
    """批量查多个产出的全部消耗记录（余量计算用，排除已中止执行）。"""
    if not output_ids:
        return []
    stmt = (
        select(BatchIntermediateConsumption)
        .outerjoin(
            NodeExecution,
            NodeExecution.id == BatchIntermediateConsumption.execution_id,
        )
        .where(
            BatchIntermediateConsumption.output_id.in_(output_ids),
            BatchIntermediateConsumption.is_deleted == False,  # noqa: E712
            # 只排除已中止执行；执行缺失的孤儿行保守计入（防超耗）
            or_(
                NodeExecution.status.is_(None),
                NodeExecution.status != "aborted",
            ),
        )
    )
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_outputs_by_type(
    db: AsyncSession, intermediate_type_id: uuid.UUID, limit: int = 1000
) -> list[BatchIntermediateOutput]:
    """某个产出物类型的所有产出记录（跨批次），默认上限 1000 条。"""
    stmt = (
        select(BatchIntermediateOutput)
        .where(
            BatchIntermediateOutput.intermediate_type_id == intermediate_type_id,
            BatchIntermediateOutput.is_deleted == False,  # noqa: E712
        )
        .order_by(BatchIntermediateOutput.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


async def get_available_outputs(
    db: AsyncSession,
    intermediate_type_id: uuid.UUID | None = None,
    line_ids: list[uuid.UUID] | None = None,
    include_null_line: bool = False,
    limit: int = 500,
) -> list[BatchIntermediateOutput]:
    """所有批次的中间体产出（可选按类型/产线过滤），用于消耗时选择上游产出。

    余量过滤（quantity - 已消耗 > 0，排除已中止执行）在 SQL 层完成，
    保证 limit 窗口内全部有可用余量，不会因 limit 截断漏掉老库存。
    line_ids 语义：None=不过滤（内部/MCP）；[]=仅无产线产出（未绑定，过渡期存量）；
    非空=该产线集合的产出，include_null_line=True 时叠加无产线产出。
    """
    consumed_subq = (
        select(
            BatchIntermediateConsumption.output_id,
            func.coalesce(
                func.sum(BatchIntermediateConsumption.quantity), 0.0,
            ).label("consumed"),
        )
        .outerjoin(
            NodeExecution,
            NodeExecution.id == BatchIntermediateConsumption.execution_id,
        )
        .where(
            BatchIntermediateConsumption.is_deleted == False,  # noqa: E712
            # 只排除已中止执行；执行缺失的孤儿行保守计入（防超耗）
            or_(
                NodeExecution.status.is_(None),
                NodeExecution.status != "aborted",
            ),
        )
        .group_by(BatchIntermediateConsumption.output_id)
        .subquery()
    )
    stmt = (
        select(BatchIntermediateOutput)
        .outerjoin(
            consumed_subq,
            consumed_subq.c.output_id == BatchIntermediateOutput.id,
        )
        .where(
            BatchIntermediateOutput.is_deleted == False,  # noqa: E712
            # 混装入库的产出通过容器取用，不进入精确批次选择（防双重记账）
            BatchIntermediateOutput.container_id.is_(None),
        )
    )
    if intermediate_type_id is not None:
        stmt = stmt.where(
            BatchIntermediateOutput.intermediate_type_id == intermediate_type_id,
        )
    if line_ids is not None:
        if line_ids:
            if include_null_line:
                stmt = stmt.where(
                    or_(
                        BatchIntermediateOutput.line_id.in_(line_ids),
                        BatchIntermediateOutput.line_id.is_(None),
                    )
                )
            else:
                stmt = stmt.where(BatchIntermediateOutput.line_id.in_(line_ids))
        else:
            stmt = stmt.where(BatchIntermediateOutput.line_id.is_(None))
    stmt = (
        stmt.where(
            BatchIntermediateOutput.quantity
            - func.coalesce(consumed_subq.c.consumed, 0.0) > 0
        )
        .order_by(BatchIntermediateOutput.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_consumptions_by_type(
    db: AsyncSession, intermediate_type_id: uuid.UUID, limit: int = 1000
) -> list[BatchIntermediateConsumption]:
    """某个产出物类型的所有消耗记录（跨批次），默认上限 1000 条。"""
    stmt = (
        select(BatchIntermediateConsumption)
        .where(
            BatchIntermediateConsumption.intermediate_type_id == intermediate_type_id,
            BatchIntermediateConsumption.is_deleted == False,  # noqa: E712
        )
        .order_by(BatchIntermediateConsumption.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_types_by_ids(
    db: AsyncSession, ids: list[uuid.UUID], *, include_deleted: bool = False,
) -> list[IntermediateType]:
    """按 ID 批量查询中间体类型。"""
    if not ids:
        return []
    stmt = select(IntermediateType).where(IntermediateType.id.in_(ids))
    if not include_deleted:
        stmt = stmt.where(IntermediateType.is_deleted == False)  # noqa: E712
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_outputs_by_ids(
    db: AsyncSession, ids: list[uuid.UUID], *, for_update: bool = False,
) -> list[BatchIntermediateOutput]:
    """按 ID 批量查询中间体产出记录。for_update=True 时加行锁（余量校验并发防护）。"""
    if not ids:
        return []
    stmt = select(BatchIntermediateOutput).where(
        BatchIntermediateOutput.id.in_(ids),
        BatchIntermediateOutput.is_deleted == False,  # noqa: E712
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await db.execute(stmt)).scalars())


async def get_non_archived_routes_by_intermediate_type(
    db: AsyncSession, intermediate_type_id: uuid.UUID
) -> list[tuple[uuid.UUID, str]]:
    """查询引用该产出物的未归档路线（去重），返回 [(route_id, route_name), ...]。"""
    stmt = (
        select(ProcessRoute.id, ProcessRoute.route_name)
        .distinct()
        .select_from(RouteNodeIntermediate)
        .join(RouteNode, RouteNode.id == RouteNodeIntermediate.node_id)
        .join(ProcessRoute, ProcessRoute.id == RouteNode.route_id)
        .where(
            RouteNodeIntermediate.intermediate_type_id == intermediate_type_id,
            RouteNodeIntermediate.is_deleted == False,  # noqa: E712
            RouteNode.is_deleted == False,  # noqa: E712
            ProcessRoute.is_deleted == False,  # noqa: E712
            ProcessRoute.status != "archived",
        )
    )
    rows = (await db.execute(stmt)).all()
    return [(row.id, row.route_name) for row in rows]


async def get_intermediate_type_by_name(
    db: AsyncSession, name: str
) -> IntermediateType | None:
    """按名称查询中间体类型（仅未删除），用于名称唯一性校验。"""
    stmt = select(IntermediateType).where(
        IntermediateType.name == name,
        IntermediateType.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ── 混装容器 ──


async def get_mixing_container(
    db: AsyncSession, container_id: uuid.UUID, *, include_deleted: bool = False,
) -> MixingContainer | None:
    stmt = select(MixingContainer).where(MixingContainer.id == container_id)
    if not include_deleted:
        stmt = stmt.where(MixingContainer.is_deleted == False)  # noqa: E712
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_mixing_containers(
    db: AsyncSession, intermediate_type_id: uuid.UUID | None = None,
) -> list[MixingContainer]:
    """容器列表（未删除），可按中间体类型过滤。"""
    stmt = select(MixingContainer).where(
        MixingContainer.is_deleted == False,  # noqa: E712
    )
    if intermediate_type_id:
        stmt = stmt.where(
            MixingContainer.intermediate_type_id == intermediate_type_id,
        )
    stmt = stmt.order_by(MixingContainer.created_at)
    return list((await db.execute(stmt)).scalars())


async def get_mixing_containers_by_ids(
    db: AsyncSession, container_ids: list[uuid.UUID],
    *, include_deleted: bool = False,
) -> list[MixingContainer]:
    if not container_ids:
        return []
    stmt = select(MixingContainer).where(MixingContainer.id.in_(container_ids))
    if not include_deleted:
        stmt = stmt.where(MixingContainer.is_deleted == False)  # noqa: E712
    return list((await db.execute(stmt)).scalars())


async def get_mixing_containers_by_line(
    db: AsyncSession, line_id: uuid.UUID,
) -> list[MixingContainer]:
    """某产线下未删除容器，用于删除产线前校验。"""
    stmt = select(MixingContainer).where(
        MixingContainer.line_id == line_id,
        MixingContainer.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_outputs_by_container(
    db: AsyncSession, container_id: uuid.UUID, *, for_update: bool = False,
) -> list[BatchIntermediateOutput]:
    """落入某容器的未删除产出，for_update=True 时行锁（消耗校验防并发）。"""
    return await get_outputs_by_container_ids(
        db, [container_id], for_update=for_update,
    )


async def get_outputs_by_container_ids(
    db: AsyncSession, container_ids: list[uuid.UUID], *, for_update: bool = False,
) -> list[BatchIntermediateOutput]:
    """落入若干容器的未删除产出（批量），for_update=True 时行锁。"""
    if not container_ids:
        return []
    stmt = select(BatchIntermediateOutput).where(
        BatchIntermediateOutput.container_id.in_(container_ids),
        BatchIntermediateOutput.is_deleted == False,  # noqa: E712
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await db.execute(stmt)).scalars())


async def get_material_links_by_batches(
    db: AsyncSession, batch_ids: set[uuid.UUID], direction: Literal["up", "down"],
) -> list[Row[Any]]:
    """批次集与物料链的关联行（精确模式消耗 → 产出批次，溯源用）。

    - ``up``：我的投料来源 —— ``consumption.batch_id ∈ batch_ids``，产出批次为 parent；
    - ``down``：我的产出去向 —— ``output.batch_id ∈ batch_ids``，消耗批次为 child。

    行结构：``(parent_batch_id, child_batch_id, intermediate_type_id, quantity,
    unit, intermediate_batch_no)``，parent 恒为产出批次（上游）。
    只取 ``output_id`` 非空的精确模式行（混装容器消耗是刻意的溯源断点），
    两表均过滤软删，排除已中止执行的消耗（与余量口径一致）。
    """
    if not batch_ids:
        return []
    c = BatchIntermediateConsumption
    o = BatchIntermediateOutput
    anchor = c.batch_id if direction == "up" else o.batch_id
    stmt = (
        select(
            o.batch_id.label("parent_batch_id"),
            c.batch_id.label("child_batch_id"),
            c.id.label("consumption_id"),
            c.intermediate_type_id,
            c.quantity,
            c.unit,
            o.intermediate_batch_no,
        )
        .select_from(c)
        .join(o, o.id == c.output_id)
        .outerjoin(NodeExecution, NodeExecution.id == c.execution_id)
        .where(
            anchor.in_(batch_ids),
            c.is_deleted == False,  # noqa: E712
            o.is_deleted == False,  # noqa: E712
            # 只排除已中止执行；执行缺失的孤儿行保守计入
            or_(
                NodeExecution.status.is_(None),
                NodeExecution.status != "aborted",
            ),
        )
    )
    return list((await db.execute(stmt)).all())


async def get_consumptions_by_container(
    db: AsyncSession, container_id: uuid.UUID, *,
    for_update: bool = False, exclude_aborted: bool = False,
) -> list[BatchIntermediateConsumption]:
    """从某容器消耗的未删除记录，for_update=True 时行锁。

    exclude_aborted=True 时排除已中止执行的消耗（与精确模式余量口径一致）。
    """
    return await get_consumptions_by_container_ids(
        db, [container_id], for_update=for_update, exclude_aborted=exclude_aborted,
    )


async def get_consumptions_by_container_ids(
    db: AsyncSession, container_ids: list[uuid.UUID], *,
    for_update: bool = False, exclude_aborted: bool = False,
) -> list[BatchIntermediateConsumption]:
    """从若干容器消耗的未删除记录（批量）。

    exclude_aborted=True 时排除已中止执行的消耗（与精确模式余量口径一致）。
    """
    if not container_ids:
        return []
    stmt = select(BatchIntermediateConsumption).where(
        BatchIntermediateConsumption.container_id.in_(container_ids),
        BatchIntermediateConsumption.is_deleted == False,  # noqa: E712
    )
    if exclude_aborted:
        stmt = stmt.outerjoin(
            NodeExecution,
            NodeExecution.id == BatchIntermediateConsumption.execution_id,
        ).where(
            # 只排除已中止执行；执行缺失的孤儿行保守计入（防超耗）
            or_(
                NodeExecution.status.is_(None),
                NodeExecution.status != "aborted",
            ),
        )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await db.execute(stmt)).scalars())


