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
from app.modules.warehouse.hardware.approval_channel import cancel_approval as ai_cancel
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
    RequisitionCreate,
    RequisitionItemIn,
)

APPROVAL_CODE = "6FECD1F4-TEST-CODE"


@pytest.fixture
def approval_code(monkeypatch):
    """审批定义编码：审批配置已迁系统配置（2026-11-26），patch runtime_store
    单例（DB>env>默认链中 DB 层被替身固定，env/settings patch 不再生效）。"""
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    original = runtime_store.get_value

    def _get_value(key: str):
        if key == "hardware_approval_code":
            return APPROVAL_CODE
        return original(key)

    monkeypatch.setattr(runtime_store, "get_value", _get_value)
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
              approval_code=APPROVAL_CODE, linked=None) -> dict:
    """合成审批实例（2026-11-19 双表明细形态）。

    dict_shape=True 时控件值用 {"text": ..} 形态验证兼容。
    linked=行级关联领料实例 code（退料行内「关联审批」connect 列默认值，
    行 dict 可用 r["linked"] 覆盖实现多单混退）。另一侧明细表以空表在场。
    """

    def val(v):
        return {"text": v} if dict_shape else v

    is_return = kind == "退料"
    qty_name = "退料量" if is_return else "领料量"
    detail_name = "五金库退料明细" if is_return else "五金库领料明细"
    other_name = "五金库领料明细" if is_return else "五金库退料明细"

    def build_row(r):
        widgets = [
            {"name": "类别", "value": val("金属阀门")},
            {"name": "物资名称", "value": val(r["name"])},
            {"name": "规格型号", "value": val(r["spec"])},
            {"name": "计量单位", "value": val("个")},
            {"name": "可领量", "value": val("100")},
        ]
        if is_return:
            widgets.insert(0, {
                "name": "关联审批", "type": "connect",
                "value": val(r.get("linked", linked)),
            })
        widgets.append({"name": qty_name, "value": val(str(r["qty"]))})
        return widgets

    form = [
        {"id": ai.KIND_WIDGET_ID, "type": "radioV2", "name": "领/退料",
         "value": val("五金库领料" if kind == "领料" else "五金库退料")},
        {"id": ai.DETAIL_WIDGET_ID, "type": "fieldList", "name": detail_name,
         "value": [build_row(r) for r in rows]},
        {"id": "widget17950492860480001", "type": "fieldList", "name": other_name,
         "value": []},
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


def test_parse_form_scrap_kind():
    """报废分支（2026-11-25）：分流键识别为报废，不建单（系统代发起专用）。"""
    parsed = ai.parse_form(
        json.dumps([{"id": ai.KIND_WIDGET_ID, "value": "五金库报废"}])
    )
    assert parsed.kind == "报废"


async def test_ingest_scrap_kind_skipped(db_session, approval_code):
    """报废分支自建实例不摄取（v1 口径：报废必须从系统发起走留证流程）。"""
    form = json.dumps(
        [
            {"id": ai.KIND_WIDGET_ID, "type": "radioV2", "value": "五金库报废"},
            {"id": "widgetX", "type": "input", "value": "WJK-BF-261125-0001"},
        ],
        ensure_ascii=False,
    )
    result = await ai.ingest_instance(
        db_session,
        "INST_SCRAP_SELF_1",
        instance={"approval_code": approval_code, "status": "PENDING", "form": form},
    )
    assert result["action"] == "skip"


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


def _platform_instance(name: str, spec: str, qty: float, *, status="PENDING",
                       approval_code=APPROVAL_CODE) -> dict:
    """合成「五金库领料-平台」分支实例（系统代发起：六个顶层普通控件）。"""
    form = [
        {"id": ai.KIND_WIDGET_ID, "type": "radioV2", "name": "领/退料",
         "value": "五金库领料-平台"},
        {"id": "widget17950811346260001", "type": "input", "name": "类别", "value": "金属阀门"},
        {"id": ai.PLATFORM_NAME_WIDGET_ID, "type": "input", "name": "名称", "value": name},
        {"id": ai.PLATFORM_SPEC_WIDGET_ID, "type": "input", "name": "规格", "value": spec},
        {"id": "widget17950811760340001", "type": "input", "name": "单位", "value": "个"},
        {"id": "widget17950811860230001", "type": "number", "name": "可领量", "value": 100},
        {"id": ai.PLATFORM_QTY_WIDGET_ID, "type": "number", "name": "领料量", "value": qty},
    ]
    return {
        "approval_code": approval_code,
        "status": status,
        "form": json.dumps(form, ensure_ascii=False),
        "start_user_id": "platform_tester_001",
    }


# ── 平台分支（系统代发起）──


def test_parse_platform_form():
    parsed = ai.parse_form(_platform_instance("304不锈钢三通", "Φ133*4", 3)["form"])
    assert parsed.kind == ai.KIND_REQUISITION and parsed.platform is True
    assert parsed.rows == [{"name": "304不锈钢三通", "spec": "Φ133*4", "quantity": 3.0}]


async def test_ingest_platform_requisition_reserves(db_session, approval_code):
    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_platform_instance(m.name, m.spec, 4)
    )
    assert result["action"] == "ingested" and result["kind"] == "领料"
    req = await ai._find_requisition(db_session, code)
    assert req is not None and req.status == "pending"
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["reserved"] == Decimal("4") and rows[0]["available"] == Decimal("96")


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

    cancelled: list[tuple[str, str, str]] = []

    async def fake_cancel(approval_code, instance_code, user_id, *, app_id=None, app_secret=None):
        cancelled.append((approval_code, instance_code, user_id))
        return True

    import app.platform.integrations.feishu.approval as approval_mod

    monkeypatch.setattr(approval_mod, "cancel_instance", fake_cancel)

    m = await _mk_material(db_session)  # 无库存
    code = f"INST-{uuid4().hex[:8]}"
    inst = _instance("领料", [{"name": m.name, "spec": m.spec, "qty": 5}])
    inst["user_id"] = "cancel_tester_001"
    result = await ai.ingest_instance(db_session, code, instance=inst)
    assert result["action"] == "rejected_shortage"
    req = await ai._find_requisition(db_session, code)
    assert req.status == "rejected" and "缺料拒收" in (req.remark or "")
    assert len(notified) == 1 and "可用量不足" in notified[0][1]
    # 未受理退回：PENDING 实例以提交人身份撤回
    assert cancelled == [(APPROVAL_CODE, code, "cancel_tester_001")]


async def _issued_linked_req(db, m, qty, *, status="APPROVED"):
    """摄取一条领料实例到 issued（APPROVED 终态=审批关闭=已发料，自动实扣）。"""
    linked = f"INST-{uuid4().hex[:8]}"
    await ai.ingest_instance(
        db, linked, instance=_instance("领料", [{"name": m.name, "spec": m.spec, "qty": qty}],
                                       status=status)
    )
    req = await ai._find_requisition(db, linked)
    assert req.status == "issued"
    return linked


async def test_ingest_return_creates_draft(db_session, approval_code):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    linked = await _issued_linked_req(db_session, m, 10)
    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code,
        instance=_instance("退料", [{"name": m.name, "spec": m.spec, "qty": 2}], linked=linked),
    )
    assert result["action"] == "ingested" and result["kind"] == "退料"
    ret = await ai._find_return(db_session, code)
    assert ret is not None and ret.status == "draft"
    assert str(code) in (ret.remark or "")
    assert ret.items[0]["material_id"] == str(m.id)
    assert ret.requisition_instance_code == linked


async def test_ingest_return_missing_link_rejected(db_session, approval_code, monkeypatch):
    cancelled, notified = [], []

    async def fake_cancel(approval_code_, instance_code, user_id, *, app_id=None, app_secret=None):
        cancelled.append(instance_code)
        return True

    async def fake_notify(open_id, return_no, problem):
        notified.append(problem)

    import app.platform.integrations.feishu.approval as approval_mod

    monkeypatch.setattr(approval_mod, "cancel_instance", fake_cancel)
    monkeypatch.setattr(ai, "_notify_return_rejected", fake_notify)

    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_instance("退料", [{"name": m.name, "spec": m.spec, "qty": 2}])
    )
    assert result["action"] == "rejected_mismatch"
    ret = await ai._find_return(db_session, code)
    assert ret.status == "rejected" and "未选择关联" in (ret.rejected_reason or "")
    assert cancelled == [code] and "未选择关联" in notified[0]


async def test_ingest_return_over_quantity_rejected(db_session, approval_code, monkeypatch):
    """领 10 退 20 → 拒收+退回审批；重复在退也计入累计（退8再退5超余2）。"""
    cancelled: list[str] = []

    async def fake_cancel(approval_code_, instance_code, user_id, *, app_id=None, app_secret=None):
        cancelled.append(instance_code)
        return True

    import app.platform.integrations.feishu.approval as approval_mod

    monkeypatch.setattr(approval_mod, "cancel_instance", fake_cancel)
    monkeypatch.setattr(ai, "_notify_return_rejected", fake_notify_noop)

    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    linked = await _issued_linked_req(db_session, m, 10)
    # 直接超量
    code1 = f"INST-{uuid4().hex[:8]}"
    r1 = await ai.ingest_instance(
        db_session, code1,
        instance=_instance("退料", [{"name": m.name, "spec": m.spec, "qty": 20}], linked=linked),
    )
    assert r1["action"] == "rejected_mismatch"
    assert "超" in (await ai._find_return(db_session, code1)).rejected_reason
    # 先合法退 8（draft 计入累计），再退 5 → 超（余 2）
    await ai.ingest_instance(
        db_session, f"INST-{uuid4().hex[:8]}",
        instance=_instance("退料", [{"name": m.name, "spec": m.spec, "qty": 8}], linked=linked),
    )
    code3 = f"INST-{uuid4().hex[:8]}"
    r3 = await ai.ingest_instance(
        db_session, code3,
        instance=_instance("退料", [{"name": m.name, "spec": m.spec, "qty": 5}], linked=linked),
    )
    assert r3["action"] == "rejected_mismatch"
    assert cancelled == [code1, code3]


async def test_ingest_return_wrong_material_rejected(db_session, approval_code, monkeypatch):
    import app.platform.integrations.feishu.approval as approval_mod

    monkeypatch.setattr(approval_mod, "cancel_instance", fake_cancel_noop)
    monkeypatch.setattr(ai, "_notify_return_rejected", fake_notify_noop)

    m1 = await _mk_material(db_session, name="甲物资", qty_stock=Decimal("50"))
    m2 = await _mk_material(db_session, name="乙物资", qty_stock=Decimal("50"))
    linked = await _issued_linked_req(db_session, m1, 10)
    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code,
        instance=_instance("退料", [{"name": m2.name, "spec": m2.spec, "qty": 2}], linked=linked),
    )
    assert result["action"] == "rejected_mismatch"
    assert "不在关联领料单" in (await ai._find_return(db_session, code)).rejected_reason


async def fake_notify_noop(open_id, return_no, problem):
    return None


async def fake_cancel_noop(approval_code_, instance_code, user_id, *, app_id=None, app_secret=None):
    return True


async def test_return_approved_auto_accepts_and_restores(db_session, approval_code):
    """审批关闭(APPROVED终态)=仓管已办理收料 → 自动验收回加（对称领料自动发料）。"""
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    linked = await _issued_linked_req(db_session, m, 10)
    code = f"INST-{uuid4().hex[:8]}"
    await ai.ingest_instance(
        db_session, code,
        instance=_instance("退料", [{"name": m.name, "spec": m.spec, "qty": 3}], linked=linked),
    )
    r = await ai.sync_status(db_session, code, status="APPROVED")
    assert r["status"] == "accepted"
    ret = await ai._find_return(db_session, code)
    assert ret.leader_signed and ret.accepted_by == "飞书审批·仓管办理"
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["on_hand"] == Decimal("43")  # 50 − 领10 + 退3 回加
    # 幂等：重复 APPROVED 同步不重复回加
    again = await ai.sync_status(db_session, code, status="APPROVED")
    assert again["status"] == "accepted"
    rows2, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows2[0]["on_hand"] == Decimal("43")


async def test_return_canceled_invalidates_draft(db_session, approval_code):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    linked = await _issued_linked_req(db_session, m, 10)
    code = f"INST-{uuid4().hex[:8]}"
    await ai.ingest_instance(
        db_session, code,
        instance=_instance("退料", [{"name": m.name, "spec": m.spec, "qty": 2}], linked=linked),
    )
    r = await ai.sync_status(db_session, code, status="CANCELED")
    assert r["status"] == "rejected"
    ret = await ai._find_return(db_session, code)
    assert "撤销" in (ret.rejected_reason or "")
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["on_hand"] == Decimal("40")  # 未回加（50−10）


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
    assert r1["action"] == "synced" and r1["status"] == "issued"
    # 驳回释放预扣
    r2 = await ai.sync_status(db_session, c2, status="REJECTED")
    assert r2["status"] == "rejected"
    rows, _ = await hw.list_stock_rows(db_session, keyword=m2.name)
    assert rows[0]["available"] == Decimal("100")  # 释放恢复

    # 重复同步幂等（issued 不再迁移）
    again = await ai.sync_status(db_session, c1, status="APPROVED")
    assert again["status"] == "issued"


async def test_sync_status_canceled_releases_and_marks_approval(db_session, approval_code):
    """飞书撤回（CANCELED）→ 单据 cancelled + approval_status=cancelled + 预扣释放。"""
    m = await _mk_material(db_session, name="撤回球阀", qty_stock=Decimal("50"))
    code = f"INST-{uuid4().hex[:8]}"
    await ai.ingest_instance(
        db_session, code, instance=_instance("领料", [{"name": m.name, "spec": m.spec, "qty": 8}])
    )
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["reserved"] == Decimal("8")

    res = await ai.sync_status(db_session, code, status="CANCELED")
    assert res["action"] == "synced" and res["status"] == "cancelled"
    req = await ai._find_requisition(db_session, code)
    assert req.approval_status == "cancelled"
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["reserved"] == Decimal("0") and rows[0]["available"] == Decimal("50")


async def test_cancel_approval_withdraws_feishu_instance(db_session, approval_code):
    """系统内取消：撤回飞书待审实例（best-effort）+ approval_status 落 cancelled。"""
    from unittest.mock import AsyncMock, patch

    import app.platform.integrations.feishu.approval as approval_mod

    m = await _mk_material(db_session, name="系统撤单球阀", qty_stock=Decimal("30"))
    req = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="发酵", applicant="测试员",
            approver_user_id="u_sup",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=Decimal("3"))],
        ),
    )
    req.status = "pending"
    req.applicant_open_id = "xukangfu"  # 撤回以提交人身份
    req.approval_channel = "feishu"
    req.approval_instance_code = "INST-SYS-CANCEL"
    req.approval_status = "pending"
    await db_session.flush()

    fake = AsyncMock(return_value=True)
    with patch.object(approval_mod, "cancel_instance", fake):
        ok = await ai_cancel(db_session, req)
    assert ok is True
    assert fake.await_count == 1
    assert req.approval_status == "cancelled"


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
    assert req.status == "issued"


async def test_reconcile_disabled_without_code(db_session, monkeypatch, approval_code):
    # 覆写编码为空（runtime 层，审批配置已迁系统配置）
    from app.modules.warehouse.ops_config.runtime_store import runtime_store

    original = runtime_store.get_value
    monkeypatch.setattr(
        runtime_store,
        "get_value",
        lambda key: "" if key == "hardware_approval_code" else original(key),
    )
    stats = await ai.reconcile_recent_instances(db_session)
    assert stats == {"enabled": 0, "codes": 0, "ingested": 0, "synced": 0, "skipped": 0}
