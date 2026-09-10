"""AI 配置读链薄封装（backend-design §8.3：resolver 保持纯净）。

- ``get_profile_config(profile) -> dict``：最终合并值（DB→env→registry 默认，字段级
  回退已展开），供 service/config.py / knowledge/* 读链消费（纯 config，含真实 api_key，
  仅内部使用、不回显）；
- ``get_profile(profile) -> ProfileView``：完整视图（label/config/api_key_masked/
  enabled/status/sources），供配置展示与测试断言。

本模块**不** import ``probe``（probe 反向依赖本模块，防环）、不 import knowledge/service。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.ai_config.store import ProfileView, store


def get_profile_config(profile: str) -> dict[str, Any]:
    """某 profile 最终生效配置（字段级回退已展开）；未知 profile 抛 ValueError。"""
    return store.get_profile_config(profile)


def get_profile(profile: str) -> ProfileView:
    """某 profile 合并视图（含 sources/status/脱敏 key）；未知 profile 抛 ValueError。"""
    return store.get_profile(profile)


__all__ = ["get_profile", "get_profile_config"]
