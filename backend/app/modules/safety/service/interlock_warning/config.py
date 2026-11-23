"""开关（app_config KV：env > DB 活行 > 代码默认）。"""

from __future__ import annotations

from app.modules.safety.app_config.store import store as _app_config_store

TOGGLE_KEY = "SAFETY_INTERLOCK_RED_WARNING_ENABLED"


def enabled() -> bool:
    """红色预警私发提醒总开关（默认开，2026-11-18 用户拍板）。"""
    return _app_config_store.get_bool(TOGGLE_KEY, True)
