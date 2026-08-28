"""Meter HTTP API 层。

按资源拆分为子模块；import 顺序即路由注册顺序。
对外只导出 ``router``（``from app.modules.meter.api import router`` 保持不变）。
"""

from app.modules.meter.api import (  # noqa: F401  （导入即注册路由）
    alerts,
    departments,
    gas_detectors,
    instruments,
    report_matching,
    reports,
    settings,
)
from app.modules.meter.api._router import router

__all__ = ["router"]
