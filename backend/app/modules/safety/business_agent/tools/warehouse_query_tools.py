"""仓储查询工具适配（2-E 消费侧：安全 agent 挂仓储 4 个只读查询）。

机制：**直接 import**（非 MCP 回环）——仓储 4 个查询函数是纯 async 函数
（无 ctx、无 DB session 依赖，内部走 Bitable Adapter），本文件只包一层
``RunContext[SafetyDeps]`` 签名进安全名册；有 subsidy_tools 跨模块直连先例。

安全边界：4 个工具均为只读（TOOL_KIND=False）；调用经安全侧 execute_tool
管道（权限校验 + agent_tool_call 审计）。确认门不涉及（无写操作）。
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.warehouse.agent.tools import query as warehouse_query


async def query_stock(
    ctx: RunContext[SafetyDeps],
    keyword: str = "",
    qc_status: str = "",
    expiring_days: int | None = None,
) -> dict[str, Any]:
    """查询仓储物料库存明细（当前在库批次，跨模块查仓储）。

    用户问「仓库里某物料还有多少库存、存在哪、放行了没」时用本工具。
    返回每批次：物料名称、批号、剩余数量、单位、贮存位置、QA放行、
    入库日期、有效期/复验期。

    Args:
        keyword: 物料名称或批号关键词（模糊匹配），如「乙醇」「10407」；空查全部
        qc_status: QA放行状态过滤：放行 / 条件放行 / 否决
        expiring_days: 临期过滤：未来 N 天内到期，如 30 查 30 天内临期批次
    """
    return await warehouse_query.query_stock(
        keyword=keyword or None,
        qc_status=qc_status or None,
        expiring_days=expiring_days,
    )


async def query_material(ctx: RunContext[SafetyDeps], keyword: str) -> dict[str, Any]:
    """查询仓储物料主数据（名称/代码/级别/规格/生产商）。

    查某物料的基本信息、代码、复验期、包装规格时用本工具。

    Args:
        keyword: 物料名称/代码/ERP名称关键词（模糊匹配），如「硫酸」
    """
    return await warehouse_query.query_material(keyword)


async def query_movements(
    ctx: RunContext[SafetyDeps],
    material: str = "",
    direction: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    """查询仓储入库/出库流水（总账，按物料聚合汇总）。

    用户问「某段时间仓库入库/领用了哪些物料、量多少」时用本工具。

    Args:
        material: 物料名称关键词（模糊匹配），空查全部
        direction: inbound（入库）/ outbound（出库）/ both（默认）
        date_from: 起始日期 YYYY-MM-DD（含当天）
        date_to: 截止日期 YYYY-MM-DD（含当天）
    """
    return await warehouse_query.query_movements(
        material=material or None,
        direction=direction or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )


async def query_report(ctx: RunContext[SafetyDeps], report_type: str = "dead") -> dict[str, Any]:
    """查询仓储汇总报表清单（跨模块查仓储）。

    Args:
        report_type: dead=呆料批次清单（默认）/ unqualified=不合格物料清单
    """
    return await warehouse_query.query_report(report_type)
