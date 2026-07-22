"""设备状态日志：区间时长计算纯函数测试。"""

from datetime import datetime, timedelta

from app.core.time import APP_TZ
from app.modules.equipment.service.status_log import compute_status_durations


def _dt(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=APP_TZ)


class TestComputeStatusDurations:
    def test_empty_events(self) -> None:
        assert compute_status_durations([], _dt(1), _dt(2)) == {}

    def test_invalid_range(self) -> None:
        events = [(_dt(1), "开机")]
        assert compute_status_durations(events, _dt(2), _dt(2)) == {}

    def test_single_status_full_range(self) -> None:
        # 基线在范围前，整段都是开机
        events = [(_dt(1), "开机")]
        result = compute_status_durations(events, _dt(2), _dt(3))
        assert result == {"开机": 24 * 3600}

    def test_change_mid_range(self) -> None:
        # 7/2 00:00 起开机，7/2 18:00 停机，统计 7/2 全天
        events = [(_dt(1), "开机"), (_dt(2, 18), "停机")]
        result = compute_status_durations(events, _dt(2), _dt(3))
        assert result == {"开机": 18 * 3600, "停机": 6 * 3600}

    def test_multiple_changes(self) -> None:
        events = [
            (_dt(1), "开机"),
            (_dt(2, 6), "停机"),
            (_dt(2, 12), "开机"),
        ]
        result = compute_status_durations(events, _dt(2), _dt(3))
        assert result == {"开机": (6 + 12) * 3600, "停机": 6 * 3600}

    def test_baseline_mid_range(self) -> None:
        # 设备 7/2 12:00 才创建（首条记录），之前无数据不计入
        events = [(_dt(2, 12), "开机")]
        result = compute_status_durations(events, _dt(2), _dt(3))
        assert result == {"开机": 12 * 3600}

    def test_events_after_range_ignored(self) -> None:
        events = [(_dt(1), "开机"), (_dt(5), "停机")]
        result = compute_status_durations(events, _dt(2), _dt(3))
        assert result == {"开机": 24 * 3600}

    def test_no_events_before_or_in_range(self) -> None:
        # 首条记录在范围之后 → 范围内无数据
        events = [(_dt(5), "开机")]
        assert compute_status_durations(events, _dt(2), _dt(3)) == {}

    def test_total_equals_calendar_when_baseline_before_range(self) -> None:
        events = [
            (_dt(1), "开机"),
            (_dt(2, 3), "停机"),
            (_dt(2, 20), "开机"),
        ]
        result = compute_status_durations(events, _dt(2), _dt(4))
        assert sum(result.values()) == (_dt(4) - _dt(2)).total_seconds()

    def test_sub_hour_precision(self) -> None:
        start = _dt(2)
        events = [(_dt(1), "开机"), (start + timedelta(minutes=90), "停机")]
        result = compute_status_durations(events, start, start + timedelta(hours=3))
        assert result == {"开机": 90 * 60, "停机": 90 * 60}
