"""仓储直读层（2026-11-04 直读改造：展示/分析类端点直读生产 Base + TTL 缓存）。"""

from app.modules.warehouse.direct import config, query, reader, service  # noqa: F401

__all__ = ["config", "query", "reader", "service"]
