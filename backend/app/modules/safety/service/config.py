"""Safety AI 模型工厂."""

import logging
import os

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# AI 模型配置（从环境变量读取，支持部署时覆盖）
# ═══════════════════════════════════════════════════════════


def _get_ai_config() -> dict:
    """读取 AI 模型配置，必须通过环境变量配置，不提供硬编码默认值。"""
    _text_key = os.getenv("SAFETY_AI_TEXT_API_KEY")
    _vision_key = os.getenv("SAFETY_AI_VISION_API_KEY")
    if not _text_key:
        raise RuntimeError(
            "环境变量 SAFETY_AI_TEXT_API_KEY 未配置，无法初始化 AI 文本模型。"
            "请在 .env 文件中设置该变量。"
        )
    if not _vision_key:
        raise RuntimeError(
            "环境变量 SAFETY_AI_VISION_API_KEY 未配置，无法初始化 AI 视觉模型。"
            "请在 .env 文件中设置该变量。"
        )
    return {
        "text": {
            "api_key": _text_key,
            "base_url": os.getenv("SAFETY_AI_TEXT_BASE_URL", "https://api.deepseek.com"),
            "model": os.getenv("SAFETY_AI_TEXT_MODEL", "deepseek-v4-flash"),
            "temperature": 0.1,
            "timeout": 120,
        },
        "vision": {
            "api_key": _vision_key,
            "base_url": os.getenv("SAFETY_AI_VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "model": os.getenv("SAFETY_AI_VISION_MODEL", "qwen-vl-max"),
            "temperature": 0.1,
            "timeout": 120,
        },
    }


def create_ai_service(config_type: str = "text"):
    """创建 AI 服务实例（硬编码配置，不依赖数据库）。

    config_type: "text"（文本模型）或 "vision"（视觉模型）
    """
    from app.platform.integrations.ai.client import AIService

    cfg = _get_ai_config().get(config_type)
    if not cfg:
        raise ValueError(f"不支持的 AI 配置类型: {config_type}，可选: text / vision")

    logger.debug("创建 AI 服务: config_type=%s model=%s", config_type, cfg["model"])
    return AIService(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        model=cfg["model"],
        timeout=cfg["timeout"],
    )
