"""紧急领用补办自动匹配挂回测试（ticket 02，防双扣核心）。

主接缝：db_session 直测 ingest_instance/sync_status（合成审批实例直传，
审批 API 不打真），通知打桩。先例=test_hardware_ingest.py。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.warehouse.hardware import approval_ingest as ai
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMovement,
    HardwareRequisition,
)
from app.modules.warehouse.hardware.schemas import (
    RequisitionCreate,
    RequisitionItemIn,
)
from app.platform.identity.models import User as IdentityUser
from tests.modules.warehouse.test_hardware_ingest import (
    _instance,
    _mk_material,
)

APPROVAL_CODE = "6FECD1F4-TEST-CODE"


@pytest.fixture
def approval_code(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "HARDWARE_APPROVAL_CODE", APPROVAL_CODE, raising=False)
    return APPROVAL_CODE


async def _mk_urgent_req(
    db,
    m,
    qty: Decimal,
    *,
    open_id: str | None = "ou_urg_001",
    user: IdentityUser | None = None,
    issued: bool = True,
) -> HardwareRequisition:
    """建一张紧急领料单并提交（预扣），缺省再发料（实扣+24h 截止）。"""
    req = await hw.create_requisition(
        db,
        RequisitionCreate(
            dept_name="发酵",
            applicant="张紧急",
            applicant_open_id=open_id,
            purpose="生产抢修",
            req_type="urgent",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=str(qty))],
        ),
        user=user,
    )
    await hw.submit_requisition(db, req.id)
    if issued:
        await hw.issue_requisition(db, req.id, issued_by="仓管测试", received_by="张紧急")
    return req


def _patch_instance(m, qty, *, status="APPROVED", open_id="ou_urg_001", start_user_id=None):
    inst = _instance("领料", [{"name": m.name, "spec": m.spec, "qty": float(qty)}], status=status)
    inst["open_id"] = open_id
    if start_user_id:
        inst["start_user_id"] = start_user_id
    return inst


async def _outbound_count(db, material_id) -> int:
    """按物料作用域计出库流水（真实库测试约定：禁全局计数，防存量污染）。"""
    return (
        await db.execute(select(func.count()).select_from(HardwareMovement).where(
            HardwareMovement.direction == "outbound",
            HardwareMovement.material_id == material_id,
        ))
    ).scalar_one()


# ── cycle 1：强键匹配挂回 ──


async def test_patch_matched_by_open_id_no_double_issue(db_session, approval_code):
    """同人（open_id 相等）+同物资同数量的补办实例挂回原紧急单，不建新单不二次扣库。"""
    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    urgent = await _mk_urgent_req(db_session, m, Decimal("30"))
    assert urgent.status == "issued" and urgent.urgent_patch_deadline is not None
    assert await _outbound_count(db_session, m.id) == 1

    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(db_session, code, instance=_patch_instance(m, 30))
    assert result["action"] == "patched" and result["doc_no"] == urgent.req_no

    linked = await ai._find_requisition(db_session, code)
    assert linked.id == urgent.id
    assert linked.approval_channel == "feishu" and linked.approval_instance_code == code
    assert linked.status == "issued" and linked.patched_at is not None
    # 防双扣：无新领料单（本部门本申请人仅 1 张）、无新出库流水、库存不变
    reqs = (await db_session.execute(select(HardwareRequisition).where(
        HardwareRequisition.dept_name == "发酵", HardwareRequisition.applicant == "张紧急",
    ))).scalars().all()
    assert len(reqs) == 1
    assert await _outbound_count(db_session, m.id) == 1
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name)
    assert rows[0]["on_hand"] == Decimal("70")


async def test_patch_matched_by_identity_user(db_session, approval_code):
    """identity 用户相等（open_id 不同作用域）也能匹配挂回。"""
    m = await _mk_material(db_session, qty_stock=Decimal("50"))
    person = IdentityUser(name="李抢修", feishu_user_id="urg_identity_001",
                          feishu_open_id="ou_identity_side")
    db_session.add(person)
    await db_session.flush()
    urgent = await _mk_urgent_req(db_session, m, Decimal("5"), open_id=None, user=person)
    assert urgent.applicant_user_id == person.id

    code = f"INST-{uuid4().hex[:8]}"
    inst = _patch_instance(m, 5, open_id="ou_warehouse_scope_other", start_user_id="urg_identity_001")
    result = await ai.ingest_instance(db_session, code, instance=inst)
    assert result["action"] == "patched"
    linked = await ai._find_requisition(db_session, code)
    assert linked.id == urgent.id and linked.patched_at is not None


async def test_patch_restores_overdue_unpatched(db_session, approval_code):
    """已逾期（overdue_unpatched）的紧急单补办通过 → 状态回 issued 并落 patched_at。"""
    m = await _mk_material(db_session, qty_stock=Decimal("20"))
    urgent = await _mk_urgent_req(db_session, m, Decimal("2"))
    urgent.status = "overdue_unpatched"
    await db_session.flush()

    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(db_session, code, instance=_patch_instance(m, 2))
    assert result["action"] == "patched"
    linked = await ai._find_requisition(db_session, code)
    assert linked.status == "issued" and linked.patched_at is not None


# ── cycle 2：事件路径（started 挂回 → 结果事件同步）与驳回 ──


async def test_patch_pending_link_then_approved_sync(db_session, approval_code, monkeypatch):
    """started 事件挂回（PENDING 只落实例码），approved 事件经 sync_status 落 patched_at。"""
    notified: list[str] = []

    async def fake_patched(req):
        notified.append(req.req_no)

    monkeypatch.setattr(ai, "_notify_patched", fake_patched)

    m = await _mk_material(db_session, qty_stock=Decimal("40"))
    urgent = await _mk_urgent_req(db_session, m, Decimal("4"))

    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_patch_instance(m, 4, status="PENDING")
    )
    assert result["action"] == "patched"
    linked = await ai._find_requisition(db_session, code)
    assert linked.patched_at is None and linked.approval_instance_code == code

    synced = await ai.sync_status(db_session, code, status="APPROVED")
    assert synced["action"] == "synced" and synced["status"] == "issued"
    await db_session.refresh(linked)
    assert linked.patched_at is not None
    assert notified == [urgent.req_no]
    # 不二次发料
    assert await _outbound_count(db_session, m.id) == 1


async def test_patch_rejected_keeps_state_and_notifies(db_session, approval_code, monkeypatch):
    """补办审批被驳回：库存与单据状态不动，仅私发申请人重新补办提醒。"""
    notified: list[tuple[str, str]] = []

    async def fake_rejected(req, status):
        notified.append((req.req_no, status))

    monkeypatch.setattr(ai, "_notify_patch_rejected", fake_rejected)

    m = await _mk_material(db_session, qty_stock=Decimal("40"))
    urgent = await _mk_urgent_req(db_session, m, Decimal("4"))

    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_patch_instance(m, 4, status="REJECTED")
    )
    assert result["action"] == "patched"
    linked = await ai._find_requisition(db_session, code)
    assert linked.status == "issued" and linked.patched_at is None
    assert linked.approval_status == "rejected"
    assert notified == [(urgent.req_no, "REJECTED")]
    assert await _outbound_count(db_session, m.id) == 1


# ── cycle 3：零命中路径（建新单+疑似补办通报）与多候选 ──


async def test_patch_qty_mismatch_creates_new_with_hint(db_session, approval_code):
    """数量不一致不强配：按现行路径建新单，但同人未补办紧急单物资有交集 → 备注追加疑似补办提示。"""
    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    urgent = await _mk_urgent_req(db_session, m, Decimal("30"))

    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(db_session, code, instance=_patch_instance(m, 20))
    assert result["action"] == "ingested"
    new_req = await ai._find_requisition(db_session, code)
    assert new_req.id != urgent.id and new_req.status == "issued"
    assert urgent.patched_at is None
    # 疑似补办通报（漏配双扣可见）：备注含原紧急单号
    assert "未补办紧急单" in (new_req.remark or "") and urgent.req_no in (new_req.remark or "")


async def test_patch_other_person_no_hint(db_session, approval_code):
    """他人（键不相等）提交的领料审批：正常建新单，无疑似补办提示。"""
    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    await _mk_urgent_req(db_session, m, Decimal("30"), open_id="ou_urg_owner")

    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_patch_instance(m, 30, open_id="ou_someone_else")
    )
    assert result["action"] == "ingested"
    new_req = await ai._find_requisition(db_session, code)
    assert "未补办紧急单" not in (new_req.remark or "")


async def test_patch_multiple_candidates_picks_earliest(db_session, approval_code):
    """同人同物资多张未补办紧急单 → 挂回最早发料的一张。"""
    from datetime import timedelta

    from app.modules.warehouse.hardware.service import _now as hw_now

    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    first = await _mk_urgent_req(db_session, m, Decimal("10"), open_id="ou_urg_multi")
    second = await _mk_urgent_req(db_session, m, Decimal("10"), open_id="ou_urg_multi")
    first.issued_at = hw_now() - timedelta(hours=3)
    second.issued_at = hw_now() - timedelta(hours=1)
    await db_session.flush()

    code = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code, instance=_patch_instance(m, 10, open_id="ou_urg_multi")
    )
    assert result["action"] == "patched" and result["doc_no"] == first.req_no
    linked = await ai._find_requisition(db_session, code)
    assert linked.id == first.id and first.patched_at is not None
    assert second.patched_at is None


# ── 跟进提醒与逾期通报（ticket 04）──


async def test_patch_reminders_t12_t2_idempotent(db_session, monkeypatch):
    """T-12h/T-2h 各催办一次（标签幂等），已补办不发。"""
    from datetime import timedelta

    from app.modules.warehouse.hardware import scheduled as sched
    from app.modules.warehouse.hardware import urgent_flow
    from app.modules.warehouse.hardware.service import _now as hw_now

    sent: list[str] = []

    async def fake_send(open_id, card):
        sent.append(str(card))

    monkeypatch.setattr(urgent_flow, "send_card_to_user", fake_send)

    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    req = await _mk_urgent_req(db_session, m, Decimal("5"))
    now = hw_now()
    # 剩 10h：t12 到点、t2 未到
    req.urgent_patch_deadline = now + timedelta(hours=10)
    await db_session.flush()
    s1 = await sched.run_urgent_patch_check(db_session, now=now)
    assert s1["reminded"] == 1 and len(sent) == 1
    await db_session.refresh(req)
    assert req.patch_reminders == ["t12"]
    # 同轮重跑不重发
    s2 = await sched.run_urgent_patch_check(db_session, now=now)
    assert s2["reminded"] == 0 and len(sent) == 1
    # 剩 1h：t2 到点
    req.urgent_patch_deadline = now + timedelta(hours=1)
    await db_session.flush()
    s3 = await sched.run_urgent_patch_check(db_session, now=now)
    assert s3["reminded"] == 1 and len(sent) == 2
    await db_session.refresh(req)
    assert req.patch_reminders == ["t12", "t2"]
    assert "仅剩" in sent[0] or "剩余" in sent[0] or "距补办截止" in sent[0]


async def test_patched_req_not_reminded(db_session, monkeypatch):
    from datetime import timedelta

    from app.modules.warehouse.hardware import scheduled as sched
    from app.modules.warehouse.hardware import urgent_flow
    from app.modules.warehouse.hardware.service import _now as hw_now

    sent: list = []

    async def fake_send(open_id, card):
        sent.append(card)

    monkeypatch.setattr(urgent_flow, "send_card_to_user", fake_send)

    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    req = await _mk_urgent_req(db_session, m, Decimal("5"))
    now = hw_now()
    req.urgent_patch_deadline = now + timedelta(hours=1)
    req.patched_at = now  # 已补办
    await db_session.flush()
    s = await sched.run_urgent_patch_check(db_session, now=now)
    assert s["reminded"] == 0 and sent == []


async def test_overdue_marks_and_daily_escalation(db_session, monkeypatch):
    """逾期标记一次 + 每日一次通报（同日不重发、跨日重发、补办后退出）。"""
    from datetime import timedelta

    from app.modules.warehouse.hardware import scheduled as sched
    from app.modules.warehouse.hardware.service import _now as hw_now
    from app.modules.warehouse.push_center import events as push_events

    fired: list[tuple[str, dict]] = []

    async def fake_fire(db, scene, payload):
        fired.append((scene, payload))

    monkeypatch.setattr(push_events, "fire_push_event", fake_fire)

    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    req = await _mk_urgent_req(db_session, m, Decimal("5"))
    now = hw_now()
    req.urgent_patch_deadline = now - timedelta(hours=30)  # 已逾期
    await db_session.flush()

    day1 = await sched.run_urgent_patch_check(db_session, now=now)
    assert day1["marked"] == 1 and day1["escalated"] == 1
    await db_session.refresh(req)
    assert req.status == "overdue_unpatched" and req.last_overdue_notified_at == now
    assert fired and fired[0][0] == "hardware_urgent_overdue"
    assert fired[0][1]["items"][0]["req_no"] == req.req_no

    # 同日再跑：不重复通报
    again = await sched.run_urgent_patch_check(db_session, now=now + timedelta(hours=1))
    assert again["marked"] == 0 and again["escalated"] == 0 and len(fired) == 1

    # 跨日再跑：再次通报
    day2 = await sched.run_urgent_patch_check(db_session, now=now + timedelta(days=1))
    assert day2["escalated"] == 1 and len(fired) == 2
    await db_session.refresh(req)
    assert req.last_overdue_notified_at == now + timedelta(days=1)

    # 补办完成后退出通报
    req.patched_at = now + timedelta(days=1, hours=1)
    await db_session.flush()
    day3 = await sched.run_urgent_patch_check(db_session, now=now + timedelta(days=2))
    assert day3["escalated"] == 0 and len(fired) == 2


# ── 审查修复锁定（Step 5）──


async def test_rejected_patch_rebinds_new_instance(db_session, approval_code):
    """补办被驳回后重提：新实例换绑回原单（不建新单不双扣）。"""
    m = await _mk_material(db_session, qty_stock=Decimal("100"))
    urgent = await _mk_urgent_req(db_session, m, Decimal("10"))

    code_a = f"INST-{uuid4().hex[:8]}"
    await ai.ingest_instance(
        db_session, code_a, instance=_patch_instance(m, 10, status="REJECTED")
    )
    linked = await ai._find_requisition(db_session, code_a)
    assert linked.id == urgent.id and linked.patched_at is None
    assert linked.approval_status == "rejected"

    # 重提的补办实例 APPROVED → 换绑并闭环（审查发现的当新单双扣洞）
    code_b = f"INST-{uuid4().hex[:8]}"
    result = await ai.ingest_instance(
        db_session, code_b, instance=_patch_instance(m, 10, status="APPROVED")
    )
    assert result["action"] == "patched" and result["doc_no"] == urgent.req_no
    await db_session.refresh(urgent)
    assert urgent.approval_instance_code == code_b
    assert urgent.patched_at is not None and urgent.approval_status == "approved"
    # 无新单、无二次扣库
    reqs = (await db_session.execute(select(HardwareRequisition).where(
        HardwareRequisition.dept_name == "发酵", HardwareRequisition.applicant == "张紧急",
    ))).scalars().all()
    assert len(reqs) == 1
    assert await _outbound_count(db_session, m.id) == 1
