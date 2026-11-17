"""仓储飞书发送静默总闸（公共下沉，2026-11-17）。

原模块级开关 ``notification._dry_run`` 下沉至此：notification（卡片/文本）与
media（文件发送）共用同一判定，避免 media → notification 反向 import 成环。
语义不变——函数参数 dry_run 优先于模块级开关；开关由 env
WAREHOUSE_NOTIFY_DRY_RUN 启动时应用（apply_env_notify_gate）。

测试期静默口径（2026-11-13 用户拍板）：true = 机器人不发任何卡片/文本/文件，
只落日志并返回模拟成功（发送方话术依赖成功语义）；上线移除该 env 即恢复。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 模块级 dry_run 开关（默认关）；函数参数 dry_run 非 None 时优先
_dry_run: bool = False


def set_dry_run(value: bool) -> None:
    """设置模块级 dry_run 开关（影响未显式传参的全部发送函数）。"""
    global _dry_run
    _dry_run = value


def is_dry_run(dry_run: bool | None) -> bool:
    """函数参数优先于模块级开关。"""
    return _dry_run if dry_run is None else dry_run


def apply_env_notify_gate() -> None:
    """启动时按 env 应用通知总闸（2026-11-13 测试期静默口径）。

    WAREHOUSE_NOTIFY_DRY_RUN=true → 全部未显式传参的发送（卡片/文本/文件）
    只落日志不真发。用户拍板：五金功能全部测试完成前机器人不发任何通知；
    测试期设 true，上线时移除该 env 即恢复。
    """
    import os

    if str(os.environ.get("WAREHOUSE_NOTIFY_DRY_RUN", "")).strip().lower() in (
        "1", "true", "yes",
    ):
        set_dry_run(True)
        logger.info("仓储通知总闸已启用（WAREHOUSE_NOTIFY_DRY_RUN=true）：全部发送仅落日志")
