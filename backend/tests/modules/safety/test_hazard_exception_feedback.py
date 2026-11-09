"""P2-1 T4 —— rescued 反馈闭环：报告卡「有用/没用」按钮 + 人工改判回写 Redis。

口径（Q6B，2026-11-09）：报告 30 天窗口内可改判、可反复切换；
``effective_rescued``=人工优先于程序；ack/dismiss 行为不变（仅 PATCH）；
未知/写语义 action 一律不处理返回 False（P1-3 铁律延续）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.feishu.exception_review_card import (
    CARD_SCOPE,
    build_exception_review_card,
    extract_button_values,
    handle_review_card_action,
)
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    REVIEWS_KEY,
    ExceptionReviewReport,
    record_human_feedback,
)
from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis
from tests.modules.safety.test_hazard_exception_writeback import (
    _report as _wb_report,
)


def _seed_report(redis: FakeRedis, report: ExceptionReviewReport) -> None:
    redis.store[REVIEWS_KEY] = {report.record_id: report.model_dump_json()}


# ── record_human_feedback（服务层）─────────────────────────────────────────


async def test_record_human_feedback_useful_overrides() -> None:
    redis = FakeRedis()
    report = _wb_report(record_id="recF", rescued=False)
    _seed_report(redis, report)
    ok = await record_human_feedback("recF", "useful", redis=redis)
    assert ok is True
    persisted = ExceptionReviewReport.model_validate_json(
        redis.store[REVIEWS_KEY]["recF"]
    )
    assert persisted.human_feedback == "useful"
    assert persisted.human_feedback_at is not None
    assert persisted.effective_rescued is True  # 人工>程序


async def test_record_human_feedback_switchable_and_missing_report() -> None:
    redis = FakeRedis()
    report = _wb_report(record_id="recF", rescued=True)
    _seed_report(redis, report)
    await record_human_feedback("recF", "useless", redis=redis)
    await record_human_feedback("recF", "useful", redis=redis)  # 可反复切换
    persisted = ExceptionReviewReport.model_validate_json(
        redis.store[REVIEWS_KEY]["recF"]
    )
    assert persisted.human_feedback == "useful"
    # 报告缺失 → False 不炸
    assert await record_human_feedback("rec404", "useful", redis=redis) is False


async def test_record_human_feedback_rejects_unknown_value() -> None:
    redis = FakeRedis()
    report = _wb_report(record_id="recF")
    _seed_report(redis, report)
    with pytest.raises(ValueError):
        await record_human_feedback("recF", "maybe", redis=redis)


# ── 卡片按钮与回调 ─────────────────────────────────────────────────────────


def test_card_has_four_buttons_including_feedback() -> None:
    card = build_exception_review_card(_wb_report(record_id="recX"))
    values = extract_button_values(card)
    actions = {v.get("action") for v in values}
    assert actions == {"ack", "dismiss", "useful", "useless"}


def test_card_buttons_no_execute_semantics_text() -> None:
    """P1-3 钉子保留：按钮文案不得出现「确认执行」（写语义防误触）。"""
    import json

    card = build_exception_review_card(_wb_report(record_id="recX"))
    buttons_text = json.dumps(
        card, ensure_ascii=False, default=str
    )
    assert "确认执行" not in buttons_text


async def test_callback_useful_updates_report_and_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    report = _wb_report(record_id="recX", rescued=False)
    _seed_report(redis, report)
    patched: list[str] = []

    async def fake_update(message_id: str, card: dict[str, Any]) -> None:
        patched.append(message_id)

    import app.modules.safety.feishu.exception_review_card as erc

    monkeypatch.setattr(erc, "update_card", fake_update)
    import app.modules.safety.service.hazard_direct.exception_reviewer as er_mod
    monkeypatch.setattr(er_mod, "review_redis_client", lambda: redis)

    ok = await handle_review_card_action(
        {"scope": CARD_SCOPE, "action": "useful", "record_id": "recX"},
        {"open_message_id": "om_1"},
    )
    assert ok is True
    assert patched == ["om_1"]
    persisted = ExceptionReviewReport.model_validate_json(
        redis.store[REVIEWS_KEY]["recX"]
    )
    assert persisted.human_feedback == "useful"


async def test_callback_useless_overrides_program_rescued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    report = _wb_report(record_id="recY", rescued=True)
    _seed_report(redis, report)

    import app.modules.safety.feishu.exception_review_card as erc

    async def fake_update(message_id: str, card: dict[str, Any]) -> None:
        pass

    monkeypatch.setattr(erc, "update_card", fake_update)
    import app.modules.safety.service.hazard_direct.exception_reviewer as er_mod
    monkeypatch.setattr(er_mod, "review_redis_client", lambda: redis)

    ok = await handle_review_card_action(
        {"scope": CARD_SCOPE, "action": "useless", "record_id": "recY"},
        {"open_message_id": "om_2"},
    )
    assert ok is True
    persisted = ExceptionReviewReport.model_validate_json(
        redis.store[REVIEWS_KEY]["recY"]
    )
    assert persisted.effective_rescued is False


async def test_callback_feedback_report_missing_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    patched: list[str] = []

    import app.modules.safety.feishu.exception_review_card as erc

    async def fake_update(message_id: str, card: dict[str, Any]) -> None:
        patched.append(message_id)

    monkeypatch.setattr(erc, "update_card", fake_update)
    import app.modules.safety.service.hazard_direct.exception_reviewer as er_mod
    monkeypatch.setattr(er_mod, "review_redis_client", lambda: redis)

    ok = await handle_review_card_action(
        {"scope": CARD_SCOPE, "action": "useful", "record_id": "rec404"},
        {"open_message_id": "om_3"},
    )
    # 报告缺失：仍 PATCH 终态提示失效，但不炸、返回 True（动作已受理）
    assert ok is True
    assert patched == ["om_3"]


async def test_callback_unknown_action_rejected() -> None:
    ok = await handle_review_card_action(
        {"scope": CARD_SCOPE, "action": "write", "record_id": "recX"},
        {"open_message_id": "om_4"},
    )
    assert ok is False
