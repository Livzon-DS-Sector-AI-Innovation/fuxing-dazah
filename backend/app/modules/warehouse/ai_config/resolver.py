"""AI 配置读链封装 — 业务代码的取值入口。

``get_profile_config(profile)`` 返回最终合并值副本（含真实 api_key，**仅内部
使用，绝不上 API 响应**）。每次调用经 store 缓存（TTL 60s / 写后失效），
配置变更即时生效。
"""

from __future__ import annotations

from typing import Any

from app.modules.warehouse.ai_config.store import store as _store


def get_profile_config(profile: str) -> dict[str, Any]:
    """某 profile 的最终合并配置（副本；含真实 api_key，仅内部使用）。"""
    return _store.get_profile_config(profile)


__all__ = ["get_profile_config"]
