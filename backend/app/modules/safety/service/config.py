"""Safety AI 模型工厂."""

import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# AI 模型配置（经 ai_config 配置中心解析：DB 活行 → env 兜底 → registry 默认，
# 字段级回退已展开；改配置后下一次调用即读到新值）
# ═══════════════════════════════════════════════════════════


def _get_ai_config() -> dict:
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
        backup: dict | None = {
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


def create_ai_service(config_type: str = "text"):
    """创建带审计留痕的 AI 服务实例（硬编码配置，不依赖数据库）。

    config_type: "text"（文本模型）或 "vision"（视觉模型）

    所有调用自动通过 AuditedAIService 记录到 safety.ai_call_audits 表。
    文本模型配置了备用模型（SAFETY_AI_TEXT_BACKUP_*）时，主模型调用失败
    （401/402/429/5xx/超时等）自动降级到备用模型重试一次；降级标记写入审计。
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
