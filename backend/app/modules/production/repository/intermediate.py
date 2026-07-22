"""中间体数据查询。"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import (
    BatchIntermediateConsumption,
    BatchIntermediateOutput,
    IntermediateType,
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
    "get_intermediate_outputs_by_type",
    "get_intermediate_consumptions_by_type",
    "get_intermediate_types_by_ids",
    "get_intermediate_outputs_by_ids",
    "get_available_outputs",
]


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
    limit: int = 500,
) -> list[BatchIntermediateOutput]:
    """所有批次的中间体产出（可选按类型过滤），用于消耗时选择上游产出。"""
    stmt = select(BatchIntermediateOutput).where(
        BatchIntermediateOutput.is_deleted == False,  # noqa: E712
    )
    if intermediate_type_id is not None:
        stmt = stmt.where(
            BatchIntermediateOutput.intermediate_type_id == intermediate_type_id,
        )
    stmt = stmt.order_by(BatchIntermediateOutput.created_at.desc()).limit(limit)
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
    db: AsyncSession, ids: list[uuid.UUID]
) -> list[IntermediateType]:
    """按 ID 批量查询中间体类型。"""
    if not ids:
        return []
    stmt = select(IntermediateType).where(
        IntermediateType.id.in_(ids),
        IntermediateType.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_intermediate_outputs_by_ids(
    db: AsyncSession, ids: list[uuid.UUID]
) -> list[BatchIntermediateOutput]:
    """按 ID 批量查询中间体产出记录。"""
    if not ids:
        return []
    stmt = select(BatchIntermediateOutput).where(
        BatchIntermediateOutput.id.in_(ids),
        BatchIntermediateOutput.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())
