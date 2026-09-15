"""特殊作业日报「直读多维表格」模式（不落库）。

入口：
- ``bitable_repo.fetch_day_views``  按日期批量直读 -> 视图对象 -> 风险判定
- ``daily.run``                     日报编排（直读 -> 判定 -> 渲染 -> 回写 -> 推送）

列契约见 ``special_op_direct.contract``；开关见 ``special_op_direct.config``
（全部默认关闭，灰度上线）。

实现说明：本 ``__init__`` **不做任何 eager import**（PEP 562 惰性加载），
避免 ``import special_op_direct`` 时把 ORM / AI 插件等重依赖一并拉起来，
也避免与 ``scheduler`` 形成导入环。
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, tuple[str, str]] = {
    "AnalystLike": ("daily", "AnalystLike"),
    "GroupPusher": ("daily", "GroupPusher"),
    "run": ("daily", "run"),
    "RecordWriter": ("bitable_repo", "RecordWriter"),
    "WritebackResult": ("bitable_repo", "WritebackResult"),
    "SpecialOpDirectError": ("bitable_repo", "SpecialOpDirectError"),
    "SpecialOpView": ("bitable_repo", "SpecialOpView"),
    "assess_view": ("bitable_repo", "assess_view"),
    "day_filter": ("bitable_repo", "day_filter"),
    "day_window": ("bitable_repo", "day_window"),
    "fetch_day_views": ("bitable_repo", "fetch_day_views"),
    "to_utc": ("bitable_repo", "to_utc"),
    "query_records": ("query", "query_records"),
    "to_query_view": ("query", "to_query_view"),
    "date_window": ("query", "date_window"),
    "to_view": ("bitable_repo", "to_view"),
    "writeback_risk_levels": ("bitable_repo", "writeback_risk_levels"),
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(f"{__name__}.{module_name}")
    value = getattr(module, attr)
    globals()[name] = value  # 缓存，后续直接命中
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
