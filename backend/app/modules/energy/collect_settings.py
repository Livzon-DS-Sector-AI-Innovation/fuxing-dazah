"""Energy auto-collect runtime settings.

These module-level variables allow the frontend to toggle auto-collect
at runtime without restarting the server.
The scheduler reads this on every tick; API endpoints read/write it.

Defaults are loaded from app config (env vars) on first import.
"""

from __future__ import annotations

import logging
from datetime import timedelta, timezone

logger = logging.getLogger(__name__)

# 中国标准时间 UTC+8（scheduler / service 共用）
CST = timezone(timedelta(hours=8))

# ── Runtime state (module-level, survives until server restart) ──
_auto_collect_enabled: bool = False
_daily_collect_time: str = "08:00"
_initialized: bool = False


def _init_from_config() -> None:
    global _auto_collect_enabled, _initialized
    if _initialized:
        return
    try:
        from app.core.config import get_settings

        settings = get_settings()
        _auto_collect_enabled = settings.ENERGY_AUTO_COLLECT_ENABLED
    except Exception:
        logger.warning("Failed to load energy collect settings from config, using defaults")
    _initialized = True


def get_auto_collect_enabled() -> bool:
    _init_from_config()
    return _auto_collect_enabled


def set_auto_collect_enabled(enabled: bool) -> None:
    global _auto_collect_enabled
    _init_from_config()
    _auto_collect_enabled = enabled


def get_daily_collect_time() -> str:
    _init_from_config()
    return _daily_collect_time


def set_daily_collect_time(value: str) -> None:
    global _daily_collect_time
    _init_from_config()
    _daily_collect_time = value
