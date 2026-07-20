"""中间体字典 CRUD + 批次台账查询组装 + 产出物出入库流水。"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.production import repository as repo
from app.modules.production.models.intermediate import (
    BatchIntermediateOutput,
    IntermediateType,
)
from app.modules.production.schemas.intermediate import (
    IntermediateConsumptionOut,
    IntermediateOutputOut,
    IntermediateTypeCreate,
    IntermediateTypeOut,
    IntermediateTypeUpdate,
    MaterialMovement,
    MaterialMovementsOut,
    MaterialStockSummary,
)
from app.platform.identity.models import User


async def create_intermediate_type(
    db: AsyncSession,
    payload: IntermediateTypeCreate,
    user: User | None,
) -> IntermediateTypeOut:
    """创建中间体字典条目，检查 code 唯一。"""
    existing = await repo.get_intermediate_type_by_code(db, payload.code)
    if existing:
        raise DuplicateException("中间体编码", payload.code)
    if payload.product_id:
        product = await repo.get_product(db, payload.product_id)
        if not product:
            raise NotFoundException("产品", str(payload.product_id))
    obj = IntermediateType(
        code=payload.code,
        name=payload.name,
        category=payload.category,
        default_unit=payload.default_unit,
        description=payload.description,
        is_product=payload.is_product,
        product_id=payload.product_id,
        created_by=user.id if user else None,
    )
    db.add(obj)
    await db.flush()
    # INSERT: RETURNING 自动回填 id/created_at/updated_at，无需 re-fetch
    return await _build_material_out(db, obj)


async def update_intermediate_type(
    db: AsyncSession,
    type_id: uuid.UUID,
    payload: IntermediateTypeUpdate,
    user: User | None,
) -> IntermediateTypeOut:
    """编辑中间体，仅更新显式传入的字段（null 值可清空可空字段）。"""
    obj = await repo.get_intermediate_type(db, type_id)
    if not obj:
        raise NotFoundException("中间体", str(type_id))
    non_nullable_fields = {"name"}
    for field_name, val in payload.model_dump(exclude_unset=True).items():
        if val is None and field_name in non_nullable_fields:
            continue  # 不允许将非空字段设为 None，保持旧值
        setattr(obj, field_name, val)
    if user:
        obj.updated_by = user.id
    # 校验最终状态：is_product=True 必须关联 product_id（防止仅更新 product_id=None 时绕过）
    if obj.is_product and not obj.product_id:
        raise AppException(status_code=400, message="标记为成品时必须关联产品")
    if obj.product_id:
        product = await repo.get_product(db, obj.product_id)
        if not product:
            raise NotFoundException("产品", str(obj.product_id))
    await db.flush()
    # UPDATE 后 re-fetch，确保 server default 同步
    refreshed = await repo.get_intermediate_type(db, type_id)
    assert refreshed is not None
    return await _build_material_out(db, refreshed)


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


async def get_intermediate_type_detail(
    db: AsyncSession, type_id: uuid.UUID
) -> IntermediateTypeOut:
    """查询中间体详情（含 product_name）。"""
    obj = await repo.get_intermediate_type(db, type_id)
    if not obj:
        raise NotFoundException("中间体", str(type_id))
    return await _build_material_out(db, obj)


async def _build_material_out(
    db: AsyncSession,
    obj: IntermediateType,
    *,
    product_name: str | None = None,
) -> IntermediateTypeOut:
    """组装 IntermediateTypeOut，补全 product_name。"""
    # ponytail: from_attributes + single patch, beats 12-line manual constructor
    out = IntermediateTypeOut.model_validate(obj)
    if product_name is not None:
        out.product_name = product_name
    elif obj.product_id:
        product = await repo.get_product(db, obj.product_id)
        if product:
            out.product_name = product.product_name
    return out


async def list_intermediate_types_paged(
    db: AsyncSession,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[IntermediateTypeOut], int]:
    items, total = await repo.list_intermediate_types(db, keyword, page, page_size)
    # 批量查询关联产品名，避免 N+1
    product_ids = [i.product_id for i in items if i.product_id]
    product_name_map: dict[uuid.UUID, str] = {}
    if product_ids:
        products = await repo.get_products_by_ids(db, product_ids)
        product_name_map = {p.id: p.product_name for p in products}
    outs = []
    for item in items:
        pn: str | None = None
        if item.product_id:
            pn = product_name_map.get(item.product_id)
        outs.append(await _build_material_out(db, item, product_name=pn))
    return outs, total


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
    type_ids = list({o.intermediate_type_id for o in outputs})
    types = await repo.get_intermediate_types_by_ids(db, type_ids)
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


async def get_available_outputs(
    db: AsyncSession,
    intermediate_type_id: uuid.UUID | None = None,
) -> list[IntermediateOutputOut]:
    """所有批次的中间体产出（可选按类型过滤），用于消耗时选择上游产出。"""
    outputs = await repo.get_available_outputs(db, intermediate_type_id)
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
    type_ids = list({c.intermediate_type_id for c in consumptions})
    types = await repo.get_intermediate_types_by_ids(db, type_ids)
    type_name_map = {t.id: t.name for t in types}
    output_ids = list({c.output_id for c in consumptions})
    outputs_map = {o.id: o for o in await repo.get_intermediate_outputs_by_ids(db, output_ids)}
    output_batch_map: dict[uuid.UUID, str | None] = {
        oid: o.intermediate_batch_no for oid, o in outputs_map.items()
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
        type_ids = list({c.intermediate_type_id for c in consumptions})
        types = await repo.get_intermediate_types_by_ids(db, type_ids)
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


# ── 产出物出入库流水 ──

async def get_material_movements(
    db: AsyncSession, material_id: uuid.UUID, batch_no: str | None = None
) -> MaterialMovementsOut:
    """产出物维度的全局出入库流水 + 汇总，支持按产出批号筛选。"""
    obj = await repo.get_intermediate_type(db, material_id)
    if not obj:
        raise NotFoundException("产出物", str(material_id))

    material_out = await _build_material_out(db, obj)

    outputs = await repo.get_intermediate_outputs_by_type(db, material_id)
    consumptions = await repo.get_intermediate_consumptions_by_type(db, material_id)

    # 提前取消费关联的 source outputs，供批号过滤用
    source_output_ids = [c.output_id for c in consumptions]
    source_outputs_map = {o.id: o for o in await repo.get_intermediate_outputs_by_ids(db, source_output_ids)}

    # 按批号过滤
    if batch_no:
        keyword = batch_no.strip()
        outputs = [o for o in outputs if o.intermediate_batch_no and keyword in o.intermediate_batch_no]
        consumptions = [
            c for c in consumptions
            if (src := source_outputs_map.get(c.output_id))
            and src.intermediate_batch_no
            and keyword in src.intermediate_batch_no
        ]

    node_ids = list({o.node_id for o in outputs} | {c.node_id for c in consumptions})
    nodes = await repo.get_nodes_by_ids(db, node_ids)
    node_name_map = {n.id: n.name for n in nodes}

    batch_ids = list({o.batch_id for o in outputs} | {c.batch_id for c in consumptions})
    batches = await repo.get_batches_by_ids(db, batch_ids)
    batch_no_map = {b.id: b.batch_no for b in batches}

    movements: list[MaterialMovement] = []

    total_output = 0.0
    for o in outputs:
        total_output += o.quantity
        movements.append(
            MaterialMovement(
                type="output",
                batch_id=o.batch_id,
                batch_no=batch_no_map.get(o.batch_id),
                node_name=node_name_map.get(o.node_id),
                quantity=o.quantity,
                unit=o.unit,
                intermediate_batch_no=o.intermediate_batch_no,
                created_at=o.created_at,
            )
        )

    total_consumed = 0.0
    for c in consumptions:
        total_consumed += c.quantity
        src = source_outputs_map.get(c.output_id)
        movements.append(
            MaterialMovement(
                type="consumption",
                batch_id=c.batch_id,
                batch_no=batch_no_map.get(c.batch_id),
                node_name=node_name_map.get(c.node_id),
                quantity=c.quantity,
                unit=c.unit,
                source_batch_no=src.intermediate_batch_no if src else None,
                source_output_id=c.output_id,
                created_at=c.created_at,
            )
        )

    movements.sort(key=lambda m: m.created_at, reverse=True)

    summary = MaterialStockSummary(
        total_output=total_output,
        total_consumed=total_consumed,
        current_stock=total_output - total_consumed,
    )

    return MaterialMovementsOut(
        material=material_out,
        movements=movements,
        summary=summary,
    )
