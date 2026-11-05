"""Safety AI 模型工厂."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.safety.ai_audit.audited_client import AuditedAIService

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# AI 模型配置（经 ai_config 配置中心解析：DB 活行 → env 兜底 → registry 默认，
# 字段级回退已展开；改配置后下一次调用即读到新值）
# ═══════════════════════════════════════════════════════════


def _get_ai_config() -> dict[str, Any]:
    """读取 AI 模型配置（resolver 薄封装，DB→env→registry 默认合并）。

    text/vision 合并后无 api_key 时抛 RuntimeError（原契约：
    ``create_ai_service`` 与 ``build_ai_config_view`` 依赖该异常语义，
    不得吞掉——否则会变 500 或静默空配置）。
    """
    from app.modules.safety.ai_config.resolver import get_profile_config

    text_cfg = get_profile_config("text")
    vision_cfg = get_profile_config("vision")
    if not text_cfg.get("api_key"):
        raise RuntimeError(
            "环境变量 SAFETY_AI_TEXT_API_KEY 未配置，无法初始化 AI 文本模型。"
            "请在 .env 文件或 AI 配置中心（text profile）设置该值。"
        )
    if not vision_cfg.get("api_key"):
        raise RuntimeError(
            "环境变量 SAFETY_AI_VISION_API_KEY 未配置，无法初始化 AI 视觉模型。"
            "请在 .env 文件或 AI 配置中心（vision profile）设置该值。"
        )

    backup_cfg = get_profile_config("text_backup")
    # 备用模型合并规则（backend-design §4.1）：api_key 与 model 均空 → None（未配置无降级）；
    # 否则有值。base_url-only 的半配置不再生成必然失败的降级客户端。
    if backup_cfg.get("api_key") or backup_cfg.get("model"):
        backup: dict[str, Any] | None = {
            "api_key": backup_cfg["api_key"],
            "base_url": backup_cfg["base_url"],
            "model": backup_cfg["model"],
            "timeout": backup_cfg.get("timeout", 120),
        }
    else:
        backup = None

    return {
        "text": {
            "api_key": text_cfg["api_key"],
            "base_url": text_cfg["base_url"],
            "model": text_cfg["model"],
            "temperature": text_cfg.get("temperature", 0.1),
            "timeout": text_cfg.get("timeout", 120),
            # 备用文本模型（主模型失败时自动降级；未配置则无降级）
            "backup": backup,
        },
        "vision": {
            "api_key": vision_cfg["api_key"],
            "base_url": vision_cfg["base_url"],
            "model": vision_cfg["model"],
            "temperature": vision_cfg.get("temperature", 0.1),
            "timeout": vision_cfg.get("timeout", 120),
        },
    }


def create_ai_service(config_type: str = "text") -> AuditedAIService:
    """创建带审计留痕的 AI 服务实例（硬编码配置，不依赖数据库）。

    config_type: "text"（文本模型）或 "vision"（视觉模型）

    所有调用自动通过 AuditedAIService 记录到 safety.ai_call_audits 表。
    文本模型配置了备用模型（SAFETY_AI_TEXT_BACKUP_*）时，主模型调用失败
    （401/402/429/5xx/超时等）自动降级到备用模型重试一次；降级标记写入审计。

    注意：本函数每次调用都新建实例（②⑤等既有调用方语义不变）；
    ① 的高频识别链路用 ``get_ai_service`` 复用进程级单例。
    """
    from app.modules.safety.ai_audit.audited_client import AuditedAIService

    cfg = _get_ai_config().get(config_type)
    if not cfg:
        raise ValueError(f"不支持的 AI 配置类型: {config_type}，可选: text / vision")

    backup = cfg.get("backup") or None
    logger.debug(
        "创建 AI 服务: config_type=%s model=%s backup=%s",
        config_type, cfg["model"], (backup or {}).get("model") or "无",
    )
    service = AuditedAIService(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        model=cfg["model"],
        timeout=cfg["timeout"],
    )
    if backup:
        service.set_backup(
            api_key=backup["api_key"],
            base_url=backup["base_url"],
            model=backup["model"],
            timeout=backup.get("timeout", 120),
        )
    return service


# ═══════════════════════════════════════════════════════════
# AI 客户端进程级单例（A6③ 效率止血）
#
# ① 隐患识别每条记录都要 AI 客户端，但进程内配置基本不变：按「当前运行
# event loop + config_type + 配置指纹」缓存同一实例，省掉每条 0.8~1.5s
# 的新建开销。
# - 审计上下文是 per-call contextvar（AIAuditContext），单例不破坏审计归因；
# - event loop 变化（pytest 每用例新 loop、多 loop 应用）必须重建：
#   httpx.AsyncClient 连接池不能跨 loop 复用；
# - config_type 必须进 key：text/vision 即使 api_key/base_url/model/timeout
#   恰好相同也不得互相顶替（视觉调用绝不能拿到文本客户端）；
# - 配置指纹变化（api_key/base_url/model/timeout/backup）自动重建；
# - create_ai_service 保持「每次新建」语义（②⑤等既有调用方不变）。
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class _CachedAIService:
    """单例缓存条目：记录所属 loop（判 id 复用/关闭）、类型与配置指纹。"""

    loop: asyncio.AbstractEventLoop | None
    config_type: str
    fingerprint: str
    service: AuditedAIService


# key = (运行中 event loop 的 id（无 loop 时 None）, config_type, 配置指纹)
_ai_service_cache: dict[tuple[int | None, str, str], _CachedAIService] = {}


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """当前运行中的 event loop；同步上下文（无 loop）返回 None。"""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _ai_config_fingerprint(cfg: dict[str, Any]) -> str:
    """配置指纹：api_key 摘要 + base_url/model/timeout + backup 元组。"""

    def _digest(secret: Any) -> str:
        return hashlib.sha256(str(secret or "").encode()).hexdigest()[:16]

    backup = cfg.get("backup")
    payload: dict[str, Any] = {
        "api_key": _digest(cfg.get("api_key")),
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "timeout": cfg.get("timeout", 120),
        "backup": None
        if not backup
        else {
            "api_key": _digest(backup.get("api_key")),
            "base_url": backup.get("base_url", ""),
            "model": backup.get("model", ""),
            "timeout": backup.get("timeout", 120),
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _prune_closed_loop_entries() -> None:
    """清掉 loop 已关闭的缓存条目（无 loop 的同步条目保留）。

    仅从缓存移除、不 close 旧实例：本函数是同步路径无法 await；旧 loop 的
    客户端已不可用，是否关闭由进程级 ``close_all_ai_services()`` 兜底
    （生产长生命周期 loop 正常不会走到这里，pytest 中客户端未使用故无泄漏）。
    """
    for key, entry in list(_ai_service_cache.items()):
        if entry.loop is not None and entry.loop.is_closed():
            del _ai_service_cache[key]


def get_ai_service(config_type: str = "text") -> AuditedAIService:
    """取 AI 客户端进程级单例（① 高频链路用；②⑤继续用 create_ai_service）。

    缓存 key = 当前运行 event loop id + config_type + 配置指纹（api_key 摘要/
    base_url/model/timeout/backup）。配置指纹变化、config_type 不同或 event
    loop 变化时各自独立重建；``close_all_ai_services()`` 负责进程级关闭与清空。
    """
    cfg = _get_ai_config().get(config_type)
    if not cfg:
        raise ValueError(f"不支持的 AI 配置类型: {config_type}，可选: text / vision")

    loop = _running_loop()
    fingerprint = _ai_config_fingerprint(cfg)
    key = (id(loop) if loop is not None else None, config_type, fingerprint)

    _prune_closed_loop_entries()
    cached = _ai_service_cache.get(key)
    if cached is not None and cached.loop is loop:
        return cached.service

    # 重建/替换时不 close 旧实例（同步函数无法 await）：进程级缓存的生命周期
    # 由 close_all_ai_services() 统一兜底，避免此处引入异步清理复杂度。
    service = create_ai_service(config_type)
    _ai_service_cache[key] = _CachedAIService(
        loop=loop,
        config_type=config_type,
        fingerprint=fingerprint,
        service=service,
    )
    logger.debug(
        "AI 服务单例已创建: config_type=%s loop=%s fingerprint=%s",
        config_type, id(loop) if loop is not None else None, fingerprint[:12],
    )
    return service


async def close_all_ai_services() -> None:
    """关闭并清空进程级 AI 服务单例缓存（停机/测试清理入口）。"""
    entries = list(_ai_service_cache.values())
    _ai_service_cache.clear()
    for entry in entries:
        try:
            await entry.service.close()
        except Exception:  # 关闭失败不能阻塞停机流程，仅日志
            logger.warning("关闭 AI 服务单例失败（忽略）", exc_info=True)
