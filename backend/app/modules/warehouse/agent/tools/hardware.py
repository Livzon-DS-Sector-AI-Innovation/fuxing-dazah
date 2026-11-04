"""五金库 agent 工具（M1：query_hardware_stock）。

本地 DB 直查（第一个系统原生仓储域，不走 Bitable adapter）——上下文/
会话模式与 supplier.py 相同：``_db_session`` 注入口（测试 monkeypatch），
失败返回 ``{"error": ...}`` 不中断 Runner 循环。

口径与 service.list_stock_rows 一致：available=on_hand−reserved，
预警=available<safety_stock（设计 §三）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareMovement,
)

logger = logging.getLogger(__name__)

DETAIL_LIMIT = 10  # 默认返回前 N 条 + total（与 query.py 分页约定一致）

QUERY_HARDWARE_STOCK_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_hardware_stock",
            "description": (
                "查询五金库实时库存（本地权威账）。返回物料的可用量 available、"
                "在手 on_hand、预扣 reserved、安全库存与是否预警。"
                "支持按名称/规格/编码关键词搜索（如「DN25 阀门」「304不锈钢管 φ25」）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "物资名称/规格/编码关键词，可空（空=看全部低库存或前 N 条）",
                    },
                    "low_only": {
                        "type": "boolean",
                        "description": "只看安全库存预警物料（默认 false）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数上限，默认 10",
                    },
                },
                "required": [],
            },
        },
    }
]


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


async def query_hardware_stock(
    keyword: str | None = None, low_only: bool = False, limit: int = DETAIL_LIMIT
) -> dict[str, Any]:
    """五金库库存查询（只读；任何异常转 error 结果自修复）。"""
    try:
        limit = max(1, min(int(limit or DETAIL_LIMIT), 50))
        async with _db_session() as db:
            rows, total = await hw_service.list_stock_rows(
                db,
                keyword=(keyword or "").strip() or None,
                managed_class=None,
                low_only=low_only,
                page=1,
                page_size=limit,
            )
            items = [
                {
                    "name": r["material"].name,
                    "spec": r["material"].spec or "",
                    "unit": r["material"].unit,
                    "code": r["material"].code or "（待回填）",
                    "category": r["material"].category,
                    "managed_class": r["material"].managed_class,
                    "available": float(r["available"]),
                    "on_hand": float(r["on_hand"]),
                    "reserved": float(r["reserved"]),
                    "safety_stock": float(r["material"].safety_stock),
                    "low_warning": bool(r["is_low"]),
                }
                for r in rows
            ]
            low_total = 0
            if not low_only:
                low_rows, _ = await hw_service.list_stock_rows(
                    db, managed_class="stocked", low_only=True, page=1, page_size=5000
                )
                low_total = len(low_rows)
            return {
                "keyword": keyword or "",
                "total": total,
                "returned": len(items),
                "low_warning_total": low_total if not low_only else total,
                "items": items,
                "note": (
                    "available=可用（在手−预扣）；low_warning=true 表示可用量低于安全库存。"
                    "direct 类不占库存（到货直发），其 available 恒为 0 属正常。"
                    if not low_only
                    else "已按安全库存预警过滤。"
                ),
            }
    except Exception as exc:  # noqa: BLE001 — 工具层兜底，不中断 Runner
        logger.exception("query_hardware_stock failed")
        return {"error": f"五金库库存查询失败: {exc}"}


HARDWARE_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "query_hardware_stock": query_hardware_stock,
}

HARDWARE_TOOLS_SCHEMA: list[dict[str, Any]] = QUERY_HARDWARE_STOCK_SCHEMA
