"""EHS 变更周度督办 — 编排（周五一轮/周一总结）集成单测。

零真机：两表拉取/发送/投格全走接缝注入；DB 用 sealed 会话（外层事务 +
savepoint，service 内 commit 只释放 savepoint，teardown 整体回滚——防测试
数据真写开发库）。三张表不存在时临时建、测完拆（迁移已应用则不動）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

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
from app.modules.safety.service.ehs_change_followup import (
    config as ecf_config,
)
from app.modules.safety.service.ehs_change_followup import (
    service as ecf_service,
)

FRIDAY = date(2026, 11, 27)
MONDAY = date(2026, 11, 30)

_APPLINK = "https://applink.feishu.cn/client/mini_program/open?appId=cli_x"


def _approval_row(
    record_id: str,
    change_no: str,
    code: str,
    dept: str = "提炼工程四部",
    status: str = "已通过",
    change_status: str = "待验收",
    progress: str = "施工中",
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "fields": {
            "申请编号": {"text": code, "link": _APPLINK, "type": "url"},
            "变更申请编号": [{"type": "text", "text": change_no}],
            "变更名称": [{"type": "text", "text": f"{change_no} 变更"}],
            "变更申请部门": [dept],
            "申请状态": status,
            "变更状态": change_status,
            "变更最新具体进展": [{"type": "text", "text": progress}],
        },
    }


def _acceptance_row(
    record_id: str,
    status: str = "已通过",
    related: str = "",
    change_no: str = "",
) -> dict[str, Any]:
    fields: dict[str, Any] = {"申请状态": status}
    if related:
        fields["关联审批"] = related
    if change_no:
        fields["变更编号"] = [{"type": "text", "text": change_no}]
    return {"record_id": record_id, "fields": fields}


def _default_tables() -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """基线：四部两项待督办 + 人力资源部一项无主 + 一项已验收 + 一项中止 + 一项排除。"""
    approval = [
        _approval_row("recA1", "FX-T1", "202601010001"),
        _approval_row("recA2", "FX-T2", "202601010002"),
        _approval_row("recH1", "FX-H1", "202601010003", dept="人力资源部"),
        _approval_row("recOK", "FX-OK", "202601010004"),
        _approval_row("recST", "FX-ST", "202601010005", change_status="变更中止"),
        _approval_row("recEX", "FX-EXC-1", "202601010006"),
    ]
    acceptance = [_acceptance_row("recAccOK", related="202601010004-验收")]
    return {"approval": approval, "acceptance": acceptance}


def _returns(rows: list[dict[str, Any]]):
    """接缝替身：() -> rows（fetch_approval/fetch_acceptance 用）。"""

    async def _fetch() -> list[dict[str, Any]]:
        return rows

    return _fetch


class _SendStub:
    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.ok = ok

    async def __call__(self, receive_id: str, card: dict, *, id_type: str = "open_id"):
        self.calls.append((receive_id, id_type, card))
        return f"om_{len(self.calls)}" if self.ok else False


class _DigestStub:
    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[date, str]] = []
        self.ok = ok

    async def __call__(self, report_date: date, key: str, cell: Any) -> bool:
        self.calls.append((report_date, key))
        return self.ok


@pytest.fixture(autouse=True)
async def _ensure_tables() -> AsyncIterator[None]:
    """三表缺失时临时建（迁移已应用则不动，也绝不拆已有表）。"""
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
                await conn.execute(
                    __import__("sqlalchemy").text("CREATE SCHEMA IF NOT EXISTS safety")
                )
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
    """外层事务 + savepoint：service 的 commit 只释放 savepoint，测后整体回滚。"""
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


@pytest.fixture(autouse=True)
def _pin_officers(monkeypatch: pytest.MonkeyPatch):
    """安全员解析钉桩（静态映射/identity 不触网触库）。"""

    async def _fake(name: str) -> tuple[str | None, str | None]:
        return f"ou_{name}", ""

    monkeypatch.setattr(ecf_service, "_resolve_officer_ids", _fake)


@pytest.fixture(autouse=True)
def _no_gray_by_default(monkeypatch: pytest.MonkeyPatch):
    """压掉 .env.development 真实灰度收件人的泄漏（灰度用例自行覆写）。"""
    monkeypatch.setattr(ecf_config, "gray_recipient", lambda: "")


@pytest.fixture(autouse=True)
def _pin_excluded(monkeypatch: pytest.MonkeyPatch):
    """排除清单钉桩（避开 app_config 默认 7 项，用例自控）。"""
    monkeypatch.setattr(ecf_config, "excluded_raw", lambda: "FX-EXC-1")


# ═══════════════════════════════════════════════════════════
# 周五
# ═══════════════════════════════════════════════════════════

async def _run_friday(session, tables, send, digest=None, *, now=FRIDAY):
    return await ecf_service.run_friday_round(
        fetch_approval=_returns(tables["approval"]),
        fetch_acceptance=_returns(tables["acceptance"]),
        send=send,
        digest=digest if digest is not None else _DigestStub(),
        now=now,
        session=session,
    )


class TestFridayRound:
    async def test_creates_and_sends(self, sealed_session):
        tables = _default_tables()
        send, digest = _SendStub(), _DigestStub()
        stats = await _run_friday(sealed_session, tables, send, digest)

        assert stats["todo"] == 3
        assert stats["closed_accepted"] == 1
        assert stats["closed_terminated"] == 1
        assert stats["excluded"] == 1
        assert stats["recipients"] == 1
        assert stats["sent"] == 1 and stats["failed"] == 0
        assert stats["unsent_departments"] == {"人力资源部": 1}
        assert stats["departments"] == 2

        # 落库：1 轮 + 1 dispatch + 3 items（含无主项）
        rounds = (await sealed_session.scalars(
            select(EhsChangeFollowupRound).where(
                EhsChangeFollowupRound.fired_on == FRIDAY
            )
        )).all()
        assert len(rounds) == 1 and rounds[0].status == "sent"
        round_id = rounds[0].id
        dispatches = (await sealed_session.scalars(
            select(EhsChangeFollowupDispatch).where(
                EhsChangeFollowupDispatch.round_id == round_id
            )
        )).all()
        assert len(dispatches) == 1
        d = dispatches[0]
        assert d.officer_name == "杨昆" and d.send_status == "sent"
        assert d.message_id and d.change_count == 2
        items = (await sealed_session.scalars(
            select(EhsChangeFollowupItem).where(
                EhsChangeFollowupItem.round_id == round_id
            )
        )).all()
        assert len(items) == 3
        assert sum(1 for i in items if i.dispatch_id is None) == 1
        # 发送目标=静态映射 ou_杨昆；速递格已投
        assert send.calls[0][0] == "ou_杨昆"
        assert digest.calls == [(FRIDAY, "ehs_change_followup")]
        # 卡面：审批 applink 进了正文
        assert _APPLINK in send.calls[0][2]["body"]["elements"][0]["content"]

    async def test_dry_run_touches_nothing(self, sealed_session):
        tables = _default_tables()
        send = _SendStub()
        stats = await ecf_service.run_friday_round(
            fetch_approval=_returns(tables["approval"]),
            fetch_acceptance=_returns(tables["acceptance"]),
            send=send, digest=_DigestStub(), now=FRIDAY,
            session=sealed_session, dry_run=True,
        )
        assert stats["todo"] == 3 and not send.calls
        rounds = (await sealed_session.scalars(
            select(EhsChangeFollowupRound).where(
                EhsChangeFollowupRound.fired_on == FRIDAY
            )
        )).all()
        assert rounds == []

    async def test_rerun_only_resends_unsent(self, sealed_session):
        tables = _default_tables()
        send = _SendStub()
        await _run_friday(sealed_session, tables, send)
        assert len(send.calls) == 1

        # 模拟一张卡失败（如发送时网络错）后重跑：只补发这一张
        d = (await sealed_session.scalars(
            select(EhsChangeFollowupDispatch).where(
                EhsChangeFollowupDispatch.round_id.in_(
                    select(EhsChangeFollowupRound.id).where(
                        EhsChangeFollowupRound.fired_on == FRIDAY
                    )
                )
            )
        )).first()
        d.send_status = "failed"
        await sealed_session.flush()

        send2 = _SendStub()
        stats = await _run_friday(sealed_session, tables, send2)
        assert len(send2.calls) == 1 and stats["sent"] == 1
        # 全部送达后再重跑：不再发送
        send3 = _SendStub()
        stats3 = await _run_friday(sealed_session, tables, send3)
        assert not send3.calls and stats3["sent"] == 0

    async def test_failed_sends_raise_for_retry_window(self, sealed_session):
        tables = _default_tables()
        send = _SendStub(ok=False)
        with pytest.raises(RuntimeError, match="未送达"):
            await _run_friday(sealed_session, tables, send)
        rounds = (await sealed_session.scalars(
            select(EhsChangeFollowupRound).where(
                EhsChangeFollowupRound.fired_on == FRIDAY
            )
        )).all()
        assert rounds[0].status == "sending"

    async def test_unresolved_officer_counts_failed(self, sealed_session, monkeypatch):
        async def _none(name: str):
            return None, None

        monkeypatch.setattr(ecf_service, "_resolve_officer_ids", _none)
        tables = _default_tables()
        send = _SendStub()
        with pytest.raises(RuntimeError):
            await _run_friday(sealed_session, tables, send)
        assert not send.calls

    async def test_gray_recipient_redirects_all(self, sealed_session, monkeypatch):
        monkeypatch.setattr(ecf_config, "gray_recipient", lambda: "ou_gray")
        tables = _default_tables()
        send = _SendStub()
        await _run_friday(sealed_session, tables, send)
        assert send.calls[0][:2] == ("ou_gray", "open_id")


# ═══════════════════════════════════════════════════════════
# 周一
# ═══════════════════════════════════════════════════════════

async def _run_monday(session, tables, digest, *, now=MONDAY, dry_run=False):
    return await ecf_service.run_monday_summary(
        fetch_approval=_returns(tables["approval"]),
        fetch_acceptance=_returns(tables["acceptance"]),
        digest=digest,
        now=now,
        session=session,
        dry_run=dry_run,
    )


class TestMondaySummary:
    async def test_classification_and_idempotency(self, sealed_session):
        await _run_friday(sealed_session, _default_tables(), _SendStub())
        d = (await sealed_session.scalars(
            select(EhsChangeFollowupDispatch).where(
                EhsChangeFollowupDispatch.round_id.in_(
                    select(EhsChangeFollowupRound.id).where(
                        EhsChangeFollowupRound.fired_on == FRIDAY
                    )
                )
            )
        )).first()

        # 周末反馈：A1 提交了进展（表内追加）；A2 无变化且点了「进展不变」；
        # H1（无卡）无变化；OK/ST 已关闭；EXC 仍排除在库外（不在 items 里）
        d.response_type = "unchanged"
        tables = _default_tables()
        tables["approval"] = [
            _approval_row("recA1", "FX-T1", "202601010001",
                          progress="施工中\n\n【卡片提交·2026-11-28 09:00·杨昆】已完工"),
            _approval_row("recA2", "FX-T2", "202601010002"),
            _approval_row("recH1", "FX-H1", "202601010003", dept="人力资源部"),
            _approval_row("recOK", "FX-OK", "202601010004"),
            _approval_row("recST", "FX-ST", "202601010005", change_status="变更中止"),
            _approval_row("recEX", "FX-EXC-1", "202601010006"),
        ]
        digest = _DigestStub()
        stats = await _run_monday(sealed_session, tables, digest)

        assert stats["friday_total"] == 3
        assert stats["updated"] == 1      # A1 进展变
        assert stats["unchanged"] == 1    # A2 按钮且未提交
        assert stats["not_updated"] == 1  # H1 无反馈
        assert stats["closed"] == 0
        assert digest.calls == [(MONDAY, "ehs_change_summary")]

        # 轮次收口 + 幂等：再跑跳过不重投
        round_row = (await sealed_session.scalars(
            select(EhsChangeFollowupRound).where(
                EhsChangeFollowupRound.fired_on == FRIDAY
            )
        )).first()
        assert round_row.status == "summarized"
        again = await _run_monday(sealed_session, tables, _DigestStub())
        assert again == {"skipped": "already_summarized"}

    async def test_closed_on_monday_excluded_from_categories(self, sealed_session):
        await _run_friday(sealed_session, _default_tables(), _SendStub())
        # 周一：A1 名下验收单已通过 → 本周已关闭
        tables = _default_tables()
        tables["acceptance"].append(_acceptance_row("recAcc1", change_no="FX-T1"))
        digest = _DigestStub()
        stats = await _run_monday(sealed_session, tables, digest)
        assert stats["closed"] == 1
        assert stats["unchanged"] + stats["not_updated"] + stats["updated"] == 2

    async def test_no_round_skips(self, sealed_session):
        stats = await _run_monday(
            sealed_session, _default_tables(), _DigestStub(), now=date(2026, 12, 31),
        )
        assert stats == {"skipped": "no_round"}

    async def test_digest_failure_raises(self, sealed_session):
        await _run_friday(sealed_session, _default_tables(), _SendStub())
        with pytest.raises(RuntimeError, match="投递失败"):
            await _run_monday(
                sealed_session, _default_tables(), _DigestStub(ok=False),
            )
