"""多行登记测试（§4.6 追加，2026-09-22 用户实测一单多批号）。

覆盖：识别 rows 解析（残行丢弃）→ 归组规范化（同批求和/异批分行/主行覆盖/
文档级字段下发）→ 行级字段组装 → 多行提交（FakeAdapter 逐行 create/读回/
审计/回执）→ 多行确认卡渲染。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.modules.warehouse.agent import cards
from app.modules.warehouse.agent.pipeline import submit as submit_module
from app.modules.warehouse.agent.pipeline.recognizer import build_finished_receipt
from app.modules.warehouse.agent.pipeline.submit import (
    build_finished_receipt_row_fields,
    normalize_finished_receipt_rows,
)
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_SELECT,
    FieldMeta,
)
from app.modules.warehouse.models import WarehouseAgentAudit, WarehouseAgentDraft
from tests.modules.warehouse.test_finished_receipt import FakeAdapter

NOW = datetime(2026, 9, 22)


def _fr_fields() -> dict[str, FieldMeta]:
    return {
        "入库日期": FieldMeta(type=5),
        "产品名称": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("达托霉素", "替考拉宁")
        ),
        "产品批号": FieldMeta(type=1),
        "品规": FieldMeta(type=FIELD_TYPE_SELECT, options=("DA低规",)),
        "入库数量": FieldMeta(type=2),
        "单位": FieldMeta(type=FIELD_TYPE_SELECT, options=("kg", "十亿")),
        "入库类型": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("正常入库", "返工入库", "退货入库")
        ),
        "库区位置": FieldMeta(type=1),
        "质量状态": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("合格", "待检", "待处理", "退货")
        ),
        "生产日期": FieldMeta(type=1),
        "有效期": FieldMeta(type=1),
        "备注": FieldMeta(type=1),
    }


def _draft(
    recognized: dict[str, Any],
    aligned: dict[str, Any] | None = None,
    *,
    status: str = "confirmed",
) -> Any:

    return WarehouseAgentDraft(
        draft_no="WR20990101-401",
        scene="finished_receipt",
        status=status,
        recognized=recognized,
        aligned=aligned or {},
    )


class TestBuildFinishedReceiptRows:
    def test_rows_parsed_and_malformed_dropped(self) -> None:
        payload = {
            "product_name": {"value": "达托霉素", "confidence": 0.9},
            "product_batch_no": {"value": "DA2609011", "confidence": 0.9},
            "quantity": {"value": "14.62", "confidence": 0.8},
            "unit": {"value": "kg", "confidence": 0.95},
            "rows": [
                {"product_name": "达托霉素", "product_batch_no": "DA2609011",
                 "quantity": 12, "unit": "kg", "spec": None,
                 "produced_at": "2026.09.14", "expiry": "2028.09.13"},
                {"product_name": "达托霉素", "product_batch_no": "DA2609011",
                 "quantity": 2.62, "unit": "kg"},
                {"product_name": "达托霉素"},  # 残行（缺批号/数量）丢弃
                "junk",
            ],
        }
        r = build_finished_receipt(payload)
        assert len(r.rows) == 2
        assert r.rows[0]["quantity"] == 12
        assert r.rows[1]["quantity"] == 2.62

    def test_single_row_document_still_has_rows(self) -> None:
        payload = {
            "product_name": {"value": "达托霉素", "confidence": 0.9},
            "product_batch_no": {"value": "DA2609001", "confidence": 0.9},
            "quantity": {"value": "5", "confidence": 0.9},
            "unit": {"value": "kg", "confidence": 0.9},
            "rows": [
                {"product_name": "达托霉素", "product_batch_no": "DA2609001",
                 "quantity": 5, "unit": "kg"}
            ],
        }
        assert len(build_finished_receipt(payload).rows) == 1

    def test_scalar_quantity_promoted_to_group_sum(self) -> None:
        """同批多行：标量 quantity 解析时提升为归组总和（卡片展示=提交口径）。"""
        payload = {
            "product_name": {"value": "盐酸万古霉素沉淀物", "confidence": 0.9},
            "product_batch_no": {"value": "HAP2609003E3", "confidence": 0.9},
            "quantity": {"value": "40", "confidence": 0.9},
            "unit": {"value": "kg", "confidence": 0.95},
            "rows": [
                {"product_name": "盐酸万古霉素沉淀物", "product_batch_no": "HAP2609003E3",
                 "quantity": 40, "unit": "kg"},
                {"product_name": "盐酸万古霉素沉淀物", "product_batch_no": "HAP2609003E3",
                 "quantity": 1.1, "unit": "kg"},
            ],
        }
        r = build_finished_receipt(payload)
        assert r.quantity.value == 41.1


class TestNormalizeRows:
    def test_same_batch_grouped_and_summed(self) -> None:
        draft = _draft(
            {
                "rows": [
                    {"product_name": "达托霉素", "product_batch_no": "DA2609011",
                     "quantity": "12", "unit": "kg"},
                    {"product_name": "达托霉素", "product_batch_no": "DA2609011",
                     "quantity": "2.62", "unit": "kg"},
                ]
            }
        )
        rows = normalize_finished_receipt_rows(draft)
        assert len(rows) == 1
        assert rows[0]["quantity"] == pytest.approx(14.62)
        assert "共2行合并" in rows[0].get("remark", "")

    def test_different_batches_stay_separate(self) -> None:
        draft = _draft(
            {
                "rows": [
                    {"product_name": "达托霉素", "product_batch_no": "DA2609011",
                     "quantity": "12", "unit": "kg"},
                    {"product_name": "达托霉素", "product_batch_no": "DA2609012",
                     "quantity": "5", "unit": "kg"},
                ]
            }
        )
        rows = normalize_finished_receipt_rows(draft)
        assert len(rows) == 2
        assert rows[0]["product_batch_no"] == "DA2609011"
        assert rows[1]["product_batch_no"] == "DA2609012"

    def test_document_level_fields_apply_to_all_rows(self) -> None:
        draft = _draft(
            {
                "workshop": {"value": "提炼工程一部", "confidence": 0.8},
                "receipt_date": {"value": "2026-09-15", "confidence": 0.9},
                "rows": [
                    {"product_name": "达托霉素", "product_batch_no": "B1",
                     "quantity": "1", "unit": "kg"},
                    {"product_name": "达托霉素", "product_batch_no": "B2",
                     "quantity": "2", "unit": "kg"},
                ],
            }
        )
        rows = normalize_finished_receipt_rows(draft)
        for row in rows:
            assert row["workshop"] == "提炼工程一部"
            assert row["receipt_date"] == "2026-09-15"

    def test_aligned_override_applies_to_first_row(self) -> None:
        draft = _draft(
            {
                "rows": [
                    {"product_name": "达托霉素", "product_batch_no": "B1",
                     "quantity": "1", "unit": "kg"},
                    {"product_name": "达托霉素", "product_batch_no": "B2",
                     "quantity": "2", "unit": "kg"},
                ]
            },
            aligned={"quantity": "55"},
        )
        rows = normalize_finished_receipt_rows(draft)
        assert rows[0]["quantity"] == 55
        assert rows[1]["quantity"] == 2  # 归组后 quantity 数字化

    def test_dialog_path_single_row_fallback(self) -> None:
        draft = _draft(
            {},
            aligned={
                "product_name": "达托霉素",
                "product_batch_no": "B1",
                "quantity": "10",
                "unit": "kg",
                "workshop": "提炼工程一部",
            },
        )
        rows = normalize_finished_receipt_rows(draft)
        assert len(rows) == 1
        assert rows[0]["workshop"] == "提炼工程一部"

    def test_receipt_type_applies_to_every_row(self) -> None:
        """入库类型为文档级字段（P0-1）：应用到每一行。"""
        draft = _draft(
            {
                "receipt_type": {"value": "退货入库", "confidence": 0.85},
                "rows": [
                    {"product_name": "达托霉素", "product_batch_no": "B1",
                     "quantity": "1", "unit": "kg"},
                    {"product_name": "达托霉素", "product_batch_no": "B2",
                     "quantity": "2", "unit": "kg"},
                ],
            }
        )
        rows = normalize_finished_receipt_rows(draft)
        for row in rows:
            assert row["receipt_type"] == "退货入库"


class TestRowFieldsBuilder:
    def test_row_defaults_and_mapping(self) -> None:
        fields, degraded = build_finished_receipt_row_fields(
            {
                "product_name": "达托霉素",
                "product_batch_no": "B1",
                "quantity": "14.62",
                "unit": "kg",
                "workshop": "提炼工程一部",
                "receipt_date": "2026-09-15",
            },
            table_fields=_fr_fields(),
            today=NOW,
        )
        assert degraded == []
        assert fields["入库数量"] == 14.62
        assert fields["质量状态"] == "待检"
        assert fields["入库日期"] == int(
            datetime(2026, 9, 15, tzinfo=UTC).timestamp() * 1000
        )
        assert fields["备注"] == "入库车间：提炼工程一部"

    def test_group_remark_lands_in_remark(self) -> None:
        fields, _ = build_finished_receipt_row_fields(
            {
                "product_name": "达托霉素",
                "product_batch_no": "B1",
                "quantity": "14.62",
                "unit": "kg",
                "remark": "共2行合并",
            },
            table_fields=_fr_fields(),
            today=NOW,
        )
        assert fields["备注"] == "共2行合并"

    def test_receipt_type_links_quality_per_row(self) -> None:
        """行级组装：入库类型写入 + 质量状态联动（退货入库→退货）。"""
        fields, degraded = build_finished_receipt_row_fields(
            {
                "product_name": "达托霉素",
                "product_batch_no": "B1",
                "quantity": "1",
                "unit": "kg",
                "receipt_type": "退货入库",
            },
            table_fields=_fr_fields(),
            today=NOW,
        )
        assert degraded == []
        assert fields["入库类型"] == "退货入库"
        assert fields["质量状态"] == "退货"


class TestMultiRowSubmit:
    async def test_submit_writes_n_rows(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        adapter = FakeAdapter()
        monkeypatch.setattr(submit_module, "get_adapter", lambda: adapter)
        draft = _draft(
            {
                "rows": [
                    {"product_name": "达托霉素", "product_batch_no": "B1",
                     "quantity": "12", "unit": "kg"},
                    {"product_name": "达托霉素", "product_batch_no": "B1",
                     "quantity": "2.62", "unit": "kg"},
                    {"product_name": "达托霉素", "product_batch_no": "B2",
                     "quantity": "5", "unit": "kg"},
                ]
            }
        )
        db_session.add(draft)
        await db_session.flush()

        try:
            note = await submit_module.submit_finished_receipt(db_session, draft)
        except KeyError:
            import traceback
            traceback.print_exc()
            raise
        assert draft.status == "submitted"
        # 同批归组：B1 一条 + B2 一条 = 2 条台账
        assert len(adapter.created_rows) == 2
        assert draft.target_record_id == "rec_fake_fr_001"
        for _f in adapter.created_rows:
            print("DEBUG elem:", type(_f), repr(list(_f.keys())) if hasattr(_f, "keys") else _f)
        quantities = [f["fields"]["入库数量"] for f in adapter.created_rows]
        assert quantities[0] == pytest.approx(14.62)
        assert quantities[1] == 5
        assert all(f["fields"]["质量状态"] == "待检" for f in adapter.created_rows)
        assert "共 2 行" in note

        audits = (
            await db_session.execute(
                select(WarehouseAgentAudit).where(
                    WarehouseAgentAudit.draft_id == draft.id
                )
            )
        ).scalars().all()
        assert audits[-1].args_summary["row_count"] == 2

    async def test_confirm_card_multi_row_render(self) -> None:
        from tests.modules.warehouse.test_finished_receipt import (
            _card_content,
            _confirm_buttons,
        )

        draft = _draft(
            {
                "rows": [
                    {"product_name": "达托霉素", "product_batch_no": "B1",
                     "quantity": "12", "unit": "kg"},
                    {"product_name": "达托霉素", "product_batch_no": "B2",
                     "quantity": "5", "unit": "kg"},
                ]
            },
            status="aligned",
        )
        card = cards.render_receipt_confirm_card(draft)
        assert card["header"]["title"]["content"] == "🏭 成品入库登记"
        content = _card_content(card)
        assert "共 2 行" in content
        assert "批 **B1**：12 kg" in content
        assert "批 **B2**：5 kg" in content
        buttons = _confirm_buttons(card)
        assert buttons[0]["value"]["scene"] == "finished_receipt"
