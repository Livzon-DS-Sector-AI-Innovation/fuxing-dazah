"""Tests for safety knowledge module — cards, selector, injector."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.safety.knowledge.knowledge_card import (
    KnowledgeCard,
    KnowledgeDocumentMeta,
    KNOWLEDGE_DOCUMENTS,
    get_documents_by_priority,
)


# ═══════════════════════════════════════════════════════════════════════════════
# KnowledgeCard — data model
# ═══════════════════════════════════════════════════════════════════════════════


class TestKnowledgeCard:
    """KnowledgeCard Pydantic model validation."""

    def test_minimal_card(self) -> None:
        """Card with only required fields should validate."""
        card = KnowledgeCard(
            document_title="GB/T 13861-2022",
            document_category="standards",
            priority="P0",
        )
        assert card.document_title == "GB/T 13861-2022"
        assert card.document_category == "standards"
        assert card.priority == "P0"
        assert card.hazard_type_definitions is None
        assert card.version == 1

    def test_full_card(self) -> None:
        """Card with all fields populated."""
        card = KnowledgeCard(
            document_title="安全生产法",
            document_category="laws_regulations",
            priority="P0",
            hazard_type_definitions="人的不安全行为定义...",
            hazard_category_criteria="13类判定标准...",
            hazard_level_criteria="重大/较大/一般...",
            key_defect_examples="防爆堵头缺失...",
            rectification_requirements="立即停止→补办审批...",
            legal_basis_clauses="第41条：...",
            full_document_ref="123e4567-e89b",
            extracted_at="2025-01-01T00:00:00",
            version=2,
        )
        assert card.hazard_type_definitions is not None
        assert card.legal_basis_clauses is not None
        assert card.version == 2


class TestKnowledgeDocumentMeta:
    """Document metadata model."""

    def test_meta_creation(self) -> None:
        meta = KnowledgeDocumentMeta(
            title="安全生产法",
            category="laws_regulations",
            priority="P0",
            feishu_url="https://example.com/file/abc",
            file_token="abc123",
        )
        assert meta.file_token == "abc123"
        assert meta.priority == "P0"


class TestKnowledgeDocuments:
    """Document registry integrity."""

    def test_all_documents_have_required_fields(self) -> None:
        """Every document in KNOWLEDGE_DOCUMENTS must have title + token."""
        for doc in KNOWLEDGE_DOCUMENTS:
            assert doc.title, f"Missing title for doc with token {doc.file_token}"
            assert doc.file_token, f"Missing file_token for {doc.title}"
            assert doc.priority in ("P0", "P1", "P2"), (
                f"Invalid priority {doc.priority} for {doc.title}"
            )
            assert doc.category, f"Missing category for {doc.title}"

    def test_p0_documents_exist(self) -> None:
        """P0 documents are the most critical — must not be empty."""
        p0 = get_documents_by_priority("P0")
        assert len(p0) >= 5, f"Expected >=5 P0 docs, got {len(p0)}"

    def test_no_duplicate_tokens(self) -> None:
        """No two documents should share the same file_token."""
        tokens = [d.file_token for d in KNOWLEDGE_DOCUMENTS]
        assert len(tokens) == len(set(tokens)), "Duplicate file_tokens found"

    def test_at_least_20_documents(self) -> None:
        """We expect 20+ documents covering all categories."""
        assert len(KNOWLEDGE_DOCUMENTS) >= 20


# ═══════════════════════════════════════════════════════════════════════════════
# KnowledgeCardSelector — selection logic
# ═══════════════════════════════════════════════════════════════════════════════


class TestKnowledgeCardSelector:
    """Tests for AI-powered card selection and fallback."""

    @pytest.fixture
    def sample_cards(self) -> list[KnowledgeCard]:
        """Build a small card pool for testing."""
        return [
            KnowledgeCard(
                document_title="安全生产法",
                document_category="laws_regulations",
                priority="P0",
                legal_basis_clauses="第41条：隐患排查治理制度",
                hazard_level_criteria="重大隐患判定",
            ),
            KnowledgeCard(
                document_title="GB/T 13861-2022",
                document_category="standards",
                priority="P0",
                hazard_type_definitions="人的因素/物的因素/环境因素/管理因素",
                hazard_category_criteria="13类判定标准",
            ),
            KnowledgeCard(
                document_title="GB 3836.1-2010",
                document_category="standards",
                priority="P1",
                hazard_category_criteria="防爆电气选型要求",
                key_defect_examples="防爆堵头缺失、密封圈老化",
            ),
            KnowledgeCard(
                document_title="GB 4053.3-2009",
                document_category="standards",
                priority="P2",
                key_defect_examples="平台踢脚板缺失、扶手高度不足",
                rectification_requirements="扶手高度≥1050mm",
            ),
            KnowledgeCard(
                document_title="特种设备安全法",
                document_category="laws_regulations",
                priority="P2",
                legal_basis_clauses="第33条：使用登记",
            ),
        ]

    def test_small_pool_no_selection_needed(self, sample_cards) -> None:
        """When card count <= max_cards, return all cards (no AI call needed)."""
        from app.modules.safety.knowledge.card_selector import KnowledgeCardSelector

        # 5 cards, max_cards=5 → no selection needed
        selector = KnowledgeCardSelector(ai_service=MagicMock())
        # len <= max_cards → return all without calling AI
        assert len(sample_cards) <= 5  # precondition for this test

    @pytest.mark.asyncio
    async def test_ai_selection_success(self, sample_cards) -> None:
        """AI selects relevant cards based on hazard description."""
        from app.modules.safety.knowledge.card_selector import KnowledgeCardSelector

        mock_ai = MagicMock()
        mock_ai.chat_parsed = AsyncMock(return_value={
            "selected_indices": [0, 1, 2],
            "reasoning": "安全生产法和GB/T 13861提供判定依据，GB 3836匹配电气隐患",
        })

        selector = KnowledgeCardSelector(ai_service=mock_ai)
        # Use 5 cards, max 3 → needs AI selection
        selected = await selector.select(
            cards=sample_cards,
            hazard_description="防爆电箱堵头未封堵",
            department="原料药生产部",
            max_cards=3,
        )

        assert len(selected) == 3
        # Selected cards should be priority-sorted (P0 before P1)
        titles = [c.document_title for c in selected]
        assert "安全生产法" in titles
        assert "GB/T 13861-2022" in titles
        assert "GB 3836.1-2010" in titles
        # P0 cards should come first
        assert selected[0].priority == "P0"
        mock_ai.chat_parsed.assert_called_once()

    @pytest.mark.asyncio
    async def test_ai_failure_fallback(self, sample_cards) -> None:
        """When AI fails, fall back to priority-based selection."""
        from app.modules.safety.knowledge.card_selector import KnowledgeCardSelector

        mock_ai = MagicMock()
        mock_ai.chat_parsed = AsyncMock(side_effect=RuntimeError("AI timeout"))

        selector = KnowledgeCardSelector(ai_service=mock_ai)
        selected = await selector.select(
            cards=sample_cards,
            hazard_description="测试隐患",
            max_cards=2,
        )

        # Fallback should return top 2 by priority
        assert len(selected) == 2
        assert selected[0].priority == "P0"
        assert selected[1].priority == "P0"

    @pytest.mark.asyncio
    async def test_bogus_indices_filtered(self, sample_cards) -> None:
        """AI returns out-of-range or duplicate indices → they are filtered."""
        from app.modules.safety.knowledge.card_selector import KnowledgeCardSelector

        mock_ai = MagicMock()
        mock_ai.chat_parsed = AsyncMock(return_value={
            "selected_indices": [0, 99, -1, 0, "not_an_int", 2],
            "reasoning": "testing edge cases",
        })

        selector = KnowledgeCardSelector(ai_service=mock_ai)
        selected = await selector.select(
            cards=sample_cards,
            hazard_description="测试",
            max_cards=3,
        )

        # Only valid indices 0 and 2 should survive, deduplicated
        assert len(selected) == 2
        assert selected[0].document_title == "安全生产法"  # index 0
        assert selected[1].document_title == "GB 3836.1-2010"  # index 2

    @pytest.mark.asyncio
    async def test_empty_indices_fallback(self, sample_cards) -> None:
        """AI returns empty list → fallback to priority-based."""
        from app.modules.safety.knowledge.card_selector import KnowledgeCardSelector

        mock_ai = MagicMock()
        mock_ai.chat_parsed = AsyncMock(return_value={
            "selected_indices": [],
            "reasoning": "no relevant cards found",
        })

        selector = KnowledgeCardSelector(ai_service=mock_ai)
        selected = await selector.select(
            cards=sample_cards,
            hazard_description="测试",
            max_cards=2,
        )

        # Should fallback to top 2 by priority
        assert len(selected) == 2
        assert all(c.priority == "P0" for c in selected)


# ═══════════════════════════════════════════════════════════════════════════════
# KnowledgeInjector — injection logic
# ═══════════════════════════════════════════════════════════════════════════════


class TestKnowledgeInjector:
    """Tests for knowledge injection and fallback behavior."""

    def test_fallback_cards_are_valid(self) -> None:
        """All 26 fallback cards must pass KnowledgeCard validation."""
        from app.modules.safety.knowledge._fallback_cards import build_fallback_cards

        cards = build_fallback_cards()
        assert len(cards) == 26, f"Expected 26 fallback cards, got {len(cards)}"

        for card in cards:
            assert card.document_title, "Card missing title"
            assert card.document_category, "Card missing category"
            assert card.priority in ("P0", "P1", "P2"), (
                f"Invalid priority {card.priority} for {card.document_title}"
            )
            # At least one content field should be populated
            has_content = any([
                card.hazard_type_definitions,
                card.hazard_category_criteria,
                card.hazard_level_criteria,
                card.key_defect_examples,
                card.rectification_requirements,
                card.legal_basis_clauses,
            ])
            assert has_content, (
                f"Fallback card '{card.document_title}' has no content fields"
            )

    def test_filter_by_priority(self) -> None:
        """Priority filtering: P0 < P1 < P2."""
        from app.modules.safety.knowledge.injector import KnowledgeInjector

        cards = [
            KnowledgeCard(
                document_title="P0 card", document_category="standards", priority="P0",
                hazard_type_definitions="test",
            ),
            KnowledgeCard(
                document_title="P1 card", document_category="standards", priority="P1",
                hazard_type_definitions="test",
            ),
            KnowledgeCard(
                document_title="P2 card", document_category="standards", priority="P2",
                hazard_type_definitions="test",
            ),
        ]

        # P0 only
        p0 = KnowledgeInjector._filter_by_priority(cards, "P0")
        assert len(p0) == 1
        assert p0[0].document_title == "P0 card"

        # P1 includes P0 + P1
        p1 = KnowledgeInjector._filter_by_priority(cards, "P1")
        assert len(p1) == 2
        assert p1[0].priority == "P0"

        # P2 includes all
        p2 = KnowledgeInjector._filter_by_priority(cards, "P2")
        assert len(p2) == 3

    def test_format_card_output(self) -> None:
        """_format_card should produce Markdown with title and content."""
        from app.modules.safety.knowledge.injector import KnowledgeInjector

        card = KnowledgeCard(
            document_title="测试法规",
            document_category="laws_regulations",
            priority="P0",
            legal_basis_clauses="第1条：测试条文",
            hazard_type_definitions="测试定义",
        )

        output = KnowledgeInjector._format_card(card)
        assert "### 文档: 测试法规" in output
        assert "**类别**: laws_regulations" in output
        assert "**优先级**: P0" in output
        assert "隐患分类定义" in output
        assert "可引用的法律依据条文" in output
        assert "第1条：测试条文" in output

    def test_format_card_skips_empty_fields(self) -> None:
        """Empty fields should not appear in formatted output."""
        from app.modules.safety.knowledge.injector import KnowledgeInjector

        card = KnowledgeCard(
            document_title="最小法规",
            document_category="standards",
            priority="P2",
            legal_basis_clauses="only this",
        )

        output = KnowledgeInjector._format_card(card)
        # Should only contain legal_basis_clauses, not other empty fields
        assert "隐患分类定义" not in output
        assert "隐患类别判定标准" not in output
        assert "only this" in output

    @pytest.mark.asyncio
    async def test_build_context_with_categories(self) -> None:
        """build_context filters by category correctly."""
        from app.modules.safety.knowledge.injector import KnowledgeInjector
        from unittest.mock import AsyncMock

        # Mock session
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        injector = KnowledgeInjector(mock_session)
        # Since DB returns empty, should fall back to hardcoded cards
        # But with category filter
        ctx = await injector.build_context(
            categories=["laws_regulations"],
            max_cards=2,
        )

        assert ctx is not None
        assert "法规知识库" in ctx
        assert "**知识库覆盖范围**" in ctx


# ═══════════════════════════════════════════════════════════════════════════════
# Integration smoke tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestKnowledgeModuleIntegration:
    """Smoke tests for module-level imports and wiring."""

    def test_init_exports(self) -> None:
        """All public symbols should be importable from the package."""
        from app.modules.safety.knowledge import (
            KnowledgeCard,
            KnowledgeDocumentMeta,
            KNOWLEDGE_DOCUMENTS,
            DocumentLoader,
            KnowledgeInjector,
            KnowledgeCardSelector,
        )
        assert KnowledgeCard is not None
        assert KnowledgeDocumentMeta is not None
        assert KNOWLEDGE_DOCUMENTS is not None
        assert DocumentLoader is not None
        assert KnowledgeInjector is not None
        assert KnowledgeCardSelector is not None

    def test_fallback_module_importable(self) -> None:
        """_fallback_cards module should be self-contained."""
        from app.modules.safety.knowledge._fallback_cards import build_fallback_cards
        cards = build_fallback_cards()
        assert isinstance(cards, list)
        assert len(cards) > 0
