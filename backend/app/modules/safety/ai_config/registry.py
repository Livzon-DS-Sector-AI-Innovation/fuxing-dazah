"""AI 模型配置注册表 — 5 组 AI 配置默认值的代码唯一事实源。

本文件是：

1. **migration 播种的来源**（单向导出，禁止手抄，防双份常量漂移）；
2. **运行时 fallback**：DB 缺行/某字段为空时 store 回退到
   ``default_config`` 与 ``env_map``（字段级回退：DB 活行 → env → registry 默认）。

- ``default_config``：仅固化非敏感项；``api_key`` 一律空串
  （密钥不落代码/不播种，由管理员在配置页录入）；
- ``env_map``：field -> env 变量名；``""`` 表示该字段无 env 兜底
  （temperature/timeout 等参数为代码默认，不提供 env）。

注意：``rerank`` 的 api_key/base_url env 兜底仍指向 ``SAFETY_EMBEDDING_*``
（spec 已明确：兼容存量 RAG 链路，存量部署的 embedding key 同时服务 rerank）。
backend-design §2.2 表格此处与 spec 冲突，以 spec 为准。

本模块零副作用导入（不 import service/、knowledge/、feishu/ 等包），
migration 可直接引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# 5 组 profile 字面量（DB 只能改值不能新增 profile）
ProfileName = Literal["text", "text_backup", "vision", "embedding", "rerank"]


@dataclass(frozen=True)
class ProfileInfo:
    """单组 AI 模型配置（profile 是稳定 key，DB 只能改值不能新增 profile）。"""

    profile: ProfileName
    label: str                          # 中文标签（如 文本模型 / 视觉模型）
    default_usage: str                  # 用途说明
    default_config: dict[str, Any]      # 仅固化非敏感项；api_key 一律 ""
    field_names: tuple[str, ...]        # 允许写到 config 的字段（trim/校验用）
    env_map: dict[str, str]             # field -> env 变量名；"" 表示该字段无 env 兜底


# ═══════════════════════════════════════════════════════════════
# 5 组注册（值来源见各 profile 注释；禁止在 migration 中手抄）
# ═══════════════════════════════════════════════════════════════

_PROFILES: tuple[ProfileInfo, ...] = (
    # ── text 文本（主模型）──────────────────────────────────────
    ProfileInfo(
        profile="text",
        label="文本模型",
        default_usage="安全文本对话与业务 Agent 主模型（飞书 Bot 问答、AI 审查等）",
        default_config={
            "api_key": "",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash-vision-exp",
            "temperature": 0.1,
            "timeout": 120,
        },
        field_names=("api_key", "base_url", "model", "temperature", "timeout"),
        env_map={
            "api_key": "SAFETY_AI_TEXT_API_KEY",
            "base_url": "SAFETY_AI_TEXT_BASE_URL",
            "model": "SAFETY_AI_TEXT_MODEL",
            "temperature": "",          # 无 env（代码默认 0.1）
            "timeout": "",              # 无 env（代码默认 120）
        },
    ),
    # ── text_backup 文本备用（降级模型）──────────────────────────
    ProfileInfo(
        profile="text_backup",
        label="文本备用",
        default_usage="主文本模型调用失败时的降级模型（未配置则无降级）",
        default_config={
            "api_key": "",
            "base_url": "",
            "model": "",
            "timeout": 120,
        },
        field_names=("api_key", "base_url", "model", "timeout"),
        env_map={
            "api_key": "SAFETY_AI_TEXT_BACKUP_API_KEY",
            "base_url": "SAFETY_AI_TEXT_BACKUP_BASE_URL",
            "model": "SAFETY_AI_TEXT_BACKUP_MODEL",
            "timeout": "",              # 无 env（代码默认 120）
        },
    ),
    # ── vision 视觉 ─────────────────────────────────────────────
    ProfileInfo(
        profile="vision",
        label="视觉模型",
        default_usage="图片/文档视觉理解（图像分析与 OCR 辅助审查）",
        default_config={
            "api_key": "",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-vl-max",
            "temperature": 0.1,
            "timeout": 120,
        },
        field_names=("api_key", "base_url", "model", "temperature", "timeout"),
        env_map={
            "api_key": "SAFETY_AI_VISION_API_KEY",
            "base_url": "SAFETY_AI_VISION_BASE_URL",
            "model": "SAFETY_AI_VISION_MODEL",
            "temperature": "",          # 无 env（代码默认 0.1）
            "timeout": "",              # 无 env（代码默认 120）
        },
    ),
    # ── embedding 向量 ──────────────────────────────────────────
    ProfileInfo(
        profile="embedding",
        label="向量模型",
        default_usage="知识库切片向量化（RAG 检索，默认智谱 embedding-3/2048）",
        default_config={
            "api_key": "",
            "base_url": "",
            "model": "embedding-3",
            "dims": 2048,
        },
        field_names=("api_key", "base_url", "model", "dims"),
        env_map={
            "api_key": "SAFETY_EMBEDDING_API_KEY",
            "base_url": "SAFETY_EMBEDDING_BASE_URL",
            "model": "SAFETY_EMBEDDING_MODEL",
            "dims": "SAFETY_EMBEDDING_DIMS",
        },
    ),
    # ── rerank 重排 ─────────────────────────────────────────────
    ProfileInfo(
        profile="rerank",
        label="重排模型",
        default_usage="知识库检索结果重排（未配置时走 DeepSeek LLM 降级）",
        default_config={
            "api_key": "",
            "base_url": "",
            "model": "rerank-pro",
        },
        field_names=("api_key", "base_url", "model"),
        # api_key/base_url 仍复用 SAFETY_EMBEDDING_*（spec 明确：兼容存量 RAG
        # 链路，存量部署 embedding key 同时服务 rerank）；model 走专属变量。
        env_map={
            "api_key": "SAFETY_EMBEDDING_API_KEY",
            "base_url": "SAFETY_EMBEDDING_BASE_URL",
            "model": "SAFETY_RERANK_MODEL",
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
    """未知 profile 抛 ValueError（消息以「未知 profile」开头，与 scheduler 404 惯例一致）。"""
    info = REGISTRY.get(profile)
    if info is None:
        raise ValueError(f"未知 profile: {profile}")
    return info


def iter_profiles() -> tuple[ProfileInfo, ...]:
    """遍历 5 组，供 migration 播种 + 断言测试。"""
    return _PROFILES


PROFILE_KEYS: tuple[str, ...] = tuple(p.profile for p in _PROFILES)
