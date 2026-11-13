"""R3 L2 job_window_extend 当日覆写 —— 进程内 dict（2026-11-12 质询拍板）。

语义（质询拍板）：
- 处方值优先：LLM 处方可带 args.until_hour/until_minute；无处方值默认 +2h；
- 上限钳 23:59；同 job 当日只允许改 1 次（防反复拉长）；
- 重启即失效 = 天然「仅当日」（零 schema 改动，不触碰 SCHEDULED_JOBS 声明）。

窗口口径接入：``apply_override`` 在 ``job_window_end`` 查 SCHEDULED_JOBS
声明前优先命中覆写（scan_source.job_window_end 是唯一读口）。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")

#: 默认延长时长（小时；无处方值时）
DEFAULT_EXTEND_HOURS = 2

#: 一键执行幂等键（进程内当日覆写；job_name → {date, until_h, until_m}）
_OVERRIDES: dict[str, dict[str, int]] = {}
_LOCK = threading.Lock()


def _bj_now() -> datetime:
    return datetime.now(_TZ)


def reset_overrides() -> None:
    """清空覆写（测试钩子；生产无调用方）。"""
    with _LOCK:
        _OVERRIDES.clear()


def get_override(job_name: str, day_iso: str) -> tuple[int, int] | None:
    """读当日覆写（跨日自动失效；返回 (until_hour, until_minute) 或 None）。"""
    with _LOCK:
        ov = _OVERRIDES.get(job_name)
    if ov is None or ov.get("date") != day_iso:
        return None
    return int(ov.get("until_h", 23)), int(ov.get("until_m", 59))


def compute_new_window(
    current: tuple[int, int], args: dict[str, Any] | None, *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """处方值优先 + 默认 +2h + 上限钳 23:59（纯函数，单测锚点）。

    处方值解析：until_hour/until_minute 一起给才有效（缺任一回落默认）；
    只给 until_hour 时 minute 按 0。溢出一律钳 23:59——延长只可能把窗口
    推到当日末，绝不允许回绕缩短（审查 BLOCK#3；总分钟比较避免 .hour 回绕）。
    """
    now = now or _bj_now()
    args = args or {}

    def _default_plus2h() -> tuple[int, int]:
        total = current[0] * 60 + current[1] + DEFAULT_EXTEND_HOURS * 60
        if total >= 24 * 60 - 1:  # ≥23:59 → 钳当日末
            return 23, 59
        return divmod(total, 60)

    raw_h, raw_m = args.get("until_hour"), args.get("until_minute")
    if raw_h is None or raw_m is None:
        if raw_h is not None and raw_m is None:
            try:
                h, m = int(raw_h), 0  # type: ignore[arg-type]
            except (TypeError, ValueError):
                h, m = _default_plus2h()
        else:
            h, m = _default_plus2h()
    else:
        try:
            h, m = int(raw_h), int(raw_m)
        except (TypeError, ValueError):
            h, m = _default_plus2h()
    if h > 23 or h < 0:
        h, m = 23, 59
    m = max(0, min(59, m))
    h = max(0, min(23, h))
    return h, m


def apply_override(
    job_name: str, current: tuple[int, int], args: dict[str, Any] | None,
) -> tuple[bool, str, tuple[int, int] | None]:
    """写入当日覆写（同 job 当日 1 次限制）。

    Returns:
        (是否成功, 原因/说明, 新窗口 (h, m) 或 None)。
    """
    now = _bj_now()
    day_iso = now.date().isoformat()
    with _LOCK:
        existing = _OVERRIDES.get(job_name)
        if existing is not None and existing.get("date") == day_iso:
            cur = (int(existing.get("until_h")), int(existing.get("until_m")))
            return False, "already_extended_today", cur
        new_hm = compute_new_window(current, args, now=now)
        _OVERRIDES[job_name] = {
            "date": day_iso, "until_h": new_hm[0], "until_m": new_hm[1],
        }
    logger.info("R3 L2 窗口覆写: job=%s → %02d:%02d（当日）", job_name, *new_hm)
    return True, "ok", new_hm
