"""检定到期提醒定时任务的触发/去重/重试判定测试。"""

from __future__ import annotations

from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.time import APP_TZ
from app.modules.meter import repository as repo
from app.modules.meter import scheduler, service

_TARGET = datetime(2026, 8, 1, 17, 45, tzinfo=APP_TZ)


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


class _FakeSessionCM:
    def __init__(self, db: _FakeSession) -> None:
        self._db = db

    async def __aenter__(self) -> _FakeSession:
        return self._db

    async def __aexit__(self, *args: object) -> bool:
        del args
        return False


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime,
    result: dict[str, int],
    last_sent_at: datetime | None = None,
) -> tuple[SimpleNamespace, _FakeSession, AsyncMock]:
    """打桩全局开关、会话、当前时间、设置与发送函数。"""
    settings = SimpleNamespace(notify_time=time(17, 45), last_sent_at=last_sent_at)
    db = _FakeSession()
    send_mock = AsyncMock(return_value=result)
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: SimpleNamespace(METER_CALIBRATION_AUTO_NOTIFY_ENABLED=True),
    )
    monkeypatch.setattr(scheduler, "async_session_factory", lambda: _FakeSessionCM(db))
    monkeypatch.setattr(scheduler, "time_now", lambda: now)
    monkeypatch.setattr(
        repo, "get_or_create_meter_settings", AsyncMock(return_value=settings)
    )
    monkeypatch.setattr(service, "send_calibration_reminders", send_mock)
    return settings, db, send_mock


class TestCalibrationReminderCoro:
    async def test_partial_delivery_marks_handled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """部分负责人已收到时不再重试，避免其他人被重复刷屏。"""
        settings, db, send_mock = _patch(
            monkeypatch,
            now=_TARGET,
            result={"sent": 0, "skipped": 0, "errors": 1, "delivered": 1},
        )
        await scheduler.calibration_reminder_coro()
        send_mock.assert_awaited_once()
        assert settings.last_sent_at == _TARGET
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_total_failure_retries_within_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """一张都没发出去且未超 30 分钟：回滚，下一轮重试。"""
        settings, db, send_mock = _patch(
            monkeypatch,
            now=_TARGET,
            result={"sent": 0, "skipped": 0, "errors": 1, "delivered": 0},
        )
        await scheduler.calibration_reminder_coro()
        send_mock.assert_awaited_once()
        assert settings.last_sent_at is None
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_total_failure_gives_up_after_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """超 30 分钟仍全失败：落标记放弃当天，避免整天空转。"""
        now = _TARGET.replace(hour=18, minute=16)
        settings, db, _ = _patch(
            monkeypatch,
            now=now,
            result={"sent": 0, "skipped": 0, "errors": 1, "delivered": 0},
        )
        await scheduler.calibration_reminder_coro()
        assert settings.last_sent_at == now
        db.commit.assert_awaited_once()

    async def test_exception_retries_within_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """发送抛异常且未超窗：按错误处理并回滚，下一轮重试。"""
        settings, db, send_mock = _patch(
            monkeypatch,
            now=_TARGET,
            result={},
        )
        send_mock.side_effect = RuntimeError("发送异常")
        await scheduler.calibration_reminder_coro()
        assert settings.last_sent_at is None
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_exception_gives_up_after_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """发送持续抛异常且已超 30 分钟：落标记放弃当天，不再每分钟重试。"""
        now = _TARGET.replace(hour=18, minute=16)
        settings, db, send_mock = _patch(monkeypatch, now=now, result={})
        send_mock.side_effect = RuntimeError("发送异常")
        await scheduler.calibration_reminder_coro()
        assert settings.last_sent_at == now
        db.commit.assert_awaited_once()

    async def test_skips_when_already_handled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """今天该时刻已处理过：不再发送。"""
        _, db, send_mock = _patch(
            monkeypatch,
            now=_TARGET,
            result={"sent": 1, "skipped": 0, "errors": 0, "delivered": 1},
            last_sent_at=_TARGET,
        )
        await scheduler.calibration_reminder_coro()
        send_mock.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_skips_before_target(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未到设定时刻：不发送。"""
        _, db, send_mock = _patch(
            monkeypatch,
            now=_TARGET.replace(hour=9),
            result={"sent": 1, "skipped": 0, "errors": 0, "delivered": 1},
        )
        await scheduler.calibration_reminder_coro()
        send_mock.assert_not_awaited()
        db.rollback.assert_awaited_once()
