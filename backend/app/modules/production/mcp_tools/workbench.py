"""生产工作台操作 — 查待办、激活计划批次、接收批次（分裂/合并）。

一线工段负责人通过飞书 Agent 完成网页端工作台的三个核心动作：
待办查询（待接收/待开工/可激活计划批次）、激活计划批次、接收批次。
全部走 workbench_service，业务校验（工段负责人权限、边界边、批次状态）在 service 内。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastmcp.tools.base import ToolResult
from pydantic import ValidationError

from app.core.exceptions import AppException
from app.modules.production import repository as repo
from app.modules.production.mcp_tools._helpers import _BATCH_STATUS_CN
from app.modules.production.schemas import ChildBatchIn, ReceiveAndStartIn
from app.modules.production.service import workbench_service
from app.platform.identity.mcp_tools import resolve_user
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

logger = logging.getLogger(__name__)
mcp = get_module_mcp("production")


@mcp.tool()
async def query_workbench_todo(operator_id: str) -> ToolResult:
    """查询当前用户的生产待办，分四段：待接收批次、待开工工序、可激活计划批次、待结束工序。

    - 待接收批次：上游批次已完成边界边起点工序，等待下游工段接收（分裂=1个父批次，合并=多个父批次）。
      「接收边标识」列的值在调用 receive_batch 时必须原样回传为 edge_id（合并卡片显示 —，不传）。
      「建议批号」由系统生成（根批号+工段尾缀），接收时可默认使用。
    - 待开工工序：批次待执行，可直接开始第一个工序。
    - 可激活计划批次：计划单下达生成、状态为已排产的批次，仅第一工段负责人可激活（列表中已过滤）。
    - 待结束工序：进行中的执行（含无工段/工序身份的单次执行负责人），
      用 change_batch_step_status action=end 结束。

    Args:
        operator_id: 操作人的飞书 user_id
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    wb = await workbench_service.query_workbench(db, user.id, view_mode="mine")
    planned = await workbench_service.query_planned_batches(db, user.id)

    # ── 待接收批次 ──
    receive_items = [it for it in wb.items if it.type == "pending_receive"]
    receive_lines = [
        "| 类型 | 父批次 | 接收工序 | 工段 | 产品 | 建议批号 | 接收边标识 |",
        "|------|--------|----------|------|------|----------|------------|",
    ]
    for it in receive_items:
        is_merge = len(it.parent_batch_ids) > 1
        parents = (
            "、".join(it.predecessor_batches)
            if is_merge
            else (it.batch_no or "—")
        )
        receive_lines.append(
            f"| {'合并' if is_merge else '分裂'} | {parents} | {it.node_name} "
            f"| {it.stage_name or '—'} | {it.product_name or '—'} "
            f"| {it.suggested_batch_no or '—'} | {it.boundary_edge_id or '—'} |"
        )

    # ── 待开工工序 ──
    start_items = [it for it in wb.items if it.type == "pending_start"]
    start_lines = [
        "| 批次 | 工序 | 工段 | 产品 | 开始类型 | 归属 |",
        "|------|------|------|------|----------|------|",
    ]
    for it in start_items:
        owner = it.batch_owner_name or "无主"
        if not it.can_operate:
            owner = f"{owner}（仅读）"
        start_lines.append(
            f"| {it.batch_no or '—'} | {it.node_name} | {it.stage_name or '—'} "
            f"| {it.product_name or '—'} | {it.start_type or 'normal'} | {owner} |"
        )

    # ── 可激活计划批次（仅第一工段负责人可见可操作项）──
    activatable = [p for p in planned.items if p.is_first_stage_owner]
    skipped = len(planned.items) - len(activatable)
    planned_lines = [
        "| 批次号 | 产品 | 路线 | 计划开始 | 计划结束 |",
        "|--------|------|------|----------|----------|",
    ]
    for p in activatable:
        planned_lines.append(
            f"| {p.batch_no} | {p.product_name or '—'} | {p.route_name} "
            f"| {p.planned_start or '—'} | {p.planned_end or '—'} |"
        )

    # ── 待结束工序（含单次执行负责人：无工段/工序身份的实际执行人）──
    complete_items = [it for it in wb.items if it.type == "pending_complete"]
    complete_lines = [
        "| 批次 | 工序 | 工段 | 产品 | 归属 |",
        "|------|------|------|------|------|",
    ]
    for it in complete_items:
        owner = it.batch_owner_name or "无主"
        if not it.can_operate:
            owner = f"{owner}（仅读）"
        complete_lines.append(
            f"| {it.batch_no or '—'} | {it.node_name} | {it.stage_name or '—'} "
            f"| {it.product_name or '—'} | {owner} |"
        )

    def _section(title: str, lines: list[str]) -> list[str]:
        return [f"## {title}", ""] + lines if len(lines) > 2 else [f"## {title}", "", "无"]

    parts: list[str] = []
    parts.extend(_section("一、待接收批次", receive_lines))
    parts.extend(_section("二、待开工工序", start_lines))
    parts.extend(_section("三、可激活计划批次", planned_lines))
    parts.extend(_section("四、待结束工序", complete_lines))
    if skipped:
        parts.append(f"\n另有 {skipped} 个计划批次不属于您负责的第一工段，不可激活。")
    return ToolResult(content="\n".join(parts))


@mcp.tool()
async def activate_planned_batch(operator_id: str, batch_no: str) -> ToolResult:
    """激活计划批次（已排产 → 待执行），即工作台排期区的「接收」按钮。

    仅路线第一工段负责人可激活。激活后批次进入待办区，
    可用 query_batch_progress 查看第一个工序，再用 change_batch_step_status 开始执行。

    Args:
        operator_id: 操作人的飞书 user_id
        batch_no: 计划批次号
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    batch = await repo.get_batch_by_no(db, batch_no)
    if not batch:
        return ToolResult(content=f"未找到批次：{batch_no}", is_error=True)

    try:
        refreshed = await workbench_service.activate_planned_batch(db, batch.id, user)
    except (ValueError, AppException) as e:
        return ToolResult(content=f"激活失败：{e}", is_error=True)
    except Exception:
        logger.exception("Unexpected error in activate_planned_batch for batch %s", batch_no)
        return ToolResult(content="激活失败：内部错误，请联系管理员", is_error=True)

    return ToolResult(
        content=(
            f"批次 **{batch_no}** 已接收（激活），状态变为"
            f"「{_BATCH_STATUS_CN.get(refreshed.status, refreshed.status)}」。\n\n"
            f"下一步：调用 `production_query_batch_progress` 查看第一个工序，"
            f"确认后可用 `production_change_batch_step_status` 开始执行。"
        )
    )


@mcp.tool()
async def receive_batch(
    operator_id: str,
    parent_batch_nos: list[str],
    children: list[dict[str, Any]],
    edge_id: str | None = None,
    deviation_reason: str | None = None,
) -> ToolResult:
    """接收批次：1 个父批次 = 分裂（1→N），多个父批次 = 合并（N→1）。

    对应工作台「待接收」卡片的接收按钮。edge_id 从 query_workbench_todo 的
    「接收边标识」列原样回传（合并卡片没有，不传）；不传 edge_id 时视为偏离，
    service 强制要求 deviation_reason（合并接收必须提供偏离原因）。

    Args:
        operator_id: 操作人的飞书 user_id
        parent_batch_nos: 父批次号列表，1 个=分裂，多个=合并
        children: 子批次列表 [{"batch_no": "…", "quantity": 12.5, "unit": "kg"}]，
            合并时只传 1 个；quantity/unit 可选
        edge_id: 接收边标识（query_workbench_todo 输出），合并/偏离不传
        deviation_reason: 偏离原因（合并或偏离场景必填）
    """
    db = get_db()
    user = await resolve_user(db, operator_id)

    # 参数预校验（Pydantic 原始文案对 LLM 不友好，先自查常见错误）
    if not children:
        return ToolResult(content="接收失败：至少需要指定一个子批次（children）", is_error=True)
    for c in children:
        if not c.get("batch_no"):
            return ToolResult(content="接收失败：每个子批次必须填写 batch_no（批次号）", is_error=True)

    parent_ids: list[uuid.UUID] = []
    missing: list[str] = []
    for no in parent_batch_nos:
        b = await repo.get_batch_by_no(db, no)
        if not b:
            missing.append(no)
        else:
            parent_ids.append(b.id)
    if missing:
        return ToolResult(
            content=f"接收失败：未找到父批次：{'、'.join(missing)}", is_error=True
        )

    parsed_edge: uuid.UUID | None = None
    if edge_id:
        try:
            parsed_edge = uuid.UUID(edge_id)
        except ValueError:
            return ToolResult(
                content=f"接收失败：无效的接收边标识「{edge_id}」", is_error=True
            )

    try:
        body = ReceiveAndStartIn(
            parent_batch_ids=parent_ids,
            edge_id=parsed_edge,
            deviation_reason=deviation_reason,
            children=[ChildBatchIn(**c) for c in children],
            start_execution=False,
            execution=None,
        )
    except ValidationError as e:
        first = e.errors()[0]
        return ToolResult(
            content=f"接收失败：子批次参数错误（{first.get('loc')}）", is_error=True
        )

    try:
        result = await workbench_service.receive_and_start(db, body, user)
    except (ValueError, AppException) as e:
        return ToolResult(content=f"接收失败：{e}", is_error=True)
    except Exception:
        logger.exception("Unexpected error in receive_batch for parents %s", parent_batch_nos)
        return ToolResult(content="接收失败：内部错误，请联系管理员", is_error=True)

    rows = [
        f"| {c['batch_no']} | {_BATCH_STATUS_CN.get(c['status'], c['status'])} |"
        for c in result["children"]
    ]
    return ToolResult(
        content=(
            "接收成功，创建子批次：\n\n"
            "| 批次号 | 状态 |\n"
            "|--------|------|\n"
            + "\n".join(rows)
            + "\n\n下一步：可用 `production_query_batch_progress` 查看下一工序，"
            "确认后用 `production_change_batch_step_status` 开始执行。"
        )
    )
