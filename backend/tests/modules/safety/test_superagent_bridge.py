"""冒烟① C 层集成测试 —— workticket 速递格旁挂 effects 双路径。

验证（ticket 03）：
- 开关关（默认）：原路径直调逐字节不变，零 effect 行
- 开关开：入队 digest_cell_upsert（chat_id 行内权威）、直调不发生
- 执行侧：行内 chat_id 获胜（resolver 漂移不可覆盖）；失败 False → 退避重试
- 重启语义：入库未执行→新轮消费恰一次（kill 模拟）
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.modules.safety.feishu.daily_digest import DigestCell
from app.modules.safety.superagent_bridge import (
    _digest_cell_upsert_handler,
    digest_cell_effects_enabled,
    post_workticket_safety_cell,
    register_superagent_bridge,
)
from app.platform.superagent.effects import execute_claimed_effect
from app.platform.superagent.models import AgentEffect


def _cell() -> DigestCell:
    return DigestCell(
        tag_color="green", tag_text="作业票审核", title="作业票审核日报",
        stats="**12** 票", zone="", detail="detail-md",
    )


@pytest.fixture(autouse=True)
def _bridge_registered():
    register_superagent_bridge()
    yield


async def test_switch_off_direct_path_unchanged(db_session, monkeypatch) -> None:
    """开关关：直调 upsert_daily_digest（同参数），零 effect 行。"""
    assert digest_cell_effects_enabled() is False

    calls: list[dict] = []

    async def fake_upsert(report_date, key, cell, *, board="safety", **kw):
        calls.append({"date": report_date, "key": key, "board": board, "cell": cell})
        return True

    import app.modules.safety.feishu.daily_digest as dd

    monkeypatch.setattr(dd, "upsert_daily_digest", fake_upsert)

    outcome = await post_workticket_safety_cell(
        db_session, digest_date=date(2026, 11, 3), cell=_cell(),
    )

    assert outcome == "direct"
    assert len(calls) == 1
    assert calls[0]["key"] == "workticket"
    assert calls[0]["board"] == "safety"
    assert calls[0]["date"] == date(2026, 11, 3)
    effects = (
        await db_session.execute(select(AgentEffect).where(AgentEffect.kind == "digest_cell_upsert"))
    ).scalars().all()
    assert effects == []


async def test_switch_on_enqueues_effect_with_inline_chat(db_session, monkeypatch) -> None:
    """开关开：入队 effect，payload 携带行内 chat_id/board/cell；直调不发生。"""
    monkeypatch.setenv("SAFETY_SUPERAGENT_DIGEST_CELL_EFFECTS", "true")
    assert digest_cell_effects_enabled() is True

    import app.modules.safety.feishu.daily_digest as dd

    async def must_not_call(*a, **kw):  # pragma: no cover - 断言用
        raise AssertionError("开关开时不得直调 upsert_daily_digest")

    monkeypatch.setattr(dd, "upsert_daily_digest", must_not_call)
    monkeypatch.setattr(
        dd, "digest_chat_id", lambda: "oc_inline_authority", raising=False,
    )

    outcome = await post_workticket_safety_cell(
        db_session, digest_date=date(2026, 11, 3), cell=_cell(),
    )
    assert outcome == "effects"

    row = (
        await db_session.execute(
            select(AgentEffect).where(AgentEffect.kind == "digest_cell_upsert")
        )
    ).scalar_one()
    assert row.payload["key"] == "workticket"
    assert row.payload["board"] == "safety"
    assert row.payload["chat_id"] == "oc_inline_authority"  # 行内权威
    assert row.payload["cell"] == asdict(_cell())
    assert row.dedupe_key == "digest_cell:safety:2026-11-03:workticket"
    assert row.status == "pending"


async def test_handler_inline_chat_wins_over_resolver(db_session, monkeypatch) -> None:
    """执行侧：只使用 payload 行内 chat_id——resolver 事后漂移不得覆盖（事故根因修复）。"""
    import app.modules.safety.feishu.daily_digest as dd

    seen: list[dict] = []

    async def fake_upsert(report_date, key, cell, *, board="safety", chat_id=None, **kw):
        seen.append({"chat_id": chat_id, "board": board})
        return True

    monkeypatch.setattr(dd, "upsert_daily_digest", fake_upsert)
    # resolver 被污染/漂移也不影响执行侧
    monkeypatch.setattr(
        dd, "digest_chat_id", lambda: "oc_DRIFTED", raising=False,
    )

    payload = {
        "date": "2026-11-03", "key": "workticket", "board": "safety",
        "chat_id": "oc_inline_authority", "cell": asdict(_cell()),
    }
    await _digest_cell_upsert_handler(payload)

    assert seen == [{"chat_id": "oc_inline_authority", "board": "safety"}]


async def test_handler_false_return_retries(db_session, monkeypatch) -> None:
    """upsert 返回 False（板停用/建卡失败）→ effect 失败退避，可对账重试。"""
    import app.modules.safety.feishu.daily_digest as dd

    async def false_upsert(*a, **kw):
        return False

    monkeypatch.setattr(dd, "upsert_daily_digest", false_upsert)

    from app.platform.superagent.effects import enqueue_effect

    effect_id = await enqueue_effect(
        db_session, "digest_cell_upsert",
        {"date": "2026-11-03", "key": "workticket", "board": "safety",
         "chat_id": "oc_x", "cell": asdict(_cell())},
        dedupe_key="digest_cell:safety:2026-11-03:workticket",
    )
    outcome = await execute_claimed_effect(db_session, effect_id)
    assert outcome == "retried"
    row = await db_session.get(AgentEffect, effect_id)
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.next_due_at > datetime.now(UTC)


async def test_kill_restart_delivers_exactly_once(db_session, monkeypatch) -> None:
    """kill 模拟：入队后进程死（未消费）→「重启」新轮消费恰一次；再扫不再执行。"""
    monkeypatch.setenv("SAFETY_SUPERAGENT_DIGEST_CELL_EFFECTS", "true")

    import app.modules.safety.feishu.daily_digest as dd

    sent: list[date] = []

    async def fake_upsert(report_date, key, cell, *, board="safety", chat_id=None, **kw):
        sent.append(report_date)
        return True

    monkeypatch.setattr(dd, "upsert_daily_digest", fake_upsert)

    # 「进程 A」：仅入队（先存），未及消费即 kill
    await post_workticket_safety_cell(
        db_session, digest_date=date(2026, 11, 3), cell=_cell(),
    )
    assert sent == []

    # 「进程 B」重启：effects 轮扫描 → 执行 → done；重扫 → skipped
    from app.platform.superagent.effects import find_due_effect_ids

    ids = await find_due_effect_ids(db_session)
    assert len(ids) == 1
    assert await execute_claimed_effect(db_session, ids[0]) == "done"
    assert await execute_claimed_effect(db_session, ids[0]) == "skipped"
    assert sent == [date(2026, 11, 3)]  # 恰一次


# ═══════════════════════════════════════════════════════════════
# 冒烟②：督办轮询旁挂开关两态 + 单记录回写
# ═══════════════════════════════════════════════════════════════


async def test_smoke2_switch_on_skips_original_round(monkeypatch) -> None:
    """开关开：原 run_supervision_round 不被触达（superagent 路径接管）。"""
    monkeypatch.setenv("SAFETY_HAZARD_SUPERVISION_VIA_SUPERAGENT", "true")

    import app.modules.safety.service.hazard_direct.supervision as supervision_mod
    from app.modules.safety.scheduled import _run_hazard_supervision_round
    from app.modules.safety.superagent_bridge import supervision_via_superagent

    assert supervision_via_superagent() is True

    async def must_not_run(*a, **kw):  # pragma: no cover - 断言用
        raise AssertionError("旁挂开关开时不得跑原轮询")

    monkeypatch.setattr(supervision_mod, "run_supervision_round", must_not_run)
    await _run_hazard_supervision_round()  # 不抛即通过


async def test_smoke2_switch_off_runs_original_round(monkeypatch) -> None:
    """开关关：原路径照常执行（行为不变断言）。"""
    import app.modules.safety.service.hazard_direct.config as hd_config
    import app.modules.safety.service.hazard_direct.supervision as supervision_mod
    from app.modules.safety.scheduled import _run_hazard_supervision_round

    monkeypatch.setattr(hd_config, "supervision_poll_enabled", lambda: True)
    monkeypatch.setattr(hd_config, "supervision_stagger_seconds", lambda: 0)

    ran: list[bool] = []

    async def fake_round(*a, **kw):
        ran.append(True)
        return None

    monkeypatch.setattr(supervision_mod, "run_supervision_round", fake_round)
    await _run_hazard_supervision_round()
    assert ran == [True]


async def test_supervision_writeback_handler_passes_record(monkeypatch) -> None:
    """执行侧：Trigger payload → 单记录回写（record_id+fields 透传）。"""
    import app.modules.safety.service.hazard_direct.supervision as supervision_mod
    from app.modules.safety.superagent_bridge import _supervision_writeback_handler

    seen: list[dict] = []

    async def fake_for_record(record):
        seen.append(record)
        return {"outcome": "unchanged"}

    monkeypatch.setattr(supervision_mod, "run_supervision_for_record", fake_for_record)
    await _supervision_writeback_handler(
        {"record_id": "recA", "fields": {"整改状态": "未关闭"}, "fingerprint": "x"}
    )
    assert seen == [{"record_id": "recA", "fields": {"整改状态": "未关闭"}}]


async def test_supervision_for_record_idempotent_unchanged(monkeypatch) -> None:
    """单记录回写幂等：算得与当前一致 → 零写调用。"""
    import time as _time

    import app.modules.safety.service.hazard_direct.bitable_repo as repo
    from app.modules.safety.service.hazard_direct.supervision import (
        run_supervision_for_record,
    )

    recent_ms = int(_time.time() * 1000)
    record = {
        "record_id": "recB",
        "fields": {
            "整改状态": "未关闭",
            "检查日期": recent_ms,
            "督办等级": "一般预警",  # 当前值 == 重算值（近期+未关闭+无级别 → 一般预警）
        },
    }
    view = repo.to_view(record)
    assert view.supervision_level == "一般预警"

    async def fake_client_update(*a, **kw):  # pragma: no cover - 断言用
        raise AssertionError("未变化不得写回")

    import app.modules.safety.feishu.bitable_client as bc

    monkeypatch.setattr(bc, "SafetyBitableClient", lambda: type("C", (), {"update_record": staticmethod(fake_client_update)})())

    result = await run_supervision_for_record(record)
    assert result["outcome"] == "unchanged"


async def test_supervision_for_record_updates_when_changed(monkeypatch) -> None:
    """单记录回写：级别变化 → 写回督办等级（>30 天未关闭 → 红色预警）。"""
    import app.modules.safety.feishu.bitable_client as bc
    from app.modules.safety.service.hazard_direct.supervision import (
        run_supervision_for_record,
    )

    writes: list[tuple[str, dict]] = []

    class FakeClient:
        async def update_record(self, record_id, fields):
            writes.append((record_id, fields))
            return True

    monkeypatch.setattr(bc, "SafetyBitableClient", FakeClient)

    async def _sleep(x):  # 测试免 0.5s 串行等待
        return None

    import app.modules.safety.service.hazard_direct.supervision as sup_mod

    monkeypatch.setattr(sup_mod.asyncio, "sleep", _sleep)

    # 检查日期 40 天前 + 未关闭 → 红色预警（>30 天规则）
    import time as _time

    old_ms = int((_time.time() - 40 * 86400) * 1000)
    record = {
        "record_id": "recC",
        "fields": {
            "整改状态": "未关闭",
            "检查日期": old_ms,
            "责任部门": "车间一",
        },
    }
    result = await run_supervision_for_record(record)
    assert result["outcome"] == "updated"
    assert result["label"]
    assert writes and writes[0][0] == "recC"
