"""S6 包内共用：北京时钟与 Bitable 直读 opener 协议。"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Protocol


BJ_TZ = _dt.timezone(_dt.timedelta(hours=8))


def bj_today() -> _dt.date:
    """北京时区今日（调度/留痕统一口径）。"""
    return _dt.datetime.now(_dt.UTC).astimezone(BJ_TZ).date()


class Opener(Protocol):
    """Bitable 直读 opener 协议（与 metrics.py MetricContext.opener 同款）。"""

    def __call__(self, domain: str, kind: str) -> Any: ...
