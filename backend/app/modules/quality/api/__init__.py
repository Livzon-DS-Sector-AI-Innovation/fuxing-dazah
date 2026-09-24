"""Quality API 路由包（api.py 1715 行拆分：路由按资源域分模块）。

注册顺序与拆分前完全一致（按资源域分组，原文件内即为该顺序）：
模块信息 → 液相 → 模板 → 产品 → 报告 → 汇总 → 标准 → 任务。
对外导出 router，装配入口（app/api/router.py）的 import 路径不变。
"""

from app.modules.quality.api import (  # noqa: F401
    _lc,
    _module_info,
    _products,
    _reports,
    _standards,
    _summary,
    _tasks,
    _templates,
)
from app.modules.quality.api._common import router

__all__ = ["router"]
