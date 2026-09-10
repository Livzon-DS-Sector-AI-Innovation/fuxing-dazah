"""AI 实体提取器 — 从隐患描述/查询文本中提取安全实体。

用于知识图谱节点匹配（GraphRetriever._match_entities），
是 SafetyKnowledgeRetriever 三层检索管线的第一层。

设计原则：
- 轻量：单次 AI 调用，小 prompt，小输出
- 可降级：AI 调用失败返回空列表，不阻塞主流程
- 类型化：返回强类型的 ExtractedEntity 列表

用法:
    from app.modules.safety.knowledge.entity_extractor import EntityExtractor

    extractor = EntityExtractor(ai_service)
    entities = await extractor.extract("防爆电箱备用引入口未使用防爆堵头封堵")
    # -> [ExtractedEntity(name="防爆堵头", entity_type="equipment", confidence=0.95), ...]
"""

from __future__ import annotations

import json as _json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── 实体提取 prompt ──

ENTITY_EXTRACTION_PROMPT = """你是一个安全生产领域的实体识别专家。请从以下文本中提取安全相关的实体。

## 实体类型
- equipment: 设备、部件、工具（如"防爆电箱""堵头""引入口""反应釜"）
- condition: 状态、缺陷、问题（如"未封堵""腐蚀""泄漏""缺失"）
- location: 场所、部位、区域（如"配电间""罐区""车间"）
- operation: 作业、操作、活动（如"动火作业""高处作业""巡检"）
- material: 物料、介质、化学品（如"乙醇""氯气""蒸汽"）

## 提取规则
1. 只提取出现在文本中的实体，不要推断或补充
2. 实体名称使用文本中的原始中文表述
3. 一个实体只出现一次
4. 如果文本中没有某类实体，对应类型不出现在输出中
5. 每个实体给出置信度（0.0-1.0）

## 输出格式
请严格以 JSON 格式返回，不要包含任何其他内容：
{{"entities": [{{"name": "实体名称", "entity_type": "equipment|condition|location|operation|material", "confidence": 0.95}}]}}

## 待提取文本
{text}"""


@dataclass
class ExtractedEntity:
    """从查询文本中提取的安全实体。"""

    name: str           # 实体名称（原始文本表述）
    entity_type: str    # equipment / condition / location / operation / material
    confidence: float   # 0.0-1.0


class EntityExtractor:
    """AI 驱动的安全实体提取器。

    使用 SafetyAI 文本模型从中文隐患描述/查询中提取结构化实体，
    结果用于知识图谱节点匹配。AI 调用失败时优雅降级返回空列表。
    """

    def __init__(self, ai_service=None):
        """初始化实体提取器。

        Args:
            ai_service: AIService 实例。None 时所有 extract() 调用返回空列表。
        """
        self._ai_service = ai_service

    async def extract(self, text: str) -> list[ExtractedEntity]:
        """从文本中提取安全实体。

        Args:
            text: 中文隐患描述或查询文本

        Returns:
            ExtractedEntity 列表（按 confidence 降序），失败时返回空列表
        """
        if not text or not text.strip():
            return []

        if self._ai_service is None:
            logger.debug("EntityExtractor: ai_service=None, 跳过实体提取")
            return []

        text = text.strip()

        try:
            prompt = ENTITY_EXTRACTION_PROMPT.format(text=text)
            messages = [{"role": "user", "content": prompt}]
            raw = await self._ai_service.chat(
                messages=messages,
                response_format="json_object",
                temperature=0.1,
                max_tokens=1024,
            )
            entities = self._parse_response(raw)
            logger.debug("EntityExtractor: 提取了 %d 个实体 (text_len=%d)", len(entities), len(text))
            return entities
        except Exception as e:
            logger.warning("EntityExtractor 提取失败（非致命）: %s", e)
            return []

    @staticmethod
    def _parse_response(raw: str) -> list[ExtractedEntity]:
        """解析 AI 返回的 JSON 响应为 ExtractedEntity 列表。"""
        if not raw:
            return []

        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            # Remove first line (```json) and last line (```)
            if len(lines) >= 3:
                lines = lines[1:-1]
            raw = "\n".join(lines)

        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError:
            logger.debug("EntityExtractor: JSON 解析失败, raw=%s", raw[:200])
            return []

        items = data.get("entities", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            return []

        entities: list[ExtractedEntity] = []
        valid_types = {"equipment", "condition", "location", "operation", "material"}

        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            entity_type = (item.get("entity_type") or "").strip().lower()
            if not name or entity_type not in valid_types:
                continue
            try:
                confidence = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            entities.append(ExtractedEntity(
                name=name,
                entity_type=entity_type,
                confidence=max(0.0, min(1.0, confidence)),
            ))

        # Sort by confidence descending
        entities.sort(key=lambda e: e.confidence, reverse=True)
        return entities
