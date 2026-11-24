"""EHS 变更周度督办 — 周五卡回调（逐项提交/勾选进展不变）单测。

零真机：Bitable 回写、卡片 PATCH、姓名解析全钉桩；DB 用 sealed 会话
（外层事务 + savepoint，_apply_submission 内 commit 只释放 savepoint）。
表临时建拆与 service 测试同配方（迁移已应用则不动）。
"""

from __future__ import annotations

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
def _no_gray_by_default(monkeypatch: pytest.MonkeyPatch):
    """压掉 .env.development 里真实灰度收件人对测试的泄漏（operator 校验恒过）。

    需要灰度行为的用例自行覆写 ecf_config.gray_recipient。
    """
    monkeypatch.setattr(ecf_config, "gray_recipient", lambda: "")
    monkeypatch.setattr(ecf_config, "writeback_dry_run", lambda: False)


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


def _form_event(
    dispatch_id: str, form_value: dict[str, Any],
    *, operator: str = "ou_yangkun",
) -> dict[str, Any]:
    return {
        "operator": {"open_id": operator},
        "action": {
            "name": f"ecf_submit_{dispatch_id}",
            "form_value": form_value,
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


def _uuid(value: str):
    import uuid

    return uuid.UUID(value)


async def _get_item(session: AsyncSession, record_id: str) -> EhsChangeFollowupItem:
    return (await session.scalars(
        select(EhsChangeFollowupItem).where(
            EhsChangeFollowupItem.record_id == record_id
        )
    )).first()


# ═══════════════════════════════════════════════════════════
# 提交反馈（逐项）
# ═══════════════════════════════════════════════════════════

class TestSubmit:
    async def test_handler_validates_and_acks_processing(
        self, sealed_session, _pin_names, _pin_writeback,
    ):
        """回调只做校验：ACK「处理中」，写链在后台（2.9s 契约）。"""
        dispatch_id = await _seed(sealed_session)
        event = _form_event(dispatch_id, {"ecf_prog_recA1": "已完工待验收"})
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            event, session=sealed_session,
        )
        assert ack["toast"]["type"] == "success"
        assert "提交处理中" in ack["toast"]["content"]

    async def test_handler_empty_form_rejected(self, sealed_session, _pin_names):
        dispatch_id = await _seed(sealed_session)
        event = _form_event(dispatch_id, {"ecf_prog_recA1": "  "})
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            event, session=sealed_session,
        )
        assert ack["toast"]["type"] == "error"
        assert "至少填写一项" in ack["toast"]["content"]

    async def test_handler_rejects_non_recipient(self, sealed_session, _pin_names):
        dispatch_id = await _seed(sealed_session)
        event = _form_event(
            dispatch_id, {"ecf_prog_recA1": "x"}, operator="ou_other",
        )
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            event, session=sealed_session,
        )
        assert ack["toast"]["content"] == "仅收卡人本人可操作"

    async def test_handler_allows_any_operator_in_gray(
        self, sealed_session, monkeypatch, _pin_names,
    ):
        monkeypatch.setattr(ecf_config, "gray_recipient", lambda: "ou_gray")
        dispatch_id = await _seed(sealed_session)
        event = _form_event(
            dispatch_id, {"ecf_prog_recA1": "灰度验证"}, operator="ou_gray_xk",
        )
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "submit", "dispatch_id": dispatch_id},
            event, session=sealed_session,
        )
        assert ack["toast"]["type"] == "success"

    async def test_apply_mixed_submission(
        self, sealed_session, _pin_names, _pin_writeback, _pin_refresh,
    ):
        """一次提交多项：A1 填文字、A2 勾「进展不变」→ 各自落库+回写+改卡。"""
        dispatch_id = await _seed(sealed_session)
        await ecf_card._apply_submission(
            dispatch_id,
            {"ecf_prog_recA1": "已完工待验收", "ecf_unchk_recA2": True},
            "ou_yangkun",
            session=sealed_session,
        )
        a1 = await _get_item(sealed_session, "recA1")
        a2 = await _get_item(sealed_session, "recA2")
        assert a1.replied_progress == "已完工待验收"
        assert a1.replied_at is not None and a1.replied_by == "ou_yangkun"
        assert a1.marked_unchanged is False
        assert a2.marked_unchanged and a2.marked_at is not None
        assert a2.replied_at is None
        assert _pin_writeback == [("recA1", "已完工待验收")]  # 勾选不写表
        assert _pin_refresh == [dispatch_id]

    async def test_apply_text_overrides_mark(
        self, sealed_session, _pin_names, _pin_writeback, _pin_refresh,
    ):
        """先前勾过「进展不变」的项再填文字 → 覆盖并清除标记。"""
        dispatch_id = await _seed(sealed_session)
        await ecf_card._apply_submission(
            dispatch_id, {"ecf_unchk_recA1": True}, "ou_yangkun",
            session=sealed_session,
        )
        await ecf_card._apply_submission(
            dispatch_id, {"ecf_prog_recA1": "补充新进展"}, "ou_yangkun",
            session=sealed_session,
        )
        a1 = await _get_item(sealed_session, "recA1")
        assert a1.replied_progress == "补充新进展"
        assert a1.marked_unchanged is False
        # 同一提交里既填文字又勾选：文字优先
        await ecf_card._apply_submission(
            dispatch_id,
            {"ecf_prog_recA2": "文字为准", "ecf_unchk_recA2": True},
            "ou_yangkun", session=sealed_session,
        )
        a2 = await _get_item(sealed_session, "recA2")
        assert a2.replied_progress == "文字为准" and a2.marked_unchanged is False

    async def test_apply_writeback_failure_skips_item(
        self, sealed_session, monkeypatch, _pin_names, _pin_refresh,
    ):
        async def _fail(record_id, text, *, operator_id=None):
            return record_id != "recA2"  # A1 成功、A2 失败

        monkeypatch.setattr(ecf_card, "push_progress_to_change_table", _fail)
        dispatch_id = await _seed(sealed_session)
        await ecf_card._apply_submission(
            dispatch_id,
            {"ecf_prog_recA1": "ok", "ecf_prog_recA2": "bad"},
            "ou_yangkun", session=sealed_session,
        )
        a1 = await _get_item(sealed_session, "recA1")
        a2 = await _get_item(sealed_session, "recA2")
        assert a1.replied_progress == "ok"
        assert a2.replied_at is None  # 写表失败不记已反馈（DESIGN §9）

    async def test_apply_ignores_out_of_scope_records(
        self, sealed_session, _pin_names, _pin_writeback,
    ):
        """表单里混入非本卡 record_id（旧卡残留 name）→ 过滤忽略。"""
        dispatch_id = await _seed(sealed_session)
        await ecf_card._apply_submission(
            dispatch_id,
            {"ecf_prog_recXX": "范围外", "ecf_unchk_recYY": True},
            "ou_yangkun", session=sealed_session,
        )
        assert _pin_writeback == []

    async def test_handler_routes_by_name_without_value(
        self, sealed_session, _pin_names, _pin_writeback,
    ):
        """form 回调 action.value 缺失：name 前缀兜底路由。"""
        dispatch_id = await _seed(sealed_session)
        event = _form_event(dispatch_id, {"ecf_prog_recA2": "资料收集中"})
        ack = await ecf_card.handle_ehs_change_followup_action(
            {}, event, session=sealed_session,
        )
        assert ack is not None and ack["toast"]["type"] == "success"


# ═══════════════════════════════════════════════════════════
# 旧版全局「进展不变」按钮（兼容）
# ═══════════════════════════════════════════════════════════

class TestUnchangedLegacy:
    async def test_unchanged_marks_and_idempotent(
        self, sealed_session, _pin_names, _pin_refresh,
    ):
        dispatch_id = await _seed(sealed_session)
        ack = await ecf_card.handle_ehs_change_followup_action(
            {"action": "unchanged", "dispatch_id": dispatch_id},
            _unchanged_event(dispatch_id),
            session=sealed_session,
        )
        assert ack["toast"]["type"] == "success"
        d = await sealed_session.get(EhsChangeFollowupDispatch, _uuid(dispatch_id))
        assert d is not None
        assert d.response_type == "unchanged" and d.responded_at is not None

        before = d.responded_at
        ack2 = await ecf_card.handle_ehs_change_followup_action(
            {"action": "unchanged", "dispatch_id": dispatch_id},
            _unchanged_event(dispatch_id),
            session=sealed_session,
        )
        assert "已反馈" in ack2["toast"]["content"]
        assert d.responded_at == before
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
            _form_event("00000000-0000-0000-0000-000000000000", {"ecf_prog_recA1": "x"}),
            session=sealed_session,
        )
        assert ack["toast"]["content"] == "督办卡不存在或已失效"

    async def test_refresh_rebuilds_with_feedback_states(
        self, sealed_session, monkeypatch,
    ):
        """refresh_dispatch_card：✅/☑ 状态行 + 表单保留（可继续提交）。"""
        from app.modules.safety.feishu import notification

        dispatch_id = await _seed(sealed_session)
        a1 = await _get_item(sealed_session, "recA1")
        a1.replied_progress = "已进料"
        a1.replied_at = datetime(2026, 11, 27, 15, 2, tzinfo=_TZ)
        a2 = await _get_item(sealed_session, "recA2")
        a2.marked_unchanged = True
        a2.marked_at = datetime(2026, 11, 27, 16, 40, tzinfo=_TZ)
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
        # 表单保留，逐项「信息块 + input + checker」仍在
        form = [e for e in elements if e.get("tag") == "form"][0]
        assert len([e for e in form["elements"] if e["tag"] == "input"]) == 2
        content = "\n".join(
            e["content"] for e in form["elements"] if e.get("tag") == "markdown"
        )
        assert "✅ FX-T1：已进料（15:02）" in content
        assert "☑ FX-T2：进展不变，无需更新（16:40）" in content
