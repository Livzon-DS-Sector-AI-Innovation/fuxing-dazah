"""KnowledgeCardSelector — AI 决策 + 优先级回退的卡片选择器。

自包含，不依赖 DB。AI 服务需提供 chat_parsed(messages=..., expected_keys=...)
返回 {"selected_indices": [...], "reasoning": ...}。
"""
from __future__ import annotations

from typing import Any

from app.modules.safety.knowledge.knowledge_card import KnowledgeCard

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def _priority_rank(card: KnowledgeCard) -> int:
    return _PRIORITY_RANK.get(card.priority, 3)


class KnowledgeCardSelector:
    """按 AI 选择结果 + 优先级回退选择知识卡片。"""

    def __init__(self, ai_service: Any = None) -> None:
        self._ai = ai_service

    async def select(
        self,
        cards: list[KnowledgeCard],
        *,
        hazard_description: str,
        department: str | None = None,
        max_cards: int = 5,
    ) -> list[KnowledgeCard]:
        cards = list(cards)
        if len(cards) <= max_cards:
            # 小池子无需 AI，直接返回全部（保持原始顺序）
            return cards

        try:
            result = await self._ai.chat_parsed(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"从以下法规知识卡片中选最相关的 {max_cards} 张。"
                            f"隐患描述：{hazard_description}。部门：{department or '未知'}。"
                            "返回 {selected_indices: [卡片下标...], reasoning: 理由}。"
                        ),
                    }
                ],
                expected_keys=["selected_indices", "reasoning"],
            )
            indices = result.get("selected_indices", [])
            chosen: list[KnowledgeCard] = []
            seen: set[int] = set()
            for idx in indices:
                if isinstance(idx, bool):
                    continue
                if not isinstance(idx, int):
                    continue
                if idx < 0 or idx >= len(cards):
                    continue
                if idx in seen:
                    continue
                seen.add(idx)
                chosen.append(cards[idx])
            if not chosen:
                return self._priority_fallback(cards, max_cards)
            chosen.sort(key=_priority_rank)
            return chosen[:max_cards]
        except Exception:
            return self._priority_fallback(cards, max_cards)

    @staticmethod
    def _priority_fallback(cards: list[KnowledgeCard], max_cards: int) -> list[KnowledgeCard]:
        """AI 失败/空结果 → 按优先级取前 N。"""
        return sorted(cards, key=_priority_rank)[:max_cards]
