"""生产分析服务。"""

import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.time import APP_TZ, now
from app.modules.production import repository as repo
from app.modules.production.repository import assignment as assignment_repo
from app.modules.production.repository import batch as batch_repo
from app.modules.production.repository import execution as exec_repo
from app.modules.production.repository import route as route_repo
from app.modules.production.schemas.analytics import (
    FieldTrendPoint,
    FieldTrendResponse,
    FieldTrendSeries,
    StageSummaryColumn,
    StageSummaryOut,
    StageSummaryRow,
    StepCycleResponse,
    StepCycleStat,
)
from app.modules.production.service import computed_service, lineage_service
from app.modules.production.service.lineage_service import MergedFieldDef, NodeFamily

_MIN_SAMPLE_FOR_CONFIDENCE = 30


async def get_step_cycle_analytics(
    db: AsyncSession,
    *,
    route_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    days: int = 30,
) -> StepCycleResponse:
    """获取路线/产品的工序周期统计。"""
    since = now() - timedelta(days=days) if days > 0 else None

    rows = await repo.get_step_cycle_stats(
        db, route_id=route_id, product_id=product_id, since=since,
    )
    total_batches = await repo.count_active_batches(
        db, route_id=route_id, product_id=product_id, since=since,
    )

    steps = [
        StepCycleStat(
            node_id=r["node_id"],
            node_name=r["node_name"],
            stage_name=r["stage_name"],
            sort_order=r["sort_order"],
            n=r["n"],
            avg_hours=r["avg_hours"],
            min_hours=r["min_hours"],
            max_hours=r["max_hours"],
        )
        for r in rows
    ]

    min_n = min((s.n for s in steps), default=0)
    sample_note = None
    if min_n == 0:
        sample_note = "暂无数据"
    elif min_n < _MIN_SAMPLE_FOR_CONFIDENCE:
        sample_note = f"数据较少（最少工序仅 {min_n} 条记录），仅供参考"

    return StepCycleResponse(steps=steps, total_batches=total_batches, sample_note=sample_note)


async def get_field_trend(
    db: AsyncSession, route_id: uuid.UUID, node_code: str
) -> FieldTrendResponse:
    """跨批次字段趋势：某路线节点下全部数值字段的值，各字段内按填写时间升序。

    沿血缘链合并前身路线同工序（节点家族）的批次：origin 指针优先、
    node_code 兜底对齐；字段定义按家族归并（当前版本优先、旧版独有保留）。
    回流场景同批同节点有多条 completed 执行时取 finished_at 最新一条，
    与工段汇总/批次详情的取数口径保持一致；只返回至少有一个数据点的字段。
    """
    node = await repo.get_node_by_code(db, route_id, node_code)
    if node is None:
        return FieldTrendResponse(series=[], merged_routes=[])

    graph = await lineage_service.resolve_lineage(db, route_id)
    family = next(
        (f for f in (graph.families if graph else []) if f.rep.id == node.id), None,
    )
    if family is None:
        return FieldTrendResponse(series=[], merged_routes=[])
    merged_routes = graph.merged_route_names if graph else []

    numeric_defs = [
        d for d in graph.merged_defs.get(node.id, []) if d.data_type == "numeric"
    ]
    executions = await exec_repo.list_completed_executions_by_nodes(db, family.node_ids)
    latest_by_batch = exec_repo.group_latest_completed_by_batch_node(executions)
    if not numeric_defs or not latest_by_batch:
        return FieldTrendResponse(series=[], merged_routes=merged_routes)

    values = await exec_repo.get_field_values_by_executions(
        db, [e.id for e in latest_by_batch.values()]
    )
    batch_no_by_id = {
        b.id: b.batch_no
        for b in await batch_repo.get_batches_by_ids(
            db, sorted({e.batch_id for e in latest_by_batch.values()})
        )
    }
    batch_by_exec = {e.id: e.batch_id for e in latest_by_batch.values()}

    points_by_field: dict[str, list[FieldTrendPoint]] = {}
    for v in values:
        if v.value_numeric is None or v.filled_at is None:
            continue
        batch_no = batch_no_by_id.get(batch_by_exec.get(v.execution_id))
        if batch_no is None:
            continue
        points_by_field.setdefault(v.field_key, []).append(
            FieldTrendPoint(batch_no=batch_no, filled_at=v.filled_at, value=v.value_numeric)
        )

    series = [
        FieldTrendSeries(
            field_key=d.field_key,
            field_label=d.field_label,
            unit=d.unit,
            data_points=sorted(points_by_field[d.field_key], key=lambda p: p.filled_at),
        )
        for d in numeric_defs
        if d.field_key in points_by_field
    ]
    return FieldTrendResponse(series=series, merged_routes=merged_routes)


async def get_stage_summary(
    db: AsyncSession,
    stage_name: str | None,
    route_id: uuid.UUID | None,
    user_id: uuid.UUID,
    view_all: bool,
    start_date: date | None = None,
    end_date: date | None = None,
) -> StageSummaryOut:
    """工段汇总平铺矩阵：每批次一行，列为工序×字段（含计算字段）。

    选定路线时沿血缘链合并历代版本的批次数据（同工序按节点家族对齐：origin
    指针优先、node_code 兜底；当前版本字段定义优先，旧版独有字段保留为列）。
    ``route_id=None`` 的全路线平铺模式不跨路线归并，保持每节点独立成列。
    ``start_date`` / ``end_date`` 为可选的日期范围筛选：取"首工序开始时间"
    落在范围内的批次，并连同它们的全部后序批次一并纳入汇总。
    """
    allowed: set[uuid.UUID] | None = None
    if not view_all:
        allowed = await assignment_repo.get_user_node_ids(db, user_id)
        if not allowed:
            return StageSummaryOut(columns=[], rows=[])

    merged_route_names: list[str] = []
    graph: lineage_service.LineageGraph | None = None
    if route_id is None:
        # 全路线平铺：不跨路线归并，每节点自成家族
        # （仅取有效路线的节点：排除草稿路线与已删除路线的孤儿节点）
        nodes = await route_repo.list_nodes(
            db, route_id=None, stage_name=stage_name, exclude_draft_route=True,
        )
        families = [NodeFamily(rep=n) for n in nodes]
        families.sort(key=lambda f: f.rep.sort_order)
    else:
        graph = await lineage_service.resolve_lineage(db, route_id)
        # 与原 exclude_draft_route 口径一致：草稿路线无生产数据，不进汇总
        if graph is None or graph.chain[-1].status == "draft":
            return StageSummaryOut(columns=[], rows=[])
        families = [
            f for f in graph.families
            if stage_name is None or f.rep.stage_name == stage_name
        ]
        merged_route_names = graph.merged_route_names

    # 权限锚定代表节点：授权随版本链延伸（当前路线有分配即可见前身路线的历史批次）
    if allowed is not None:
        families = [f for f in families if f.rep.id in allowed]
    if not families:
        return StageSummaryOut(columns=[], rows=[], merged_routes=merged_route_names)

    code_by_rep = {f.rep.id: f.rep.node_code for f in families}
    name_by_rep = {f.rep.id: f.rep.name for f in families}
    order_by_rep = {f.rep.id: i for i, f in enumerate(families)}
    # 成员节点 → 代表节点；血缘模式用解析结果（含被过滤家族，超集无害），
    # 平铺模式为恒等映射
    rep_by_member: dict[uuid.UUID, uuid.UUID] = (
        graph.rep_by_member if graph is not None
        else {f.rep.id: f.rep.id for f in families}
    )
    # 字段定义：血缘模式用家族归并结果（当前版本优先、旧版独有补后），
    # 平铺模式直接用节点自身定义
    if graph is not None:
        merged_defs = graph.merged_defs
    else:
        merged_defs: dict[uuid.UUID, list[MergedFieldDef]] = {}
        for d in await route_repo.get_field_defs_by_nodes(db, list(order_by_rep)):
            merged_defs.setdefault(d.node_id, []).append(
                MergedFieldDef(
                    node_id=d.node_id,
                    field_key=d.field_key,
                    field_label=d.field_label,
                    unit=d.unit,
                    data_type=d.data_type,
                    sort_order=d.sort_order,
                )
            )

    # 字段列（按家族归并）
    columns: list[StageSummaryColumn] = [
        StageSummaryColumn(
            node_id=f.rep.id,
            node_code=code_by_rep[f.rep.id],
            node_name=name_by_rep[f.rep.id],
            field_key=d.field_key,
            field_label=d.field_label,
            unit=d.unit,
            kind="field",
            col_key=f"{f.rep.id}.{d.field_key}",
        )
        for f in families
        for d in merged_defs.get(f.rep.id, [])
    ]

    # 计算字段列（route_computed_fields，只含作用域内的展示归属）。
    # scope_computed 为未去重全集（批次按自己路线的定义找展示节点要用）；
    # 血缘模式下列定义按 (家族, field_key) 去重、最新版本优先
    scope_route_ids = (
        graph.route_ids if graph is not None
        else {f.rep.route_id for f in families}
    )
    scope_computed = await route_repo.get_computed_fields_by_routes(db, sorted(scope_route_ids))
    scope_computed = [c for c in scope_computed if rep_by_member.get(c.node_id) in order_by_rep]
    column_computed = scope_computed
    if graph is not None:
        route_pos = {r.id: i for i, r in enumerate(graph.chain)}
        column_computed = sorted(
            scope_computed, key=lambda c: -route_pos.get(c.route_id, -1)
        )
        seen_cols: set[tuple[uuid.UUID, str]] = set()
        deduped: list = []
        for c in column_computed:
            key = (rep_by_member[c.node_id], c.field_key)
            if key in seen_cols:
                continue
            seen_cols.add(key)
            deduped.append(c)
        column_computed = deduped
    column_computed.sort(key=lambda c: (order_by_rep[rep_by_member[c.node_id]], c.sort_order))
    columns += [
        StageSummaryColumn(
            node_id=rep_by_member[c.node_id],
            node_code=code_by_rep[rep_by_member[c.node_id]],
            node_name=name_by_rep[rep_by_member[c.node_id]],
            field_key=c.field_key,
            field_label=c.field_label,
            unit=c.unit,
            kind="computed",
            col_key=f"{rep_by_member[c.node_id]}.{c.field_key}",
        )
        for c in column_computed
    ]

    # 行（跨批次，含血缘前身路线的批次）
    if start_date is not None or end_date is not None:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise AppException(status_code=400, message="开始日期不能晚于结束日期")
        # 日期范围筛选：日期范围内"开始"的批次 + 其全部后序批次（限制在作用域路线内）
        start_dt = (
            datetime.combine(start_date, time.min, tzinfo=APP_TZ)
            if start_date is not None else None
        )
        end_dt = (
            datetime.combine(end_date, time.min, tzinfo=APP_TZ) + timedelta(days=1)
            if end_date is not None else None
        )
        source_ids = await batch_repo.list_batches_started_within(
            db, start_dt, end_dt, scope_route_ids,
        )
        descendant_ids = await batch_repo.list_descendant_batch_ids(
            db, set(source_ids),
        )
        candidate_ids = set(source_ids) | descendant_ids
        candidate_batches = [
            b for b in await batch_repo.get_batches_by_ids(db, list(candidate_ids))
            if b.route_id in scope_route_ids
        ]
    else:
        # ponytail: 以最近 500 个批次为汇总窗口，防全量历史扫描；批次量超窗口后改服务端分页
        candidate_batches, _ = await batch_repo.list_batches(
            db, None, None, None, page=1, page_size=500, order_by="created_at",
        )
    member_node_ids = [n.id for f in families for n in f.members]
    executions = await exec_repo.list_completed_executions_by_nodes(
        db, member_node_ids, batch_ids=[b.id for b in candidate_batches],
    )
    # 回流场景同批同节点可能有多条 completed 执行：矩阵取 finished_at 最新一条，
    # 与计算字段/批次详情的"最后一次 completed 执行"取数规则保持一致。
    # ponytail: 应用层字典分组 O(n)，数据量大时改 repository 用 DISTINCT ON。
    executions = list(
        exec_repo.group_latest_completed_by_batch_node(executions).values()
    )
    exec_meta = {e.id: (e.node_id, e.batch_id) for e in executions}
    values = await exec_repo.get_field_values_by_executions(db, [e.id for e in executions])
    batches = await batch_repo.get_batches_by_ids(db, sorted({e.batch_id for e in executions}))

    # 字段值按批次一次遍历分组；col_key 用代表节点维度（跨版本同工序归并到同列，
    # node_code 仅路线内唯一，多路线平铺时同名工序不互相覆盖）
    values_by_batch: dict[uuid.UUID, dict[str, float | str | bool | None]] = {}
    for v in values:
        member_node_id, b_id = exec_meta[v.execution_id]
        col_key = f"{rep_by_member[member_node_id]}.{v.field_key}"
        if v.value_numeric is not None:
            values_by_batch.setdefault(b_id, {})[col_key] = v.value_numeric
        elif v.value_bool is not None:
            values_by_batch.setdefault(b_id, {})[col_key] = v.value_bool
        else:
            values_by_batch.setdefault(b_id, {})[col_key] = v.value_text

    computed_by_batch = (
        await computed_service.expand_computed_fields_for_batches(db, batches)
        if scope_computed
        else {}
    )

    # 计算字段键 → 展示节点（按路线区分；field_key 仅路线内唯一）
    computed_node_by_route_key: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    for c in scope_computed:
        computed_node_by_route_key.setdefault(c.route_id, {})[c.field_key] = c.node_id

    rows: list[StageSummaryRow] = []
    for batch in batches:
        node_by_key = computed_node_by_route_key.get(batch.route_id, {})
        computed_row: dict[str, float | None] = {}
        for c in computed_by_batch.get(batch.id, []):
            display_node = node_by_key.get(c.field_key)
            if display_node is None:
                continue
            rep = rep_by_member.get(display_node)
            if rep is not None:
                computed_row[f"{rep}.{c.field_key}"] = c.value
        rows.append(
            StageSummaryRow(
                batch_id=batch.id,
                batch_no=batch.batch_no,
                values=values_by_batch.get(batch.id, {}),
                computed=computed_row,
            )
        )
    return StageSummaryOut(columns=columns, rows=rows, merged_routes=merged_route_names)
