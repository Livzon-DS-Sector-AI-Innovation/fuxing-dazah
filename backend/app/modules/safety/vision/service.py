"""VisionService — 安全模块统一视觉 AI 入口。

封装完整的"图片预处理→视觉模型调用→响应解析→降级回退"管线。
所有调用自动走 AuditedAIService → AI 审计日志。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.modules.safety.vision.utils import encode_image_for_vision

if TYPE_CHECKING:
    from app.modules.safety.ai_audit.audited_client import AuditedAIService

logger = logging.getLogger(__name__)

# ── 视觉模型默认参数 ──
_DEFAULT_TEMPERATURE = 0.1
_DEFAULT_MAX_TOKENS = 16384


class VisionService:
    """统一视觉 AI 服务。

    职责：
    - 图片预处理（本地路径→base64 data URI）
    - 视觉模型调用（通过 AuditedAIService，自动记录审计日志）
    - 支持 chat_vision（原始文本）和 chat_vision_parsed（结构化 JSON）
    - 视觉模型不可用时提供降级信号

    Usage::

        from app.modules.safety.service.config import create_ai_service
        from app.modules.safety.vision.service import VisionService

        ai = create_ai_service("vision")
        vision = VisionService(ai)

        result = await vision.analyze_parsed(
            text_prompt="分析这张隐患图片...",
            image_urls=["uploads/safety/hazard/img.jpg", "https://..."],
            expected_keys=["hazard_type", "hazard_level", ...],
        )
    """

    def __init__(self, ai_service: AuditedAIService | None = None):
        self._ai = ai_service

    # ── 实例属性 ──

    @property
    def ai(self) -> Any:
        """获取 AI 服务实例（延迟创建）。"""
        if self._ai is None:
            from app.modules.safety.service.config import create_ai_service
            self._ai = create_ai_service("vision")
        return self._ai

    @property
    def supports_vision(self) -> bool:
        """当前 AI 服务是否支持视觉分析。"""
        return hasattr(self.ai, "chat_vision_parsed")

    # ── 公共 API ──

    async def analyze_parsed(
        self,
        text_prompt: str,
        image_urls: list[str],
        expected_keys: list[str],
        *,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        preprocess: bool = True,
    ) -> dict | None:
        """视觉分析 + JSON 解析。

        Args:
            text_prompt: 文本提示词。
            image_urls: 图片路径/URL/data URI 列表。
            expected_keys: 期望从响应中提取的 JSON 键。
            temperature: 模型温度。
            max_tokens: 最大输出 token。
            preprocess: 是否预处理本地图片（编码为 data URI）。

        Returns:
            Parsed dict on success，视觉不可用时返回 None。
            None 意味着调用方应走降级路径（纯文本分析）。
        """
        if not self.supports_vision:
            logger.warning("AI 服务不支持 vision，返回 None 触发降级")
            return None

        # 预处理图片（本地路径 → base64 data URI）
        processed_urls = image_urls
        if preprocess:
            processed_urls = self._preprocess_image_urls(image_urls)
            if not processed_urls:
                logger.warning("图片预处理后全部无效，返回 None 触发降级")
                return None

        try:
            return await self.ai.chat_vision_parsed(
                text_prompt=text_prompt,
                image_urls=processed_urls,
                expected_keys=expected_keys,
                temperature=temperature,
            )
        except Exception:
            logger.exception("视觉 AI 调用失败")
            return None

    async def analyze(
        self,
        text_prompt: str,
        image_urls: list[str],
        *,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        preprocess: bool = True,
    ) -> str | None:
        """视觉分析（原始文本输出）。

        与 analyze_parsed 的区别：不解析 JSON，返回原始文本。

        Returns:
            AI 回复文本，视觉不可用或失败时返回 None。
        """
        if not self.supports_vision:
            logger.warning("AI 服务不支持 vision，返回 None 触发降级")
            return None

        processed_urls = image_urls
        if preprocess:
            processed_urls = self._preprocess_image_urls(image_urls)
            if not processed_urls:
                return None

        try:
            return await self.ai.chat_vision(
                text_prompt=text_prompt,
                image_urls=processed_urls,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception:
            logger.exception("视觉 AI 调用失败")
            return None

    # ── 内部方法 ──

    def _preprocess_image_urls(self, urls: list[str]) -> list[str]:
        """预处理图片 URL 列表：本地路径 → base64 data URI。

        已经是 http/data URL 的保持不变。无法处理的返回空列表。
        """
        processed: list[str] = []
        for url in urls:
            # 已经是远程/内联 URL，直接使用
            if url.startswith("http://") or url.startswith("https://") or url.startswith("data:"):
                processed.append(url)
                continue
            # 本地路径 → base64 data URI
            data_uri = _load_and_encode_image(url)
            if data_uri:
                processed.append(data_uri)
            else:
                logger.info("跳过无效图片，不送视觉模型: %s", url)
        return processed

    async def close(self) -> None:
        """关闭底层 AI 服务连接。"""
        if self._ai is not None:
            try:
                await self._ai.close()
            except Exception:
                pass


# ── 模块级辅助函数 ──


def _load_and_encode_image(file_path: str) -> str | None:
    """加载本地图片文件并编码为 data URI。

    对单个文件执行：path → bytes → encode_image_for_vision。
    文件不存在或编码失败返回 None。
    """
    import os as _os

    if not _os.path.exists(file_path):
        logger.debug("图片文件不存在: %s", file_path)
        return None

    ext = _os.path.splitext(file_path)[1].lower()
    from app.modules.safety.vision.constants import IMAGE_MIME_MAP

    mime = IMAGE_MIME_MAP.get(ext)
    if mime is None:
        logger.info("非图片扩展名，跳过: %s", file_path)
        return None

    try:
        with open(file_path, "rb") as f:
            raw = f.read()
        return encode_image_for_vision(raw, mime, file_path)
    except OSError:
        logger.warning("无法读取图片文件: %s", file_path)
        return None
