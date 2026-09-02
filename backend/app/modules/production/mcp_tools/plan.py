"""计划查询 — 查询计划单内预计某日结束的计划项。"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from fastmcp.tools.base import ToolResult

from app.modules.production import repository as repo
from app.modules.production.mcp_tools._helpers import _SHANGHAI_TZ
from app.modules.production.schemas.planning import ScheduleViewItem
from app.modules.production.service import planning_service
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("production")


@mcp.tool()
async def query_plan_items_ending_on_date(
    date_text: str,
    product_keyword: str | None = None,
) -> ToolResult:
    """查询指定日期在执行中计划单内预计结束的计划项。

    日期必须为 YYYY/MM/DD 格式，例如 "2026/08/24"。
    产品关键词可选，按产品名称、产品编码和计划项产品快照进行不区分大小写的子串匹配。
    仅返回状态为 released（已下达、执行中）的计划单中的计划项。

    Args:
        date_text: 目标日期，格式 YYYY/MM/DD，例如 "2026/08/24"
        product_keyword: 可选产品名称或产品编码简称
    """
    try:
        target_date = datetime.strptime(date_text.strip(), "%Y/%m/%d").date()
    except ValueError:
        return ToolResult(
            content=f"无法识别日期 `{date_text}`，请输入 YYYY/MM/DD 格式，例如 2026/08/24。",
            is_error=True,
        )

    day_start = datetime.combine(target_date, time.min, tzinfo=_SHANGHAI_TZ)
    day_end = day_start + timedelta(days=1)
    db = get_db()
    schedule_items = await planning_service.get_schedule_view(
        db=db,
        from_time=day_start,
        to_time=day_end,
        equipment_id=None,
    )

    product_ids = list({item.product_id for item in schedule_items})
    products = await repo.get_products_by_ids(db, product_ids)
    products_by_id = {product.id: product for product in products}
    keyword = product_keyword.casefold() if product_keyword else ""

    def matches_product(item: ScheduleViewItem) -> bool:
        if not keyword:
            return True
        product = products_by_id.get(item.product_id)
        candidates = [item.product_name]
        if product:
            candidates.extend([product.product_name, product.product_code or ""])
        return any(
            keyword in candidate.casefold()
            for candidate in candidates
            if candidate
        )

    matching_items = [
        item
        for item in schedule_items
        if item.order_status == "released"
        and item.planned_end is not None
        and item.planned_end.astimezone(_SHANGHAI_TZ).date() == target_date
        and matches_product(item)
    ]
    matching_items.sort(key=lambda item: (item.planned_end, item.order_no, item.item_no))

    product_hint = f" · 产品：{product_keyword}" if product_keyword else ""
    title = f"## {target_date:%Y-%m-%d} 预计结束的计划项{product_hint}"
    if not matching_items:
        return ToolResult(
            content=f"{title}\n\n当天没有符合条件的执行中计划项。"
        )

    lines = [
        title,
        "",
        f"> 在 **{len({item.order_no for item in matching_items})}** 张执行中计划单中，共找到 **{len(matching_items)}** 个计划项。",
        "",
        "| 预计结束 | 计划单 | 计划项 | 产品 | 批次 | 数量 | 设备/产线 | 状态 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in matching_items:
        assert item.planned_end is not None
        planned_end = item.planned_end.astimezone(_SHANGHAI_TZ).strftime("%H:%M")
        quantity = (
            f"{item.planned_quantity:g} {item.unit or ''}"
            if item.planned_quantity is not None
            else "—"
        )
        item_status = {
            "allocated": "已分配",
            "in_progress": "进行中",
            "completed": "已完成",
            "scheduled": "已排程",
        }.get(item.item_status, item.item_status)
        lines.append(
            f"| {planned_end} | `{item.order_no}` | #{item.item_no} | {item.product_name} | "
            f"`{item.batch_no or '—'}` | {quantity} | {item.equipment_id or '—'} | {item_status} |"
        )

    return ToolResult(content="\n".join(lines))
