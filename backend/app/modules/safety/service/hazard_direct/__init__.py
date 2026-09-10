"""隐患系统「直读多维表格」模式（不落库）。

入口：
- ``run_ai_analysis_round``   ① 隐患AI分析轮询
- ``run_review_round``        ② AI整改审核轮询
- ``run_supervision_round``   ③ 督办等级计算（轮询）
- ``send_bulletin``           ④ 隐患督办通报（周四 08:30）
- ``send_progress_dunning_dynamic`` ⑤ 未更新进展催办（周三 10:00，动态名单）

由 ``scheduler.scheduled_task_loop`` 启动 ``hazard_direct_loop``（①②③）；
④⑤ 仍走调度器的定点任务，但数据源同为多维表格。
Agent 工具与调度器共用同一套 service 函数，避免逻辑分叉。

开关见 ``config`` 模块（全部默认关闭，灰度上线）。

实现说明：本 ``__init__`` **不做任何 eager import**（PEP 562 惰性加载），
避免 ``import hazard_direct.config`` 时把 AI 插件 / ORM 等重依赖一并拉起来，
也避免与 ``scheduler`` 形成导入环。
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, tuple[str, str]] = {
    "RoundResult": ("ai_analysis", "RoundResult"),
    "run_ai_analysis_round": ("ai_analysis", "run_ai_analysis_round"),
    "ReviewRoundResult": ("review", "ReviewRoundResult"),
    "run_review_round": ("review", "run_review_round"),
    "SupervisionRoundResult": ("supervision", "SupervisionRoundResult"),
    "run_supervision_round": ("supervision", "run_supervision_round"),
    "build_bulletin": ("bulletin", "build_bulletin"),
    "send_bulletin": ("bulletin", "send_bulletin"),
    "send_progress_dunning_dynamic": (
        "progress_dunning",
        "send_progress_dunning_dynamic",
    ),
    "resolve_dunning_recipients": (
        "progress_dunning",
        "resolve_dunning_recipients",
    ),
    "hazard_direct_loop": ("loop", "hazard_direct_loop"),
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
