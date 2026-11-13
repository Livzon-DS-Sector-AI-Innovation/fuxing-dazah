"""R3 L2 窗口覆写纯函数（二期新接缝 ⑤）—— 处方值优先/默认+2h/上限钳制/当日一次/跨日失效。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Shanghai")


def _now(h: int = 10, m: int = 0) -> datetime:
    return datetime(2026, 11, 12, h, m, tzinfo=_TZ)


def test_compute_new_window_prescription_priority() -> None:
    from app.modules.safety.service.ops_selfheal_r3.window_override import (
        compute_new_window,
    )

    # 处方值优先
    assert compute_new_window((12, 0), {"until_hour": 14, "until_minute": 30}, now=_now()) == (14, 30)
    # 无处方值：默认 +2h
    assert compute_new_window((12, 0), None, now=_now()) == (14, 0)
    assert compute_new_window((12, 0), {}, now=_now()) == (14, 0)
    # 上限钳 23:59（处方 25 点 → 23:59 整体钳；处方 23:70 → 23:59）
    assert compute_new_window((12, 0), {"until_hour": 25}, now=_now()) == (23, 59)
    assert compute_new_window(
        (12, 0), {"until_hour": 23, "until_minute": 70}, now=_now(),
    ) == (23, 59)
    # 默认 +2h 溢出：22:30 → 23:59（绝不回绕缩短——审查 BLOCK#3 锚点）
    assert compute_new_window((22, 30), None, now=_now()) == (23, 59)
    assert compute_new_window((23, 30), None, now=_now()) == (23, 59)
    # 非法处方值回落默认
    assert compute_new_window((12, 0), {"until_hour": "abc"}, now=_now()) == (14, 0)


def test_apply_override_once_per_day() -> None:
    from app.modules.safety.service.ops_selfheal_r3 import window_override

    window_override.reset_overrides()
    try:
        ok1, reason1, new1 = window_override.apply_override(
            "r3win任务", (12, 0), {"until_hour": 15, "until_minute": 0},
        )
        assert ok1 and reason1 == "ok" and new1 == (15, 0)
        # 同 job 当日第二次：拒绝
        ok2, reason2, cur2 = window_override.apply_override(
            "r3win任务", (12, 0), {"until_hour": 20},
        )
        assert not ok2 and reason2 == "already_extended_today" and cur2 == (15, 0)
        # 其他 job 不受影响
        ok3, _, new3 = window_override.apply_override("r3win任务B", (12, 0), None)
        assert ok3 and new3 == (14, 0)
    finally:
        window_override.reset_overrides()


def test_get_override_cross_day_expiry() -> None:
    """apply 写当日 → 查当日命中；查明日（未来日）= 跨日失效。"""
    from datetime import timedelta

    from app.modules.safety.service.ops_selfheal_r3 import window_override

    window_override.reset_overrides()
    try:
        window_override.apply_override("r3win跨日", (12, 0), {"until_hour": 15})
        today = window_override._bj_now().date()
        assert window_override.get_override(
            "r3win跨日", today.isoformat(),
        ) == (15, 0)
        # 跨日失效：明天查询命不中（覆写只存当日）
        assert window_override.get_override(
            "r3win跨日", (today + timedelta(days=1)).isoformat(),
        ) is None
    finally:
        window_override.reset_overrides()


def test_job_window_end_uses_override(monkeypatch) -> None:
    """scan_source.job_window_end 查覆写优先于 SCHEDULED_JOBS 声明（接缝 ⑤）。

    覆写 apply 只存「当日」（_bj_now 动态日期），读口 day 必须与 apply 同日
    才命中——用动态今日，勿硬编码（跨日滚动即失效，2026-11-13 验收实测）。
    """
    from app.modules.safety.service.ops_selfheal_r3 import scan_source, window_override

    window_override.reset_overrides()
    try:
        day = window_override._bj_now().date()
        # 无覆写：声明口径（作业票审核 12:00）
        assert scan_source.job_window_end("作业票审核", day).hour == 12
        # 写覆写 → 15:00
        window_override.apply_override(
            "作业票审核", (12, 0), {"until_hour": 15, "until_minute": 0},
        )
        end = scan_source.job_window_end("作业票审核", day)
        assert (end.hour, end.minute) == (15, 0)
    finally:
        window_override.reset_overrides()
