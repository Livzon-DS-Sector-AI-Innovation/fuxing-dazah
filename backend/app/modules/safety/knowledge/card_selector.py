"""AI 智能卡片选择器 —— 用一次轻量级 AI 调用从卡片池中精准选择相关卡片。

在知识注入前，根据隐患描述/部门等上下文信息，由 AI 判断哪些法规标准文档
与当前隐患最相关，只将选中的卡片注入主识别 prompt，避免 prompt 过长。

用法:
    from app.modules.safety.knowledge import KnowledgeCardSelector

    selector = KnowledgeCardSelector(ai_service)
    selected = await selector.select(
        cards=all_cards,
        hazard_description="防爆电箱堵头未封堵",
        department="原料药生产部",
        max_cards=5,
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.modules.safety.knowledge.knowledge_card import KnowledgeCard

if TYPE_CHECKING:
    from app.platform.integrations.ai.client import AIService

logger = logging.getLogger(__name__)

# ── 卡片选择 system prompt ──
SELECTOR_SYSTEM_PROMPT = """你是一个安全生产法规知识库检索专家。你的任务是根据隐患描述和部门信息，
从知识卡片池中选出与该隐患**最直接相关**的法规标准文档。

选择原则：
1. 优先选择与隐患类型直接匹配的法规（如电气隐患→GB 3836 防爆标准）
2. 其次选择提供判定依据的法规（如重大隐患判定标准、安全生产法）
3. 再次选择提供整改措施指导的标准
4. 不相关或仅间接相关的法规不要选择
5. 确保选中的法规覆盖"判定"和"整改"两个维度

返回选中的卡片索引列表（从 0 开始），以及简短的选择理由。"""


class KnowledgeCardSelector:
    """AI 智能卡片选择器。

    用一次轻量级 AI 调用（~2-3K token），根据隐患上下文从全部卡片池中选择
    最相关的 N 张卡片。选中的卡片注入主识别 prompt，未选中的不参与。
    """

    def __init__(self, ai_service: AIService):
        self.ai_service = ai_service

    async def select(
        self,
        cards: list[KnowledgeCard],
        hazard_description: str,
        department: str | None = None,
        max_cards: int = 5,
    ) -> list[KnowledgeCard]:
        """从卡片池中智能选择最相关的卡片。

        Args:
            cards: 全部可用卡片列表
            hazard_description: 隐患描述文本
            department: 部门名称（可选，用于判断行业场景）
            max_cards: 最多选择的卡片数量

        Returns:
            选中的卡片列表（按原优先级排序），数量 <= max_cards。
            AI 调用失败时返回前 max_cards 张高优先级卡片作为 fallback。
        """
        if len(cards) <= max_cards:
            return list(cards)

        try:
            card_list_text = self._build_card_list_text(cards)
            prompt = self._build_selection_prompt(
                hazard_description, department, card_list_text, max_cards
            )

            result = await self.ai_service.chat_parsed(
                messages=[
                    {"role": "system", "content": SELECTOR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                expected_keys=["selected_indices", "reasoning"],
                temperature=0.05,
            )

            indices = result.get("selected_indices", [])
            reasoning = result.get("reasoning", "")
            logger.info(
                "卡片选择完成: %d/%d 张选中 → %s",
                len(indices), len(cards), reasoning[:120],
            )

            selected = self._resolve_cards(cards, indices, max_cards)
            return selected

        except Exception as e:
            logger.warning(
                "智能卡片选择失败 (%s)，回退到优先级排序取前 %d 张",
                e, max_cards,
            )
            return self._fallback_select(cards, max_cards)

    # ── 内部方法 ──

    @staticmethod
    def _build_card_list_text(cards: list[KnowledgeCard]) -> str:
        """构建卡片摘要列表（每张一行，供 AI 选择）。"""
        lines: list[str] = []
        for i, card in enumerate(cards):
            summary = KnowledgeCardSelector._make_card_summary(card)
            lines.append(
                f"[{i}] [{card.priority}] {card.document_title} "
                f"({card.document_category})\n    {summary}"
            )
        return "\n".join(lines)

    @staticmethod
    def _make_card_summary(card: KnowledgeCard) -> str:
        """为单张卡片生成简短摘要（~40-80 字符）。"""
        # 优先使用第一条非空字段的前 60 字符作为摘要
        summary_fields = [
            card.hazard_type_definitions,
            card.hazard_category_criteria,
            card.hazard_level_criteria,
            card.key_defect_examples,
            card.rectification_requirements,
            card.legal_basis_clauses,
        ]
        for field in summary_fields:
            if field:
                # 取第一行或前 60 字符
                first_line = field.split("\n")[0].strip()
                if len(first_line) > 60:
                    first_line = first_line[:60] + "…"
                return first_line
        return "（待提取）"

    @staticmethod
    def _build_selection_prompt(
        hazard_description: str,
        department: str | None,
        card_list_text: str,
        max_cards: int,
    ) -> str:
        """构建选择 prompt。"""
        parts: list[str] = [
            "## 隐患信息",
            f"- 隐患描述：{hazard_description or '（未提供）'}",
        ]
        if department:
            parts.append(f"- 所属部门：{department}")
        parts.append("")
        parts.append("## 可选知识卡片")
        parts.append(card_list_text)
        parts.append("")
        parts.append(
            f"## 任务\n"
            f"从以上卡片中选择与当前隐患最相关的 **最多 {max_cards} 张** 卡片。\n"
            "返回 JSON：{\"selected_indices\": [0, 3, 7], \"reasoning\": \"选择理由\"}"
        )
        return "\n".join(parts)

    @staticmethod
    def _resolve_cards(
        cards: list[KnowledgeCard],
        indices: list[int],
        max_cards: int,
    ) -> list[KnowledgeCard]:
        """根据 AI 返回的索引列表解析卡片对象。"""
        selected: list[KnowledgeCard] = []
        seen: set[int] = set()
        for idx in indices:
            if not isinstance(idx, int):
                continue
            if idx < 0 or idx >= len(cards):
                continue
            if idx in seen:
                continue
            seen.add(idx)
            selected.append(cards[idx])
            if len(selected) >= max_cards:
                break
        if not selected:
            return KnowledgeCardSelector._fallback_select(cards, max_cards)
        # 按原优先级排序
        priority_order = {"P0": 0, "P1": 1, "P2": 2}
        selected.sort(key=lambda c: priority_order.get(c.priority, 2))
        return selected

    @staticmethod
    def _fallback_select(
        cards: list[KnowledgeCard], max_cards: int
    ) -> list[KnowledgeCard]:
        """Fallback：按优先级排序取前 N 张。"""
        priority_order = {"P0": 0, "P1": 1, "P2": 2}
        sorted_cards = sorted(cards, key=lambda c: priority_order.get(c.priority, 2))
        return sorted_cards[:max_cards]
