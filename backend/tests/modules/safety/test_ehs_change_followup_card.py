"""EHS 变更周度督办 — 周五卡回调（提交进展/进展不变）单测。

零真机：Bitable 回写、卡片 PATCH、姓名解析全钉桩；DB 用 sealed 会话
（service 同款外层事务 + savepoint，回调内 commit 只释放 savepoint）。
表临时建拆与 service 测试同配方（迁移已应用则不动）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import inspect, pool, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.modules.safety.models.ehs_change_followup import (
    EhsChangeFollowupDispatch,
    EhsChangeFollowupItem,
    EhsChangeFollowupRound,
)
from app.modules.safety.feishu import ehs_change_followup_card as ecf_card
from app.modules.safety.service.ehs_change_followup import config as ecf_config

_TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture(autouse=True)
async def _ensure_tables() -> AsyncIterator[None]:
    from app.shared.base_model import Base

    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=pool.NullPool)
    created = False
    try:
        async with engine.begin() as conn:
            exists = await conn.run_sync(
                lambda sc: inspect(sc).has_table(
                    "ehs_change_followup_rounds", schema="safety"
                )
            )
            if not exists:
                import sqlalchemy as sa

                await conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS safety"))
                await conn.run_sync(
                    Base.metadata.create_all,
                    tables=[
                        EhsChangeFollowupRound.__table__,
                        EhsChangeFollowupDispatch.__table__,
                        EhsChangeFollowupItem.__table__,
                    ],
                )
                created = True
        yield
        if created:
            async with engine.begin() as conn:
                await conn.run_sync(
                    Base.metadata.drop_all,
                    tables=[
                        EhsChangeFollowupItem.__table__,
                        EhsChangeFollowupDispatch.__table__,
                        EhsChangeFollowupRound.__table__,
                    ],
                )
    finally:
        await engine.dispose()


@pytest.fixture
async def sealed_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=pool.NullPool)
    try:
        async with engine.connect() as conn:
            outer = await conn.begin()
            session = async_sessionmaker(
                bind=conn,
                class_=AsyncSession,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )()
            yield session
            await outer.rollback()
            await session.close()
    finally:
        await engine.dispose()


async def _seed(session: AsyncSession) -> str:
    """一轮 + 杨昆一张卡（message_id 锚定）+ 两项变更，返回 dispatch_id。"""
    round_row = EhsChangeFollowupRound(
        year=2026, week_no=48, fired_on=date(2026, 11, 27), status="sent",
    )
    session.add(round_row)
    await session.flush()
    dispatch = EhsChangeFollowupDispatch(
        round_id=round_row.id,
        officer_name="杨昆",
        officer_open_id="ou_yangkun",
        departments="提炼工程四部",
        change_count=2,
        send_status="sent",
        message_id="om_card_1",
    )
    session.add(dispatch)
    await session.flush()
    for record_id, change_no in (("recA1", "FX-T1"), ("recA2", "FX-T2")):
        session.add(EhsChangeFollowupItem(
            round_id=round_row.id,
            dispatch_id=dispatch.id,
            record_id=record_id,
            change_no=change_no,
            title=f"{change_no} 变更",
            department="提炼工程四部",
            status_shown="待验收",
            progress_friday="施工中",
            nag_weeks=1,
        ))
    await session.flush()
    return str(dispatch.id)


def _submit_event(dispatch_id: str, record_id: str, text: str) -> dict[str, Any]:
    return {
        "operator": {"open_id": "ou_yangkun"},
        "action": {
            "name": f"ecf_submit_{dispatch_id}",
            "form_value": {"change": record_id, "progress": text},
        },
        "context": {"open_message_id": "om_card_1"},
    }


def _unchanged_event(dispatch_id: str) -> dict[str, Any]:
    return {
        "operator": {"open_id": "ou_yangkun"},
        "action": {"name": f"ecf_unchanged_{dispatch_id}", "value": "{}"},
        "context": {"open_message_id": "om_card_1"},
    }


@pytest.fixture
def _pin_names(monkeypatch: pytest.MonkeyPatch):
    """operator open_id → 姓名钉桩（静态映射不触库）。"""
    from app.modules.safety.feishu import progress_card

    monkeypatch.setattr(progress_card, "resolve_operator_name", lambda ident: {
        "ou_yangkun": "杨昆", "ou_other": "别人",
    }.get(ident or "", ident[-12:] if ident else ""))


@pytest.fixture
def _pin_writeback(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []

    async def _fake(record_id: str, text: str, *, operator_id: str | None = None):
        calls.append((record_id, text))
        return True

    monkeypatch.setattr(ecf_card, "push_progress_to_change_table", _fake)
    return calls


@pytest.fixture
def _pin_refresh(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def _fake(dispatch_id: str, *, session: Any = None):
        calls.append(dispatch_id)
        return True

    monkeypatch.setattr(ecf_card, "refresh_dispatch_card", _fake)
    return calls


# ═══════════════════════════════════════════════════════════
# 提交进展
# ═══════════════════════════════════════════════════════════

class TestSubmit:
    async def test_submit_success(
        self, sealed_session, _pin_names, _pin_writeback, _pin_refresh,
    ):
        dispatch_id = await _seed(sealed_session)
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"scope": ecf_card.cards.SCOPE, "action": "submit",
             "dispatch_id": dispatch_id},
            _submit_event(dispatch_id, "recA1", "已完工待验收"),
            session=sealed_session,
        )
        assert ack == {"toast": {"type": "success", "content": "进展已提交，感谢更新！"}}
        assert _pin_writeback == [("recA1", "已完工待验收")]
        await asyncio.sleep(0)  # 让 create_task 调度的改卡后台任务跑一拍
        assert _pin_refresh == [dispatch_id]
        item = (await sealed_session.scalars(
            select(EhsChangeFollowupItem).where(
                EhsChangeFollowupItem.record_id == "recA1"
            )
        )).first()
        assert item.replied_progress == "已完工待验收"
        assert item.replied_at is not None and item.replied_by == "ou_yangkun"

    async def test_submit_routes_by_name_without_value(
        self, sealed_session, _pin_names, _pin_writeback, _pin_refresh,
    ):
        """form 回调 action.value 缺失：name 前缀兜底路由（progress_card 同款）。"""
        dispatch_id = await _seed(sealed_session)
        ack = await ecf_card.handle_ehs_change_followup_action(
            {}, _submit_event(dispatch_id, "recA2", "资料收集中"),
            session=sealed_session,
        )
        assert ack is not None and ack["toast"]["type"] == "success"
        assert _pin_writeback == [("recA2", "资料收集中")]

    async def test_submit_empty_input(self, sealed_session, _pin_names, _pin_writeback):
        dispatch_id = await _seed(sealed_session)
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            _submit_event(dispatch_id, "recA1", "  "),
            session=sealed_session,
        )
        assert ack["toast"]["type"] == "error"
        assert not _pin_writeback

    async def test_submit_rejects_non_recipient(
        self, sealed_session, _pin_names, _pin_writeback,
    ):
        dispatch_id = await _seed(sealed_session)
        event = _submit_event(dispatch_id, "recA1", "x")
        event["operator"] = {"open_id": "ou_other"}
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            event, session=sealed_session,
        )
        assert ack["toast"]["content"] == "仅收卡人本人可操作"
        assert not _pin_writeback

    async def test_submit_allows_any_operator_in_gray(
        self, sealed_session, monkeypatch, _pin_names, _pin_writeback,
    ):
        monkeypatch.setattr(ecf_config, "gray_recipient", lambda: "ou_gray")
        dispatch_id = await _seed(sealed_session)
        event = _submit_event(dispatch_id, "recA1", "灰度验证")
        event["operator"] = {"open_id": "ou_gray_xk"}
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            event, session=sealed_session,
        )
        assert ack["toast"]["type"] == "success"
        assert _pin_writeback == [("recA1", "灰度验证")]

    async def test_submit_writeback_failure_not_recorded(
        self, sealed_session, monkeypatch, _pin_names, _pin_refresh,
    ):
        async def _fail(record_id, text, *, operator_id=None):
            return False

        monkeypatch.setattr(ecf_card, "push_progress_to_change_table", _fail)
        dispatch_id = await _seed(sealed_session)
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            _submit_event(dispatch_id, "recA1", "x"),
            session=sealed_session,
        )
        assert ack["toast"]["content"] == "提交失败，请稍后重试"
        item = (await sealed_session.scalars(
            select(EhsChangeFollowupItem).where(
                EhsChangeFollowupItem.record_id == "recA1"
            )
        )).first()
        assert item.replied_at is None

    async def test_submit_out_of_scope_change(self, sealed_session, _pin_names):
        dispatch_id = await _seed(sealed_session)
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            _submit_event(dispatch_id, "recXX", "x"),
            session=sealed_session,
        )
        assert ack["toast"]["content"] == "该变更不在本卡督办范围内"


# ═══════════════════════════════════════════════════════════
# 进展不变
# ═══════════════════════════════════════════════════════════

class TestUnchanged:
    async def test_unchanged_marks_and_idempotent(
        self, sealed_session, _pin_names, _pin_refresh,
    ):
        dispatch_id = await _seed(sealed_session)
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"scope": ecf_card.cards.SCOPE, "action": "unchanged",
             "dispatch_id": dispatch_id},
            _unchanged_event(dispatch_id),
            session=sealed_session,
        )
        assert ack["toast"]["type"] == "success"
        d = (await sealed_session.scalars(
            select(EhsChangeFollowupDispatch)
        )).first()
        assert d.response_type == "unchanged" and d.responded_at is not None

        # 重复点：幂等，不再刷新 responded_at，也不再触发改卡
        before = d.responded_at
        ack2 = await ecf_card.handle_ehs_change_followup_action(
            {"action": "unchanged", "dispatch_id": dispatch_id},
            _unchanged_event(dispatch_id),
            session=sealed_session,
        )
        assert "已反馈" in ack2["toast"]["content"]
        assert d.responded_at == before
        await asyncio.sleep(0)  # 首次点击调度的改卡任务（重复点不再调度）
        assert _pin_refresh == [dispatch_id]

    async def test_unchanged_rejects_non_recipient(
        self, sealed_session, _pin_names,
    ):
        dispatch_id = await _seed(sealed_session)
        event = _unchanged_event(dispatch_id)
        event["operator"] = {"open_id": "ou_other"}
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "unchanged", "dispatch_id": dispatch_id},
            event, session=sealed_session,
        )
        assert ack["toast"]["content"] == "仅收卡人本人可操作"


# ═══════════════════════════════════════════════════════════
# 未知路由 / 原卡重建
# ═══════════════════════════════════════════════════════════

class TestRoutingAndRefresh:
    async def test_missing_dispatch_id_returns_none(self):
        ack = await ecf_card.handle_ehs_change_followup_action(
            {}, {"action": {"name": "ecf_submit_"}},
        )
        assert ack is None

    async def test_unknown_dispatch(self, sealed_session, _pin_names):
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": "00000000-0000-0000-0000-000000000000"},
            _submit_event("00000000-0000-0000-0000-000000000000", "recA1", "x"),
            session=sealed_session,
        )
        assert ack["toast"]["content"] == "督办卡不存在或已失效"

    async def test_refresh_rebuilds_responded_card(self, sealed_session, monkeypatch):
        """refresh_dispatch_card：按库内状态重建（已反馈态无表单无按钮）。"""
        from app.modules.safety.feishu import notification

        dispatch_id = await _seed(sealed_session)
        d = (await sealed_session.scalars(
            select(EhsChangeFollowupDispatch)
        )).first()
        d.response_type = "unchanged"
        d.responded_at = datetime(2026, 11, 27, 14, 32, tzinfo=_TZ)
        item = (await sealed_session.scalars(
            select(EhsChangeFollowupItem).where(
                EhsChangeFollowupItem.record_id == "recA2"
            )
        )).first()
        item.replied_progress = "资料收集中"
        item.replied_at = datetime(2026, 11, 27, 15, 2, tzinfo=_TZ)
        await sealed_session.flush()

        captured: list[tuple[str, dict]] = []

        async def _fake_update(message_id: str, card: dict) -> bool:
            captured.append((message_id, card))
            return True

        monkeypatch.setattr(notification, "update_card", _fake_update)
        ok = await ecf_card.refresh_dispatch_card(dispatch_id, session=sealed_session)
        assert ok is True
        message_id, card = captured[0]
        assert message_id == "om_card_1"
        elements = card["body"]["elements"]
        assert not [e for e in elements if e.get("tag") == "form"]
        content = "".join(
            e["content"] for e in elements if e.get("tag") == "markdown"
        )
        assert "已反馈：其余变更进展不变，无需更新（14:32）" in content
        assert "✅ FX-T2：资料收集中（15:02）" in content
