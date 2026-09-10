"""LLM-powered query expansion for Chinese regulatory text retrieval.

Uses the existing AI chat service to expand hazard descriptions into
standard terminology keywords, bridging the gap between colloquial
inspection language and formal regulatory text.

Usage:
    from app.modules.safety.knowledge.llm_retriever import LLMQueryExpander
    expander = LLMQueryExpander(ai_service)
    keywords = await expander.expand("防爆堵头未封堵")
    # -> ["防爆堵头", "电缆引入装置", "密封堵头", "防爆电气设备", ...]
"""

from __future__ import annotations

import json as _json
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.platform.integrations.ai.client import AIService

logger = logging.getLogger(__name__)

# 关键词缓存上限（超出删最旧，避免长驻进程无限增长）
_MAX_KEYWORD_CACHE = 500
# description 注入 prompt 前截断（防超长描述撑爆输入）
_MAX_DESCRIPTION_CHARS = 200

EXPANSION_PROMPT = """你是一个安全生产法规检索专家。请将以下隐患描述扩展为标准检索关键词。

## 任务
将检查人员口语化的隐患描述，转换为与法规标准（GB/GB-T/AQ/HG/SH等）中使用的**规范术语**和**近义词**。

## 规则
1. 保留原始描述中的所有关键词
2. 为每个口语化表达提供 2-3 个标准术语（如 "堵头" → "电缆引入装置密封件"、"防爆封堵件"）
3. 补充相关的上位概念（如 "防爆堵头" → 同时加上 "防爆电气"、"隔爆"）
4. 补充相关标准编号（如 "GB 3836"、"GB 30871"）
5. 输出关键词数组，数组元素为搜索关键词字符串
6. 总共输出 10-20 个关键词

## 隐患描述
{description}

## 输出格式
请以 JSON 对象格式输出，结构为：
{{"keywords": ["关键词1", "关键词2", ...]}}

只输出 JSON 对象，不要包含其他内容。"""


class LLMQueryExpander:
    """Use LLM to expand queries with standard terminology."""

    def __init__(self, ai_service: AIService):
        self.ai = ai_service
        self._cache: OrderedDict[str, list[str]] = OrderedDict()

    async def expand(self, description: str, max_keywords: int = 15) -> list[str]:
        """Expand a hazard description into standardized search keywords.

        Returns the original description + expanded keywords.
        Uses cache to avoid repeated API calls for the same description.
        """
        if not description or not description.strip():
            return []

        desc = description.strip()
        if desc in self._cache:
            self._cache.move_to_end(desc)  # LRU：命中置最新
            return self._cache[desc]

        try:
            keywords = await self._call_llm(desc)
        except Exception as e:
            logger.warning("LLM query expansion failed: %s — using original text", e)
            keywords = [desc]

        # Always include original description
        if desc not in keywords:
            keywords.insert(0, desc)

        result = keywords[:max_keywords]
        self._cache[desc] = result
        if len(self._cache) > _MAX_KEYWORD_CACHE:
            self._cache.popitem(last=False)  # 删最旧（FIFO/LRU 上限）
        return result

    async def _call_llm(self, description: str) -> list[str]:
        """Call LLM to generate expanded keywords."""
        prompt = EXPANSION_PROMPT.format(description=description[:_MAX_DESCRIPTION_CHARS])
        raw = await self.ai.chat(
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.1,
            max_tokens=1024,
        )
        return _parse_keywords(raw, description)


def _parse_keywords(raw: str, fallback: str) -> list[str]:
    """Parse LLM output into keyword list. Handles various formats."""
    # Try JSON array first
    try:
        parsed = _json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
            return [x.strip() for x in parsed if x.strip()]
        if isinstance(parsed, dict):
            # Maybe {"keywords": [...]} or similar
            for v in parsed.values():
                if isinstance(v, list) and all(isinstance(x, str) for x in v):
                    return [x.strip() for x in v if x.strip()]
    except _json.JSONDecodeError:
        pass

    # Fallback: split by newline/comma
    lines = [line.strip().lstrip("-*0123456789. ") for line in raw.split("\n")]
    results = [line for line in lines if len(line) >= 2]
    if results:
        return results[:20]

    return [fallback]
