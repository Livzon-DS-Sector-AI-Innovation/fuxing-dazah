"""工序字段查询 — 查询批次工序需要填报的字段定义。"""

from __future__ import annotations

from fastmcp.tools.base import ToolResult

from app.modules.production import repository as repo
from app.modules.production.mcp_tools._helpers import (
    _DATA_TYPE_CN,
    _STATUS_MARK,
    _format_field_value,
    _get_latest_execution,
    _resolve_batch_and_node,
)
from app.modules.production.models import NodeFieldValue
from app.modules.production.service.execution_service import (
    compute_missing_required_fields,
)
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("production")


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
        return ToolResult(content=f"无效阶段 `{phase}`，仅支持 start 或 end。", is_error=True)

    db = get_db()
    try:
        batch, node = await _resolve_batch_and_node(db, batch_no, step_name)
    except ValueError as e:
        return ToolResult(content=f"{e}", is_error=True)
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
