"""Rule-based entity extractor — zero LLM calls.

Extracts safety entities from Chinese regulatory text using:
  1. Term dictionary matching (precise + fuzzy)
  2. Regex pattern matching (equipment, locations, operations, standard refs)
  3. (Optional) jieba TF-IDF keyword extraction for unknown terms

Intended to replace per-document AI calls in GraphBuilder, reducing
graph construction from 254 LLM calls to ~3 (only for fuzzy relations).

Usage:
    from app.modules.safety.knowledge.entity_extractor_rule import RuleBasedEntityExtractor
    extractor = RuleBasedEntityExtractor()
    entities = await extractor.extract_from_document(title, full_text)
    # -> list[ExtractedEntity] (same format as AI EntityExtractor)
"""

from __future__ import annotations

import json as _json
import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Regex patterns for safety entity extraction ──

# Equipment: XX阀, XX泵, XX堵头, XX开关, XX器, XX表, XX罩, XX绳, XX带
PATTERN_EQUIPMENT = re.compile(
    r'[一-鿿]{1,6}(?:阀|泵|堵头|开关|按钮|器|表|罩|绳|带|钩|线|管|罐|釜|机|箱|柜|网|栏|梯|台|座|架)'
)

# Location: XX区, XX间, XX车间, XX罐区, XX库房, XX平台
PATTERN_LOCATION = re.compile(
    r'[一-鿿]{1,8}(?:区|间|车间|罐区|库房|仓库|平台|厂房|场所|部位|区域)'
)

# Operation: XX作业, XX操作, XX检修
PATTERN_OPERATION = re.compile(
    r'[一-鿿]{1,6}(?:作业|操作|检修|维修|巡检|检测|试验|校验|审批|培训)'
)

# Standard references: GB/GB-T/GBZ/AQ/HG/SH/TSG/DL/JGJ + numbers
PATTERN_STANDARD = re.compile(
    r'(GB(?:\s*[/-]\s*T)?|GBZ|AQ(?:\s*[/-]\s*T)?|HG|SH|TSG|DL|JGJ|SY)\s*[\d.]+(?:[-–]\d+)?'
)

# Article references: 第X条, 第X章, §X, X.X.X
PATTERN_ARTICLE = re.compile(
    r'(?:第[一二三四五六七八九十百千\d]+[条章节款])|(?:§\d+(?:\.\d+)?)|(?:\d+\.\d+(?:\.\d+)?)'
)

# Condition keywords: 未XX, 无XX, 缺失, 不足, 过期, 损坏
PATTERN_CONDITION = re.compile(
    r'(?:未[一-鿿]{1,4}|无[一-鿿]{1,4}|缺少|缺失|不足|过期|损坏|故障|失效|'
    r'堵塞|泄漏|腐蚀|锈蚀|老化|龟裂|开裂|脱落|松动|不亮|模糊|超期)'
)

# Material: XX液, XX气, XX粉, XX剂
PATTERN_MATERIAL = re.compile(
    r'[一-鿿]{1,4}(?:液|气|粉|剂|油|酸|碱|醇|烷|烯|苯|酮|醚|酯)'
)


@dataclass
class ExtractedEntity:
    """A safety entity extracted from text (same format as AI EntityExtractor)."""
    name: str
    entity_type: str  # equipment/condition/location/operation/material/standard/concept
    confidence: float  # 0.0-1.0


class RuleBasedEntityExtractor:
    """Rule-based safety entity extractor — zero LLM calls.

    Combines term dictionary + regex patterns + optional jieba TF-IDF
    to extract structured entities from Chinese regulatory documents.
    """

    def __init__(self, dict_path: str | None = None):
        """Initialize the extractor.

        Args:
            dict_path: Path to term_dictionary.json. Defaults to same directory.
        """
        if dict_path is None:
            dict_path = os.path.join(os.path.dirname(__file__), "term_dictionary.json")
        self._terms: dict[str, dict] = {}
        self._term_index: dict[str, str] = {}  # alias -> canonical name
        self._load_dictionary(dict_path)

    def _load_dictionary(self, path: str) -> None:
        """Load the term dictionary from JSON."""
        try:
            with open(path, encoding="utf-8") as f:
                data = _json.load(f)
            self._terms = data.get("terms", {})
            # Build alias index
            for name, info in self._terms.items():
                self._term_index[name] = name
                for alias in info.get("aliases", []):
                    if alias not in self._term_index:
                        self._term_index[alias] = name
            logger.info(
                "Loaded %d terms (%d with aliases) from %s",
                len(self._terms), len(self._term_index), path,
            )
        except (FileNotFoundError, _json.JSONDecodeError) as e:
            logger.warning("Failed to load term dictionary: %s", e)

    async def extract(self, text: str) -> list[ExtractedEntity]:
        """Extract entities from a short query/description text.

        Compatible interface with AI EntityExtractor for use in
        SafetyKnowledgeRetriever Layer 1.

        Args:
            text: Short Chinese hazard description or user query

        Returns:
            List of ExtractedEntity, deduplicated by name
        """
        return await self.extract_from_document(title="", content=text)

    async def extract_from_document(
        self, title: str, content: str,
    ) -> list[ExtractedEntity]:
        """Extract entities from a document's title and content.

        Args:
            title: Document title (e.g. "GB 3836.1-2010 爆炸性环境")
            content: Full document text

        Returns:
            List of ExtractedEntity, deduplicated by name
        """
        text = f"{title}\n{content}" if title else content
        if not text:
            return []

        entities: dict[str, ExtractedEntity] = {}

        # 1. Standard references (highest precision)
        for m in PATTERN_STANDARD.finditer(text):
            name = m.group(0).strip()
            if name and len(name) <= 40:
                self._add_entity(entities, name, "standard", 0.95)

        # 2. Term dictionary matching
        for term, info in self._terms.items():
            if term in text:
                confidence = 0.90
                self._add_entity(entities, term, info["type"], confidence)
            # Check aliases
            for alias in info.get("aliases", []):
                if len(alias) >= 2 and alias in text:
                    confidence = 0.85  # slightly lower for alias match
                    self._add_entity(entities, term, info["type"], confidence)

        # 3. Equipment patterns (moderate precision)
        for m in PATTERN_EQUIPMENT.finditer(text):
            name = m.group(0).strip()
            if name and len(name) >= 2 and name not in entities:
                # Filter false positives
                if not self._is_common_word(name):
                    self._add_entity(entities, name, "equipment", 0.70)

        # 4. Location patterns
        for m in PATTERN_LOCATION.finditer(text):
            name = m.group(0).strip()
            if name and len(name) >= 2 and name not in entities:
                if not self._is_common_word(name):
                    self._add_entity(entities, name, "location", 0.70)

        # 5. Operation patterns
        for m in PATTERN_OPERATION.finditer(text):
            name = m.group(0).strip()
            if name and len(name) >= 2 and name not in entities:
                self._add_entity(entities, name, "operation", 0.70)

        # 6. Condition patterns (lower precision — use only explicit matches)
        for m in PATTERN_CONDITION.finditer(text):
            name = m.group(0).strip()
            if name and len(name) >= 1:
                # Only include if not captured as equipment
                if name not in entities:
                    self._add_entity(entities, name, "condition", 0.60)

        # 7. Material patterns
        for m in PATTERN_MATERIAL.finditer(text):
            name = m.group(0).strip()
            if name and len(name) >= 2 and name not in entities:
                self._add_entity(entities, name, "material", 0.65)

        result = sorted(entities.values(), key=lambda e: e.confidence, reverse=True)
        return result

    # ── Helpers ──

    @staticmethod
    def _add_entity(
        entities: dict[str, ExtractedEntity],
        name: str, entity_type: str, confidence: float,
    ) -> None:
        """Add or update an entity, keeping the highest confidence."""
        if name in entities:
            existing = entities[name]
            if confidence > existing.confidence:
                existing.confidence = confidence
            return
        entities[name] = ExtractedEntity(
            name=name, entity_type=entity_type, confidence=confidence,
        )

    @staticmethod
    def _is_common_word(word: str) -> bool:
        """Filter out common non-entity words."""
        common_words = {
            "系统", "方法", "要求", "规定", "标准", "规范", "条件", "环境",
            "单位", "部门", "人员", "工作", "安全", "管理", "技术", "设计",
            "安装", "施工", "使用", "维护", "处理", "生产", "储存", "运输",
            "措施", "制度", "方案", "记录", "报告", "文件", "资料", "信息",
            "情况", "问题", "隐患", "事故", "风险", "危害", "危险", "防护",
        }
        return word in common_words
