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
    StageSummaryColumn,
    StageSummaryOut,
    StageSummaryRow,
    StepCycleResponse,
    StepCycleStat,
)
from app.modules.production.service import computed_service

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
    db: AsyncSession, route_id: uuid.UUID, node_code: str, field_key: str
) -> list[FieldTrendPoint]:
    """跨批次字段趋势：某路线节点下全部完成执行中该字段的值，按填写时间升序。"""
    node = await repo.get_node_by_code(db, route_id, node_code)
    if node is None:
        return []
    rows = await repo.get_field_trend_values(db, node.id, field_key)
    return [
        FieldTrendPoint(batch_no=b, filled_at=t, value=v) for b, t, v in rows
    ]


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

    ``start_date`` / ``end_date`` 为可选的日期范围筛选：取"首工序开始时间"
    落在范围内的批次，并连同它们的全部后序批次一并纳入汇总。
    """
    allowed: set[uuid.UUID] | None = None
    if not view_all:
        allowed = await assignment_repo.get_user_node_ids(db, user_id)
        if not allowed:
            return StageSummaryOut(columns=[], rows=[])

    # 仅取有效路线的节点：排除草稿路线（无生产数据）与已删除路线的孤儿节点
    nodes = await route_repo.list_nodes(
        db, route_id=route_id, stage_name=stage_name, exclude_draft_route=True,
    )
    nodes = [n for n in nodes if allowed is None or n.id in allowed]
    if not nodes:
        return StageSummaryOut(columns=[], rows=[])
    nodes.sort(key=lambda n: n.sort_order)

    node_ids = [n.id for n in nodes]
    code_by_id = {n.id: n.node_code for n in nodes}
    name_by_id = {n.id: n.name for n in nodes}
    order_by_id = {n.id: i for i, n in enumerate(nodes)}
    route_ids = {n.route_id for n in nodes}

    # 字段列（node_field_defs，按节点顺序 × 字段顺序）
    defs = await route_repo.get_field_defs_by_nodes(db, node_ids)
    defs.sort(key=lambda d: (order_by_id[d.node_id], d.sort_order))
    columns: list[StageSummaryColumn] = [
        StageSummaryColumn(
            node_id=d.node_id,
            node_code=code_by_id[d.node_id],
            node_name=name_by_id[d.node_id],
            field_key=d.field_key,
            field_label=d.field_label,
            unit=d.unit,
            kind="field",
            col_key=f"{d.node_id}.{d.field_key}",
        )
        for d in defs
    ]

    # 计算字段列（route_computed_fields，只含当前节点范围内的展示归属）
    computed_defs = await route_repo.get_computed_fields_by_routes(db, sorted(route_ids))
    computed_defs = [c for c in computed_defs if c.node_id in code_by_id]
    computed_defs.sort(key=lambda c: (order_by_id[c.node_id], c.sort_order))
    allowed_computed_keys = {c.field_key for c in computed_defs}
    columns += [
        StageSummaryColumn(
            node_id=c.node_id,
            node_code=code_by_id[c.node_id],
            node_name=name_by_id[c.node_id],
            field_key=c.field_key,
            field_label=c.field_label,
            unit=c.unit,
            kind="computed",
            col_key=f"{c.node_id}.{c.field_key}",
        )
        for c in computed_defs
    ]

    # 行（跨批次）
    if start_date is not None or end_date is not None:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise AppException(status_code=400, message="开始日期不能晚于结束日期")
        # 日期范围筛选：日期范围内"开始"的批次 + 其全部后序批次（限制在当前路线作用域）
        start_dt = (
            datetime.combine(start_date, time.min, tzinfo=APP_TZ)
            if start_date is not None else None
        )
        end_dt = (
            datetime.combine(end_date, time.min, tzinfo=APP_TZ) + timedelta(days=1)
            if end_date is not None else None
        )
        source_ids = await batch_repo.list_batches_started_within(
            db, start_dt, end_dt, route_ids,
        )
        descendant_ids = await batch_repo.list_descendant_batch_ids(
            db, set(source_ids),
        )
        candidate_ids = set(source_ids) | descendant_ids
        candidate_batches = [
            b for b in await batch_repo.get_batches_by_ids(db, list(candidate_ids))
            if b.route_id in route_ids
        ]
    else:
        # ponytail: 以最近 500 个批次为汇总窗口，防全量历史扫描；批次量超窗口后改服务端分页
        candidate_batches, _ = await batch_repo.list_batches(
            db, None, None, None, page=1, page_size=500, order_by="created_at",
        )
    executions = await exec_repo.list_completed_executions_by_nodes(
        db, node_ids, batch_ids=[b.id for b in candidate_batches],
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

    # 字段值按批次一次遍历分组；col_key 用节点 id 维度（node_code 仅路线内唯一，
    # 多路线平铺时同名工序会互相覆盖）
    values_by_batch: dict[uuid.UUID, dict[str, float | str | bool | None]] = {}
    for v in values:
        node_id, b_id = exec_meta[v.execution_id]
        col_key = f"{node_id}.{v.field_key}"
        if v.value_numeric is not None:
            values_by_batch.setdefault(b_id, {})[col_key] = v.value_numeric
        elif v.value_bool is not None:
            values_by_batch.setdefault(b_id, {})[col_key] = v.value_bool
        else:
            values_by_batch.setdefault(b_id, {})[col_key] = v.value_text

    computed_by_batch = (
        await computed_service.expand_computed_fields_for_batches(db, batches)
        if allowed_computed_keys
        else {}
    )

    # 计算字段键 → 展示节点（按路线区分；field_key 仅路线内唯一）
    computed_node_by_route_key: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    for c in computed_defs:
        computed_node_by_route_key.setdefault(c.route_id, {})[c.field_key] = c.node_id

    rows: list[StageSummaryRow] = []
    for batch in batches:
        node_by_key = computed_node_by_route_key.get(batch.route_id, {})
        rows.append(
            StageSummaryRow(
                batch_id=batch.id,
                batch_no=batch.batch_no,
                values=values_by_batch.get(batch.id, {}),
                computed={
                    f"{node_by_key[c.field_key]}.{c.field_key}": c.value
                    for c in computed_by_batch.get(batch.id, [])
                    if c.field_key in node_by_key
                },
            )
        )
    return StageSummaryOut(columns=columns, rows=rows)
