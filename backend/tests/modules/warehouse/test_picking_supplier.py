"""领料 FIFO 匹配与供应商准入测试（V3.0 分期C，设计 §4.2/§4.3）。

接缝（spec Testing Decisions，沿用分期A/B）：服务函数级 + FakeBaseAdapter /
dry_run / monkeypatch 开关与 runtime 参数；共享库有真机数据，精确断言前
事务内清表（_hermetic 模式）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.tools import picking


def _stock_record(
    record_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    return {"record_id": record_id, "fields": fields}


def _released_batch(
    batch: str,
    *,
    qty: float,
    inbound: str,
    location: str = "25#仓库(一)一层 原辅料库1区",
    unit: str = "Kg",
    name: str = "硫酸",
) -> dict[str, Any]:
    """QA放行=放行 的库存行（lookup 列读回数组形态，与真机契约一致）。"""
    return _stock_record(
        f"rec_{batch}",
        {
            "物料批号": batch,
            "物料名称": name,
            "剩余数量": {"type": 20, "value": [qty]},
            "单位": unit,
            "QA放行": ["放行"],
            "入库日期": f"{inbound} 00:00:00",
            "贮存/槽车取样点": location,
        },
    )


class FakeStockAdapter:
    """material_stock 拉取假件（按构造的记录集返回）。"""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.calls: list[dict[str, Any]] = []

    async def search_records_page(
        self,
        table_key: str,
        *,
        filter_json: dict[str, Any] | None,
        field_names: list[str],
        limit: int,
        page_token: str | None,
        sort: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"table_key": table_key, "filter_json": filter_json})
        assert table_key == "material_stock"
        return {"records": self._records, "total": len(self._records), "page_token": None}


# ── Ticket 01：FIFO 匹配引擎（纯函数级）──


class TestFifoPlan:
    """fifo_plan：纯函数（记录集 → 建议批次列表）。"""

    def test_orders_by_inbound_date_ascending(self) -> None:
        records = [
            _released_batch("B2", qty=300, inbound="2026-09-02"),
            _released_batch("B1", qty=300, inbound="2026-08-01"),
        ]
        plan = picking.fifo_plan(records, quantity=500)
        assert [item["batch_no"] for item in plan] == ["B1", "B2"]
        assert plan[0]["pick_qty"] == 300
        assert plan[1]["pick_qty"] == 200

    def test_cross_batch_split_exact_remainder(self) -> None:
        records = [
            _released_batch("B1", qty=120.5, inbound="2026-08-01"),
            _released_batch("B2", qty=1000, inbound="2026-09-01"),
        ]
        plan = picking.fifo_plan(records, quantity=620.5)
        assert plan[0]["pick_qty"] == 120.5
        assert plan[1]["pick_qty"] == 500

    def test_ignores_non_released_batches(self) -> None:
        records = [
            _released_batch("B1", qty=100, inbound="2026-08-01"),
            _stock_record(
                "recB2",
                {
                    "物料批号": "B2",
                    "物料名称": "硫酸",
                    "剩余数量": {"type": 20, "value": [500]},
                    "单位": "Kg",
                    "QA放行": ["条件放行"],  # 非放行不进建议
                    "入库日期": "2026-07-01 00:00:00",
                    "贮存/槽车取样点": "x",
                },
            ),
            _stock_record(
                "recB3",
                {
                    "物料批号": "B3",
                    "物料名称": "硫酸",
                    "剩余数量": {"type": 20, "value": [500]},
                    "QA放行": [],  # lookup 空数组 = 未放行
                },
            ),
        ]
        plan = picking.fifo_plan(records, quantity=80)
        assert [item["batch_no"] for item in plan] == ["B1"]

    def test_carries_batch_meta_fields(self) -> None:
        records = [_released_batch("B1", qty=100, inbound="2026-08-01")]
        plan = picking.fifo_plan(records, quantity=50)
        item = plan[0]
        assert item["batch_no"] == "B1"
        assert item["pick_qty"] == 50
        assert item["stock_qty"] == 100
        assert item["unit"] == "Kg"
        assert item["location"] == "25#仓库(一)一层 原辅料库1区"
        assert item["record_id"] == "rec_B1"

    def test_insufficient_total_raises(self) -> None:
        records = [_released_batch("B1", qty=100, inbound="2026-08-01")]
        with pytest.raises(picking.PickingError) as exc_info:
            picking.fifo_plan(records, quantity=500)
        assert exc_info.value.code == "insufficient_stock"
        assert "100" in exc_info.value.message  # 附可用总量

    def test_no_records_raises_no_released(self) -> None:
        with pytest.raises(picking.PickingError) as exc_info:
            picking.fifo_plan([], quantity=10)
        assert exc_info.value.code == "no_released_batch"


# ── Ticket 01：库存拉取（async）──


class TestFetchStockForPicking:
    async def test_fetch_filters_by_material_keyword(self) -> None:
        adapter = FakeStockAdapter(
            [
                _released_batch("B1", qty=100, inbound="2026-08-01"),
                _stock_record(
                    "recOther",
                    {"物料批号": "X1", "物料名称": "丙酮", "QA放行": ["放行"]},
                ),
            ]
        )
        rows = await picking.fetch_stock_for_picking(adapter, "硫酸")
        assert len(rows) == 1
        assert rows[0]["fields"]["物料批号"] == "B1"

    async def test_fetch_local_match_tolerates_wrapped_name(self) -> None:
        """物料名称为单选/lookup 混合形态（读回数组），本地匹配走规范化。"""
        adapter = FakeStockAdapter(
            [
                _stock_record(
                    "recW",
                    {
                        "物料批号": "W1",
                        "物料名称": {"type": 3, "value": ["无水碳酸钾"]},
                        "QA放行": ["放行"],
                    },
                ),
            ]
        )
        rows = await picking.fetch_stock_for_picking(adapter, "碳酸钾")
        assert len(rows) == 1


# ── Ticket 01：指定批号校验 ──


class TestValidateDesignatedBatch:
    def test_designated_released_batch_ok(self) -> None:
        records = [
            _released_batch("B1", qty=100, inbound="2026-08-01"),
            _released_batch("B2", qty=800, inbound="2026-09-01"),
        ]
        plan, warning = picking.plan_for_designated_batch(records, "B2", quantity=500)
        assert [item["batch_no"] for item in plan] == ["B2"]
        assert plan[0]["pick_qty"] == 500
        assert warning == ""

    def test_designated_batch_not_found(self) -> None:
        with pytest.raises(picking.PickingError) as exc_info:
            picking.plan_for_designated_batch([], "NOPE", quantity=10)
        assert exc_info.value.code == "batch_not_found"

    def test_designated_batch_not_released(self) -> None:
        records = [
            _stock_record(
                "recB1",
                {
                    "物料批号": "B1",
                    "剩余数量": {"type": 20, "value": [100]},
                    "QA放行": [],
                },
            ),
        ]
        with pytest.raises(picking.PickingError) as exc_info:
            picking.plan_for_designated_batch(records, "B1", quantity=10)
        assert exc_info.value.code == "no_released_batch"

    def test_designated_conditional_release_allowed_with_warning(self) -> None:
        records = [
            _stock_record(
                "recB1",
                {
                    "物料批号": "B1",
                    "物料名称": "硫酸",
                    "剩余数量": {"type": 20, "value": [100]},
                    "单位": "Kg",
                    "QA放行": ["条件放行"],
                    "入库日期": "2026-08-01 00:00:00",
                    "贮存/槽车取样点": "x",
                },
            ),
        ]
        plan, warning = picking.plan_for_designated_batch(records, "B1", quantity=100)
        assert [item["batch_no"] for item in plan] == ["B1"]
        assert "条件放行" in warning

    def test_designated_batch_insufficient_qty(self) -> None:
        records = [_released_batch("B1", qty=100, inbound="2026-08-01")]
        with pytest.raises(picking.PickingError) as exc_info:
            picking.plan_for_designated_batch(records, "B1", quantity=500)
        assert exc_info.value.code == "insufficient_stock"


# ── Ticket 01：create_picking_draft 工具壳（工具级接缝）──


def _outbound_fields_for_test() -> dict[str, Any]:
    """material_outbound 字段元数据（单测注入；选项集受控子集）。"""
    from app.modules.warehouse.bitable_schema import FIELD_TYPE_SELECT, FieldMeta

    return {
        "物料批号": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("B1", "B2", "10407-251008")
        ),
        "领用类型": FieldMeta(
            type=FIELD_TYPE_SELECT,
            options=("生产使用", "研发使用", "部门领用", "采购退货"),
        ),
        "领用部门": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("精制工程一部", "提炼工程一部")
        ),
        "出库数量": FieldMeta(type=2),
        "领用日期": FieldMeta(type=5),
        "备注": FieldMeta(type=1),
    }


@pytest.fixture
async def picking_unit_env(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """picking 工具环境：_db_session 注入测试 session、选项集静态假件、
    notification 发送捕获（dry-run，不触网）。返回 {"db", "sends"}。"""
    import json as _json
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    from app.modules.warehouse.feishu import notification

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(picking, "_db_session", _patched)

    table_fields = _outbound_fields_for_test()

    async def _fake_table_fields() -> dict[str, Any]:
        return table_fields

    monkeypatch.setattr(picking, "_outbound_table_fields", _fake_table_fields)

    sent: list[dict[str, str]] = []

    async def fake_send(payload: dict[str, str]) -> str | None:
        sent.append(payload)
        return "om_fake_id"

    monkeypatch.setattr(notification, "_send_create", fake_send)

    def _card_content(title: str) -> str:
        for payload in sent:
            if payload.get("msg_type") != "interactive":
                continue
            card = _json.loads(payload["content"])
            if card.get("header", {}).get("title", {}).get("content") == title:
                return "\n".join(
                    element.get("content") or ""
                    for element in card.get("body", {}).get("elements", [])
                    if isinstance(element, dict)
                )
        return ""

    return {"db": db_session, "sends": sent, "card_content": _card_content}


def _with_adapter(
    monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]
) -> FakeStockAdapter:
    adapter = FakeStockAdapter(records)
    monkeypatch.setattr(picking, "get_adapter", lambda: adapter)
    return adapter


async def test_create_picking_draft_missing_fields(
    picking_unit_env: dict[str, Any],
) -> None:
    """缺领用部门 → missing 追问，不建草稿。"""
    result = await picking.create_picking_draft(
        {"物料": "硫酸", "领用数量": "500", "单位": "Kg"},
        _ctx={"open_id": "ou_pick_miss", "chat_id": "oc_pick_miss"},
    )
    assert result["status"] == "incomplete"
    assert result["missing"] == ["领用部门"]
    assert "请补充" in result["hint"]


async def test_create_picking_draft_no_released_batch(
    picking_unit_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """无放行批次 → 明确 error（no_released_batch），不建草稿。"""
    _with_adapter(
        monkeypatch,
        [
            _stock_record(
                "recB1",
                {
                    "物料批号": "B1",
                    "物料名称": "硫酸",
                    "剩余数量": {"type": 20, "value": [100]},
                    "QA放行": ["否决"],
                },
            ),
        ],
    )
    result = await picking.create_picking_draft(
        {"物料": "硫酸", "领用数量": "500", "单位": "Kg", "领用部门": "精制工程一部"},
        _ctx={"open_id": "ou_pick_nr", "chat_id": "oc_pick_nr"},
    )
    assert result["error_code"] == "no_released_batch"
    assert "放行" in result["error"]


async def test_create_picking_draft_insufficient_stock(
    picking_unit_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """放行总量不足 → error 附可用总量，不建草稿。"""
    _with_adapter(
        monkeypatch, [_released_batch("B1", qty=100, inbound="2026-08-01")]
    )
    result = await picking.create_picking_draft(
        {"物料": "硫酸", "领用数量": "500", "单位": "Kg", "领用部门": "精制工程一部"},
        _ctx={"open_id": "ou_pick_ins", "chat_id": "oc_pick_ins"},
    )
    assert result["error_code"] == "insufficient_stock"
    assert "100" in result["error"]


async def test_create_picking_draft_success_with_plan(
    picking_unit_env: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """齐全 → 草稿 + FIFO 建议 + 默认生产使用 + 确认卡片（领料分支）。"""
    from sqlalchemy import select

    from app.modules.warehouse.agent.cards import PICKING_CONFIRM_CARD_TITLE
    from app.modules.warehouse.models import WarehouseAgentDraft

    db: AsyncSession = picking_unit_env["db"]
    _with_adapter(
        monkeypatch,
        [
            _released_batch("B2", qty=300, inbound="2026-09-02"),
            _released_batch("B1", qty=300, inbound="2026-08-01", location="16#旧原料库一"),
        ],
    )
    result = await picking.create_picking_draft(
        {
            "物料": "硫酸",
            "领用数量": "500",
            "单位": "Kg",
            "领用部门": "精制工程一部",
            "备注": "急用",
        },
        _ctx={"open_id": "ou_pick_ok", "chat_id": "oc_pick_ok"},
    )
    assert "error" not in result, result
    assert result["status"] == "pending_confirm"
    # 默认领用类型 + 部门选项归一
    assert result["fields"]["use_type"] == "生产使用"
    assert result["fields"]["department"] == "精制工程一部"
    # FIFO 建议：最早入库优先，跨批拆分
    plan = result["picking_plan"]
    assert [item["batch_no"] for item in plan] == ["B1", "B2"]
    assert plan[0]["pick_qty"] == 300 and plan[1]["pick_qty"] == 200

    drafts = (
        (
            await db.execute(
                select(WarehouseAgentDraft).where(
                    WarehouseAgentDraft.created_by_open_id == "ou_pick_ok"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.status == "pending_confirm"
    assert draft.scene == "picking_outbound"
    assert [item["batch_no"] for item in draft.aligned["picking_plan"]] == ["B1", "B2"]
    assert draft.aligned["use_type"] == "生产使用"
    assert draft.aligned["material_name"] == "硫酸"

    content = picking_unit_env["card_content"](PICKING_CONFIRM_CARD_TITLE)
    assert "FIFO 批次建议" in content
    assert "B1" in content and "B2" in content
    assert "16#旧原料库一" in content
    assert "1. 物料：硫酸" in content


async def test_create_picking_draft_designated_conditional_warning(
    picking_unit_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户指定条件放行批号 → 放行该操作并附 warning。"""
    _with_adapter(
        monkeypatch,
        [
            _stock_record(
                "recB1",
                {
                    "物料批号": "B1",
                    "物料名称": "硫酸",
                    "剩余数量": {"type": 20, "value": [100]},
                    "单位": "Kg",
                    "QA放行": ["条件放行"],
                    "入库日期": "2026-08-01 00:00:00",
                    "贮存/槽车取样点": "x",
                },
            ),
        ],
    )
    result = await picking.create_picking_draft(
        {
            "物料": "硫酸",
            "领用数量": "100",
            "单位": "Kg",
            "领用部门": "精制工程一部",
            "指定批号": "B1",
        },
        _ctx={"open_id": "ou_pick_cond", "chat_id": "oc_pick_cond"},
    )
    assert "error" not in result, result
    assert any("条件放行" in w for w in result["warnings"])
    assert result["picking_plan"][0]["batch_no"] == "B1"
    from app.modules.warehouse.agent.cards import PICKING_CONFIRM_CARD_TITLE

    assert "条件放行" in picking_unit_env["card_content"](PICKING_CONFIRM_CARD_TITLE)


# ── Ticket 02：submit_picking 写台账 / 确认人放开 / 对话改批号 ──


class FakeOutboundAdapter:
    """material_outbound 写入假件（捕获 create_record，get_record 原样读回）。"""

    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, Any]]] = []

    async def refresh_table_fields(self, table_key: str) -> None:
        return None

    async def create_record(
        self, table_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self.created.append((table_key, dict(fields)))
        return {"record_id": "recOUT1"}

    async def get_record(self, table_key: str, record_id: str) -> dict[str, Any]:
        fields = dict(self.created[-1][1]) if self.created else {}
        return {"record_id": record_id, "fields": fields}


def _picking_draft_row(
    aligned: dict[str, Any], *, status: str = "confirmed"
) -> Any:
    """领料草稿 ORM 对象（aligned 即 working set；draft_no/id 供审计/卡片）。"""
    import uuid as _uuid

    from app.modules.warehouse.models import WarehouseAgentDraft

    return WarehouseAgentDraft(
        draft_no="WR20990101-201",
        scene="picking_outbound",
        status=status,
        recognized=dict(aligned),
        aligned=dict(aligned),
        id=_uuid.uuid4(),
        chat_id="oc_pick_receipt",
    )


class TestBuildPickingFields:
    def test_designated_batch_and_defaults(self) -> None:
        from datetime import date

        from app.modules.warehouse.agent.pipeline.submit import (
            _today_ms,
            build_picking_fields,
        )

        draft = _picking_draft_row(
            {
                "material": "硫酸",
                "material_name": "硫酸",
                "quantity": 500,
                "unit": "Kg",
                "department": "精制工程一部",
                "use_type": "生产使用",
                "designated_batch": "10407-251008",
                "picking_plan": [{"batch_no": "10407-251008", "pick_qty": 500}],
            }
        )
        fields, degraded = build_picking_fields(
            draft,
            table_fields=_outbound_fields_for_test(),
            today=date(2026, 9, 18),
        )
        assert degraded == []
        assert fields["物料批号"] == "10407-251008"
        assert fields["出库数量"] == 500
        assert fields["领用日期"] == _today_ms(date(2026, 9, 18))
        assert fields["领用类型"] == "生产使用"
        assert fields["领用部门"] == "精制工程一部"

    def test_first_plan_batch_when_no_designation(self) -> None:
        from app.modules.warehouse.agent.pipeline.submit import build_picking_fields

        draft = _picking_draft_row(
            {
                "material": "硫酸",
                "quantity": 500,
                "department": "精制工程一部",
                "picking_plan": [
                    {"batch_no": "B1", "pick_qty": 300},
                    {"batch_no": "B2", "pick_qty": 200},
                ],
            }
        )
        fields, degraded = build_picking_fields(
            draft, table_fields=_outbound_fields_for_test()
        )
        # 首批自动写入（跨批拆分余量人工在 Base 拆行，回执提示）
        assert fields["物料批号"] == "B1"
        assert fields["出库数量"] == 300
        assert degraded == []

    def test_select_mismatch_degraded(self) -> None:
        from app.modules.warehouse.agent.pipeline.submit import build_picking_fields

        draft = _picking_draft_row(
            {
                "material": "硫酸",
                "quantity": 500,
                "department": "精制工程一部",
                "use_type": "不存在的类型",
                "picking_plan": [{"batch_no": "NOPE", "pick_qty": 500}],
            }
        )
        fields, degraded = build_picking_fields(
            draft, table_fields=_outbound_fields_for_test()
        )
        assert "物料批号" in degraded and "物料批号" not in fields
        assert "领用类型" in degraded and "领用类型" not in fields
        assert fields["出库数量"] == 500


class TestSubmitPicking:
    async def test_requires_confirmed(self, db_session: AsyncSession) -> None:
        from app.modules.warehouse.agent.pipeline.draft_flow import DraftFlowError
        from app.modules.warehouse.agent.pipeline.submit import submit_picking

        draft = _picking_draft_row({"material": "硫酸"}, status="pending_confirm")
        with pytest.raises(DraftFlowError):
            await submit_picking(db_session, draft)
        assert draft.status == "pending_confirm"

    async def test_submit_success_writes_outbound(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        from app.modules.warehouse.agent.pipeline import submit as submit_module
        from app.modules.warehouse.feishu import notification

        adapter = FakeOutboundAdapter()
        monkeypatch.setattr(submit_module, "get_adapter", lambda: adapter)

        async def _fake_table_fields() -> dict[str, Any]:
            return _outbound_fields_for_test()

        monkeypatch.setattr(
            submit_module, "_picking_table_fields", _fake_table_fields
        )
        sent: list[dict[str, str]] = []

        async def fake_send(payload: dict[str, str]) -> str | None:
            sent.append(payload)
            return "om_out"

        monkeypatch.setattr(notification, "_send_create", fake_send)

        draft = _picking_draft_row(
            {
                "material": "硫酸",
                "quantity": 500,
                "unit": "Kg",
                "department": "精制工程一部",
                "designated_batch": "10407-251008",
                "picking_plan": [{"batch_no": "10407-251008", "pick_qty": 500}],
            }
        )
        note = await submit_module.submit_picking(db_session, draft)
        assert draft.status == "submitted"
        assert draft.target_record_id == "recOUT1"
        assert len(adapter.created) == 1
        table_key, fields = adapter.created[0]
        assert table_key == "material_outbound"
        assert fields["物料批号"] == "10407-251008"
        assert fields["领用类型"] == "生产使用"
        assert note and "✅ 领料已登记" in note
        # 回执卡（领料分支标题）已捕获
        import json as _json

        receipt_cards = [
            _json.loads(p["content"])
            for p in sent
            if p.get("msg_type") == "interactive"
        ]
        assert any(
            c.get("header", {}).get("title", {}).get("content") == "✅ 领料已登记"
            for c in receipt_cards
        )

    async def test_submit_create_failure_propagates(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """写入异常向上抛（confirm 统一置 failed）；draft 保持 confirmed。"""
        from app.modules.warehouse.agent.pipeline import submit as submit_module
        from app.modules.warehouse.bitable_schema import WarehouseBitableError

        class _BoomAdapter(FakeOutboundAdapter):
            async def create_record(
                self, table_key: str, fields: dict[str, Any]
            ) -> dict[str, Any]:
                raise WarehouseBitableError("Base 写入失败", code=91403)

        monkeypatch.setattr(submit_module, "get_adapter", lambda: _BoomAdapter())

        async def _fake_table_fields() -> dict[str, Any]:
            return _outbound_fields_for_test()

        monkeypatch.setattr(
            submit_module, "_picking_table_fields", _fake_table_fields
        )
        draft = _picking_draft_row(
            {
                "material": "硫酸",
                "quantity": 500,
                "department": "精制工程一部",
                "picking_plan": [{"batch_no": "10407-251008", "pick_qty": 500}],
            }
        )
        with pytest.raises(WarehouseBitableError):
            await submit_module.submit_picking(db_session, draft)
        assert draft.status == "confirmed"  # 异常路径不改状态（confirm 收尾处置）


class TestConfirmRequesterBypass:
    async def test_picking_allows_non_requester(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """领料场景放开「仅发起人可点」：仓管员（非发起人）可确认。"""
        from app.modules.warehouse.agent import confirm
        from app.modules.warehouse.models import WarehouseAgentDraft

        draft = WarehouseAgentDraft(
            draft_no="WR20990101-210",
            scene="picking_outbound",
            status="pending_confirm",
            recognized={},
            aligned={},
            created_by_open_id="ou_requester",
        )
        db_session.add(draft)
        await db_session.flush()

        async def _fake_callback(db: AsyncSession, d: Any) -> str:
            return "ok"

        monkeypatch.setitem(confirm._confirm_callbacks, "picking_outbound", _fake_callback)
        outcome = await confirm.handle_action(
            db_session,
            value={
                "scene": "picking_outbound",
                "draft_id": str(draft.id),
                "action": "confirm",
            },
            operator_open_id="ou_warehouse_keeper",
        )
        assert outcome.ok and outcome.status == "confirmed"
        assert draft.status == "confirmed"

    async def test_other_scenes_still_requester_only(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回归：GMP 场景非发起人仍 denied。"""
        from app.modules.warehouse.agent import confirm
        from app.modules.warehouse.models import WarehouseAgentDraft

        draft = WarehouseAgentDraft(
            draft_no="WR20990101-211",
            scene="gmp_outbound",
            status="pending_confirm",
            recognized={},
            aligned={},
            created_by_open_id="ou_requester",
        )
        db_session.add(draft)
        await db_session.flush()
        outcome = await confirm.handle_action(
            db_session,
            value={
                "scene": "gmp_outbound",
                "draft_id": str(draft.id),
                "action": "confirm",
            },
            operator_open_id="ou_other",
        )
        assert not outcome.ok and outcome.status == "denied"
        assert draft.status == "pending_confirm"


class TestUpdateDraftRepick:
    async def test_designated_batch_replans(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """改指定批号 → aligned 更新 + picking_plan 重算 + 卡片重发。"""
        import json as _json
        from collections.abc import AsyncIterator
        from contextlib import asynccontextmanager

        from app.modules.warehouse.agent.tools import draft_update as du_module
        from app.modules.warehouse.agent.tools import picking as picking_module
        from app.modules.warehouse.agent.tools.draft_update import update_draft
        from app.modules.warehouse.feishu import notification
        from app.modules.warehouse.models import WarehouseAgentDraft

        draft = WarehouseAgentDraft(
            draft_no="WR20990101-220",
            scene="picking_outbound",
            status="pending_confirm",
            recognized={},
            aligned={
                "material": "硫酸",
                "quantity": 500,
                "unit": "Kg",
                "department": "精制工程一部",
                "picking_plan": [
                    {"batch_no": "B1", "pick_qty": 300},
                    {"batch_no": "B2", "pick_qty": 200},
                ],
            },
            created_by_open_id="ou_req",
        )
        db_session.add(draft)
        await db_session.flush()

        @asynccontextmanager
        async def _patched() -> AsyncIterator[AsyncSession]:
            yield db_session

        monkeypatch.setattr(du_module, "_db_session", _patched)

        sent: list[dict[str, str]] = []

        async def fake_send(payload: dict[str, str]) -> str | None:
            sent.append(payload)
            return "om_replan"

        monkeypatch.setattr(notification, "_send_create", fake_send)

        replan_records = [
            _released_batch("B1", qty=300, inbound="2026-08-01"),
            _released_batch("B2", qty=800, inbound="2026-09-01"),
        ]
        replan_adapter = FakeStockAdapter(replan_records)
        monkeypatch.setattr(picking_module, "get_adapter", lambda: replan_adapter)

        result = await update_draft(
            "WR20990101-220",
            {"指定批号": "B2"},
            _ctx={"open_id": "ou_req", "chat_id": "oc_x"},
        )
        assert "error" not in result, result
        assert draft.aligned["designated_batch"] == "B2"
        assert [item["batch_no"] for item in draft.aligned["picking_plan"]] == ["B2"]
        assert draft.aligned["picking_plan"][0]["pick_qty"] == 500

        # 确认卡已重发（领料分支标题，建议更新为单批 B2）
        from app.modules.warehouse.agent.cards import PICKING_CONFIRM_CARD_TITLE

        resend_cards = [
            _json.loads(p["content"])
            for p in sent
            if p.get("msg_type") == "interactive"
            and _json.loads(p["content"])
            .get("header", {})
            .get("title", {})
            .get("content")
            == PICKING_CONFIRM_CARD_TITLE
        ]
        assert len(resend_cards) == 1
        content = "\n".join(
            el.get("content") or ""
            for el in resend_cards[0]["body"]["elements"]
            if isinstance(el, dict)
        )
        assert "B2" in content and "B1：" not in content


# ── Ticket 03：供应商名录准入 ──


class FakeSupplierAdapter:
    """supplier_directory 写入假件（fail=True 模拟表未接入）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    async def refresh_table_fields(self, table_key: str) -> None:
        return None

    async def create_record(
        self, table_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        if self.fail:
            from app.modules.warehouse.bitable_schema import WarehouseBitableError

            raise WarehouseBitableError("表坐标未配置", code="unknown_table")
        self.created.append((table_key, dict(fields)))
        return {"record_id": "recSUP1"}


@pytest.fixture
def supplier_unit_env(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """supplier 工具环境：_db_session 注入 + 确认卡发送捕获。"""
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    from app.modules.warehouse.agent.tools import supplier as supplier_module
    from app.modules.warehouse.feishu import notification

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(supplier_module, "_db_session", _patched)

    sent: list[dict[str, str]] = []

    async def fake_send(payload: dict[str, str]) -> str | None:
        sent.append(payload)
        return "om_sup"

    monkeypatch.setattr(notification, "_send_create", fake_send)
    return {"db": db_session, "sends": sent}


class TestSupplierAdmissionTool:
    async def test_missing_supplier_name(
        self, supplier_unit_env: dict[str, Any]
    ) -> None:
        from app.modules.warehouse.agent.tools import supplier

        result = await supplier.create_supplier_admission(
            {"备注": "无名称"}, _ctx={"open_id": "ou_s1", "chat_id": "oc_s1"}
        )
        assert result["status"] == "incomplete"
        assert "供应商名称" in result["missing"]

    async def test_table_unavailable_error(
        self, supplier_unit_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.agent.tools import supplier

        monkeypatch.setattr(
            supplier, "get_adapter", lambda: FakeSupplierAdapter(fail=True)
        )
        result = await supplier.create_supplier_admission(
            {"供应商名称": "测试供应商A"},
            _ctx={"open_id": "ou_s2", "chat_id": "oc_s2"},
        )
        assert result["error_code"] == "supplier_directory_unavailable"
        assert "未接入" in result["error"] or "未就绪" in result["error"]

    async def test_success_creates_row_and_gate(
        self,
        supplier_unit_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """开关开 → 建行（待准入）+ QA 确认门（writeback 两字段）。"""
        from sqlalchemy import select

        from app.modules.warehouse.agent.tools import supplier
        from app.modules.warehouse.models import WarehouseConfirmRequest

        db: AsyncSession = supplier_unit_env["db"]
        adapter = FakeSupplierAdapter()
        monkeypatch.setattr(supplier, "get_adapter", lambda: adapter)
        monkeypatch.setattr(
            "app.modules.warehouse.qc_flow.qc_writeback_enabled", lambda: True
        )

        result = await supplier.create_supplier_admission(
            {"供应商名称": "测试供应商A", "备注": "新供方"},
            _ctx={"open_id": "ou_s3", "chat_id": "oc_s3"},
        )
        assert "error" not in result, result
        assert result["gate_created"] is True
        # 建行字段：名称/待准入/备注
        table_key, fields = adapter.created[0]
        assert table_key == "supplier_directory"
        assert fields["供应商名称"] == "测试供应商A"
        assert fields["审计状态"] == "待准入"
        assert fields["备注"] == "新供方"
        assert "申请日期" in fields
        # 确认门落库 + 回写映射
        gates = (
            (
                await db.execute(
                    select(WarehouseConfirmRequest).where(
                        WarehouseConfirmRequest.business_type
                        == "supplier_admission"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(gates) == 1
        gate = gates[0]
        assert gate.ref_table == "supplier_directory"
        assert gate.ref_record_ids == ["recSUP1"]
        assert gate.writeback == {"审计状态": "准入", "准入日期": "@today"}
        assert gate.status == "pending"
        # 确认卡已发送（dry-run 捕获）
        assert supplier_unit_env["sends"], "确认卡应已发送"

    async def test_switch_off_creates_row_without_gate(
        self,
        supplier_unit_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.warehouse.agent.tools import supplier

        adapter = FakeSupplierAdapter()
        monkeypatch.setattr(supplier, "get_adapter", lambda: adapter)
        monkeypatch.setattr(
            "app.modules.warehouse.qc_flow.qc_writeback_enabled", lambda: False
        )
        result = await supplier.create_supplier_admission(
            {"供应商名称": "测试供应商B"},
            _ctx={"open_id": "ou_s4", "chat_id": "oc_s4"},
        )
        assert "error" not in result, result
        assert result["gate_created"] is False
        assert len(adapter.created) == 1
        assert "待准入" in result["message"] or "待 QA" in result["message"]

    async def test_pending_gate_dedup(
        self,
        supplier_unit_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """同供应商已有 pending 门 → 建行但不重复建门。"""
        from datetime import timedelta

        from app.modules.warehouse.agent.tools import supplier
        from app.modules.warehouse.models import WarehouseConfirmRequest

        db: AsyncSession = supplier_unit_env["db"]
        adapter = FakeSupplierAdapter()
        monkeypatch.setattr(supplier, "get_adapter", lambda: adapter)
        monkeypatch.setattr(
            "app.modules.warehouse.qc_flow.qc_writeback_enabled", lambda: True
        )
        # 预置 pending 门（同名供应商）
        db.add(
            WarehouseConfirmRequest(
                request_no="CR-TEST-SUP-1",
                business_type="supplier_admission",
                title="t",
                summary="s",
                ref_table="supplier_directory",
                ref_record_ids=["recOLD"],
                payload={"supplier_name": "测试供应商C"},
                target="oc_qa",
                writeback={"审计状态": "准入"},
                status="pending",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )
        await db.flush()

        result = await supplier.create_supplier_admission(
            {"供应商名称": "测试供应商C"},
            _ctx={"open_id": "ou_s5", "chat_id": "oc_s5"},
        )
        assert "error" not in result, result
        assert result["gate_created"] is False
        assert result["gate_deduped"] is True


class TestSupplierGateSwitch:
    def test_supplier_admission_governed_by_qc_switch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """supplier_admission 纳入 qc_writeback_allowed 管辖。"""
        from app.modules.warehouse import qc_flow

        monkeypatch.setattr(
            "app.modules.warehouse.qc_flow.qc_writeback_enabled", lambda: False
        )
        assert qc_flow.qc_writeback_allowed("supplier_admission") is False
        monkeypatch.setattr(
            "app.modules.warehouse.qc_flow.qc_writeback_enabled", lambda: True
        )
        assert qc_flow.qc_writeback_allowed("supplier_admission") is True
        # 非 QC/供应商类型不受管辖
        assert qc_flow.qc_writeback_allowed("unqualified_disposition") is True

    async def test_confirm_rejected_when_switch_off(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """开关关 → 遗留 pending 的准入门确认被拒绝、保持 pending。"""
        from datetime import UTC, datetime, timedelta

        from app.modules.warehouse import confirm_request
        from app.modules.warehouse.models import WarehouseConfirmRequest

        monkeypatch.setattr(
            "app.modules.warehouse.base_mirror.bitable_writeback_enabled",
            lambda: True,
        )
        monkeypatch.setattr(
            "app.modules.warehouse.qc_flow.qc_writeback_enabled", lambda: False
        )
        gate = WarehouseConfirmRequest(
            request_no="CR-TEST-SUP-2",
            business_type="supplier_admission",
            title="t",
            summary="s",
            ref_table="supplier_directory",
            ref_record_ids=["recSUP9"],
            payload={"supplier_name": "测试供应商D"},
            target="oc_qa",
            writeback={"审计状态": "准入"},
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        db_session.add(gate)
        await db_session.flush()
        outcome = await confirm_request.handle_action(
            db_session,
            value={
                "scene": confirm_request.CONFIRM_GATE_SCENE,
                "request_id": str(gate.id),
                "action": "confirm",
            },
            operator_open_id="ou_qa",
            execute=False,
        )
        assert not outcome.ok
        assert gate.status == "pending"

    async def test_gate_confirm_writeback_full_path(
        self,
        supplier_unit_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """确认全链路：门确认 → 回写 supplier_directory 两字段（@today 解析）。"""
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock

        from sqlalchemy import select

        from app.modules.warehouse import confirm_request
        from app.modules.warehouse.agent.tools import supplier
        from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
        from app.modules.warehouse.models import WarehouseConfirmRequest

        db: AsyncSession = supplier_unit_env["db"]
        monkeypatch.setattr(supplier, "get_adapter", lambda: FakeSupplierAdapter())
        monkeypatch.setattr(
            "app.modules.warehouse.base_mirror.bitable_writeback_enabled",
            lambda: True,
        )
        monkeypatch.setattr(
            "app.modules.warehouse.qc_flow.qc_writeback_enabled", lambda: True
        )
        result = await supplier.create_supplier_admission(
            {"供应商名称": "测试供应商E"},
            _ctx={"open_id": "ou_s6", "chat_id": "oc_s6"},
        )
        assert result["gate_created"] is True

        gate = (
            (
                await db.execute(
                    select(WarehouseConfirmRequest).where(
                        WarehouseConfirmRequest.business_type == "supplier_admission",
                        WarehouseConfirmRequest.payload.contains(
                            {"supplier_name": "测试供应商E"}
                        ),
                    )
                )
            )
            .scalars()
            .one()
        )

        update_mock = AsyncMock(return_value={"record_id": gate.ref_record_ids[0]})
        monkeypatch.setattr(WarehouseBitableAdapter, "update_record", update_mock)
        outcome = await confirm_request.handle_action(
            db,
            value={
                "scene": confirm_request.CONFIRM_GATE_SCENE,
                "request_id": str(gate.id),
                "action": "confirm",
            },
            operator_open_id="ou_qa_user",
            execute=True,
        )
        assert outcome.ok and outcome.status == "confirmed"
        update_mock.assert_awaited_once()
        args = update_mock.await_args.args
        assert args[0] == "supplier_directory"  # ref_table
        fields = args[2]
        today_ms = int(
            datetime.now(UTC)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
            * 1000
        )
        assert fields["审计状态"] == "准入"
        assert fields["准入日期"] == today_ms  # @today 哨兵解析


# ── Ticket 04：入库供应商比对提醒 ──


def _supplier_mismatch_draft(
    *, supplier_matched: bool, supplier_text: str | None = "可疑供方"
) -> Any:
    from app.modules.warehouse.models import WarehouseAgentDraft

    recognized: dict[str, Any] = {}
    if supplier_text is not None:
        recognized = {"supplier": {"value": supplier_text, "confidence": 0.9}}
    return WarehouseAgentDraft(
        draft_no="WR20990101-301",
        scene="receipt",
        status="submitted",
        recognized=recognized,
        aligned={
            "material_name": "硫酸",
            "supplier_matched": supplier_matched,
        },
        chat_id="oc_mismatch",
    )


class TestSupplierMismatchHook:
    async def test_fires_on_mismatch(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """supplier_matched=False 且识别供应商非空 → 触发推送（payload 断言）。"""
        from app.modules.warehouse.agent.pipeline import submit as submit_module
        from app.modules.warehouse.push_center import events
        from app.modules.warehouse.push_center.engine import PushRunResult

        captured: dict[str, Any] = {}

        async def _fake_fire(db: Any, scene: str, payload: dict, **kw: Any):
            captured["scene"] = scene
            captured["payload"] = payload
            return [PushRunResult("supplier_mismatch_alert", scene, "executed", None, 1)]

        monkeypatch.setattr(events, "fire_push_event", _fake_fire)
        fired = await submit_module._fire_supplier_mismatch(
            db_session,
            _supplier_mismatch_draft(supplier_matched=False),
            {"物料名称(API)": "硫酸", "物料批号": "10307-251201"},
            "recM1",
            {"base_token": "bt", "table_id": "tbl1"},
        )
        assert fired is True
        assert captured["scene"] == "supplier_mismatch_alert"
        assert captured["payload"]["supplier"] == "可疑供方"
        assert captured["payload"]["material_name"] == "硫酸"
        assert captured["payload"]["batch_no"] == "10307-251201"
        assert captured["payload"]["record_url"].endswith("record=recM1")

    async def test_skips_when_matched_or_no_supplier(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """一致 / 识别供应商为空 / 字段缺失 → 不触发。"""
        from app.modules.warehouse.agent.pipeline import submit as submit_module
        from app.modules.warehouse.push_center import events

        async def _boom(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("不应触发推送")

        monkeypatch.setattr(events, "fire_push_event", _boom)
        meta = {"base_token": "b", "table_id": "t"}
        fields = {"物料名称(API)": "硫酸"}
        assert (
            await submit_module._fire_supplier_mismatch(
                db_session,
                _supplier_mismatch_draft(supplier_matched=True),
                fields,
                "rec1",
                meta,
            )
            is False
        )
        assert (
            await submit_module._fire_supplier_mismatch(
                db_session,
                _supplier_mismatch_draft(supplier_matched=False, supplier_text=None),
                fields,
                "rec1",
                meta,
            )
            is False
        )

    async def test_push_failure_swallows(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """推送通道异常吞掉返回 False（不影响登记）。"""
        from app.modules.warehouse.agent.pipeline import submit as submit_module
        from app.modules.warehouse.push_center import events

        async def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("推送通道异常")

        monkeypatch.setattr(events, "fire_push_event", _boom)
        assert (
            await submit_module._fire_supplier_mismatch(
                db_session,
                _supplier_mismatch_draft(supplier_matched=False),
                {"物料名称(API)": "硫酸"},
                "rec1",
                {"base_token": "b", "table_id": "t"},
            )
            is False
        )


class TestSupplierMismatchRegistry:
    def test_task_row_registered(self) -> None:
        from app.modules.warehouse.push_center.registry import iter_tasks

        info = {t.task_name: t for t in iter_tasks()}["supplier_mismatch_alert"]
        assert info.trigger == "event"
        assert info.default_schedule is None
        assert info.target_env_var == "WAREHOUSE_TEST_CHAT_ID"

    def test_renderer_registered_and_renders(self) -> None:
        from app.modules.warehouse.push_center.events import get_event_renderer

        renderer = get_event_renderer("supplier_mismatch_alert")
        assert renderer is not None
        card = renderer(
            {
                "material_name": "硫酸",
                "batch_no": "10307-251201",
                "supplier": "可疑供方",
                "record_url": "https://example.feishu.cn/base/b?table=t&record=r1",
            }
        )
        text = "\n".join(
            element.get("content") or ""
            for element in card.get("body", {}).get("elements", [])
            if isinstance(element, dict)
        )
        assert "硫酸" in text and "可疑供方" in text
        assert "人工核实" in text
        assert "r1" in text

    def test_renderer_tolerates_missing_fields(self) -> None:
        from app.modules.warehouse.push_center.events import get_event_renderer

        renderer = get_event_renderer("supplier_mismatch_alert")
        card = renderer({"supplier": "X"})
        assert card["header"]["title"]["content"]
