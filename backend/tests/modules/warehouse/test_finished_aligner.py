"""成品名录对齐器测试（2026-09-28 识别完善 A 项）。

覆盖：
- batch_prefix 前缀提取规则；
- match_product 四级匹配（exact/prefix 双向/fuzzy/none）+ 单位 tie-break；
- align_finished_receipt：标准名落 aligned、单位/批号警示、rows 逐行对名、
  名录拉取失败 no-op 降级；
- mark_finished_aligned 落库与状态迁移；
- draft_update 改字段清对应警示；
- normalize_finished_receipt_rows 优先读 aligned["rows"]（对名行集）；
- 确认卡对齐/警示行渲染（对话路径零回归）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.warehouse.agent.pipeline.finished_aligner as fa
from app.modules.warehouse.agent import cards
from app.modules.warehouse.agent.pipeline import (
    FINISHED_RECEIPT_SCENE,
    FinishedAlignedReceipt,
    FinishedProductEntry,
    RecognizedField,
    RecognizedFinishedReceipt,
)
from app.modules.warehouse.agent.pipeline import draft_flow as df
from app.modules.warehouse.agent.pipeline.finished_aligner import (
    align_finished_receipt,
    batch_prefix,
    match_product,
)
from app.modules.warehouse.agent.pipeline.submit import normalize_finished_receipt_rows
from app.modules.warehouse.agent.tools import draft_update
from app.modules.warehouse.models import WarehouseAgentDraft


def _entries() -> list[FinishedProductEntry]:
    return [
        FinishedProductEntry(
            name="达托霉素",
            specs=("DA低规",),
            units=("kg",),
            batch_prefixes=("DA",),
        ),
        FinishedProductEntry(
            name="硫酸黏菌素",
            specs=(),
            units=("十亿", "g"),
            batch_prefixes=("COL",),
        ),
    ]


# ── batch_prefix ──


class TestBatchPrefix:
    def test_letters_extracted_upper(self) -> None:
        assert batch_prefix("DA2609001") == "DA"
        assert batch_prefix("ab2609") == "AB"

    def test_no_prefix_cases(self) -> None:
        assert batch_prefix("10407-251008") == ""  # 纯数字开头
        assert batch_prefix("A1") == ""  # 单字母不足 2 位
        assert batch_prefix("") == ""


# ── match_product ──


class TestMatchProduct:
    def test_exact(self) -> None:
        entry, confidence, detail = match_product("达托霉素", _entries())
        assert confidence == "exact"
        assert entry is not None and entry.name == "达托霉素"
        assert detail["batch_prefixes"] == ("DA",)

    def test_prefix_forward(self) -> None:
        entry, confidence, detail = match_product("达托", _entries())
        assert confidence == "prefix"
        assert entry is not None and entry.name == "达托霉素"
        assert detail["direction"] == "forward"

    def test_prefix_reverse(self) -> None:
        """识别名带杂质后缀 → reverse 方向（警示请核对）。"""
        entry, confidence, detail = match_product("达托霉素（进口分装）", _entries())
        assert confidence == "prefix"
        assert entry is not None and entry.name == "达托霉素"
        assert detail["direction"] == "reverse"

    def test_fuzzy(self) -> None:
        entry, confidence, _ = match_product("硫酸粘菌素", _entries())
        assert confidence == "fuzzy"
        assert entry is not None and entry.name == "硫酸黏菌素"

    def test_none(self) -> None:
        entry, confidence, _ = match_product("青霉素", _entries())
        assert entry is None and confidence == "none"

    def test_empty_name(self) -> None:
        entry, confidence, _ = match_product("", _entries())
        assert entry is None and confidence == "none"

    def test_unit_tiebreak(self) -> None:
        """同名多录入口径 → 单位一致者优先。"""
        entries = [
            FinishedProductEntry(name="产品A", specs=(), units=("kg",), batch_prefixes=()),
            FinishedProductEntry(name="产品A", specs=(), units=("瓶",), batch_prefixes=()),
        ]
        entry, confidence, _ = match_product("产品A", entries, unit="瓶")
        assert confidence == "exact"
        assert entry is not None and entry.units == ("瓶",)


def _recognized(
    *,
    name: str | None = "达托霉素",
    batch: str | None = "DA2609001",
    quantity: str | None = "100",
    unit: str | None = "kg",
    rows: list[dict[str, Any]] | None = None,
) -> RecognizedFinishedReceipt:
    kwargs: dict[str, Any] = {
        "product_name": RecognizedField(value=name, confidence=0.9 if name else 0.0),
        "product_batch_no": RecognizedField(value=batch, confidence=0.9),
        "quantity": RecognizedField(value=quantity, confidence=0.9),
        "unit": RecognizedField(value=unit, confidence=0.9),
    }
    if rows is not None:
        kwargs["rows"] = rows
    return RecognizedFinishedReceipt(**kwargs)


async def _align_with_entries(
    recognized: RecognizedFinishedReceipt,
    entries: list[FinishedProductEntry],
    monkeypatch: pytest.MonkeyPatch,
) -> FinishedAlignedReceipt:
    async def _fake_entries(*, force_refresh: bool = False) -> list[FinishedProductEntry]:
        return entries

    monkeypatch.setattr(fa, "get_finished_product_entries", _fake_entries)
    return await align_finished_receipt(recognized)


# ── align_finished_receipt ──


class TestAlignFinishedReceipt:
    async def test_exact_match_no_warnings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = await _align_with_entries(_recognized(), _entries(), monkeypatch)
        assert result.aligned["product_name"] == "达托霉素"
        assert result.match_confidence == "exact"
        assert result.warnings == {}

    async def test_unit_suspect_warns_not_rewrites(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = await _align_with_entries(_recognized(unit="pl"), _entries(), monkeypatch)
        assert result.aligned["product_name"] == "达托霉素"  # 标准名照常落
        assert "unit" in result.warnings
        assert "「pl」" in result.warnings["unit"]

    async def test_batch_prefix_mismatch_warns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = await _align_with_entries(
            _recognized(batch="XX2609001"), _entries(), monkeypatch
        )
        assert "product_batch_no" in result.warnings
        assert "XX" in result.warnings["product_batch_no"]

    async def test_fuzzy_match_warns_with_standard_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = await _align_with_entries(
            _recognized(name="硫酸粘菌素", batch="COL2609001", unit="十亿"),
            _entries(),
            monkeypatch,
        )
        assert result.match_confidence == "fuzzy"
        assert result.aligned["product_name"] == "硫酸黏菌素"
        assert "product_name" in result.warnings

    async def test_unmatched_keeps_recognized_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = await _align_with_entries(
            _recognized(name="青霉素"), _entries(), monkeypatch
        )
        assert "product_name" not in result.aligned  # 不写 aligned（保留识别值展示）
        assert result.match_confidence == "none"
        assert "product_name" in result.warnings

    async def test_rows_standardized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [
            {
                "product_name": "达托霉",
                "product_batch_no": "DA2609001",
                "quantity": "10",
                "unit": "kg",
            },
            {
                "product_name": "硫酸黏菌素",
                "product_batch_no": "COL2609002",
                "quantity": "20",
                "unit": "十亿",
            },
        ]
        result = await _align_with_entries(_recognized(rows=rows), _entries(), monkeypatch)
        aligned_rows = result.aligned["rows"]
        assert aligned_rows[0]["product_name"] == "达托霉素"  # 前缀匹配纠正
        assert aligned_rows[1]["product_name"] == "硫酸黏菌素"
        assert aligned_rows[0]["quantity"] == "10"  # 数量原样

    async def test_fetch_failure_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _boom(*, force_refresh: bool = False) -> list[FinishedProductEntry]:
            raise RuntimeError("bitable down")

        monkeypatch.setattr(fa, "get_finished_product_entries", _boom)
        result = await align_finished_receipt(_recognized())
        assert result.aligned == {}
        assert result.match_confidence == ""
        assert result.warnings == {}

    async def test_empty_directory_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _empty(*, force_refresh: bool = False) -> list[FinishedProductEntry]:
            return []

        monkeypatch.setattr(fa, "get_finished_product_entries", _empty)
        result = await align_finished_receipt(_recognized())
        assert result.aligned == {}
        assert "product_name" not in result.warnings


# ── mark_finished_aligned（落库） ──


class TestMarkFinishedAligned:
    async def test_writes_aligned_and_transitions(self, db_session: AsyncSession) -> None:
        draft = WarehouseAgentDraft(
            draft_no="WR20990101-501",
            scene=FINISHED_RECEIPT_SCENE,
            status="created",
            recognized={"product_name": {"value": "达托霉素", "confidence": 0.9}},
            aligned={},
            created_by_open_id="ou_align_t",
        )
        db_session.add(draft)
        await db_session.flush()

        aligned = FinishedAlignedReceipt(
            aligned={"product_name": "达托霉素"},
            match_confidence="exact",
            match_detail={"key": "达托霉素", "matched_by": "exact"},
            warnings={"unit": "单位「pl」不在历史单位中，请核对"},
        )
        await df.mark_finished_aligned(db_session, draft, aligned)
        assert draft.status == "aligned"
        assert draft.aligned["product_name"] == "达托霉素"
        assert draft.aligned["match_confidence"] == "exact"
        assert draft.aligned["warnings"] == {"unit": "单位「pl」不在历史单位中，请核对"}
        assert draft.aligned["match_detail"]["matched_by"] == "exact"


# ── draft_update 改字段清对应警示 ──


class TestDraftUpdateClearsWarnings:
    async def test_unit_update_clears_unit_warning(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        draft = WarehouseAgentDraft(
            draft_no="WR20990101-502",
            scene=FINISHED_RECEIPT_SCENE,
            status="aligned",
            recognized={"unit": {"value": "pl", "confidence": 0.4}},
            aligned={
                "product_name": "达托霉素",
                "unit": "pl",
                "match_confidence": "exact",
                "match_detail": {},
                "warnings": {"unit": "单位「pl」不在历史单位中，请核对"},
            },
            created_by_open_id="ou_warn_t",
        )
        db_session.add(draft)
        await db_session.flush()

        @asynccontextmanager
        async def _patched_db() -> AsyncIterator[AsyncSession]:
            yield db_session

        async def _fake_send_create(payload: dict[str, str]) -> str | None:
            return "om_fake"

        from app.modules.warehouse.feishu import notification

        monkeypatch.setattr(draft_update, "_db_session", lambda: _patched_db())
        monkeypatch.setattr(notification, "_send_create", _fake_send_create)

        result = await draft_update.update_draft(
            "WR20990101-502", {"unit": "kg"}, _ctx={"open_id": "ou_warn_t"}
        )
        assert "error" not in result
        assert draft.aligned["unit"] == "kg"
        assert "unit" not in draft.aligned["warnings"]
        # 未修改字段的产品对齐元数据保留
        assert draft.aligned["match_confidence"] == "exact"


# ── normalize_finished_receipt_rows 优先读 aligned["rows"] ──


class TestNormalizePrefersAlignedRows:
    def test_aligned_rows_win_over_recognized(self) -> None:
        draft = WarehouseAgentDraft(
            draft_no="WR20990101-503",
            scene=FINISHED_RECEIPT_SCENE,
            status="aligned",
            recognized={
                "rows": [
                    {
                        "product_name": "达托霉",
                        "product_batch_no": "DA2609001",
                        "quantity": "10",
                        "unit": "kg",
                    },
                    {
                        "product_name": "达托霉",
                        "product_batch_no": "DA2609001",
                        "quantity": "5",
                        "unit": "kg",
                    },
                ],
                "product_name": {"value": "达托霉", "confidence": 0.4},
                "product_batch_no": {"value": "DA2609001", "confidence": 0.9},
                "quantity": {"value": "15", "confidence": 0.9},
                "unit": {"value": "kg", "confidence": 0.9},
            },
            aligned={
                "rows": [
                    {
                        "product_name": "达托霉素",
                        "product_batch_no": "DA2609001",
                        "quantity": "10",
                        "unit": "kg",
                    },
                    {
                        "product_name": "达托霉素",
                        "product_batch_no": "DA2609001",
                        "quantity": "5",
                        "unit": "kg",
                    },
                ],
            },
        )
        rows = normalize_finished_receipt_rows(draft)
        assert len(rows) == 1  # 同批号归组
        assert rows[0]["product_name"] == "达托霉素"  # 对名后标准名
        assert rows[0]["quantity"] == 15  # 归组求和


# ── 卡片：对齐行与警示行 ──


def _card_content(card: dict[str, Any]) -> str:
    return "\n".join(
        element.get("content") or ""
        for element in card.get("body", {}).get("elements", [])
        if isinstance(element, dict)
    )


class TestCardAlignmentLines:
    def test_alignment_and_warning_lines_render(self) -> None:
        draft = WarehouseAgentDraft(
            draft_no="WR20990101-504",
            scene=FINISHED_RECEIPT_SCENE,
            status="aligned",
            recognized={
                "product_name": {"value": "达托霉素", "confidence": 0.9},
                "product_batch_no": {"value": "XX2609001", "confidence": 0.8},
                "quantity": {"value": "100", "confidence": 0.9},
                "unit": {"value": "pl", "confidence": 0.5},
            },
            aligned={
                "product_name": "达托霉素",
                "match_confidence": "exact",
                "match_detail": {},
                "warnings": {
                    "unit": "单位「pl」不在「达托霉素」历史单位（kg）中，请核对",
                    "product_batch_no": "批号前缀「XX」与「达托霉素」历史批号前缀（DA）不符，请核对",
                },
            },
        )
        card = cards.render_receipt_confirm_card(draft)
        assert card["header"]["title"]["content"] == "🏭 成品入库登记"
        content = _card_content(card)
        assert "产品对齐**：达托霉素（名录精确匹配）" in content
        assert "⚠ 单位「pl」" in content
        assert "批号前缀「XX」" in content

    def test_dialog_path_card_has_no_alignment_noise(self) -> None:
        """对话收集路径 aligned 无元数据键 → 不渲染对齐/警示行（零回归）。"""
        draft = WarehouseAgentDraft(
            draft_no="WR20990101-505",
            scene=FINISHED_RECEIPT_SCENE,
            status="aligned",
            recognized={"product_name": "达托霉素"},
            aligned={
                "product_name": "达托霉素",
                "product_batch_no": "DA2609001",
                "quantity": "100",
                "unit": "kg",
            },
        )
        card = cards.render_receipt_confirm_card(draft)
        assert "产品对齐" not in _card_content(card)
