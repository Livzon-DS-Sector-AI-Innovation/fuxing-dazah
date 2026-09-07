"""仓储模块对外 MCP Tools：4 个只读查询（S3 ticket 03，spec Implementation Decisions 4）。

安全边界：**只读暴露，不暴露任何写入工具**——外部 Agent 经 MCP 写入会绕过
机器人确认门（HITL），写入能力（submit_gmp / submit_outbound / submit_receipt
等）仅注册在飞书对话 Runner（agent/tools/），绝不进入 /mcp/warehouse 端点。

数据源：内部调用 agent/tools/query.py 的同名查询函数（规范化/分页/过滤逻辑
完全复用），经 WarehouseBitableAdapter 真查 Base，不依赖 DB 会话（DB session
由 MCPToolLoggingMiddleware 按调用粒度创建，此处仅用于平台级审计日志）。
"""

from __future__ import annotations

from typing import Any

from fastmcp.tools.base import ToolResult

from app.modules.warehouse.agent.tools import query as query_impl
from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("warehouse")


# ── 渲染辅助：查询实现结果 → ToolResult ──────────────────────────


def _render_table(rows: list[dict[str, Any]]) -> str:
    """字典列表 → markdown 表格（空列表返回占位符）。"""
    if not rows:
        return "（无记录）"
    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(row.get(h, "")) or "-" for h in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _error_result(result: dict[str, Any]) -> ToolResult:
    return ToolResult(
        content=f"查询失败：{result['error']}",
        structured_content=result,
        is_error=True,
    )


def _detail_result(result: dict[str, Any], title: str) -> ToolResult:
    """通用明细型查询结果（{total, records, note}）→ ToolResult。"""
    if "error" in result:
        return _error_result(result)
    records: list[dict[str, Any]] = result.get("records", [])
    total = result.get("total", 0)
    parts = [f"{title}：共 {total} 条", "", _render_table(records)]
    if total > len(records):
        parts.append(f"（仅显示前 {len(records)} 条）")
    if result.get("note"):
        parts.append(f"注：{result['note']}")
    return ToolResult(content="\n".join(parts), structured_content=result)


# ── Tool 1: 查询物料库存明细 ─────────────────────────────────────


@mcp.tool()
async def query_stock(
    keyword: str | None = None,
    qc_status: str | None = None,
    expiring_days: int | None = None,
) -> ToolResult:
    """
    查询物料库存明细（当前在库批次）。

    问「某种物料还有多少库存、存在哪、放行了没」时用本工具。
    返回每批次：物料名称、物料批号、剩余数量、单位、贮存位置、QA放行、
    入库日期、有效期至/复验期至。

    Args:
        keyword: 物料名称或批号关键词（模糊匹配），如「硫酸」「10407」；不传查全部
        qc_status: QA放行状态过滤，可选值：放行 / 条件放行 / 否决
        expiring_days: 临期过滤：未来 N 天内到有效期/复验期，如传 30 查 30 天内临期批次
    """
    result = await query_impl.query_stock(
        keyword=keyword, qc_status=qc_status, expiring_days=expiring_days
    )
    return _detail_result(result, "物料库存明细")


# ── Tool 2: 查询物料主数据 ───────────────────────────────────────


@mcp.tool()
async def query_material(keyword: str) -> ToolResult:
    """
    查询物料主数据（物料名称代码一览表）。

    查物料的基本信息/代码/级别/规格/生产商时用本工具。
    返回：代码、物料名称、级别、规格、物料大类、单位换算、生产商、
    免检物料、复验期、包装规格。

    Args:
        keyword: 物料名称/代码/ERP名称/使用品种关键词（模糊匹配），如「硫酸」
    """
    result = await query_impl.query_material(keyword)
    return _detail_result(result, "物料主数据")


# ── Tool 3: 查询入库/出库流水 ────────────────────────────────────


@mcp.tool()
async def query_movements(
    material: str | None = None,
    direction: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ToolResult:
    """
    查询物料入库/出库流水（总账），按物料聚合汇总数量。

    问「某段时间入库/领用了哪些物料、量多少」时用本工具。
    返回按物料聚合的汇总 + 最近明细（每方向前 10 条）。

    Args:
        material: 物料名称关键词（模糊匹配），不传查全部
        direction: 方向过滤，可选值：inbound（入库）/ outbound（出库）/ both（默认两者）
        date_from: 起始日期 YYYY-MM-DD（含当天），按入库日期/领用日期过滤
        date_to: 截止日期 YYYY-MM-DD（含当天）
    """
    result = await query_impl.query_movements(
        material=material, direction=direction, date_from=date_from, date_to=date_to
    )
    if "error" in result:
        return _error_result(result)
    parts = [f"出入库流水：共 {result.get('total', 0)} 条", ""]
    for section in result.get("summary", []):
        for label, rows in section.items():
            parts += [f"### {label}", _render_table(rows), ""]
    for section in result.get("records", []):
        for label, rows in section.items():
            parts += [f"### {label}（前 {len(rows)} 条）", _render_table(rows), ""]
    if result.get("note"):
        parts.append(f"注：{result['note']}")
    return ToolResult(content="\n".join(parts), structured_content=result)


# ── Tool 4: 查询汇总报表 ─────────────────────────────────────────


@mcp.tool()
async def query_report(report_type: str = "dead") -> ToolResult:
    """
    查询汇总报表清单。

    Args:
        report_type: 报表类型，可选值：
            - dead：呆料批次清单（入库总账中呆料判断=是，默认）
            - unqualified：不合格物料清单（物料/不合格项目/处理方式/到货日期）
    """
    result = await query_impl.query_report(report_type)
    title = str(result.get("report_name", "汇总报表")) if "error" not in result else ""
    return _detail_result(result, title)
