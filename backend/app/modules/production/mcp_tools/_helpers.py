"""生产 MCP Tools 公共 helper — 格式化常量、解析与解析辅助函数。"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production import repository as repo
from app.modules.production.models import (
    Batch,
    NodeExecution,
    RouteNode,
)
from app.modules.production.repository.assignment import (
    get_user_node_assignments,
    get_user_stages,
)
from app.modules.production.schemas import FieldValueIn


# ponytail: 无批量 get_route_nodes_by_route_ids 仓库方法，内联批量查询避免 N+1
async def _get_route_nodes_by_ids(
    db: AsyncSession, route_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[RouteNode]]:
    """批量查询多条路线的节点，返回 {route_id: [nodes]}。"""
    if not route_ids:
        return {}
    stmt = (
        select(RouteNode)
        .where(
            RouteNode.route_id.in_(route_ids),
            RouteNode.is_deleted == False,  # noqa: E712
        )
        .order_by(RouteNode.route_id, RouteNode.sort_order, RouteNode.node_code)
    )
    rows = list((await db.execute(stmt)).scalars())
    result: dict[uuid.UUID, list[RouteNode]] = defaultdict(list)
    for node in rows:
        result[node.route_id].append(node)
    return dict(result)


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

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


async def _get_user_permitted_nodes(
    db: AsyncSession, user_id: uuid.UUID,
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """返回 {route_id: {node_id}} — 用户在每条路线上有权限操作的节点集合。

    来源：StageAssignment（工段负责人）→ 工段下所有节点
         + NodeAssignment（工序负责人）→ 指定节点
    """
    stages = await get_user_stages(db, user_id)
    node_assignments = await get_user_node_assignments(db, user_id)

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

    # 批量查询所有路线的节点（避免 N+1）
    nodes_by_route = await _get_route_nodes_by_ids(db, list(route_ids))
    for route_id, nodes in nodes_by_route.items():
        route_stages = stage_map.get(route_id, set())
        for node in nodes:
            if node.stage_name in route_stages:
                result[route_id].add(node.id)

    for route_id, node_ids in node_route_map.items():
        result[route_id].update(node_ids)

    return dict(result)


async def _get_user_permitted_nodes_xor(
    db: AsyncSession, user_id: uuid.UUID,
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """返回 {route_id: {node_id}}，使用 XOR 权限模型（与工作台一致）。

    - 有 StageAssignment → stage_owner，只看工段下节点，忽略 NodeAssignment
    - 无 StageAssignment → node_owner，只看 NodeAssignment 指派的节点

    此逻辑与 workbench_service.query_workbench 保持一致，变更时需同步。
    """
    stages = await get_user_stages(db, user_id)
    if stages:
        route_stages: dict[uuid.UUID, set[str]] = defaultdict(set)
        for s in stages:
            route_stages[s.route_id].add(s.stage_name)
        nodes_by_route = await _get_route_nodes_by_ids(db, list(route_stages.keys()))
        permitted: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for route_id, nodes in nodes_by_route.items():
            stage_set = route_stages[route_id]
            for node in nodes:
                if node.stage_name in stage_set:
                    permitted[route_id].add(node.id)
        return dict(permitted)

    node_assignments = await get_user_node_assignments(db, user_id)
    permitted = defaultdict(set)
    for na in node_assignments:
        permitted[na.route_id].add(na.node_id)
    return dict(permitted)


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


async def _get_latest_execution(
    db: AsyncSession, batch_id: uuid.UUID, node_id: uuid.UUID,
    status: str | None = None,
) -> NodeExecution | None:
    """查找批次+节点的最新一次执行，可按 status 过滤。"""
    stmt = (
        select(NodeExecution)
        .where(
            NodeExecution.batch_id == batch_id,
            NodeExecution.node_id == node_id,
            NodeExecution.is_deleted == False,  # noqa: E712
        )
    )
    if status:
        stmt = stmt.where(NodeExecution.status == status)
    stmt = stmt.order_by(NodeExecution.execution_seq.desc()).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


def _scope_nodes(
    nodes: list[RouteNode],
    entry_node_id: uuid.UUID | None,
    entry_sort_order: int | None = None,
) -> list[RouteNode]:
    """派生批次只看 entry_node 及之后的工序；普通批次返回全部。

    若调用方已预先查到 entry_node，可传入 entry_sort_order 避免二次线性扫描。
    """
    if not entry_node_id:
        return nodes
    if entry_sort_order is None:
        entry = next((n for n in nodes if n.id == entry_node_id), None)
        entry_sort_order = entry.sort_order if entry else 0
    return [n for n in nodes if n.sort_order >= entry_sort_order]


def _format_field_value(value_text: str | None, value_numeric: float | None, value_bool: bool | None) -> str:
    """将字段值转为可读字符串。"""
    if value_numeric is not None:
        return str(value_numeric)
    if value_bool is not None:
        return "是" if value_bool else "否"
    return value_text if value_text is not None else "（未填）"


def _field_dict_to_in(f: dict[str, Any]) -> FieldValueIn:
    """将 Agent 传入的 {field_key, value} dict 转为 FieldValueIn。"""
    try:
        key = f["field_key"]
    except KeyError:
        raise ValueError(f"字段缺少 field_key：{f}")
    return FieldValueIn(field_key=key, value=f.get("value"))
