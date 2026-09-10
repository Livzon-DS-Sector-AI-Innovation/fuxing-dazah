"""KnowledgeInjector — 知识上下文注入（DB 优先，空则回退硬编码卡片）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.modules.safety.knowledge._fallback_cards import build_fallback_cards
from app.modules.safety.knowledge.knowledge_card import KnowledgeCard

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}

_FIELD_LABELS: list[tuple[str, str]] = [
    ("hazard_type_definitions", "隐患分类定义"),
    ("hazard_category_criteria", "隐患类别判定标准"),
    ("hazard_level_criteria", "隐患等级判定标准"),
    ("key_defect_examples", "典型缺陷示例"),
    ("rectification_requirements", "整改要求"),
    ("legal_basis_clauses", "可引用的法律依据条文"),
]


class KnowledgeInjector:
    """构建注入 LLM 前备的知识上下文。"""

    def __init__(self, session: Any = None) -> None:
        self.session = session

    @staticmethod
    def _priority_rank(card: KnowledgeCard) -> int:
        return _PRIORITY_RANK.get(card.priority, 3)

    @classmethod
    def _filter_by_priority(cls, cards: list[KnowledgeCard], priority: str) -> list[KnowledgeCard]:
        """按优先级过滤：P0 只含 P0；P1 含 P0+P1；P2 含全部。"""
        rank_limit = _PRIORITY_RANK.get(priority, 3)
        return [c for c in cards if cls._priority_rank(c) <= rank_limit]

    @classmethod
    def _format_card(cls, card: KnowledgeCard) -> str:
        """单张卡片 → Markdown 块；空字段不输出。"""
        lines = [
            f"### 文档: {card.document_title}",
            f"**类别**: {card.document_category}",
            f"**优先级**: {card.priority}",
        ]
        for field, label in _FIELD_LABELS:
            value = getattr(card, field, None)
            if value:
                lines.append(f"**{label}**：{value}")
        return "\n".join(lines)

    async def build_context(
        self,
        *,
        categories: list[str] | None = None,
        max_cards: int = 8,
    ) -> str:
        """构建知识上下文。DB 无结果时回退硬编码卡片。"""
        cards: list[KnowledgeCard] = []
        if self.session is not None:
            try:
                from app.modules.safety.models import SafetyKnowledgeArticle

                result = await self.session.execute(select(SafetyKnowledgeArticle))
                cards = [
                    KnowledgeCard(
                        document_title=a.title or "未命名",
                        document_category=a.category or "standards",
                        priority=(a.priority or "P2"),
                        full_document_ref=str(a.id) if getattr(a, "id", None) else None,
                    )
                    for a in result.scalars().all()
                ]
            except Exception:
                cards = []

        if not cards:
            cards = build_fallback_cards()

        if categories:
            cards = [c for c in cards if c.document_category in categories]

        cards = sorted(cards, key=self._priority_rank)
        selected = cards[:max_cards]

        parts = ["**知识库覆盖范围**", ""]
        for c in selected:
            parts.append(self._format_card(c))
            parts.append("")

        header = f"法规知识库备选卡片共 {len(selected)} 张："
        return "\n".join([header, *parts]).strip()
