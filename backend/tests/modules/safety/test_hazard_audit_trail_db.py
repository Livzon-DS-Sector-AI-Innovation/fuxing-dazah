"""督办留痕（方向 B）DB 测试 —— 提交动作落 Trigger / 催办发送落 Outbox 留痕行。

开关关=零旁挂零行为；开关开=仅增留痕数据（交互不变）。
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.modules.safety.service.hazard_direct import audit_trail
from app.platform.superagent.models import AgentOutboxMessage, AgentTrigger


@pytest_asyncio.fixture(autouse=True)
async def _purge_audit_rows():
    yield
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        rows = (
            await s.execute(
                select(AgentTrigger).where(
                    AgentTrigger.external_id.like("card_submit:%"))
            )
        ).scalars().all()
        for r in rows:
            await s.delete(r)
        src = (
            await s.execute(
                select(AgentOutboxMessage).where(
                    AgentOutboxMessage.conversation.like("hazard_dunning:%"))
            )
        ).scalars().all()
        for r in src:
            await s.delete(r)
        from app.platform.superagent.models import AgentSource

        audit_src = (
            await s.execute(
                select(AgentSource).where(
                    AgentSource.name == audit_trail.AUDIT_SOURCE_NAME)
            )
        ).scalars().all()
        for r in audit_src:
            await s.delete(r)
        await s.commit()


def _on(monkeypatch) -> None:
    monkeypatch.setenv("SAFETY_HAZARD_AUDIT_TRAIL_ENABLED", "true")


def _off(monkeypatch) -> None:
    monkeypatch.delenv("SAFETY_HAZARD_AUDIT_TRAIL_ENABLED", raising=False)


# ═══════════════════════════════════════════════════════════════
# 提交动作 → Trigger
# ═══════════════════════════════════════════════════════════════


async def test_submission_recorded_as_trigger(db_session, monkeypatch) -> None:
    """开：提交动作落 Trigger（同隐患同线程、disposition 记 applied）。"""
    _on(monkeypatch)

    created = await audit_trail.record_card_submission(
        db_session, record_id="rec_b1", text="阀门已订购",
        operator="ou_zhang", message_key="om_card1:progress_form_rec_b1",
        applied=True, hazard_no="HZ-B1",
    )

    assert created is True
    trigger = (
        await db_session.execute(
            select(AgentTrigger).where(
                AgentTrigger.external_id == "card_submit:om_card1:progress_form_rec_b1")
        )
    ).scalar_one()
    assert trigger.thread_key == "bitable:hazard:rec_b1"
    assert trigger.human is True
    assert trigger.actor == {"id": "ou_zhang", "type": "feishu_user"}
    assert trigger.payload["text"] == "阀门已订购"
    steps = [s["step"] for s in trigger.disposition]
    assert steps == ["stored", "applied"]


async def test_submission_idempotent(db_session, monkeypatch) -> None:
    """同 message_key 重记 → duplicate 不加行（飞书重推/重试幂等）。"""
    _on(monkeypatch)
    for _ in range(2):
        await audit_trail.record_card_submission(
            db_session, record_id="rec_b1", text="文本",
            operator="ou_z", message_key="om_x:act", applied=True,
        )

    rows = (
        await db_session.execute(
            select(AgentTrigger).where(
                AgentTrigger.external_id == "card_submit:om_x:act")
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_submission_switch_off_zero_rows(db_session, monkeypatch) -> None:
    """关：零 Trigger 行零 Source 行（零旁挂）。"""
    _off(monkeypatch)

    created = await audit_trail.record_card_submission(
        db_session, record_id="rec_b1", text="文本",
        operator="ou_z", message_key="om_x:act", applied=True,
    )

    assert created is False
    rows = list((
        await db_session.execute(
            select(AgentTrigger.id).where(
                AgentTrigger.external_id.like("card_submit:%"))
        )
    ).scalars().all())
    assert rows == []


async def test_failed_submission_marked(db_session, monkeypatch) -> None:
    """写台账失败的动作也留痕（disposition=failed，不静默）。"""
    _on(monkeypatch)

    await audit_trail.record_card_submission(
        db_session, record_id="rec_b2", text="内容",
        operator="ou_z", message_key="om_y:act", applied=False,
        note="bitable_write_failed",
    )

    trigger = (
        await db_session.execute(
            select(AgentTrigger).where(
                AgentTrigger.external_id == "card_submit:om_y:act")
        )
    ).scalar_one()
    steps = [s["step"] for s in trigger.disposition]
    assert steps == ["stored", "failed"]
    assert trigger.disposition[1]["reason"] == "bitable_write_failed"


# ═══════════════════════════════════════════════════════════════
# 催办发送 → Outbox 留痕行
# ═══════════════════════════════════════════════════════════════


async def test_dunning_sent_recorded(db_session, monkeypatch) -> None:
    """开：发送成功落 sent 终态留痕行（channel 行内权威，永不 pending）。"""
    _on(monkeypatch)

    await audit_trail.record_dunning_card_sent(
        db_session, record_id="rec_d1", hazard_no="HZ-D1",
        receive_id="111003032", id_type="user_id",
        role="责任人", name="张三",
    )

    row = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("hazard_dunning:rec_d1:%"))
        )
    ).scalar_one()
    assert row.status == "sent" and row.sent_at is not None
    assert row.channel == {
        "type": "feishu_dm", "id_type": "user_id", "receive_id": "111003032",
    }
    assert row.body["hazard_no"] == "HZ-D1" and row.body["role"] == "责任人"


async def test_dunning_sent_switch_off(db_session, monkeypatch) -> None:
    """关：零留痕行。"""
    _off(monkeypatch)

    await audit_trail.record_dunning_card_sent(
        db_session, record_id="rec_d1", hazard_no="HZ-D1",
        receive_id="x", id_type="open_id", role="责任人", name="张三",
    )

    rows = list((
        await db_session.execute(
            select(AgentOutboxMessage.id).where(
                AgentOutboxMessage.conversation.like("hazard_dunning:%"))
        )
    ).scalars().all())
    assert rows == []


# ═══════════════════════════════════════════════════════════════
# 直读回调集成：提交 → 台账署名追加 + 留痕 Trigger
# ═══════════════════════════════════════════════════════════════


async def test_direct_submit_full_audit(monkeypatch) -> None:
    """开：表单提交一次产生——台账署名行 + Trigger 留痕（applied）。"""
    _on(monkeypatch)
    from tests.conftest import _test_session_factory

    monkeypatch.setattr(
        "app.core.database.async_session_factory", _test_session_factory,
    )

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def get_record(self, rid: str) -> dict:
            return {"整改状态": "未关闭", "目前进展": "旧",
                    "隐患编号": "HZ-C1"}

        async def update_record(self, rid: str, fields: dict) -> bool:
            self.calls.append(dict(fields))
            return True

    fake = FakeClient()
    monkeypatch.setattr(
        "app.modules.safety.feishu.progress_card.SafetyBitableClient", lambda: fake,
    )
    from app.modules.safety.feishu import bitable_id_mapper

    monkeypatch.setattr(
        bitable_id_mapper, "get_name_by_bitable_open_id",
        lambda oid: "张三",
    )

    async def _noop(*a, **kw) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.safety.feishu.bitable_handler._set_sync_ignore", _noop,
    )

    from app.modules.safety.feishu import progress_card

    await progress_card.handle_progress_submit_direct(
        "rec_c1",
        {
            "action": {"form_value": {"progress": "已完成更换"}, "name": "progress_submit_rec_c1"},
            "operator": {"open_id": "ou_zhang", "user_id": ""},
            "context": {"open_message_id": "om_card_c1"},
        },
    )

    assert len(fake.calls) == 1
    assert "·张三】已完成更换" in fake.calls[0]["目前进展"]

    async with _test_session_factory() as s:
        trigger = (
            await s.execute(
                select(AgentTrigger).where(
                    AgentTrigger.external_id
                    == "card_submit:om_card_c1:progress_submit_rec_c1")
            )
        ).scalar_one()
        assert trigger.thread_key == "bitable:hazard:rec_c1"
        assert [x["step"] for x in trigger.disposition] == ["stored", "applied"]
        assert trigger.payload["hazard_no"] == "HZ-C1"


# ═══════════════════════════════════════════════════════════════
# 方向 C：聚合查询（list / timeline）
# ═══════════════════════════════════════════════════════════════


async def _seed_query_data(db_session, monkeypatch) -> None:
    _on(monkeypatch)
    await audit_trail.record_card_submission(
        db_session, record_id="rec_q1", text="已完成更换",
        operator="ou_zhang", message_key="om_q1:a", applied=True, hazard_no="HZ-Q1",
    )
    await audit_trail.record_card_submission(
        db_session, record_id="rec_q1", text="补充照片",
        operator="ou_li", message_key="om_q1:b", applied=False, hazard_no="HZ-Q1",
    )
    await audit_trail.record_dunning_card_sent(
        db_session, record_id="rec_q1", hazard_no="HZ-Q1",
        receive_id="ou_a", id_type="open_id", role="责任人", name="张三",
    )
    await audit_trail.record_dunning_card_sent(
        db_session, record_id="rec_q2", hazard_no="HZ-Q2",
        receive_id="ou_b", id_type="open_id", role="分管安全员", name="李四",
    )


async def test_query_list_aggregates(db_session, monkeypatch) -> None:
    """聚合：同隐患提交/催办计数、失败计数、最近活动排序。"""
    from app.modules.safety.service.hazard_direct.audit_query import list_hazard_audit

    await _seed_query_data(db_session, monkeypatch)

    items = await list_hazard_audit(db_session, days=30)

    by_rid = {i["record_id"]: i for i in items}
    q1 = by_rid["rec_q1"]
    assert q1["hazard_no"] == "HZ-Q1"
    assert q1["dunning_count"] == 1 and q1["dunning_recipient_count"] == 1
    assert q1["submission_count"] == 2 and q1["submission_failed"] == 1
    assert q1["last_submission"]["operator"] == "ou_li"  # 最近一次提交
    q2 = by_rid["rec_q2"]
    assert q2["dunning_count"] == 1 and q2["submission_count"] == 0
    # keyword 过滤
    only_q2 = await list_hazard_audit(db_session, days=30, keyword="HZ-Q2")
    assert [i["record_id"] for i in only_q2] == ["rec_q2"]


async def test_query_timeline_merges(db_session, monkeypatch) -> None:
    """时间线：催办+提交合并、倒序、提交带 outcome。"""
    from app.modules.safety.service.hazard_direct.audit_query import (
        hazard_audit_timeline,
    )

    await _seed_query_data(db_session, monkeypatch)

    events = await hazard_audit_timeline(db_session, "rec_q1", days=30)

    kinds = [e["kind"] for e in events]
    assert kinds.count("submission") == 2 and kinds.count("dunning") == 1
    assert events == sorted(events, key=lambda e: e["at"], reverse=True)
    failed = [e for e in events if e["kind"] == "submission" and e["outcome"] == "failed"]
    assert failed and failed[0]["text"] == "补充照片"
