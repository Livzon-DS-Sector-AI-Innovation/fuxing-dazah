"""紧急领用对话链路测试（ticket 01：发起→临时单据→仓管一键发料）。

接缝：service 直测 + urgent_flow/gateway 处理器直调，通知全部打桩。
先例=test_hardware_ingest.py / test_confirm_integration.py。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware import urgent_flow
from app.modules.warehouse.hardware.models import HardwareRequisition
from app.modules.warehouse.hardware.schemas import (
    RequisitionCreate,
    RequisitionItemIn,
)
from tests.modules.warehouse.test_hardware_ingest import _mk_material

KEEPER = "ou_keeper_001"


@pytest.fixture
def notify_targets(monkeypatch):
    monkeypatch.setattr(
        get_settings(), "HARDWARE_URGENT_NOTIFY_TARGETS",
        f"{KEEPER},oc_urgent_grp", raising=False,
    )
    return [KEEPER, "oc_urgent_grp"]


@pytest.fixture
def sent_cards(monkeypatch):
    """通知桩：私发卡与目标卡全量采集。"""
    box: dict[str, list] = {"user": [], "target": []}

    async def fake_user(open_id, card):
        box["user"].append((open_id, card))

    async def fake_target(target, card):
        box["target"].append((target, card))

    monkeypatch.setattr(urgent_flow, "send_card_to_user", fake_user)
    monkeypatch.setattr(urgent_flow, "send_card_to_target", fake_target)
    return box


async def _mk_urgent_pending(db, m, qty=Decimal("5")) -> HardwareRequisition:
    req = await hw.create_requisition(
        db,
        RequisitionCreate(
            dept_name="动力机修",
            applicant="王抢修",
            applicant_open_id="ou_app_001",
            purpose="泵体抢修",
            req_type="urgent",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=str(qty))],
        ),
    )
    await hw.submit_requisition(db, req.id)
    return req


# ── cycle A：仓管卡动作（发料出库/作废/鉴权）──


async def test_keeper_issue_via_card(db_session, notify_targets, sent_cards):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    req = await _mk_urgent_pending(db_session, m)

    ok, message = await urgent_flow.handle_keeper_action(
        db_session, req.id, "issue", operator_open_id=KEEPER
    )
    assert ok, message
    await db_session.refresh(req)
    assert req.status == "issued" and req.urgent_patch_deadline is not None
    # 出库流水 + 申请人收到出库确认卡（含单号与补办指引）
    mv = (await db_session.execute(
        select(hw.HardwareMovement).where(
            hw.HardwareMovement.direction == "outbound",
            hw.HardwareMovement.material_id == m.id,
            hw.HardwareMovement.business_type == "urgent_issue",
        )
    )).scalars().all()
    assert len(mv) == 1
    assert [t for t, _ in sent_cards["user"]] == ["ou_app_001"]
    body = str(sent_cards["user"][0][1])
    assert req.req_no in body and "24" in body


async def test_keeper_action_unauthorized_denied(db_session, notify_targets, sent_cards):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    req = await _mk_urgent_pending(db_session, m)

    ok, message = await urgent_flow.handle_keeper_action(
        db_session, req.id, "issue", operator_open_id="ou_stranger_999"
    )
    assert not ok and "仓管" in message
    await db_session.refresh(req)
    assert req.status == "pending"  # 状态不动（fail-closed）
    assert sent_cards["user"] == []


async def test_keeper_cancel_releases(db_session, notify_targets, sent_cards):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    req = await _mk_urgent_pending(db_session, m)
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["available"] == Decimal("45")

    ok, message = await urgent_flow.handle_keeper_action(
        db_session, req.id, "cancel", operator_open_id=KEEPER
    )
    assert ok, message
    await db_session.refresh(req)
    assert req.status == "cancelled"
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["available"] == Decimal("50")  # 预扣释放
    assert sent_cards["user"] and "作废" in str(sent_cards["user"][0][1])


async def test_keeper_issue_idempotent_guard(db_session, notify_targets, sent_cards):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    req = await _mk_urgent_pending(db_session, m)
    await hw.issue_requisition(db_session, req.id, issued_by="仓管", received_by="王抢修")

    ok, message = await urgent_flow.handle_keeper_action(
        db_session, req.id, "issue", operator_open_id=KEEPER
    )
    assert not ok and "不可发料" in message


# ── cycle B：确认门提交回调（建单+预扣+双卡）──


async def test_submit_hardware_urgent_sends_cards(db_session, notify_targets, sent_cards):
    from app.modules.warehouse.hardware import agent_submit
    from app.modules.warehouse.agent import repository as agent_repository
    from datetime import UTC, datetime, timedelta

    m = await _mk_material(db_session, qty_stock=Decimal("80"))
    draft = await agent_repository.create_agent_draft(
        db_session,
        draft_no=f"CF-URG-{uuid4().hex[:6].upper()}",
        scene="hardware_urgent",
        status="confirmed",
        created_by_open_id="ou_app_001",
        aligned={
            "items": [{"name": m.name, "spec": m.spec, "qty": 6}],
            "purpose": "夜间抢修",
            "dept": "动力机修",
            "applicant": "王抢修",
            "applicant_open_id": "ou_app_001",
        },
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    note = await agent_submit.submit_hardware_urgent(db_session, draft)
    assert note and "WJK-LY" in note

    reqs = (await db_session.execute(select(HardwareRequisition).where(
        HardwareRequisition.dept_name == "动力机修",
        HardwareRequisition.applicant == "王抢修",
    ))).scalars().all()
    assert len(reqs) == 1
    req = reqs[0]
    assert req.req_type == "urgent" and req.status == "pending"  # 预扣生效待发料
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["available"] == Decimal("74")
    # 双卡：申请人临时单据卡（私发）+ 仓管通知卡（两个目标各一张）
    assert [t for t, _ in sent_cards["user"]] == ["ou_app_001"]
    assert sorted(t for t, _ in sent_cards["target"]) == sorted(notify_targets)
    keeper_card = str(sent_cards["target"][0][1])
    assert req.req_no in keeper_card and "发料" in keeper_card
    temp_card = str(sent_cards["user"][0][1])
    assert "补办" in temp_card  # 24h 补办指引
    await db_session.refresh(draft)
    assert draft.status == "submitted"


async def test_submit_hardware_urgent_shortage_fails(db_session, notify_targets, sent_cards):
    from app.modules.warehouse.hardware import agent_submit
    from app.modules.warehouse.agent.pipeline.draft_flow import DraftFlowError
    from app.modules.warehouse.agent import repository as agent_repository
    from datetime import UTC, datetime, timedelta

    m = await _mk_material(db_session, qty_stock=Decimal("1"))  # 库存不足
    draft = await agent_repository.create_agent_draft(
        db_session,
        draft_no=f"CF-URG-{uuid4().hex[:6].upper()}",
        scene="hardware_urgent",
        status="confirmed",
        created_by_open_id="ou_app_001",
        aligned={
            "items": [{"name": m.name, "spec": m.spec, "qty": 50}],
            "purpose": "抢修",
            "dept": "动力机修",
            "applicant": "王抢修",
            "applicant_open_id": "ou_app_001",
        },
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    with pytest.raises(DraftFlowError):
        await agent_submit.submit_hardware_urgent(db_session, draft)


# ── cycle C：对话工具 + 场景预判 + 网关回调路由 + 确认卡渲染 ──


async def test_tool_collect_validate_and_draft(db_session, monkeypatch, notify_targets):
    from contextlib import asynccontextmanager

    from app.modules.warehouse.agent.pipeline import draft_flow
    from app.modules.warehouse.agent.tools import hardware_urgent as tool_mod
    from app.modules.warehouse.models import WarehouseAgentDraft
    from app.platform.identity.models import User as IdentityUser

    person = IdentityUser(name="王抢修", feishu_user_id="urg_chat_001",
                          feishu_open_id="ou_app_001", department="动力机修")
    db_session.add(person)
    await db_session.flush()

    @asynccontextmanager
    async def fake_db():
        yield db_session

    monkeypatch.setattr(tool_mod, "_db_session", fake_db)
    confirmed: list = []

    async def fake_send(db, draft, **kw):
        confirmed.append(draft.id)

    monkeypatch.setattr(draft_flow, "send_confirm_card", fake_send)

    # 缺用途 → missing 追问
    r = await tool_mod.create_urgent_requisition(
        {"items": [{"name": "x", "spec": "s", "qty": 1}]}, _ctx={"open_id": "ou_app_001"}
    )
    assert r["status"] == "incomplete" and any("用途" in m for m in r["missing"])

    # 身份未识别（陌生 open_id）→ missing 追问姓名/部门
    r = await tool_mod.create_urgent_requisition(
        {"items": [{"name": "x", "spec": "s", "qty": 1}], "purpose": "抢修"},
        _ctx={"open_id": "ou_stranger_000"},
    )
    assert r["status"] == "incomplete" and any("姓名" in m for m in r["missing"])

    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    # 物资不匹配（规格错）→ error
    r = await tool_mod.create_urgent_requisition(
        {"items": [{"name": m.name, "spec": "WRONG-SPEC", "qty": 1}], "purpose": "抢修"},
        _ctx={"open_id": "ou_app_001"},
    )
    assert "error" in r and "不匹配" in r["error"]
    # 可领量不足 → error 如实转告
    r = await tool_mod.create_urgent_requisition(
        {"items": [{"name": m.name, "spec": m.spec, "qty": 500}], "purpose": "抢修"},
        _ctx={"open_id": "ou_app_001"},
    )
    assert r.get("error_code") == "insufficient_stock"

    # happy：建草稿 + 确认卡
    r = await tool_mod.create_urgent_requisition(
        {"items": [{"name": m.name, "spec": m.spec, "qty": 3}], "purpose": "泵体抢修"},
        _ctx={"open_id": "ou_app_001"},
    )
    assert "draft_no" in r and confirmed, r
    draft = (await db_session.execute(
        select(WarehouseAgentDraft).where(
            WarehouseAgentDraft.draft_no == r["draft_no"])
    )).scalars().one()
    assert draft.scene == "hardware_urgent"
    assert draft.aligned["applicant"] == "王抢修" and draft.aligned["dept"] == "动力机修"
    assert draft.aligned["items"][0]["name"] == m.name


def test_scene_hint_urgent_priority():
    from app.modules.warehouse.agent import gateway

    hint = gateway._scene_hint("紧急领用DN25球阀2个")
    assert hint and "create_urgent_requisition" in hint
    hint2 = gateway._scene_hint("抢修，领料轴承6204两个")
    assert hint2 and "create_urgent_requisition" in hint2
    # 普通领料仍走路由 picking
    hint3 = gateway._scene_hint("精制一部领料硫酸500Kg")
    assert hint3 and "create_picking_draft" in hint3


async def test_gateway_routes_urgent_keeper_card(db_session, monkeypatch, notify_targets):
    from contextlib import asynccontextmanager

    from app.modules.warehouse.agent import gateway
    from app.modules.warehouse.hardware import urgent_flow as uf

    calls: list = []

    async def fake_action(db, rid, action, *, operator_open_id):
        calls.append((str(rid), action, operator_open_id))
        return True, "已发料出库"

    monkeypatch.setattr(uf, "handle_keeper_action", fake_action)

    @asynccontextmanager
    async def fake_db():
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", fake_db)

    acks: list = []

    async def fake_ack(message_id, ok, message):
        acks.append((ok, message))
        return {"code": 200}

    monkeypatch.setattr(gateway, "_ack_with_patch", fake_ack)

    event = {
        "operator": {"open_id": KEEPER},
        "action": {"value": {"scene": uf.URGENT_ISSUE_SCENE, "requisition_id": "req-abc"}},
    }
    resp = await gateway.handle_card_action_trigger(event)
    assert resp == {"code": 200}
    assert calls == [("req-abc", "issue", KEEPER)]
    assert acks and acks[0][0] is True and "已发料" in acks[0][1]


def test_render_urgent_confirm_card():
    from app.modules.warehouse.agent import cards

    class _Draft:
        scene = "hardware_urgent"
        draft_no = "CF-URG-TEST"
        id = "draft-id-1"
        recognized: dict = {}
        aligned = {
            "items": [{"name": "球阀", "spec": "DN25", "qty": 2, "unit": "个"}],
            "purpose": "泵体抢修",
            "dept": "动力机修",
            "applicant": "王抢修",
        }

    card = cards.render_receipt_confirm_card(_Draft())
    body = str(card)
    assert "紧急领用" in body and "24" in body and "王抢修" in body
    assert "确认发起" in body


# ── ticket 03：手动兜底 + 前端 urgent 提交链（API）──


async def test_patch_manual_service_guards(db_session, notify_targets, sent_cards):
    m = await _mk_material(db_session, qty_stock=Decimal("50"))

    # 普通单不可手动补办
    normal = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="发酵", applicant="张三", req_type="normal",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty="1")],
        ),
    )
    await hw.submit_requisition(db_session, normal.id)
    await hw.approve_requisition(db_session, normal.id, approver="主管")
    await hw.issue_requisition(db_session, normal.id, issued_by="仓管", received_by="张三")
    with pytest.raises(hw.HardwareError):
        await hw.patch_requisition_manually(db_session, normal.id, operator="仓管甲")

    # urgent 已发料 → 手动闭环；重复点拒绝；overdue 恢复 issued
    req = await _mk_urgent_pending(db_session, m)
    await hw.issue_requisition(db_session, req.id, issued_by="仓管", received_by="王抢修")
    patched = await hw.patch_requisition_manually(db_session, req.id, operator="仓管甲")
    assert patched.patched_at is not None and patched.status == "issued"
    assert patched.approval_channel == "manual" and "补办" in (patched.approval_note or "")
    with pytest.raises(hw.HardwareError):
        await hw.patch_requisition_manually(db_session, req.id, operator="仓管甲")

    req2 = await _mk_urgent_pending(db_session, m)
    await hw.issue_requisition(db_session, req2.id, issued_by="仓管", received_by="王抢修")
    req2.status = "overdue_unpatched"
    await db_session.flush()
    patched2 = await hw.patch_requisition_manually(db_session, req2.id, operator="仓管甲")
    assert patched2.status == "issued" and patched2.patched_at is not None


async def test_api_urgent_submit_skips_channel_and_patch_manual(
    db_session, api_context, notify_targets, sent_cards, monkeypatch
):
    """前端链：urgent 提交不建审批实例只发双卡；patch-manual 端点鉴权+闭环。"""
    from unittest.mock import patch as mock_patch

    from tests.modules.warehouse.conftest import WAREHOUSE_PERMS

    client, db = api_context
    hw_perms = {
        "warehouse:hardware:requisition:create",
        "warehouse:hardware:requisition:issue",
        "warehouse:hardware:requisition:read",
    }
    m = await _mk_material(db, qty_stock=Decimal("100"))

    created = None

    async def _granted(uid, d):  # noqa: ANN001
        return WAREHOUSE_PERMS | hw_perms

    with mock_patch(
        "app.platform.permission.deps.get_user_permissions",
        new=_granted,
    ):
        resp = await client.post(
            "/api/v1/warehouse/hardware/requisitions",
            json={
                "dept_name": "动力机修",
                "applicant": "王抢修",
                "applicant_open_id": "ou_app_001",
                "purpose": "夜间抢修",
                "req_type": "urgent",
                "items": [{"material_id": str(m.id), "need_qty": "4"}],
            },
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()["data"]

        resp = await client.post(
            f"/api/v1/warehouse/hardware/requisitions/{created['id']}/submit"
        )
        assert resp.status_code == 200, resp.text
        submitted = resp.json()["data"]
        assert submitted["status"] == "pending"
        # urgent 不走审批通道：无实例码；双卡已发
        assert submitted["approval_instance_code"] is None
        assert sent_cards["user"] and len(sent_cards["target"]) == 2

        # 发料后手动补办闭环
        item_id = created["items"][0]["id"]
        resp = await client.post(
            f"/api/v1/warehouse/hardware/requisitions/{created['id']}/issue",
            json={
                "issued_by": "仓管甲",
                "received_by": "王抢修",
                "items": [{"item_id": item_id, "issued_qty": 4}],
            },
        )
        assert resp.status_code == 200, resp.text
        resp = await client.post(
            f"/api/v1/warehouse/hardware/requisitions/{created['id']}/patch-manual"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["patched_at"] is not None and data["status"] == "issued"

    # 无硬件权限 → 403（fail-closed）
    async def _denied(uid, d):  # noqa: ANN001
        return WAREHOUSE_PERMS

    with mock_patch(
        "app.platform.permission.deps.get_user_permissions",
        new=_denied,
    ):
        resp = await client.post(
            f"/api/v1/warehouse/hardware/requisitions/{created['id']}/patch-manual"
        )
        assert resp.status_code == 403


# ── 审查修复锁定（Step 5）──


async def test_keeper_action_authorized_by_issue_permission(
    db_session, notify_targets, sent_cards, monkeypatch
):
    """操作人不在通知目标但持发料权限 → 放行（spec「或持发料权限」旁路）。"""
    from unittest.mock import patch as mock_patch

    from app.platform.identity.models import User as IdentityUser
    from app.modules.warehouse.hardware import urgent_flow as uf

    person = IdentityUser(name="权限仓管", feishu_user_id="perm_keeper_001",
                          feishu_open_id="ou_perm_keeper")
    db_session.add(person)
    await db_session.flush()

    async def _perms(uid, d):  # noqa: ANN001
        return {"warehouse:hardware:requisition:issue"}

    with mock_patch(
        "app.platform.permission.deps.get_user_permissions", new=_perms
    ):
        m = await _mk_material(db_session, qty_stock=Decimal("50"))
        req = await _mk_urgent_pending(db_session, m)
        ok, message = await uf.handle_keeper_action(
            db_session, req.id, "issue", operator_open_id="ou_perm_keeper"
        )
        assert ok, message
        await db_session.refresh(req)
        assert req.status == "issued"

    # 陌生 open_id（不在目标、无 identity）→ 仍拒（fail-closed）
    m2 = await _mk_material(db_session, qty_stock=Decimal("50"))
    req2 = await _mk_urgent_pending(db_session, m2)
    ok2, message2 = await uf.handle_keeper_action(
        db_session, req2.id, "issue", operator_open_id="ou_ghost_000"
    )
    assert not ok2 and "仓管" in message2
    await db_session.refresh(req2)
    assert req2.status == "pending"


async def test_create_requisition_autofills_open_id(db_session, notify_targets):
    """前端登录态发起（payload 不带 open_id）→ 自动取 identity 三绑 open_id。"""
    from app.platform.identity.models import User as IdentityUser

    person = IdentityUser(name="赵登录", feishu_user_id="web_user_001",
                          feishu_open_id="ou_web_user")
    db_session.add(person)
    await db_session.flush()

    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    req = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="精制机修", applicant="赵登录", req_type="urgent",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty="2")],
        ),
        user=person,
    )
    assert req.applicant_open_id == "ou_web_user"
    assert req.applicant_user_id == person.id
