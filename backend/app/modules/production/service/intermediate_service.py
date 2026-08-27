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
    ContainerStockOut,
    IntermediateConsumptionOut,
    IntermediateOutputOut,
    IntermediateTypeCreate,
    IntermediateTypeOut,
    IntermediateTypeUpdate,
    MaterialMovement,
    MaterialMovementsOut,
    MaterialStockSummary,
    MixingContainerOut,
)
from app.modules.production.service.line_service import resolve_user_line_ids
from app.platform.identity.models import User


async def create_intermediate_type(
    db: AsyncSession,
    payload: IntermediateTypeCreate,
    user: User | None,
) -> IntermediateTypeOut:
    """创建中间体字典条目，检查 code 与 name 唯一。"""
    existing = await repo.get_intermediate_type_by_code(db, payload.code)
    if existing:
        raise DuplicateException("中间体编码", payload.code)
    existing_name = await repo.get_intermediate_type_by_name(db, payload.name)
    if existing_name:
        raise DuplicateException("中间体名称", payload.name)
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
    # 名称唯一性校验（排除自身）
    if payload.name is not None and payload.name != obj.name:
        existing_name = await repo.get_intermediate_type_by_name(db, payload.name)
        if existing_name:
            raise DuplicateException("中间体名称", payload.name)
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
    """软删除中间体字典条目。被未归档路线引用时拒绝删除。"""
    obj = await repo.get_intermediate_type(db, type_id)
    if not obj:
        raise NotFoundException("中间体", str(type_id))
    # 检查未归档路线引用
    ref_routes = await repo.get_non_archived_routes_by_intermediate_type(db, type_id)
    if ref_routes:
        names = "、".join(name for _, name in ref_routes)
        raise AppException(
            status_code=409,
            message=f"该产出物被 {len(ref_routes)} 条未归档工艺路线引用（{names}），请先归档或移除引用后再删除",
        )
    obj.is_deleted = True
    if user:
        obj.updated_by = user.id
    await db.flush()


async def get_intermediate_type_detail(
    db: AsyncSession, type_id: uuid.UUID
) -> IntermediateTypeOut:
    """查询中间体详情（含已删除，用于查看历史流水）。"""
    obj = await repo.get_intermediate_type(db, type_id, include_deleted=True)
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
    *,
    include_deleted: bool = False,
    product_id: uuid.UUID | None = None,
) -> tuple[list[IntermediateTypeOut], int]:
    """分页查询中间体类型，批量补全 product_name。"""
    items, total = await repo.list_intermediate_types(
        db, keyword, page, page_size, include_deleted=include_deleted,
        product_id=product_id,
    )
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


async def _line_name_map(
    db: AsyncSession, line_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """批量查产线名（含已删除产线，历史产出名展示用）。"""
    lines = await repo.get_lines_by_ids(db, line_ids, include_deleted=True)
    return {ln.id: ln.name for ln in lines}


async def _build_output_outs(
    db: AsyncSession,
    outputs: list[BatchIntermediateOutput],
) -> list[IntermediateOutputOut]:
    """将 ORM 产出记录组装为对外 schema，补全节点名、中间体名、批号、产线名。"""
    if not outputs:
        return []
    node_ids = list({o.node_id for o in outputs})
    nodes = await repo.get_nodes_by_ids(db, node_ids)
    node_name_map = {n.id: n.name for n in nodes}
    type_ids = list({o.intermediate_type_id for o in outputs})
    types = await repo.get_intermediate_types_by_ids(db, type_ids, include_deleted=True)
    type_name_map = {t.id: t.name for t in types}
    batch_ids = list({o.batch_id for o in outputs})
    batches = await repo.get_batches_by_ids(db, batch_ids)
    batch_no_map = {b.id: b.batch_no for b in batches}
    container_ids = list({o.container_id for o in outputs if o.container_id})
    containers = await repo.get_mixing_containers_by_ids(db, container_ids)
    container_name_map = {ct.id: ct.name for ct in containers}
    # 产线名 join 必须含已软删产线，保证历史流水仍显示名称
    line_name_map = await _line_name_map(
        db, [o.line_id for o in outputs if o.line_id],
    )
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
                line_id=o.line_id,
                line_name=line_name_map.get(o.line_id) if o.line_id else None,
                container_id=o.container_id,
                container_name=container_name_map.get(o.container_id) if o.container_id else None,
            )
        )
    return result


async def get_batch_outputs(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[IntermediateOutputOut]:
    outputs = await repo.get_intermediate_outputs_by_batch(db, batch_id)
    return await _build_output_outs(db, outputs)


async def get_available_containers(
    db: AsyncSession,
    intermediate_type_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> list[MixingContainerOut]:
    """可用混装容器列表（消耗时选择），按操作人产线可见性过滤，带当前余量。

    产线可见性与消耗/产出校验一致：操作人绑定 → 批次负责人绑定兜底 → 皆无则空。
    """
    from app.modules.production.service.container_service import list_containers

    outs = await list_containers(db, intermediate_type_id)
    if not user_id:
        return outs
    owner_user_id: uuid.UUID | None = None
    if batch_id:
        batch = await repo.get_batch(db, batch_id)
        if batch:
            owner_user_id = batch.owner_user_id
    line_ids = set(await resolve_user_line_ids(db, user_id, owner_user_id))
    return [o for o in outs if o.line_id in line_ids]


async def get_consumed_quantity_map(
    db: AsyncSession, output_ids: list[uuid.UUID],
) -> dict[uuid.UUID, float]:
    """产出余量消耗汇总：按 output_id 累加历史消耗量。

    供余量校验（start_execution 硬拦截）与展示（get_available_outputs 限值）共用，
    保证两处口径一致。
    """
    consumed_map: dict[uuid.UUID, float] = {}
    for c in await repo.get_consumptions_by_outputs(db, output_ids):
        assert c.output_id is not None  # 查询按 output_id IN 过滤，恒非空
        consumed_map[c.output_id] = consumed_map.get(c.output_id, 0.0) + c.quantity
    return consumed_map


async def get_available_outputs(
    db: AsyncSession,
    intermediate_type_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
) -> list[IntermediateOutputOut]:
    """所有批次的中间体产出（按类型/产线可见性过滤），用于消耗时选择上游产出。

    可见性规则：操作人绑定产线 → 该产线集合的产出；操作人未绑定 → 用批次负责人的
    绑定兜底；两者皆无 → 仅无产线产出（过渡期存量在制品）。
    None 产线的历史产出对已绑定用户始终可见（过渡期兼容）。
    余量过滤已在 SQL 层完成（排除已中止执行），limit 窗口内全部有可用余量。
    """
    line_ids: list[uuid.UUID] | None = None
    if user_id:
        owner_user_id: uuid.UUID | None = None
        if batch_id:
            batch = await repo.get_batch(db, batch_id)
            owner_user_id = batch.owner_user_id if batch else None
        line_ids = await resolve_user_line_ids(db, user_id, owner_user_id)
    outputs = await repo.get_available_outputs(
        db, intermediate_type_id, line_ids,
        include_null_line=True,
    )
    outs = await _build_output_outs(db, outputs)
    # 余量：产出数量 - 历史已消耗（供消耗下拉展示与前端限值）
    consumed_map = await get_consumed_quantity_map(db, [o.id for o in outputs])
    for out in outs:
        out.available_quantity = round(
            out.quantity - consumed_map.get(out.id, 0.0), 6,
        )
    # 余量为 0 的批次不再出现在消耗下拉（用户要求）
    return [out for out in outs if (out.available_quantity or 0) > 0]


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
    types = await repo.get_intermediate_types_by_ids(db, type_ids, include_deleted=True)
    type_name_map = {t.id: t.name for t in types}
    output_ids = list({c.output_id for c in consumptions if c.output_id is not None})
    outputs_map = {o.id: o for o in await repo.get_intermediate_outputs_by_ids(db, output_ids)}
    output_batch_map: dict[uuid.UUID, str | None] = {
        oid: o.intermediate_batch_no for oid, o in outputs_map.items()
    }
    # 消耗行的产线 = 所消耗产出的产线（join 来源产出）
    line_name_map = await _line_name_map(
        db, [o.line_id for o in outputs_map.values() if o.line_id],
    )
    batch_ids = list({c.batch_id for c in consumptions})
    batches = await repo.get_batches_by_ids(db, batch_ids)
    batch_no_map = {b.id: b.batch_no for b in batches}
    container_ids = list({c.container_id for c in consumptions if c.container_id is not None})
    containers = await repo.get_mixing_containers_by_ids(db, container_ids)
    container_name_map = {ct.id: ct.name for ct in containers}
    result = []
    for c in consumptions:
        src = outputs_map.get(c.output_id) if c.output_id else None
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
                output_batch_no=output_batch_map.get(c.output_id) if c.output_id else None,
                container_id=c.container_id,
                container_name=container_name_map.get(c.container_id) if c.container_id else None,
                quantity=c.quantity,
                unit=c.unit,
                remark=c.remark,
                created_at=c.created_at,
                line_name=(
                    line_name_map.get(src.line_id)
                    if src and src.line_id else None
                ),
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
        types = await repo.get_intermediate_types_by_ids(db, type_ids, include_deleted=True)
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
                    line_name=output_out.line_name,
                )
            )
    return {"output": output_out, "consumptions": cons_outs}


# ── 产出物出入库流水 ──

async def get_material_movements(
    db: AsyncSession, material_id: uuid.UUID,
    batch_no: str | None = None, container_name: str | None = None,
) -> MaterialMovementsOut:
    """产出物维度的全局出入库流水 + 汇总。

    支持按产出批号筛选（精确模式）或按容器名筛选（混装模式），两者可组合（含已删除）。
    """
    obj = await repo.get_intermediate_type(db, material_id, include_deleted=True)
    if not obj:
        raise NotFoundException("产出物", str(material_id))

    material_out = await _build_material_out(db, obj)

    outputs = await repo.get_intermediate_outputs_by_type(db, material_id)
    consumptions = await repo.get_intermediate_consumptions_by_type(db, material_id)

    # 容器名映射：产出行自身容器 + 消耗行混装容器
    container_ids = list({
        o.container_id for o in outputs if o.container_id
    } | {
        c.container_id for c in consumptions if c.container_id
    })
    containers = await repo.get_mixing_containers_by_ids(db, container_ids)
    container_name_map = {ct.id: ct.name for ct in containers}
    container_id_by_name = {ct.name: ct.id for ct in containers}

    # 容器余量：各容器 Σ落入产出 − Σ未中止容器消耗（与消耗校验/容器列表口径一致，须在筛选前计算）
    container_stocks: list[ContainerStockOut] = []
    if containers:
        stock_consumptions = await repo.get_consumptions_by_container_ids(
            db, [ct.id for ct in containers], exclude_aborted=True,
        )
        stocks: dict[uuid.UUID, float] = {ct.id: 0.0 for ct in containers}
        for o in outputs:
            if o.container_id is not None and o.container_id in stocks:
                stocks[o.container_id] += o.quantity
        for c in stock_consumptions:
            assert c.container_id is not None  # 查询按 container_id IN 过滤
            stocks[c.container_id] -= c.quantity
        container_stocks = [
            ContainerStockOut(
                container_id=ct.id,
                container_name=ct.name,
                available_quantity=stocks[ct.id],
            )
            for ct in containers
        ]

    # 提前取消费关联的 source outputs，供批号过滤用
    source_output_ids = [c.output_id for c in consumptions if c.output_id is not None]
    source_outputs_map = {o.id: o for o in await repo.get_intermediate_outputs_by_ids(db, source_output_ids)}

    # 按批号过滤（精确模式行）
    if batch_no:
        keyword = batch_no.strip()
        outputs = [o for o in outputs if o.intermediate_batch_no and keyword in o.intermediate_batch_no]
        consumptions = [
            c for c in consumptions
            if c.output_id
            and (src := source_outputs_map.get(c.output_id))
            and src.intermediate_batch_no
            and keyword in src.intermediate_batch_no
        ]

    # 按容器名过滤（混装模式行）
    if container_name:
        keyword = container_name.strip()
        matched_ids = {
            ct_id for ct_name, ct_id in container_id_by_name.items()
            if keyword in ct_name
        }
        outputs = [o for o in outputs if o.container_id in matched_ids]
        consumptions = [c for c in consumptions if c.container_id in matched_ids]

    node_ids = list({o.node_id for o in outputs} | {c.node_id for c in consumptions})
    nodes = await repo.get_nodes_by_ids(db, node_ids)
    node_name_map = {n.id: n.name for n in nodes}

    batch_ids = list({o.batch_id for o in outputs} | {c.batch_id for c in consumptions})
    batches = await repo.get_batches_by_ids(db, batch_ids)
    batch_no_map = {b.id: b.batch_no for b in batches}

    # 产线名 join：产出行自身 line_id + 消耗行经来源产出 line_id + 容器产线
    line_name_map = await _line_name_map(
        db,
        [o.line_id for o in outputs if o.line_id]
        + [src.line_id for src in source_outputs_map.values() if src.line_id]
        + [ct.line_id for ct in containers],
    )

    movements: list[MaterialMovement] = []

    # 历史数据单位可能为空串，展示层用类型默认单位兜底
    fallback_unit = obj.default_unit or ""

    total_output = 0.0
    for o in outputs:
        total_output += o.quantity
        movements.append(
            MaterialMovement(
                id=o.id,
                type="output",
                batch_id=o.batch_id,
                batch_no=batch_no_map.get(o.batch_id),
                node_name=node_name_map.get(o.node_id),
                quantity=o.quantity,
                unit=o.unit or fallback_unit,
                intermediate_batch_no=o.intermediate_batch_no,
                container_name=container_name_map.get(o.container_id) if o.container_id else None,
                created_at=o.created_at,
                line_name=(
                    line_name_map.get(o.line_id)
                    if o.line_id else None
                ),
            )
        )

    container_by_id = {ct.id: ct for ct in containers}
    total_consumed = 0.0
    for c in consumptions:
        total_consumed += c.quantity
        src = source_outputs_map.get(c.output_id) if c.output_id else None
        # 产线名：精确消耗走来源产出产线，混装消耗走容器产线
        if src and src.line_id:
            line_name = line_name_map.get(src.line_id)
        elif c.container_id and c.container_id in container_by_id:
            line_name = line_name_map.get(container_by_id[c.container_id].line_id)
        else:
            line_name = None
        movements.append(
            MaterialMovement(
                id=c.id,
                type="consumption",
                batch_id=c.batch_id,
                batch_no=batch_no_map.get(c.batch_id),
                node_name=node_name_map.get(c.node_id),
                quantity=c.quantity,
                unit=c.unit or fallback_unit,
                source_batch_no=src.intermediate_batch_no if src else None,
                source_output_id=c.output_id,
                container_name=container_name_map.get(c.container_id) if c.container_id else None,
                created_at=c.created_at,
                line_name=line_name,
            )
        )

    movements.sort(key=lambda m: m.created_at, reverse=True)

    summary = MaterialStockSummary(
        total_output=total_output,
        total_consumed=total_consumed,
        current_stock=total_output - total_consumed,
        container_stocks=container_stocks,
    )

    return MaterialMovementsOut(
        material=material_out,
        movements=movements,
        summary=summary,
    )
