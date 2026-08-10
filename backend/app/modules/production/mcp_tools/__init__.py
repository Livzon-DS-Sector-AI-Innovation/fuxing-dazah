"""生产模块 MCP Tools — 为一线工序负责人提供移动端（Agent）操作能力。

目标用户：由工段负责人配置的工序负责人，这些人可能无法接触电脑使用网页端生产工作台。
通过飞书 Agent 调用这些工具完成工序状态查询和操作。
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastmcp.tools.base import ToolResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production import repository as repo
from app.modules.production.models import (
    Batch,
    NodeExecution,
    NodeFieldValue,
    RouteNode,
)
from app.modules.production.schemas import (
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
)
from app.modules.production.service.execution_service import (
    backfill_execution_fields,
    complete_execution,
    compute_missing_required_fields,
    start_execution,
)
from app.platform.identity.mcp_tools import resolve_user
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import mcp

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

_STATUS_MARK: dict[str | None, str] = {
    "completed": "[完成]",
    "in_progress": "[进行中]",
    "aborted": "[中止]",
    None: "[待开始]",
}

_BATCH_STATUS_CN: dict[str, str] = {
    "draft": "草稿",
    "scheduled": "已排产",
    "released": "已下达",
    "pending": "待执行",
    "in_progress": "进行中",
    "completed": "已完成",
    "cancelled": "已取消",
}

_DATA_TYPE_CN: dict[str, str] = {
    "numeric": "数值",
    "text": "文本",
    "boolean": "是否",
    "select": "选项",
}


async def _get_user_permitted_nodes(
    db: AsyncSession, user_id: uuid.UUID,
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """返回 {route_id: {node_id}} — 用户在每条路线上有权限操作的节点集合。

    来源：StageAssignment（工段负责人）→ 工段下所有节点
         + NodeAssignment（工序负责人）→ 指定节点
    """
    stages = await repo.get_user_stages(db, user_id)
    node_assignments = await repo.get_user_node_assignments(db, user_id)

    route_ids: set[uuid.UUID] = set()
    stage_map: dict[uuid.UUID, set[str]] = defaultdict(set)
    for s in stages:
        route_ids.add(s.route_id)
        stage_map[s.route_id].add(s.stage_name)

    node_route_map: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for na in node_assignments:
        route_ids.add(na.route_id)
        node_route_map[na.route_id].add(na.node_id)

    result: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)

    for route_id in route_ids:
        nodes = await repo.get_route_nodes(db, route_id)
        for node in nodes:
            if node.stage_name in stage_map.get(route_id, set()):
                result[route_id].add(node.id)

    for route_id, node_ids in node_route_map.items():
        result[route_id].update(node_ids)

    return dict(result)


async def _resolve_batch_and_node(
    db: AsyncSession, batch_no: str, step_name: str,
) -> tuple[Batch, RouteNode]:
    """根据批号和工序名称解析 Batch 和 RouteNode。找不到时抛 ValueError。"""
    batch = await repo.get_batch_by_no(db, batch_no)
    if not batch:
        raise ValueError(f"未找到批次：{batch_no}")

    nodes = await repo.get_route_nodes(db, batch.route_id)
    match = [n for n in nodes if n.name == step_name]
    if not match:
        names = ", ".join(n.name for n in nodes)
        raise ValueError(
            f"批次 {batch_no} 的工艺路线中未找到工序「{step_name}」。"
            f"可用工序：{names}"
        )

    return batch, match[0]


async def _get_in_progress_execution(
    db: AsyncSession, batch_id: uuid.UUID, node_id: uuid.UUID,
) -> NodeExecution | None:
    """查找批次+节点的进行中执行（最新一次）。"""
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id == batch_id,
            NodeExecution.node_id == node_id,
            NodeExecution.status == "in_progress",
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.started_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _get_latest_execution(
    db: AsyncSession, batch_id: uuid.UUID, node_id: uuid.UUID,
) -> NodeExecution | None:
    """查找批次+节点的最新一次执行（不限状态）。"""
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id == batch_id,
            NodeExecution.node_id == node_id,
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.execution_seq.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _format_field_value(value_text: str | None, value_numeric: float | None, value_bool: bool | None) -> str:
    """将字段值转为可读字符串。"""
    if value_numeric is not None:
        return str(value_numeric)
    if value_bool is not None:
        return "是" if value_bool else "否"
    return value_text or "（未填）"


def _field_dict_to_in(f: dict) -> FieldValueIn:
    """将 Agent 传入的 {field_key, value} dict 转为 FieldValueIn。"""
    return FieldValueIn(field_key=f["field_key"], value=f.get("value"))


# ═══════════════════════════════════════════════════════════════
# Tool 1: 查询用户负责的工序
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def query_user_processes(operator_id: str) -> ToolResult:
    """查询指定用户目前负责哪些产品、哪些工艺路线上的哪些工序。

    基于工段负责人（StageAssignment）和工序负责人（NodeAssignment）配置。
    适用于 Agent 帮一线工人确认自己的职责范围。

    Args:
        operator_id: 用户的飞书 user_id 或姓名
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    permitted = await _get_user_permitted_nodes(db, user.id)

    if not permitted:
        return ToolResult(
            content=f"用户 **{user.name}** 目前没有负责任何工序。",
        )

    route_ids = list(permitted.keys())
    routes = await repo.get_routes_by_ids(db, route_ids)

    product_ids = list({r.product_id for r in routes})
    products = await repo.get_products_by_ids(db, product_ids)

    # 按 产品 → 路线 → 工段 → 工序 组织
    lines = [f"## {user.name} 负责的工序\n"]

    for product in sorted(products, key=lambda p: p.product_name):
        lines.append(f"### {product.product_name}")
        if product.product_code:
            lines.append(f"编码：{product.product_code}")
        lines.append("")

        product_routes = [r for r in routes if r.product_id == product.id]
        for route in sorted(product_routes, key=lambda r: r.route_name):
            lines.append(f"**{route.route_name}**（{route.status}）\n")

            all_route_nodes = await repo.get_route_nodes(db, route.id)
            route_permitted = permitted.get(route.id, set())
            route_nodes = [n for n in all_route_nodes if n.id in route_permitted]

            by_stage: dict[str, list[RouteNode]] = defaultdict(list)
            for node in route_nodes:
                stage = node.stage_name or "未分组"
                by_stage[stage].append(node)

            for stage in sorted(by_stage):
                nodes = sorted(by_stage[stage], key=lambda n: n.sort_order)
                lines.append(f"**{stage}**：")
                for node in nodes:
                    lines.append(f"  - {node.name}（`{node.node_code}`）")
                lines.append("")

    content = "\n".join(lines)
    return ToolResult(content=content)


# ═══════════════════════════════════════════════════════════════
# Tool 2: 变更批次工序状态
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def change_batch_step_status(
    operator_id: str,
    batch_no: str,
    step_name: str,
    action: str,
    field_values: list[dict] | None = None,
) -> ToolResult:
    """变更指定批次在指定工序上的开始/结束状态。

    约束：
    - 开始前校验工序顺序（前道未完成且不允许重叠则拒绝）
    - 结束前必须已开始（无进行中的执行则拒绝）
    - 已结束的工序不能重复结束（finished_at 不会被重置）

    权限：需要是该工序的工段/工序负责人，或持有 production:batch:submit 权限。

    Args:
        operator_id: 操作人的飞书 user_id
        batch_no: 批次号
        step_name: 工序名称（与工艺路线配置的名称一致）
        action: "start" 开始工序 / "end" 结束工序
        field_values: 可选，字段值列表 [{"field_key": "温度", "value": 25.3}, ...]。
            未填的数据可在工序结束后通过 backfill_step_fields 补录。
    """
    if action not in ("start", "end"):
        return ToolResult(
            content=f"无效操作 `{action}`，仅支持 `start` 或 `end`。",
        )

    db = get_db()
    user = await resolve_user(db, operator_id)

    try:
        batch, node = await _resolve_batch_and_node(db, batch_no, step_name)
    except ValueError as e:
        return ToolResult(content=f"{e}")

    # 解析 field_values
    fvs = [_field_dict_to_in(f) for f in (field_values or [])]

    if action == "start":
        payload = ExecutionStartIn(
            node_id=node.id,
            owner_id=user.id,
            owner_name=user.name,
            field_values=fvs,
        )
        try:
            execution = await start_execution(db, batch.id, payload, user)
        except Exception as e:
            return ToolResult(content=f"开始工序失败：{e}")

        msg = (
            f"批次 **{batch_no}** 的工序「**{step_name}**」已开始。\n\n"
            f"| 项目 | 值 |\n"
            f"|------|----|\n"
            f"| 执行序号 | 第 {execution.execution_seq} 次 |\n"
            f"| 开始时间 | {execution.started_at.strftime('%Y-%m-%d %H:%M')} |\n"
            f"| 负责人 | {user.name} |\n"
            f"| 批次状态 | {_BATCH_STATUS_CN.get(batch.status, batch.status)} |"
        )
        return ToolResult(content=msg)

    # action == "end"
    in_progress_ex = await _get_in_progress_execution(db, batch.id, node.id)
    if not in_progress_ex:
        return ToolResult(
            content=(
                f"批次 **{batch_no}** 的工序「**{step_name}**」没有进行中的执行。\n"
                f"请先开始该工序后，再进行结束操作。"
            ),
        )

    end_payload = ExecutionCompleteIn(field_values=fvs)
    try:
        completed_ex = await complete_execution(db, in_progress_ex.id, end_payload, user)
    except Exception as e:
        return ToolResult(content=f"结束工序失败：{e}")

    finished = (
        completed_ex.finished_at.strftime("%Y-%m-%d %H:%M")
        if completed_ex.finished_at
        else "—"
    )

    # 检查缺填的必填字段
    missing = await compute_missing_required_fields(db, [completed_ex])
    missing_fields = missing.get(completed_ex.id, [])

    msg = (
        f"批次 **{batch_no}** 的工序「**{step_name}**」已结束。\n\n"
        f"| 项目 | 值 |\n"
        f"|------|----|\n"
        f"| 执行序号 | 第 {completed_ex.execution_seq} 次 |\n"
        f"| 开始时间 | {completed_ex.started_at.strftime('%Y-%m-%d %H:%M')} |\n"
        f"| 结束时间 | {finished} |\n"
        f"| 负责人 | {user.name} |"
    )
    if missing_fields:
        names = "、".join(m.field_label for m in missing_fields)
        msg += (
            f"\n\n**注意**：以下必填字段尚未填写，请尽快补录（在批次完成前）：\n"
            f"{names}\n"
            f"可使用 `backfill_step_fields` 工具补录。"
        )
    return ToolResult(content=msg)


# ═══════════════════════════════════════════════════════════════
# Tool 3: 查询批次进度
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def query_batch_progress(batch_no: str) -> ToolResult:
    """查询指定批次号当前进行到哪个工序。

    返回每个工序的状态（待开始 / 进行中 / 已完成 / 已中止），
    以及批次整体的进度概览和当前正在哪个工序上。

    Args:
        batch_no: 批次号
    """
    db = get_db()
    batch = await repo.get_batch_by_no(db, batch_no)
    if not batch:
        return ToolResult(content=f"未找到批次：{batch_no}")

    nodes = await repo.get_route_nodes(db, batch.route_id)
    executions = await repo.list_executions(db, batch.id)
    product = await repo.get_product(db, batch.product_id)
    route = await repo.get_route(db, batch.route_id)

    # 派生批次只看 entry_node 及之后的工序
    entry_node = None
    if batch.entry_node_id:
        entry_node = next((n for n in nodes if n.id == batch.entry_node_id), None)
        min_sort = entry_node.sort_order if entry_node else 0
        scope_nodes = [n for n in nodes if n.sort_order >= min_sort]
    else:
        scope_nodes = nodes

    # 每节点最新执行
    latest: dict[uuid.UUID, NodeExecution] = {}
    for ex in executions:
        cur = latest.get(ex.node_id)
        if cur is None or ex.execution_seq > cur.execution_seq:
            latest[ex.node_id] = ex

    # 仅在范围内的节点中统计
    scope_latest = {nid: ex for nid, ex in latest.items() if nid in {n.id for n in scope_nodes}}
    completed_nodes = [
        n for n in scope_nodes
        if scope_latest.get(n.id) and scope_latest[n.id].status == "completed"
    ]
    in_progress_node = next(
        (n for n in scope_nodes
         if scope_latest.get(n.id) and scope_latest[n.id].status == "in_progress"),
        None,
    )

    status_cn = _BATCH_STATUS_CN.get(batch.status, batch.status)
    lines = [
        f"## 批次 {batch_no} 进度",
        "",
        f"- 产品：{product.product_name if product else '—'}",
        f"- 路线：{route.route_name if route else '—'}",
        f"- 状态：{status_cn}",
        f"- 数量：{batch.quantity or '—'} {batch.unit or ''}",
    ]

    if in_progress_node:
        ex = scope_latest[in_progress_node.id]
        stage_hint = f" [{in_progress_node.stage_name}]" if in_progress_node.stage_name else ""
        lines.append(f"- 当前工序：{in_progress_node.name}{stage_hint} — 进行中，第{ex.execution_seq}次，开始 {ex.started_at.strftime('%Y-%m-%d %H:%M')}，负责人 {ex.owner_name or '—'}")
    elif completed_nodes:
        last = completed_nodes[-1]
        ex = scope_latest[last.id]
        finished = ex.finished_at.strftime('%Y-%m-%d %H:%M') if ex.finished_at else '—'
        stage_hint = f" [{last.stage_name}]" if last.stage_name else ""
        lines.append(f"- 最后完成工序：{last.name}{stage_hint} — 已完成，第{ex.execution_seq}次，{ex.started_at.strftime('%Y-%m-%d %H:%M')} -> {finished}，负责人 {ex.owner_name or '—'}")
    else:
        # 尚未开始任何工序
        if scope_nodes:
            first = scope_nodes[0]
            lines.append(f"- 下一工序：{first.name} [{first.stage_name or '—'}] — 等待开始")

    if completed_nodes:
        names = "、".join(n.name for n in completed_nodes)
        lines.append(f"- 已完成工序：{len(completed_nodes)} 道（{names}）")

    if batch.entry_node_id and entry_node:
        lines.append(f"- 入口节点：{entry_node.name}（派生批次，此前工序属父批次）")

    return ToolResult(content="\n".join(lines))


# ═══════════════════════════════════════════════════════════════
# Tool 4: 查询用户负责的进行中批次
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def query_user_active_batches(operator_id: str) -> ToolResult:
    """查询指定用户负责的工序中，哪些批次正在进行中。

    返回用户负责的工序所在的活跃批次（pending / in_progress），
    以及每个批次当前在哪个工序上。仅返回包含用户负责工序的批次。

    Args:
        operator_id: 用户的飞书 user_id 或姓名
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    # 权限模型与工作台 query_workbench 一致：
    # - 有 StageAssignment → stage_owner，只看工段下节点，忽略 NodeAssignment
    # - 无 StageAssignment → node_owner，只看 NodeAssignment 指派的节点
    stages = await repo.get_user_stages(db, user.id)
    if stages:
        route_stages: dict[uuid.UUID, set[str]] = defaultdict(set)
        for s in stages:
            route_stages[s.route_id].add(s.stage_name)
        permitted: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for route_id in route_stages:
            nodes = await repo.get_route_nodes(db, route_id)
            stage_set = route_stages[route_id]
            for node in nodes:
                if node.stage_name in stage_set:
                    permitted[route_id].add(node.id)
    else:
        node_assignments = await repo.get_user_node_assignments(db, user.id)
        permitted = defaultdict(set)
        for na in node_assignments:
            permitted[na.route_id].add(na.node_id)

    if not permitted:
        return ToolResult(
            content=f"用户 **{user.name}** 目前没有负责任何工序，无进行中批次。",
        )

    route_ids = list(permitted.keys())

    # 查找活跃批次
    batch_stmt = (
        select(Batch)
        .where(
            Batch.route_id.in_(route_ids),
            Batch.status.in_(["pending", "in_progress"]),
            Batch.is_deleted == False,  # noqa: E712
        )
        .order_by(Batch.created_at.desc())
    )
    batches = list((await db.execute(batch_stmt)).scalars())

    if not batches:
        return ToolResult(
            content=f"用户 **{user.name}** 负责的工序暂无活跃批次。",
        )

    # 批量加载
    product_ids = list({b.product_id for b in batches})
    products = await repo.get_products_by_ids(db, product_ids)
    product_map = {p.id: p for p in products}

    route_ids_set = list({b.route_id for b in batches})
    routes = await repo.get_routes_by_ids(db, route_ids_set)
    route_map = {r.id: r for r in routes}

    # 批量加载节点和执行
    nodes_cache: dict[uuid.UUID, list[RouteNode]] = {}
    exec_cache: dict[uuid.UUID, list[NodeExecution]] = {}

    lines = [f"## {user.name} 负责的进行中批次\n"]
    count = 0

    for batch in batches:
        if batch.route_id not in nodes_cache:
            nodes_cache[batch.route_id] = await repo.get_route_nodes(db, batch.route_id)
        if batch.id not in exec_cache:
            exec_cache[batch.id] = await repo.list_executions(db, batch.id)

        nodes = nodes_cache[batch.route_id]
        executions = exec_cache[batch.id]
        permitted_set = permitted.get(batch.route_id, set())

        # 构建每节点最新执行快照
        latest: dict[uuid.UUID, NodeExecution] = {}
        for ex in executions:
            cur = latest.get(ex.node_id)
            if cur is None or ex.execution_seq > cur.execution_seq:
                latest[ex.node_id] = ex

        # 确定本批次的工序范围：派生批次仅包含 entry_node 及之后的节点
        if batch.entry_node_id:
            entry_node = next((n for n in nodes if n.id == batch.entry_node_id), None)
            min_sort = entry_node.sort_order if entry_node else 0
            scope_nodes = [n for n in nodes if n.sort_order >= min_sort]
        else:
            scope_nodes = nodes

        # 筛选用户在本次批次范围内负责的节点（按 sort_order 排序）
        my_nodes = sorted(
            [n for n in scope_nodes if n.id in permitted_set],
            key=lambda n: n.sort_order,
        )
        if not my_nodes:
            continue

        # 判断是否相关：负责的节点中有 in_progress 或尚未开始
        has_in_progress = any(
            latest.get(n.id) and latest[n.id].status == "in_progress"
            for n in my_nodes
        )
        has_pending = any(
            latest.get(n.id) is None for n in my_nodes
        )
        if not has_in_progress and not has_pending:
            continue

        count += 1

        # --- 构建批次输出 ---
        product = product_map.get(batch.product_id)
        route = route_map.get(batch.route_id)

        lines.append(f"### {batch.batch_no}")
        lines.append(f"- 产品：{product.product_name if product else '—'} | 路线：{route.route_name if route else '—'} | 状态：{_BATCH_STATUS_CN.get(batch.status, batch.status)} | 数量：{batch.quantity or '—'} {batch.unit or ''}")

        # 进度概览（仅统计用户负责的工序，与表格一致）
        total_count = len(my_nodes)
        completed_count = sum(
            1 for n in my_nodes if latest.get(n.id) and latest[n.id].status == "completed"
        )
        in_progress_nodes = [
            n for n in my_nodes
            if latest.get(n.id) and latest[n.id].status == "in_progress"
        ]
        if in_progress_nodes:
            ip = in_progress_nodes[0]
            stage_hint = f" [{ip.stage_name}]" if ip.stage_name else ""
            lines.append(f"- 你的工序进度：{completed_count}/{total_count} 已完成，当前进行中：{ip.name}{stage_hint}")
        elif completed_count == total_count:
            lines.append(f"- 你的工序进度：{completed_count}/{total_count} 全部完成")
        else:
            lines.append(f"- 你的工序进度：{completed_count}/{total_count} 已完成")

        # 仅列出用户负责的工序
        lines.append("")
        lines.append("你的负责工序：")
        lines.append("| 状态 | 工序 | 工段 | 详情 |")
        lines.append("|------|------|------|------|")
        for node in my_nodes:
            entry = latest.get(node.id)
            status = entry.status if entry else None
            mark = _STATUS_MARK.get(status, "[待开始]")
            stage = node.stage_name or "—"

            detail_parts = []
            if entry:
                detail_parts.append(f"第{entry.execution_seq}次")
                detail_parts.append(entry.started_at.strftime("%m-%d %H:%M"))
                if entry.finished_at:
                    detail_parts.append(f"-> {entry.finished_at.strftime('%m-%d %H:%M')}")
                if entry.owner_name:
                    detail_parts.append(entry.owner_name)
            detail = " · ".join(detail_parts) if detail_parts else "—"

            lines.append(f"| {mark} | {node.name} | {stage} | {detail} |")
        lines.append("")

    if count == 0:
        return ToolResult(
            content=f"用户 **{user.name}** 负责的工序暂无进行中的批次。",
        )

    lines.append(f"---\n共 **{count}** 个批次。")
    return ToolResult(content="\n".join(lines))


# ═══════════════════════════════════════════════════════════════
# Tool 5: 查询工序字段定义
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def query_step_fields(
    batch_no: str,
    step_name: str,
    phase: str,
) -> ToolResult:
    """查询某批次某工序需要填报的字段定义。

    返回该工序在指定阶段（开始/结束）的全部字段：
    field_key（字段键）、field_label（显示名）、data_type（类型）、
    unit（单位）、required（是否必填）、options（选项）、范围等。

    如果已有执行记录，同时返回当前已填的值。
    如果工序已结束但缺少必填字段，会标注可补录的字段。

    Args:
        batch_no: 批次号
        step_name: 工序名称
        phase: 阶段，"start"（开始工序时填）或 "end"（结束工序时填）
    """
    if phase not in ("start", "end"):
        return ToolResult(content=f"无效阶段 `{phase}`，仅支持 start 或 end。")

    db = get_db()
    batch = await repo.get_batch_by_no(db, batch_no)
    if not batch:
        return ToolResult(content=f"未找到批次：{batch_no}")

    nodes = await repo.get_route_nodes(db, batch.route_id)
    match = [n for n in nodes if n.name == step_name]
    if not match:
        names = ", ".join(n.name for n in nodes)
        return ToolResult(content=f"未找到工序「{step_name}」。可用工序：{names}")

    node = match[0]
    defs = await repo.get_field_defs_by_nodes(db, [node.id])
    phase_defs = [d for d in defs if d.phase == phase]

    # 查询已有执行和字段值
    execution = await _get_latest_execution(db, batch.id, node.id)
    existing_values: dict[str, NodeFieldValue] = {}
    missing_fields: list[str] = []
    if execution:
        fvs = await repo.get_field_values_by_executions(db, [execution.id])
        for v in fvs:
            existing_values[v.field_key] = v
        if execution.status == "completed":
            missing_map = await compute_missing_required_fields(db, [execution])
            missing_list = missing_map.get(execution.id, [])
            missing_fields = [m.field_label for m in missing_list]

    phase_cn = "开始" if phase == "start" else "结束"
    lines = [
        f"## 批次 {batch_no} · {step_name} · {phase_cn}阶段字段",
        "",
    ]

    if not phase_defs:
        lines.append("该阶段无需填报字段。")
        return ToolResult(content="\n".join(lines))

    lines.append("| # | 字段 | 键 | 类型 | 必填 | 约束 | 当前值 |")
    lines.append("|---|------|-----|------|------|------|--------|")

    for i, d in enumerate(sorted(phase_defs, key=lambda x: x.sort_order), 1):
        type_cn = _DATA_TYPE_CN.get(d.data_type, d.data_type)
        required = "是" if d.required else "否"
        constraint = ""
        if d.data_type == "numeric":
            parts = []
            if d.min_value is not None:
                parts.append(f">= {d.min_value}")
            if d.max_value is not None:
                parts.append(f"<= {d.max_value}")
            constraint = ", ".join(parts) if parts else "—"
            if d.unit:
                constraint += f" {d.unit}"
        elif d.data_type == "select" and d.options:
            constraint = " / ".join(d.options)
        else:
            constraint = d.unit or "—"

        cur_val = "—"
        fv = existing_values.get(d.field_key)
        if fv:
            cur_val = _format_field_value(fv.value_text, fv.value_numeric, fv.value_bool)

        lines.append(
            f"| {i} | {d.field_label} | `{d.field_key}` | {type_cn} | {required} | {constraint} | {cur_val} |"
        )

    if execution:
        lines.append("")
        status_cn = _STATUS_MARK.get(execution.status, execution.status)
        lines.append(f"当前执行状态：{status_cn}（第 {execution.execution_seq} 次）")
        if missing_fields:
            lines.append(f"待补录必填字段：{'、'.join(missing_fields)}")
            lines.append("可使用 `backfill_step_fields` 工具补录。")

    return ToolResult(content="\n".join(lines))


# ═══════════════════════════════════════════════════════════════
# Tool 6: 补录工序字段
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def backfill_step_fields(
    operator_id: str,
    batch_no: str,
    step_name: str,
    field_values: list[dict],
) -> ToolResult:
    """补录已结束工序的 end 阶段字段值（upsert）。

    仅可对已完成（completed）的执行补录。批次完成后禁止补录。
    权限：同开始/结束操作。

    Args:
        operator_id: 操作人的飞书 user_id
        batch_no: 批次号
        step_name: 工序名称
        field_values: 字段值列表 [{"field_key": "温度", "value": 25.3}, ...]
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    try:
        batch, node = await _resolve_batch_and_node(db, batch_no, step_name)
    except ValueError as e:
        return ToolResult(content=f"{e}")

    if batch.status in ("completed", "cancelled"):
        return ToolResult(
            content=f"批次 {batch_no} 已{_BATCH_STATUS_CN.get(batch.status, batch.status)}，禁止补录。"
        )

    # 查找最新一次 completed 执行
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id == batch.id,
            NodeExecution.node_id == node.id,
            NodeExecution.status == "completed",
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        .order_by(NodeExecution.execution_seq.desc())
        .limit(1)
    )
    execution = (await db.execute(stmt)).scalar_one_or_none()
    if not execution:
        return ToolResult(
            content=f"批次 {batch_no} 的工序「{step_name}」没有已完成的执行，无法补录。"
        )

    fvs = [_field_dict_to_in(f) for f in field_values]
    try:
        await backfill_execution_fields(db, execution.id, fvs, user)
    except Exception as e:
        return ToolResult(content=f"补录失败：{e}")

    # 再次检查是否还有缺填
    missing_map = await compute_missing_required_fields(db, [execution])
    missing_list = missing_map.get(execution.id, [])
    missing_names = [m.field_label for m in missing_list]

    msg = (
        f"批次 **{batch_no}** 的工序「**{step_name}**」已补录 {len(field_values)} 个字段。\n"
        f"补录人：{user.name}"
    )
    if missing_names:
        msg += (
            f"\n\n仍有必填字段缺填：{'、'.join(missing_names)}。"
            f"请继续补录后，方可完成批次。"
        )
    return ToolResult(content=msg)
