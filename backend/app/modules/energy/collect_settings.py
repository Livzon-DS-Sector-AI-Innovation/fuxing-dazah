"""Energy auto-collect runtime settings.

These module-level variables allow the frontend to toggle auto-collect
and adjust the collection interval at runtime without restarting the server.
The scheduler reads these on every tick; API endpoints read/write them.

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
_auto_collect_interval_seconds: int = 3600
_initialized: bool = False


def _init_from_config() -> None:
    global _auto_collect_enabled, _auto_collect_interval_seconds, _initialized
    if _initialized:
        return
    try:
        from app.core.config import get_settings

        settings = get_settings()
        _auto_collect_enabled = settings.ENERGY_AUTO_COLLECT_ENABLED
        _auto_collect_interval_seconds = settings.ENERGY_AUTO_COLLECT_INTERVAL_SECONDS
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


def get_auto_collect_interval_seconds() -> int:
    _init_from_config()
    return _auto_collect_interval_seconds


def set_auto_collect_interval_seconds(seconds: int) -> None:
    global _auto_collect_interval_seconds
    _init_from_config()
    _auto_collect_interval_seconds = max(3600, min(seconds, 86400))  # 1h ~ 24h
