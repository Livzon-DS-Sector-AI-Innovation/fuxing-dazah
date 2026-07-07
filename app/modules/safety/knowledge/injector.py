"""Knowledge injection layer — assembles regulation knowledge cards into AI prompt context.

Before each AI hazard identification call, loads published knowledge cards from the DB
and formats them as structured Markdown for prompt injection. When ai_service is provided,
uses KnowledgeCardSelector to intelligently select only the most relevant cards.

Usage:
    from app.modules.safety.knowledge import KnowledgeInjector

    injector = KnowledgeInjector(session)
    context = await injector.build_knowledge_context()
    # -> pass to AIHazardIdentifier(knowledge_context=context)

    # With smart selection:
    context = await injector.build_knowledge_context(
        hazard_description="防爆电箱堵头未封堵",
        department="原料药生产部",
        ai_service=ai_service,
        max_cards=5,
    )
"""

from __future__ import annotations

import json as _json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.knowledge.knowledge_card import KnowledgeCard
from app.modules.safety.models import SafetyKnowledgeArticle

if TYPE_CHECKING:
    from app.platform.integrations.ai.client import AIService

logger = logging.getLogger(__name__)

KNOWLEDGE_CARD_COLUMN = "knowledge_card"

KNOWLEDGE_HEADER = """## 法规知识库

⚠️ **重要指令**：以下是本次隐患识别必须严格参照的法规标准原文摘要。
所有判断（分类、类别、级别、整改建议、判定依据）必须基于以下内容，
**不得依赖你的训练记忆**。若以下内容不足以做出判断，填写“知识库信息不足，待人工确认”。
"""


class KnowledgeInjector:
    """法规知识注入器。

    在 AI 调用前从 knowledge_articles 表加载已发布的知识卡片，
    组装为 Markdown 文本注入到 prompt 中。

    支持两种加载模式：
    - 全量模式：按优先级加载全部卡片（ai_service=None）
    - 智能模式：用 AI 智能选择相关卡片后注入（ai_service 传入时）

    数据库不可用时自动降级为硬编码 fallback，确保换服务器部署时 AI 识别不受影响。
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._cache: list[KnowledgeCard] | None = None

    async def build_knowledge_context(
        self,
        hazard_description: str = "",
        department: str | None = None,
        include_priority: str = "P2",
        ai_service: AIService | None = None,
        max_cards: int = 5,
    ) -> str:
        """构建注入 prompt 的知识上下文（供 AI隐患识别 / AI整改审核 使用）。

        Args:
            hazard_description: 隐患描述文本（供智能选择器匹配）
            department: 部门名称（供智能选择器匹配）
            include_priority: 最高优先级（默认 P2 = 全部卡片）
            ai_service: 传入则启用 AI 智能卡片选择；不传入则加载全部卡片
            max_cards: 智能选择时的最大卡片数量

        Returns:
            组装好的 Markdown 知识上下文文本
        """
        cards = await self._load_cards(include_priority)
        if not cards:
            logger.warning("未找到已发布的知识卡片，使用空上下文")
            return "(法规知识库暂未加载，请依据通用安全知识进行判断，但不要编造法规条文。)"

        # 智能选择
        if ai_service and len(cards) > max_cards:
            from app.modules.safety.knowledge.card_selector import (
                KnowledgeCardSelector,
            )
            selector = KnowledgeCardSelector(ai_service)
            selected = await selector.select(
                cards=cards,
                hazard_description=hazard_description,
                department=department,
                max_cards=max_cards,
            )
            if selected:
                cards = selected
                logger.info(
                    "智能卡片选择: %d/%d 张被选中用于隐患识别",
                    len(cards), len(self._cache or []),
                )

        sections: list[str] = [KNOWLEDGE_HEADER]
        for card in cards:
            section = self._format_card(card)
            if section:
                sections.append(section)

        sections.append(
            "\n---\n"
            f"**知识库覆盖范围**：以上共 {len(cards)} 份法规标准文档。\n"
            "请严格基于以上原文内容进行隐患识别，并在 major_hazard_basis 中逐字引用原文条文。"
        )
        return "\n\n".join(sections)

    async def get_relevant_clauses(self, hazard_type: str, hazard_category: str) -> str:
        """获取与指定隐患类型相关的法规条文。"""
        cards = await self._load_cards("P1")
        clauses: list[str] = []
        for card in cards:
            if card.legal_basis_clauses:
                clauses.append(f"**{card.document_title}** 相关条文：\n{card.legal_basis_clauses}")
        return "\n\n".join(clauses) if clauses else ""

    async def build_context(
        self,
        categories: list[str] | None = None,
        max_cards: int = 3,
        ai_service: AIService | None = None,
        hazard_description: str = "",
    ) -> str | None:
        """按类别筛选知识卡片并组装为 Markdown 上下文（供危险源辨识 Orchestrator 使用）。

        Args:
            categories: 需要的知识卡片类别列表（如 ["laws_regulations", "standards"]），
                        None 表示不筛选类别
            max_cards: 最多注入的卡片数量（按优先级排序后取前 N 张）
            ai_service: 传入则启用 AI 智能卡片选择
            hazard_description: 隐患描述（供智能选择器匹配）

        Returns:
            组装好的 Markdown 文本，无可用卡片时返回 None
        """
        cards = await self._load_cards("P2")
        if not cards:
            return None

        # 按类别筛选
        if categories:
            cards = [c for c in cards if c.document_category in categories]

        if not cards:
            logger.warning("无匹配类别的知识卡片: categories=%s", categories)
            return None

        # 智能选择（在类别筛选之后、max_cards 截断之前）
        if ai_service and len(cards) > max_cards:
            from app.modules.safety.knowledge.card_selector import (
                KnowledgeCardSelector,
            )
            selector = KnowledgeCardSelector(ai_service)
            selected = await selector.select(
                cards=cards,
                hazard_description=hazard_description,
                max_cards=max_cards,
            )
            if selected:
                cards = selected

        # 按优先级排序，取前 N 张
        priority_order = {"P0": 0, "P1": 1, "P2": 2}
        cards.sort(key=lambda c: priority_order.get(c.priority, 2))
        cards = cards[:max_cards]

        sections: list[str] = [KNOWLEDGE_HEADER]
        for card in cards:
            section = self._format_card(card)
            if section:
                sections.append(section)

        sections.append(
            "\n---\n"
            f"**知识库覆盖范围**：以上共 {len(cards)} 份法规标准文档。\n"
            "请严格基于以上原文内容进行判断，不得依赖训练记忆。"
        )
        return "\n\n".join(sections)

    async def get_cards_summary(self) -> list[dict[str, Any]]:
        """获取知识卡片状态摘要（供诊断命令使用）。"""
        cards = await self._load_cards("P2")
        field_names = [
            "hazard_type_definitions", "hazard_category_criteria",
            "hazard_level_criteria", "key_defect_examples",
            "rectification_requirements", "legal_basis_clauses",
        ]
        return [
            {
                "title": c.document_title,
                "category": c.document_category,
                "priority": c.priority,
                "fields_populated": [n for n in field_names if getattr(c, n)],
                "version": c.version,
            }
            for c in cards
        ]

    # ── 内部：卡片加载 ──

    async def _load_cards(self, max_priority: str = "P2") -> list[KnowledgeCard]:
        """加载知识卡片（优先 DB，fallback 硬编码）。"""
        if self._cache is not None:
            return self._filter_by_priority(self._cache, max_priority)

        cards: list[KnowledgeCard] = []
        try:
            db_cards = await self._load_from_db()
            if db_cards:
                logger.info("从 DB 加载了 %d 张知识卡片", len(db_cards))
                cards = db_cards
        except Exception as e:
            logger.warning("从 DB 加载知识卡片失败，降级为 fallback: %s", e)

        if not cards:
            cards = self._build_fallback_cards()
            logger.info("使用硬编码 fallback 知识卡片: %d 张", len(cards))

        self._cache = cards
        return self._filter_by_priority(cards, max_priority)

    async def _load_from_db(self) -> list[KnowledgeCard]:
        """从 safety.knowledge_articles 表加载已发布的卡片（ORM 方式）。"""
        stmt = (
            select(SafetyKnowledgeArticle)
            .where(
                SafetyKnowledgeArticle.status == "published",
                SafetyKnowledgeArticle.knowledge_card != None,  # noqa: E711
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
            )
            .order_by(SafetyKnowledgeArticle.card_version.desc())
        )
        result = await self.session.execute(stmt)
        articles = result.scalars().all()

        cards: list[KnowledgeCard] = []
        for article in articles:
            try:
                card_data = article.knowledge_card
                if isinstance(card_data, str):
                    card_data = _json.loads(card_data)
                card_data["document_title"] = article.title or card_data.get("document_title", "")
                card_data["document_category"] = article.category or card_data.get("document_category", "")
                card_data["full_document_ref"] = str(article.id)
                card_data.setdefault("priority", "P1")
                card_data.setdefault("version", article.card_version or 1)
                cards.append(KnowledgeCard(**card_data))
            except Exception as e:
                logger.warning("解析知识卡片失败 (article=%s): %s", article.id, e)
                continue

        return cards

    @staticmethod
    def _filter_by_priority(cards: list[KnowledgeCard], max_priority: str) -> list[KnowledgeCard]:
        """按优先级筛选卡片（P0 < P1 < P2）。"""
        priority_order = {"P0": 0, "P1": 1, "P2": 2}
        max_level = priority_order.get(max_priority, 2)
        filtered = [c for c in cards if priority_order.get(c.priority, 2) <= max_level]
        filtered.sort(key=lambda c: priority_order.get(c.priority, 2))
        return filtered

    @staticmethod
    def _build_fallback_cards() -> list[KnowledgeCard]:
        """Return hardcoded fallback cards (delegated to _fallback_cards module).

        Separate file keeps injector.py under the ~300 line threshold.
        """
        from app.modules.safety.knowledge._fallback_cards import (
            build_fallback_cards,
        )
        return build_fallback_cards()

    @staticmethod
    def _format_card(card: KnowledgeCard) -> str:
        """将单张 KnowledgeCard 格式化为 Markdown 文本。"""
        attr_labels = {
            "hazard_type_definitions": "隐患分类定义",
            "hazard_category_criteria": "隐患类别判定标准",
            "hazard_level_criteria": "隐患级别分级标准",
            "key_defect_examples": "典型缺陷示例",
            "rectification_requirements": "整改措施要求",
            "legal_basis_clauses": "可引用的法律依据条文",
        }

        parts: list[str] = [
            "### 文档: " + card.document_title,
            "**类别**: " + card.document_category
            + " | **优先级**: " + card.priority,
        ]

        for attr, label in attr_labels.items():
            value = getattr(card, attr, None)
            if value:
                parts.append("\n**" + label + "**:\n" + value)

        parts.append("")
        return "\n".join(parts)
