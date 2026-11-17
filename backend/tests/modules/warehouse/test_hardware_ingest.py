"""五金库领/退料审批实例摄取测试（二期：飞书发单入口）。

合成实例（mock 表单值两种形态）→ 分流建单/退库草稿/缺料拒收/幂等/状态
同步/对账兜底。审批 API 全部不打真（instance 直传或 monkeypatch）。
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.warehouse.hardware import approval_ingest as ai
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareReceipt,
    HardwareRequisition,
    HardwareReturn,
)
from app.modules.warehouse.hardware.schemas import (
    ReceiptCreate,
    ReceiptItemIn,
)

APPROVAL_CODE = "6FECD1F4-TEST-CODE"


@pytest.fixture
def approval_code(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "HARDWARE_APPROVAL_CODE", APPROVAL_CODE, raising=False)
    return APPROVAL_CODE


async def _mk_material(db, *, name="304不锈钢球阀", spec="DN25", qty_stock=None):
    m = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec=spec, unit="个",
        category="金属阀门", managed_class="stocked", safety_stock=Decimal("0"),
        no_expiry=True,
    )
    db.add(m)
    await db.flush()
    if qty_stock is not None:
        payload = ReceiptCreate(
            source="manual", mode="stocked",
            items=[ReceiptItemIn(material_id=str(m.id), name=m.name, spec=m.spec,
                                 unit=m.unit, quantity=qty_stock, match_confidence="manual")],
        )
        receipt = await hw.create_receipt(db, payload)
        await hw.accept_receipt(
            db, receipt.id, inspected_by_warehouse="ou_test_wh", inspected_by_dept="ou_test_dept"
        )
    return m


def _instance(kind: str, rows: list[dict], *, status="PENDING", dict_shape=False,
              approval_code=APPROVAL_CODE) -> dict:
    """合成审批实例。dict_shape=True 时控件值用 {"text": ..} 形态验证兼容。"""

    def val(v):
        return {"text": v} if dict_shape else v

    form = [
        {"id": ai.KIND_WIDGET_ID, "type": "radioV2", "name": "领/退料",
         "value": val("五金库领料" if kind == "领料" else "五金库退料")},
        {"id": ai.DETAIL_WIDGET_ID, "type": "fieldList", "name": "明细",
         "value": [
             [
                 {"name": "类别", "value": val("金属阀门")},
                 {"name": "物资名称", "value": val(r["name"])},
                 {"name": "规格型号", "value": val(r["spec"])},
                 {"name": "计量单位", "value": val("个")},
                 {"name": "编码", "value": val("")},
                 {"name": "库存快照", "value": val("100")},
                 {"name": "数量", "value": val(str(r["qty"]))},
             ]
             for r in rows
         ]},
    ]
    return {
        "approval_code": approval_code,
        "status": status,
        "form": json.dumps(form, ensure_ascii=False),
        "start_user_id": "ingest_tester_001",
    }


# ── 表单解析（纯函数）──


def test_parse_form_both_shapes():
    plain = ai.parse_form(_instance("领料", [{"name": "A", "spec": "S1", "qty": 3}])["form"])
    assert plain.kind == "领料" and plain.rows == [{"name": "A", "spec": "S1", "quantity": 3.0}]
    dict_shape = ai.parse_form(
        _instance("退料", [{"name": "B", "spec": "S2", "qty": 1.5}], dict_shape=True)["form"]
    )
    assert dict_shape.kind == "退料"
    assert dict_shape.rows[0]["quantity"] == 1.5


def test_parse_form_rejects_unknown_kind():
    with pytest.raises(ai.IngestError):
        ai.parse_form(json.dumps([{"id": ai.KIND_WIDGET_ID, "value": "乱值"}]))


def test_extract_instance_code_shapes():
    assert ai._extract_instance_code({"instance": {"instance_code": "x1"}}) == "x1"
    assert ai._extract_instance_code({"instance_code": "x2"}) == "x2"
    assert ai._extract_instance_code({"data": {"instance_code": "x3"}}) == "x3"
    assert ai._extract_instance_code({}) == ""


def test_event_handlers_registered():
    from app.modules.warehouse.feishu import event_client

    for et in ("approval.instance.started", "approval.instance.approved",
               "approval.instance.rejected", "approval.instance.canceled"):
        assert et in event_client._handlers, et


# ── 摄取主流程 ──


async def test_ingest_requisition_pending_reserves(db_session, approval_code):
    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_instance("领料", [{"name": m.name, "spec": m.spec, "qty": 30}])
    )
    assert result["action"] == "ingested" and result["kind"] == "领料"
    req = await ai._find_requisition(db_session, code)
    assert req is not None and req.status == "pending"
    assert req.approval_channel == "feishu" and req.approval_instance_code == code
    # 预扣生效（PENDING 即锁库存）
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["reserved"] == Decimal("30") and rows[0]["available"] == Decimal("70")


async def test_ingest_requisition_shortage_rejected_and_notified(
    db_session, approval_code, monkeypatch
):
    notified: list[tuple[str, str]] = []

    async def fake_notify(open_id, matched, exc):
        notified.append((open_id, str(exc)))

    monkeypatch.setattr(ai, "_notify_rejected", fake_notify)

    m = await _mk_material(db_session)  # 无库存
    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_instance("领料", [{"name": m.name, "spec": m.spec, "qty": 5}])
    )
    assert result["action"] == "rejected_shortage"
    req = await ai._find_requisition(db_session, code)
    assert req.status == "rejected" and "缺料拒收" in (req.remark or "")
    assert len(notified) == 1 and "可用量不足" in notified[0][1]


async def test_ingest_return_creates_draft(db_session, approval_code):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_instance("退料", [{"name": m.name, "spec": m.spec, "qty": 2}])
    )
    assert result["action"] == "ingested" and result["kind"] == "退料"
    ret = await ai._find_return(db_session, code)
    assert ret is not None and ret.status == "draft"
    assert str(code) in (ret.remark or "")
    assert ret.items[0]["material_id"] == str(m.id)


async def test_ingest_skips_foreign_definition(db_session, approval_code):
    result = await ai.ingest_instance(
        db_session, "INST-X", instance=_instance("领料", [{"name": "a", "spec": "b", "qty": 1}],
                                                 approval_code="OTHER-DEF")
    )
    assert result["action"] == "skip"


async def test_ingest_idempotent(db_session, approval_code):
    m = await _mk_material(db_session, qty_stock=Decimal("10"))
    code = f"INST-{uuid4().hex[:8]}"
    inst = _instance("领料", [{"name": m.name, "spec": m.spec, "qty": 1}])
    first = await ai.ingest_instance(db_session, code, instance=inst)
    second = await ai.ingest_instance(db_session, code, instance=inst)
    assert first["action"] == "ingested" and second["action"] == "exists"
    reqs = (await db_session.execute(
        __import__("sqlalchemy").select(HardwareRequisition.id)
        .where(HardwareRequisition.approval_instance_code == code)
    )).scalars().all()
    assert len(reqs) == 1


# ── 状态同步 ──


async def test_sync_status_approved_and_rejected(db_session, approval_code):
    m1 = await _mk_material(db_session, name="球阀A", qty_stock=Decimal("100"))
    m2 = await _mk_material(db_session, name="球阀B", qty_stock=Decimal("100"))
    c1, c2 = f"INST-{uuid4().hex[:8]}", f"INST-{uuid4().hex[:8]}"
    await ai.ingest_instance(db_session, c1,
                             instance=_instance("领料", [{"name": m1.name, "spec": m1.spec, "qty": 10}]))
    await ai.ingest_instance(db_session, c2,
                             instance=_instance("领料", [{"name": m2.name, "spec": m2.spec, "qty": 10}]))

    r1 = await ai.sync_status(db_session, c1, status="APPROVED")
    assert r1["action"] == "synced" and r1["status"] == "approved"
    # 驳回释放预扣
    r2 = await ai.sync_status(db_session, c2, status="REJECTED")
    assert r2["status"] == "rejected"
    rows, _ = await hw.list_stock_rows(db_session, keyword=m2.name)
    assert rows[0]["available"] == Decimal("100")  # 释放恢复

    # 重复同步幂等（approved 不再迁移）
    again = await ai.sync_status(db_session, c1, status="APPROVED")
    assert again["status"] == "approved"


async def test_sync_status_ignores_unknown_instance(db_session, approval_code):
    result = await ai.sync_status(db_session, "INST-UNKNOWN", status="APPROVED")
    assert result["action"] == "ignore"


# ── 对账兜底 ──


async def test_reconcile_ingests_and_syncs(db_session, approval_code, monkeypatch):
    m = await _mk_material(db_session, name="对账阀", qty_stock=Decimal("100"))
    started_code = f"INST-{uuid4().hex[:8]}"
    approved_code = f"INST-{uuid4().hex[:8]}"
    # 既有：已摄取 pending 单（对账应把 APPROVED 状态补齐）
    await ai.ingest_instance(
        db_session, approved_code,
        instance=_instance("领料", [{"name": m.name, "spec": m.spec, "qty": 10}]),
    )
    repo: dict[str, dict] = {
        started_code: _instance("退料", [{"name": m.name, "spec": m.spec, "qty": 3}]),
        approved_code: _instance("领料", [{"name": m.name, "spec": m.spec, "qty": 10}],
                                 status="APPROVED"),
    }

    async def fake_list(approval_code_, s, e, *, app_id=None, app_secret=None):
        return list(repo.keys())

    async def fake_get(instance_code, *, app_id=None, app_secret=None):
        return repo[instance_code]

    import app.platform.integrations.feishu.approval as approval_mod

    monkeypatch.setattr(approval_mod, "list_instance_codes", fake_list)
    monkeypatch.setattr(approval_mod, "get_instance", fake_get)

    stats = await ai.reconcile_recent_instances(db_session)
    assert stats["codes"] == 2 and stats["ingested"] == 1 and stats["synced"] == 1
    assert await ai._find_return(db_session, started_code) is not None
    req = await ai._find_requisition(db_session, approved_code)
    assert req.status == "approved"


async def test_reconcile_disabled_without_code(db_session, monkeypatch, approval_code):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "HARDWARE_APPROVAL_CODE", "", raising=False)
    stats = await ai.reconcile_recent_instances(db_session)
    assert stats == {"enabled": 0, "codes": 0, "ingested": 0, "synced": 0}
