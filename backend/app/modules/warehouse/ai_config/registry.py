"""AI 模型配置注册表 — agent / agent_backup 双 profile 的代码唯一事实源。

本文件是：

1. **migration 播种的来源**（单向导出，禁止手抄，防双份常量漂移）；
2. **运行时 fallback**：DB 缺行/某字段为空时 store 回退到
   ``default_config`` 与 ``env_map``（字段级回退：DB 活行 → env → registry 默认）。

- ``default_config``：仅固化非敏感项；``api_key`` 一律空串
  （密钥不落代码/不播种，由管理员在配置页录入）；
- ``env_map``：field -> env 变量名；``""`` 表示该字段无 env 兜底。

模型 ID 平台差异（2026-09-14 实测）：官方网关 api.deepseek.com 的 flash 通道
唯一 ID 为 ``deepseek-flash``（即最新 DeepSeek V4.1 Flash 别名，无独立 v4.1
型号）；公司代理上显式 ID 为 ``deepseek-v4.1-flash``（备用链路使用）。

本模块零副作用导入（不 import store/service/feishu 等包），migration 可直接引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# 2 组 profile 字面量（DB 只能改值不能新增 profile）
ProfileName = Literal["agent", "agent_backup"]


@dataclass(frozen=True)
class ProfileInfo:
    """单组 AI 模型配置（profile 是稳定 key，DB 只能改值不能新增 profile）。"""

    profile: ProfileName
    label: str                          # 中文标签
    default_usage: str                  # 用途说明
    default_config: dict[str, Any]      # 仅固化非敏感项；api_key 一律 ""
    field_names: tuple[str, ...]        # 允许写到 config 的字段（trim/校验用）
    env_map: dict[str, str]             # field -> env 变量名；"" 表示该字段无 env 兜底


_PROFILES: tuple[ProfileInfo, ...] = (
    # ── agent 主模型（视觉 + 文本单模型位）──────────────────────
    ProfileInfo(
        profile="agent",
        label="Agent 主模型",
        default_usage="仓库助手对话与送货单视觉识别（tool-calling + vision 单模型位）",
        default_config={
            "api_key": "",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-flash",
            "temperature": 0.1,
            "max_tokens": 16384,
            "timeout": 120,
        },
        field_names=("api_key", "base_url", "model", "temperature", "max_tokens", "timeout"),
        env_map={
            "api_key": "WAREHOUSE_AGENT_API_KEY",
            "base_url": "WAREHOUSE_AGENT_BASE_URL",
            "model": "WAREHOUSE_AGENT_MODEL",
            "temperature": "",          # 无 env（代码默认）
            "max_tokens": "",           # 无 env（代码默认）
            "timeout": "WAREHOUSE_AGENT_TIMEOUT",
        },
    ),
    # ── agent_backup 备用（降级模型）────────────────────────────
    ProfileInfo(
        profile="agent_backup",
        label="Agent 备用",
        default_usage="主模型调用失败（401/429/5xx/超时）时的降级模型；未配置则无降级",
        default_config={
            "api_key": "",
            "base_url": "",
            "model": "",
            "timeout": 120,
        },
        field_names=("api_key", "base_url", "model", "timeout"),
        env_map={
            "api_key": "WAREHOUSE_AGENT_BACKUP_API_KEY",
            "base_url": "WAREHOUSE_AGENT_BACKUP_BASE_URL",
            "model": "WAREHOUSE_AGENT_BACKUP_MODEL",
            "timeout": "",
        },
    ),
)

# 构造时断言：profile 唯一 / field_names 唯一 / default_config 键 ⊆ field_names /
# api_key 默认空串（重复 key 会在 dict 推导时静默覆盖，故显式校验）
REGISTRY: dict[str, ProfileInfo] = {p.profile: p for p in _PROFILES}
assert len(REGISTRY) == len(_PROFILES), "AI profile 注册表存在重复 profile"
for _info in _PROFILES:
    assert len(_info.field_names) == len(set(_info.field_names)), (
        f"AI profile {_info.profile} 存在重复 field name"
    )
assert all(set(p.default_config) <= set(p.field_names) for p in _PROFILES), (
    "AI profile 存在 default_config 键不在 field_names 内"
)
assert all(p.default_config.get("api_key", "") == "" for p in _PROFILES), (
    "AI profile api_key 默认必须为空串（密钥不播种）"
)


def get_profile(profile: str) -> ProfileInfo:
    """未知 profile 抛 ValueError（消息以「未知 profile」开头，404 语义）。"""
    info = REGISTRY.get(profile)
    if info is None:
        raise ValueError(f"未知 profile: {profile}")
    return info


def iter_profiles() -> tuple[ProfileInfo, ...]:
    """遍历全部 profile，供 migration 播种 + 断言测试。"""
    return _PROFILES


PROFILE_KEYS: tuple[str, ...] = tuple(p.profile for p in _PROFILES)
