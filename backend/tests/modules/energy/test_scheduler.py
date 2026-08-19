from __future__ import annotations

from datetime import datetime

from app.modules.energy.collect_settings import CST
from app.modules.energy.scheduler import _within_collect_window


def _at(day: int, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 8, day, hh, mm, ss, tzinfo=CST)


def test_collect_window_before_trigger():
    assert _within_collect_window(_at(19, 11, 0), "11:30") is False


def test_collect_window_at_trigger():
    assert _within_collect_window(_at(19, 11, 30), "11:30") is True


def test_collect_window_within_grace():
    assert _within_collect_window(_at(19, 11, 32), "11:30") is True


def test_collect_window_grace_upper_bound_exclusive():
    # 11:35 整点（触发时间 + 5 分钟宽限）已过窗口
    assert _within_collect_window(_at(19, 11, 35), "11:30") is False
    # 11:34:59 仍在窗口内
    assert _within_collect_window(_at(19, 11, 34, 59), "11:30") is True


def test_collect_window_well_past_trigger():
    assert _within_collect_window(_at(19, 14, 0), "11:30") is False


def test_collect_window_invalid_trigger_time():
    assert _within_collect_window(_at(19, 11, 30), "abc") is False
