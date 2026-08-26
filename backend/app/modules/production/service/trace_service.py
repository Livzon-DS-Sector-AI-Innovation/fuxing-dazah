"""全链路溯源：沿 batch_links 双向递归（谱系），叠加跨路线物料链。

谱系边（link_type="lineage"）来自同路线 derive/merge 的 batch_links；
物料边（link_type="material"）来自跨路线投料消耗的精确模式引用：
parent = 产出批次（上游），child = 消耗批次（下游），与谱系边方向语义一致。

物料链范围：
- 投料来源（up）：从目标批次沿物料链递归上溯（A→B→C），深度上限 + 防环；
- 物料去向（down）：仅目标批次自身一跳（谁消耗了"我"的产出），不递归；
- 物料命中的批次只展示批次本身，不展开其谱系家族 —— 谱系始终只按
  目标批次的前后序展开，避免无关分支（如去向批次的其他前序）混入溯源图。
混装容器消耗（无 output_id）是刻意的溯源断点，不产生物料边。
"""

import uuid
from typing import Any

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.production import repository as repo
from app.modules.production.schemas import (
    TraceBatch,
    TraceExecutionBrief,
    TraceLink,
    TraceOut,
)

# 物料链递归深度上限（防环之外的双保险，与谱系 CTE 深度 20 相呼应）
_MAX_MATERIAL_DEPTH = 10


async def get_trace(db: AsyncSession, batch_id: uuid.UUID) -> TraceOut:
    root = await repo.get_batch(db, batch_id)
    if not root:
        raise NotFoundException("批次", str(batch_id))

    # ── 谱系边：目标批次自身双向递归 ──
    lineage_rows: list[Row[Any]] = [
        *await repo.trace_links(db, batch_id, "up"),
        *await repo.trace_links(db, batch_id, "down"),
    ]
    batch_ids: set[uuid.UUID] = {batch_id}
    for row in lineage_rows:
        batch_ids.add(row.parent_batch_id)
        batch_ids.add(row.child_batch_id)

    # ── 物料去向：仅目标批次自身一跳（谁消耗了我的产出），不递归 ──
    material_rows: list[Row[Any]] = []
    down_rows = await repo.get_material_links_by_batches(db, {batch_id}, "down")
    material_rows.extend(down_rows)
    destinations = {r.child_batch_id for r in down_rows} - batch_ids
    batch_ids |= destinations

    # ── 投料来源链：从目标批次沿物料链递归上溯（A→B→C），带深度上限与防环。
    # 物料命中的批次只展示批次本身，不并入其谱系家族：谱系仍只按目标批次的
    # 前后序展开，避免无关分支（去向批次的其他前序、来源批次的其他分支）
    # 混入溯源图。需要看某个命中批次的谱系时，前端点击该节点以其为根重新溯源 ──
    frontier = {batch_id}
    for _ in range(_MAX_MATERIAL_DEPTH):
        up_rows = await repo.get_material_links_by_batches(db, frontier, "up")
        material_rows.extend(up_rows)
        new_producers = {r.parent_batch_id for r in up_rows} - batch_ids
        if not new_producers:
            break
        batch_ids |= new_producers
        frontier = new_producers

    # ── 谱系边去重（多根共享祖先/后代时 CTE 会按根重复）──
    lineage_by_pair: dict[tuple[uuid.UUID, uuid.UUID], Row[Any]] = {}
    for row in lineage_rows:
        pair = (row.parent_batch_id, row.child_batch_id)
        if pair not in lineage_by_pair:
            lineage_by_pair[pair] = row

    # ── 物料行去重（同一消耗行会被 up/down 双向发现）后按批次对聚合 ──
    unique_material: dict[uuid.UUID, Row[Any]] = {
        row.consumption_id: row for row in material_rows
    }
    material_by_key: dict[
        tuple[uuid.UUID, uuid.UUID, uuid.UUID, str | None], dict[str, Any]
    ] = {}
    for row in unique_material.values():
        key = (
            row.parent_batch_id,
            row.child_batch_id,
            row.intermediate_type_id,
            row.intermediate_batch_no,
        )
        agg = material_by_key.setdefault(
            key,
            {
                "parent_batch_id": row.parent_batch_id,
                "child_batch_id": row.child_batch_id,
                "intermediate_type_id": row.intermediate_type_id,
                "intermediate_batch_no": row.intermediate_batch_no,
                "quantity": 0.0,
                "unit": row.unit,
            },
        )
        agg["quantity"] += row.quantity or 0.0
        if not agg["unit"] and row.unit:
            agg["unit"] = row.unit

    # ── 批量加载展示数据 ──
    batches = await repo.get_batches_by_ids(db, sorted(batch_ids))
    batch_map = {b.id: b for b in batches}
    executions = await repo.list_executions_by_batches(db, sorted(batch_ids))
    exec_ids = [e.id for e in executions]
    values = await repo.get_field_values_by_executions(db, exec_ids)
    nodes = await repo.get_nodes_by_ids(db, list({e.node_id for e in executions}))
    node_names = {n.id: n.name for n in nodes}
    node_stages = {n.id: n.stage_name for n in nodes}

    product_ids = {b.product_id for b in batches}
    products = await repo.get_products_by_ids(db, sorted(product_ids))
    product_names = {p.id: p.product_name for p in products}

    type_ids = {row.intermediate_type_id for row in material_rows}
    type_name_map: dict[uuid.UUID, str] = {}
    if type_ids:
        types = await repo.get_intermediate_types_by_ids(
            db, sorted(type_ids), include_deleted=True,
        )
        type_name_map = {t.id: t.name for t in types}

    # 每批最新 execution 所在节点 → 当前工段
    batch_latest_node: dict[uuid.UUID, uuid.UUID] = {}
    for e in sorted(executions, key=lambda x: x.started_at):
        batch_latest_node[e.batch_id] = e.node_id
    batch_stages = {bid: node_stages.get(nid) for bid, nid in batch_latest_node.items()}

    abnormal_by_exec: dict[uuid.UUID, int] = {}
    for v in values:
        if v.is_abnormal:
            abnormal_by_exec[v.execution_id] = abnormal_by_exec.get(v.execution_id, 0) + 1

    briefs_by_batch: dict[uuid.UUID, list[TraceExecutionBrief]] = {}
    for e in executions:
        briefs_by_batch.setdefault(e.batch_id, []).append(
            TraceExecutionBrief(
                node_name=node_names.get(e.node_id, ""),
                status=e.status,
                owner_name=e.owner_name,
                started_at=e.started_at,
                finished_at=e.finished_at,
                is_deviation=e.is_deviation,
                abnormal_count=abnormal_by_exec.get(e.id, 0),
            )
        )

    trace_batches = [
        TraceBatch(
            id=b.id,
            batch_no=b.batch_no,
            product_id=b.product_id,
            product_name=product_names.get(b.product_id),
            status=b.status,
            quantity=b.quantity,
            unit=b.unit,
            current_stage_name=batch_stages.get(b.id),
            executions=briefs_by_batch.get(b.id, []),
        )
        for b in batches
    ]

    # ── 组装边：端点批次已软删的边过滤掉，保证前端图一致 ──
    links: list[TraceLink] = []
    for (parent_id, child_id), row in lineage_by_pair.items():
        if parent_id not in batch_map or child_id not in batch_map:
            continue
        links.append(
            TraceLink(
                parent_batch_id=parent_id,
                child_batch_id=child_id,
                link_type="lineage",
                edge_id=row.edge_id,
                allocated_qty=row.allocated_qty,
                is_deviation=row.is_deviation,
            )
        )
    for agg in material_by_key.values():
        parent_id, child_id = agg["parent_batch_id"], agg["child_batch_id"]
        if parent_id not in batch_map or child_id not in batch_map:
            continue
        type_id: uuid.UUID = agg["intermediate_type_id"]
        links.append(
            TraceLink(
                parent_batch_id=parent_id,
                child_batch_id=child_id,
                link_type="material",
                intermediate_type_id=type_id,
                intermediate_type_name=type_name_map.get(type_id),
                intermediate_batch_no=agg["intermediate_batch_no"],
                quantity=agg["quantity"],
                unit=agg["unit"],
            )
        )

    return TraceOut(root_batch_id=batch_id, batches=trace_batches, links=links)
