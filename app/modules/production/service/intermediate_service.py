"""中间体字典 CRUD + 批次台账查询组装。"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.production import repository as repo
from app.modules.production.models.intermediate import (
    BatchIntermediateOutput,
    IntermediateType,
)
from app.modules.production.schemas.intermediate import (
    IntermediateConsumptionOut,
    IntermediateOutputOut,
    IntermediateTypeCreate,
    IntermediateTypeUpdate,
)
from app.platform.identity.models import User


async def create_intermediate_type(
    db: AsyncSession,
    payload: IntermediateTypeCreate,
    user: User | None,
) -> IntermediateType:
    """创建中间体字典条目，检查 code 唯一。"""
    existing = await repo.get_intermediate_type_by_code(db, payload.code)
    if existing:
        raise DuplicateException("中间体编码", payload.code)
    obj = IntermediateType(
        code=payload.code,
        name=payload.name,
        category=payload.category,
        default_unit=payload.default_unit,
        description=payload.description,
        created_by=user.id if user else None,
    )
    db.add(obj)
    await db.flush()
    return obj  # INSERT: RETURNING 自动回填，无需 re-fetch


async def update_intermediate_type(
    db: AsyncSession,
    type_id: uuid.UUID,
    payload: IntermediateTypeUpdate,
    user: User | None,
) -> IntermediateType:
    """编辑中间体，仅更新非 None 字段。"""
    obj = await repo.get_intermediate_type(db, type_id)
    if not obj:
        raise NotFoundException("中间体", str(type_id))
    for field_name in ("name", "category", "default_unit", "description"):
        val = getattr(payload, field_name)
        if val is not None:
            setattr(obj, field_name, val)
    if user:
        obj.updated_by = user.id
    await db.flush()
    # UPDATE 后 re-fetch
    refreshed = await repo.get_intermediate_type(db, type_id)
    assert refreshed is not None
    return refreshed


async def delete_intermediate_type(
    db: AsyncSession, type_id: uuid.UUID, user: User | None
) -> None:
    """软删除中间体字典条目。不级联删除引用。"""
    obj = await repo.get_intermediate_type(db, type_id)
    if not obj:
        raise NotFoundException("中间体", str(type_id))
    obj.is_deleted = True
    if user:
        obj.updated_by = user.id
    await db.flush()


async def list_intermediate_types_paged(
    db: AsyncSession,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[IntermediateType], int]:
    return await repo.list_intermediate_types(db, keyword, page, page_size)


async def _build_output_outs(
    db: AsyncSession,
    outputs: list[BatchIntermediateOutput],
) -> list[IntermediateOutputOut]:
    """将 ORM 产出记录组装为对外 schema，补全节点名、中间体名、批号。"""
    if not outputs:
        return []
    node_ids = list({o.node_id for o in outputs})
    nodes = await repo.get_nodes_by_ids(db, node_ids)
    node_name_map = {n.id: n.name for n in nodes}
    types = await repo.list_intermediate_types_all(db)
    type_name_map = {t.id: t.name for t in types}
    batch_ids = list({o.batch_id for o in outputs})
    batches = await repo.get_batches_by_ids(db, batch_ids)
    batch_no_map = {b.id: b.batch_no for b in batches}
    result = []
    for o in outputs:
        result.append(
            IntermediateOutputOut(
                id=o.id,
                batch_id=o.batch_id,
                batch_no=batch_no_map.get(o.batch_id),
                execution_id=o.execution_id,
                node_id=o.node_id,
                node_name=node_name_map.get(o.node_id),
                intermediate_type_id=o.intermediate_type_id,
                intermediate_type_name=type_name_map.get(o.intermediate_type_id),
                intermediate_batch_no=o.intermediate_batch_no,
                quantity=o.quantity,
                unit=o.unit,
                is_product=o.is_product,
                remark=o.remark,
                created_at=o.created_at,
            )
        )
    return result


async def get_batch_outputs(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[IntermediateOutputOut]:
    outputs = await repo.get_intermediate_outputs_by_batch(db, batch_id)
    return await _build_output_outs(db, outputs)


async def get_batch_consumptions(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[IntermediateConsumptionOut]:
    """批次中间体消耗列表，补全来源批号等。"""
    consumptions = await repo.get_intermediate_consumptions_by_batch(db, batch_id)
    if not consumptions:
        return []
    node_ids = list({c.node_id for c in consumptions})
    nodes = await repo.get_nodes_by_ids(db, node_ids)
    node_name_map = {n.id: n.name for n in nodes}
    types = await repo.list_intermediate_types_all(db)
    type_name_map = {t.id: t.name for t in types}
    output_ids = list({c.output_id for c in consumptions})
    # 批量查产出记录以获取来源批号
    gathered: list[BatchIntermediateOutput] = []
    for oid in output_ids:
        out = await repo.get_intermediate_output(db, oid)
        if out:
            gathered.append(out)
    output_batch_map: dict[uuid.UUID, str | None] = {
        o.id: o.intermediate_batch_no for o in gathered
    }
    batch_ids = list({c.batch_id for c in consumptions})
    batches = await repo.get_batches_by_ids(db, batch_ids)
    batch_no_map = {b.id: b.batch_no for b in batches}
    result = []
    for c in consumptions:
        result.append(
            IntermediateConsumptionOut(
                id=c.id,
                batch_id=c.batch_id,
                batch_no=batch_no_map.get(c.batch_id),
                execution_id=c.execution_id,
                node_id=c.node_id,
                node_name=node_name_map.get(c.node_id),
                intermediate_type_id=c.intermediate_type_id,
                intermediate_type_name=type_name_map.get(c.intermediate_type_id),
                output_id=c.output_id,
                output_batch_no=output_batch_map.get(c.output_id),
                quantity=c.quantity,
                unit=c.unit,
                remark=c.remark,
                created_at=c.created_at,
            )
        )
    return result


async def trace_intermediate_output(
    db: AsyncSession, output_id: uuid.UUID
) -> dict[str, Any]:
    """中间体物料流向：产出记录 + 下游消耗记录。"""
    output = await repo.get_intermediate_output(db, output_id)
    if not output:
        raise NotFoundException("中间体产出记录", str(output_id))
    output_out = (await _build_output_outs(db, [output]))[0]
    consumptions = await repo.get_consumptions_by_output(db, output_id)
    cons_outs = []
    if consumptions:
        node_ids = list({c.node_id for c in consumptions})
        nodes = await repo.get_nodes_by_ids(db, node_ids)
        node_name_map = {n.id: n.name for n in nodes}
        types = await repo.list_intermediate_types_all(db)
        type_name_map = {t.id: t.name for t in types}
        batch_ids = list({c.batch_id for c in consumptions})
        batches = await repo.get_batches_by_ids(db, batch_ids)
        batch_no_map = {b.id: b.batch_no for b in batches}
        for c in consumptions:
            cons_outs.append(
                IntermediateConsumptionOut(
                    id=c.id,
                    batch_id=c.batch_id,
                    batch_no=batch_no_map.get(c.batch_id),
                    execution_id=c.execution_id,
                    node_id=c.node_id,
                    node_name=node_name_map.get(c.node_id),
                    intermediate_type_id=c.intermediate_type_id,
                    intermediate_type_name=type_name_map.get(c.intermediate_type_id),
                    output_id=c.output_id,
                    output_batch_no=output.intermediate_batch_no,
                    quantity=c.quantity,
                    unit=c.unit,
                    remark=c.remark,
                    created_at=c.created_at,
                )
            )
    return {"output": output_out, "consumptions": cons_outs}
