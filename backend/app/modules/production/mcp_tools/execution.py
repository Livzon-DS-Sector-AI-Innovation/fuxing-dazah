"""工序执行操作 — 开始/结束工序、补录工序字段。"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.tools.base import ToolResult

from app.core.exceptions import AppException
from app.modules.production.mcp_tools._helpers import (
    _BATCH_STATUS_CN,
    _SHANGHAI_TZ,
    _field_dict_to_in,
    _get_latest_execution,
    _resolve_batch_and_node,
)
from app.modules.production.schemas import ExecutionCompleteIn, ExecutionStartIn
from app.modules.production.service.execution_service import (
    backfill_execution_fields,
    complete_execution,
    compute_missing_required_fields,
    start_execution,
)
from app.platform.identity.mcp_tools import resolve_user
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

logger = logging.getLogger(__name__)
mcp = get_module_mcp("production")


@mcp.tool()
async def change_batch_step_status(
    operator_id: str,
    batch_no: str,
    step_name: str,
    action: str,
    field_values: list[dict[str, Any]] | None = None,
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
            is_error=True,
        )

    db = get_db()
    user = await resolve_user(db, operator_id)

    try:
        batch, node = await _resolve_batch_and_node(db, batch_no, step_name)
    except ValueError as e:
        return ToolResult(content=f"{e}", is_error=True)

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
        except (ValueError, AppException) as e:
            # AppException 覆盖权限拒绝（含批次归属校验）与业务校验，直接透出文案；
            # is_error 标记让中间件回滚会话——异常前可能已有部分写操作入会话
            return ToolResult(content=f"开始工序失败：{e}", is_error=True)
        except Exception:
            logger.exception("Unexpected error in start_execution for batch %s", batch_no)
            return ToolResult(content="开始工序失败：内部错误，请联系管理员", is_error=True)

        started_str = execution.started_at.astimezone(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")
        msg = (
            f"批次 **{batch_no}** 的工序「**{step_name}**」已开始。\n\n"
            f"| 项目 | 值 |\n"
            f"|------|----|\n"
            f"| 执行序号 | 第 {execution.execution_seq} 次 |\n"
            f"| 开始时间 | {started_str} |\n"
            f"| 负责人 | {user.name} |\n"
            f"| 批次状态 | {_BATCH_STATUS_CN.get(batch.status, batch.status)} |"
        )
        return ToolResult(content=msg)

    # action == "end"
    in_progress_ex = await _get_latest_execution(db, batch.id, node.id, status="in_progress")
    if not in_progress_ex:
        return ToolResult(
            content=(
                f"批次 **{batch_no}** 的工序「**{step_name}**」没有进行中的执行。\n"
                f"请先开始该工序后，再进行结束操作。"
            ),
            is_error=True,
        )

    end_payload = ExecutionCompleteIn(field_values=fvs)
    try:
        completed_ex = await complete_execution(db, in_progress_ex.id, end_payload, user)
    except (ValueError, AppException) as e:
        return ToolResult(content=f"结束工序失败：{e}", is_error=True)
    except Exception:
        logger.exception("Unexpected error in complete_execution for batch %s", batch_no)
        return ToolResult(content="结束工序失败：内部错误，请联系管理员", is_error=True)

    finished = (
        completed_ex.finished_at.astimezone(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")
        if completed_ex.finished_at
        else "—"
    )
    started_str = completed_ex.started_at.astimezone(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")

    # 检查缺填的必填字段
    missing = await compute_missing_required_fields(db, [completed_ex])
    missing_fields = missing.get(completed_ex.id, [])

    msg = (
        f"批次 **{batch_no}** 的工序「**{step_name}**」已结束。\n\n"
        f"| 项目 | 值 |\n"
        f"|------|----|\n"
        f"| 执行序号 | 第 {completed_ex.execution_seq} 次 |\n"
        f"| 开始时间 | {started_str} |\n"
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


@mcp.tool()
async def backfill_step_fields(
    operator_id: str,
    batch_no: str,
    step_name: str,
    field_values: list[dict[str, Any]],
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
        return ToolResult(content=f"{e}", is_error=True)

    if batch.status in ("completed", "cancelled"):
        return ToolResult(
            content=f"批次 {batch_no} 已{_BATCH_STATUS_CN.get(batch.status, batch.status)}，禁止补录。",
            is_error=True,
        )

    execution = await _get_latest_execution(db, batch.id, node.id, status="completed")
    if not execution:
        return ToolResult(
            content=f"批次 {batch_no} 的工序「{step_name}」没有已完成的执行，无法补录。",
            is_error=True,
        )

    fvs = [_field_dict_to_in(f) for f in field_values]
    try:
        await backfill_execution_fields(db, execution.id, fvs, user)
    except (ValueError, AppException) as e:
        # AppException 覆盖权限拒绝（含批次归属校验）与业务校验，直接透出文案
        return ToolResult(content=f"补录失败：{e}", is_error=True)
    except Exception:
        logger.exception("Unexpected error in backfill_execution_fields for batch %s", batch_no)
        return ToolResult(content="补录失败：内部错误，请联系管理员", is_error=True)

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
