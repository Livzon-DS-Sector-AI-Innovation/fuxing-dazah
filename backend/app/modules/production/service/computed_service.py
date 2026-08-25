"""计算字段动态展开与批次谱系聚合（查询时计算，不物化）。"""

import uuid
from collections import deque
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch, NodeExecution
from app.modules.production.models.route import RouteComputedField
from app.modules.production.repository import batch as batch_repo
from app.modules.production.repository import execution as exec_repo
from app.modules.production.repository import route as route_repo
from app.modules.production.repository.trace import trace_links
from app.modules.production.schemas.batch import ComputedFieldValueOut
from app.modules.production.service.formula import evaluate, extract_refs, parse_formula


@dataclass
class _RouteContext:
    """单路线的计算字段展开上下文（定义与拓扑序，多批次共享）。"""

    by_key: dict[str, RouteComputedField]
    node_id_by_code: dict[str, uuid.UUID]
    code_by_id: dict[uuid.UUID, str]
    order: list[str]


def _topo_sort(deps: dict[str, set[str]]) -> list[str]:
    """Kahn 拓扑排序（O(V+E)）；无环时返回全部键。"""
    indegree = {k: len(v) for k, v in deps.items()}
    dependents: dict[str, list[str]] = {k: [] for k in deps}
    for k, dset in deps.items():
        for dep in dset:
            dependents[dep].append(k)
    queue = deque(k for k, d in indegree.items() if d == 0)
    order: list[str] = []
    while queue:
        k = queue.popleft()
        order.append(k)
        for other in dependents[k]:
            indegree[other] -= 1
            if indegree[other] == 0:
                queue.append(other)
    order.extend(k for k in indegree if k not in order)  # 防御：保存时已校验无环
    return order


async def _resolve_field_values(
    db: AsyncSession,
    refs_by_batch: dict[uuid.UUID, set[tuple[uuid.UUID, str]]],
    *,
    allow_ancestor_fallback: bool = True,
) -> dict[uuid.UUID, dict[tuple[uuid.UUID, str], float | None]]:
    """批量取 (batch, node_id, field_key) 引用值：本批最后 completed 执行，缺失沿谱系向父批次逐级找。

    执行查询按谱系内批次限定（本批 + 被 trace 的祖先），避免全量历史扫描；
    字段值只取最终命中的执行，一次查询。每个批次最多 trace 一次父链。
    allow_ancestor_fallback=False 时只取本批自身执行（用于子批次求和等聚合口径）。
    """
    all_node_ids = sorted({nid for refs in refs_by_batch.values() for nid, _ in refs})
    if not all_node_ids:
        return {}

    latest: dict[tuple[uuid.UUID, uuid.UUID], NodeExecution] = {}

    # 一次性加载全部相关批次（本批）的执行；祖先批次在缺失时按需补载
    rows = await exec_repo.list_completed_executions_by_nodes(
        db, all_node_ids, batch_ids=sorted(refs_by_batch.keys()),
    )
    latest.update(exec_repo.group_latest_completed_by_batch_node(rows))
    loaded_batch_ids: set[uuid.UUID] = set(refs_by_batch.keys())

    async def _load_batch(batch_id: uuid.UUID) -> None:
        if batch_id in loaded_batch_ids:
            return
        loaded_batch_ids.add(batch_id)
        rows = await exec_repo.list_completed_executions_by_nodes(
            db, all_node_ids, batch_ids=[batch_id],
        )
        latest.update(exec_repo.group_latest_completed_by_batch_node(rows))

    ancestors_cache: dict[uuid.UUID, list[uuid.UUID]] = {}

    async def _ancestors(batch_id: uuid.UUID) -> list[uuid.UUID]:
        if batch_id not in ancestors_cache:
            links = await trace_links(db, batch_id, "up")
            ancestors_cache[batch_id] = [row.parent_batch_id for row in links]
        return ancestors_cache[batch_id]

    # 第 1 遍：为每个引用确定取数执行（本批或祖先）
    exec_by_ref: dict[tuple[uuid.UUID, tuple[uuid.UUID, str]], uuid.UUID | None] = {}
    for batch_id, refs in refs_by_batch.items():
        await _load_batch(batch_id)
        for nid, fk in refs:
            e = latest.get((batch_id, nid))
            if e is not None:
                exec_by_ref[(batch_id, (nid, fk))] = e.id
                continue
            found: uuid.UUID | None = None
            if allow_ancestor_fallback:
                for parent_id in await _ancestors(batch_id):
                    await _load_batch(parent_id)
                    e = latest.get((parent_id, nid))
                    if e is not None:
                        found = e.id
                        break
            exec_by_ref[(batch_id, (nid, fk))] = found

    # 第 2 遍：一次查询全部命中的字段值
    exec_ids = sorted({eid for eid in exec_by_ref.values() if eid is not None})
    value_by_exec: dict[tuple[uuid.UUID, str], float | None] = {}
    for v in await exec_repo.get_field_values_by_executions(db, exec_ids):
        value_by_exec[(v.execution_id, v.field_key)] = v.value_numeric

    resolved: dict[uuid.UUID, dict[tuple[uuid.UUID, str], float | None]] = {}
    for batch_id, refs in refs_by_batch.items():
        resolved[batch_id] = {
            (nid, fk): (
                value_by_exec.get((eid, fk))
                if (eid := exec_by_ref[(batch_id, (nid, fk))]) is not None
                else None
            )
            for nid, fk in refs
        }
    return resolved


async def expand_computed_fields_for_batches(
    db: AsyncSession,
    batches: list[Batch],
    *,
    allow_ancestor_fallback: bool = True,
) -> dict[uuid.UUID, list[ComputedFieldValueOut]]:
    """批量展开多批次的全部计算字段，返回 {batch_id: [计算字段值]}（拓扑序）。

    与单批次取数口径一致：引用值取本批次最后 completed 执行，缺失沿谱系向父批次找。
    allow_ancestor_fallback=False 时只取本批自身执行（聚合求和口径，防止父批值计入）。
    """
    if not batches:
        return {}

    # 路线级定义每路线只查一次
    contexts: dict[uuid.UUID, _RouteContext] = {}
    for route_id in {b.route_id for b in batches}:
        fields = await route_repo.get_computed_fields_by_route(db, route_id)
        if not fields:
            continue
        nodes = await route_repo.get_route_nodes(db, route_id)
        by_key = {f.field_key: f for f in fields}
        deps = {
            f.field_key: {ref_key for _code, ref_key in extract_refs(f.formula) if ref_key in by_key}
            for f in fields
        }
        contexts[route_id] = _RouteContext(
            by_key=by_key,
            node_id_by_code={n.node_code: n.id for n in nodes},
            code_by_id={n.id: n.node_code for n in nodes},
            order=_topo_sort(deps),
        )

    # 收集全部字段引用（计算字段间引用走内存 values 链，无需取数）
    refs_by_batch: dict[uuid.UUID, set[tuple[uuid.UUID, str]]] = {}
    for b in batches:
        ctx = contexts.get(b.route_id)
        if ctx is None:
            continue
        refs: set[tuple[uuid.UUID, str]] = set()
        for f in ctx.by_key.values():
            for code, ref_key in extract_refs(f.formula):
                if ref_key in ctx.by_key:
                    continue
                node_id = ctx.node_id_by_code.get(code)
                if node_id is not None:
                    refs.add((node_id, ref_key))
        if refs:
            refs_by_batch[b.id] = refs

    resolved = await _resolve_field_values(
        db, refs_by_batch, allow_ancestor_fallback=allow_ancestor_fallback,
    )

    results: dict[uuid.UUID, list[ComputedFieldValueOut]] = {}
    for b in batches:
        ctx = contexts.get(b.route_id)
        if ctx is None:
            results[b.id] = []
            continue
        values: dict[tuple[str, str], float | None] = {
            (ctx.code_by_id[nid], fk): v
            for (nid, fk), v in resolved.get(b.id, {}).items()
        }
        outs: list[ComputedFieldValueOut] = []
        for key in ctx.order:
            f = ctx.by_key[key]
            v = evaluate(parse_formula(f.formula), values)
            values[(ctx.code_by_id[f.node_id], key)] = v  # 供链式引用取值
            outs.append(
                ComputedFieldValueOut(
                    field_key=f.field_key, field_label=f.field_label, unit=f.unit, value=v
                )
            )
        results[b.id] = outs
    return results


async def expand_computed_fields(
    db: AsyncSession, batch: Batch
) -> list[ComputedFieldValueOut]:
    """展开批次的全部计算字段（拓扑序）。"""
    return (await expand_computed_fields_for_batches(db, [batch]))[batch.id]


async def get_descendant_batch_ids(db: AsyncSession, batch_id: uuid.UUID) -> list[uuid.UUID]:
    """全部后代批次 id（含多级，去重）。"""
    rows = await trace_links(db, batch_id, "down")
    return list({row.child_batch_id for row in rows})


async def aggregate_children_field(
    db: AsyncSession,
    batch_id: uuid.UUID,
    field_key: str,
    node_code: str | None,
) -> float | None:
    """沿谱系对所有子批次某字段求和。node_code 为空表示计算字段。

    缺失值跳过；无子批次或无任何值返回 None。
    求和口径只取子批自身执行的值，不回退祖先——否则父批（本批）的值会
    按缺失子批数量重复计入合计。
    """
    child_ids = await get_descendant_batch_ids(db, batch_id)
    if not child_ids:
        return None
    batches = await batch_repo.get_batches_by_ids(db, child_ids)
    total: float | None = None
    if node_code is None:
        for items in (
            await expand_computed_fields_for_batches(
                db, batches, allow_ancestor_fallback=False,
            )
        ).values():
            for item in items:
                if item.field_key == field_key and item.value is not None:
                    total = item.value if total is None else total + item.value
        return total
    # 普通字段：子批该节点最后 completed 执行的值（只取子批自身执行）
    node_by_route: dict[uuid.UUID, uuid.UUID | None] = {}
    refs_by_batch: dict[uuid.UUID, set[tuple[uuid.UUID, str]]] = {}
    for child in batches:
        if child.route_id not in node_by_route:
            node = await route_repo.get_node_by_code(db, child.route_id, node_code)
            node_by_route[child.route_id] = node.id if node else None
        node_id = node_by_route[child.route_id]
        if node_id is not None:
            refs_by_batch[child.id] = {(node_id, field_key)}
    resolved = await _resolve_field_values(
        db, refs_by_batch, allow_ancestor_fallback=False,
    )
    for child in batches:
        node_id = node_by_route[child.route_id]
        if node_id is None:
            continue
        v = resolved.get(child.id, {}).get((node_id, field_key))
        if v is not None:
            total = v if total is None else total + v
    return total
