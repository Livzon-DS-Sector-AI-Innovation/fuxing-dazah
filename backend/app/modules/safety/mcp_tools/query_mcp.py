"""安全模块对外 MCP Tools：5 个只读查询（2-E 暴露侧）。

安全边界：**只读暴露，不暴露任何写入工具**——对齐仓储先例（结构性排除：
只 import 查询实现核，写工具根本不进入本模块）。外部 Agent 经 MCP 写入
会绕过机器人确认门（PendingAction HITL），写入能力仅存在于
business_agent/tools/（经 execute_tool 管道 + requires_approval 挂起）。

数据源：内部复用 business_agent/tools/read_tools.py 的同名查询实现核
（直读多维表格 / 本地同步库 / RAG 收录管线，过滤/分页逻辑零复制），
以轻量 shim ctx 注入 MCP 请求级 DB 会话（平台 MCPToolLoggingMiddleware
按调用粒度创建/提交，并写平台审计日志）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastmcp.tools.base import ToolResult

from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("safety")


def _shim_ctx() -> SimpleNamespace:
    """构造只含 db 的轻量 ctx（read_tools 实现核仅消费 ctx.deps.db）。"""
    from app.platform.mcp.deps import get_db

    return SimpleNamespace(
        deps=SimpleNamespace(
            db=get_db(), role="mcp_agent", session_id=None,
            channel="mcp", person=None,
        )
    )


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


def _records_result(result: dict[str, Any], title: str, records_key: str) -> ToolResult:
    """明细型结果（{total, <records_key>}）→ ToolResult。"""
    if "error" in result:
        return _error_result(result)
    records = result.get(records_key) or []
    total = result.get("total", len(records))
    parts = [f"{title}：共 {total} 条", "", _render_table(records)]
    if total > len(records):
        parts.append(f"（仅显示前 {len(records)} 条）")
    if result.get("note"):
        parts.append(f"注：{result['note']}")
    return ToolResult(content="\n".join(parts), structured_content=result)


# ── Tool 1: 查询隐患记录 ─────────────────────────────────────────


@mcp.tool()
async def query_hazards(
    department: str = "",
    status: str = "",
    rectification_status: str = "",
    keyword: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 20,
) -> ToolResult:
    """
    查询安全隐患记录（直读多维表格「隐患登记表」）。

    可按部门、隐患状态、整改状态、关键词、检查日期范围筛选。

    Args:
        department: 部门名称（如「生产部」）
        status: 隐患状态（open/closed）
        rectification_status: 整改状态（pending 未关闭 / closed 已关闭）
        keyword: 关键词（匹配隐患描述或编号）
        date_from: 起始日期 ISO（按检查日期）
        date_to: 截止日期 ISO（按检查日期）
        limit: 返回条数上限（默认 20）
    """
    from app.modules.safety.business_agent.tools.read_tools import (
        query_hazards as impl,
    )

    result = await impl(
        _shim_ctx(), department=department, status=status,
        rectification_status=rectification_status, keyword=keyword,
        date_from=date_from, date_to=date_to, limit=limit,
    )
    return _records_result(result, "隐患记录", "records")


# ── Tool 2: 隐患统计 ─────────────────────────────────────────────


@mcp.tool()
async def query_hazard_stats(
    date_from: str = "",
    date_to: str = "",
    department: str = "",
) -> ToolResult:
    """
    获取隐患统计精确计数（总数/未关闭/各部门分布/整改完成率）。

    统计类问题应优先用本工具而不是逐条拉取后估算。

    Args:
        date_from: 起始日期 ISO（按检查日期）
        date_to: 截止日期 ISO
        department: 部门（不传统计全部）
    """
    from app.modules.safety.business_agent.tools.read_tools import (
        query_hazard_stats as impl,
    )

    result = await impl(_shim_ctx(), date_from=date_from, date_to=date_to,
                        department=department)
    if "error" in result:
        return _error_result(result)
    lines = [f"隐患统计（{department or '全部部门'}）："]
    for key, value in result.items():
        if key != "error":
            lines.append(f"- {key}: {value}")
    return ToolResult(content="\n".join(lines), structured_content=result)


# ── Tool 3: 危化品库存台账 ───────────────────────────────────────


@mcp.tool()
async def query_chemical_inventory(
    department: str | None = None,
    material_name: str | None = None,
    limit: int = 50,
) -> ToolResult:
    """
    查询危化品库存台账（部门/存放部位/物料/库存数量/上限/风险标记）。

    Args:
        department: 部门（如「仓储部」「QC」）
        material_name: 物料名称模糊匹配（如「乙醇」）
        limit: 返回条数上限（默认 50）
    """
    from app.modules.safety.business_agent.tools.read_tools import (
        query_chemical_inventory as impl,
    )

    result = await impl(_shim_ctx(), department=department,
                        material_name=material_name, limit=limit)
    return _records_result(result, "危化品库存台账", "items")


# ── Tool 4: 特殊作业判定明细 ─────────────────────────────────────


@mcp.tool()
async def query_special_op_records(
    department: str = "",
    date_from: str = "",
    date_to: str = "",
    operation_type: str = "",
    daily_risk_level: str = "",
    report_type: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> ToolResult:
    """
    查询全厂特殊作业判定明细（动火/受限空间/高处/吊装等，含每日风险判定）。

    Args:
        department: 部门（子串匹配，如「五部」）
        date_from: 起始日期 ISO（按作业计划开始时间）
        date_to: 结束日期 ISO
        operation_type: 动火/受限空间/高处/吊装/临时用电/动土/断路/盲板抽堵
        daily_risk_level: 高/中/低
        report_type: 计划内/计划外
        keyword: 内容/地点/申请编号模糊匹配
        page: 页码（默认 1）
        page_size: 每页条数（默认 20，最大 100）
    """
    from app.modules.safety.business_agent.tools.read_tools import (
        query_special_op_records as impl,
    )

    result = await impl(
        _shim_ctx(), department=department, date_from=date_from, date_to=date_to,
        operation_type=operation_type, daily_risk_level=daily_risk_level,
        report_type=report_type, keyword=keyword, page=page, page_size=page_size,
    )
    return _records_result(result, "特殊作业判定明细", "records")


# ── Tool 5: 最新法规动态 ─────────────────────────────────────────


@mcp.tool()
async def query_latest_regulations(
    view: str = "crawl",
    limit: int | None = None,
    days: int = 30,
    impact_level: str = "",
    business_domain: str = "",
) -> ToolResult:
    """
    查询最新安全法规标准动态（两个视角）。

    Args:
        view: crawl=爬取视角（最近抓取的法规更新）/ ingested=收录管线视角（含 AI 判定摘要）
        limit: 返回条数上限（缺省 crawl=10 / ingested=5，最大 20）
        days: 最近 N 天（默认 30，仅 crawl 视角）
        impact_level: 影响等级：高/中/低（仅 crawl 视角）
        business_domain: 业务领域：安全生产/职业健康/环保/消防/危化品/特种设备（仅 crawl 视角）
    """
    from app.modules.safety.business_agent.tools.read_tools import (
        query_latest_regulations as impl,
    )

    result = await impl(
        _shim_ctx(), view=view, limit=limit, days=days,
        impact_level=impact_level, business_domain=business_domain,
    )
    if "error" in result:
        return _error_result(result)
    items = result.get("items") or result.get("records") or []
    title = "最新法规动态（爬取视角）" if view == "crawl" else "最新收录法规"
    return _records_result({**result, "records": items}, title, "records")
