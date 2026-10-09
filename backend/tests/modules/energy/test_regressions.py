"""本次修复的回归守卫：这些 bug 复现时都是静默的数据错误，不会报错。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.energy.adapters.platform_a import _fetch_meter_data
from app.modules.energy.repository import _soft_delete_rename
from app.modules.energy.service import _cst_date


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """只实现 _fetch_meter_data 需要的 post()，固定返回一页数据。"""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    async def post(self, url: str, data: dict[str, str]) -> _FakeResponse:
        payload = {"syncData": self._records, "nCount": len(self._records)}
        return _FakeResponse(f"<string>{json.dumps(payload)}</string>")


async def test_hour_mode_only_takes_the_target_date_and_hour() -> None:
    """小时模式拉的是 3 天窗口，必须只取目标日那一条。

    只比小时（不比日期）会把三天的同一小时累加，使每小时读数约 3 倍虚高。
    """
    records = [
        {"POSTDATE": "2026/9/21 10:00:00", "AANALOGFLOW": 1.0},
        {"POSTDATE": "2026/9/22 10:00:00", "AANALOGFLOW": 2.0},
        {"POSTDATE": "2026/9/23 10:00:00", "AANALOGFLOW": 3.0},
        {"POSTDATE": "2026/9/23 11:00:00", "AANALOGFLOW": 99.0},
    ]
    values = await _fetch_meter_data(
        _FakeClient(records),  # type: ignore[arg-type]
        "M1",
        "2026-09-21",
        "2026-09-24",
        target_hour=datetime(2026, 9, 23, 10),
        api_url="http://example.invalid",
    )
    assert values == {10: 3.0}


def test_soft_delete_rename_never_overflows_the_column() -> None:
    """改名列宽：即使业务键已经顶满列宽也不能溢出（曾用完整 uuid 撑爆 varchar(50)）。"""
    row_id = uuid4()
    for max_length in (50, 100):
        renamed = _soft_delete_rename("x" * max_length, row_id, max_length)
        assert len(renamed) <= max_length
    assert _soft_delete_rename("electricity", row_id, 50).startswith("electricity__del_")


def test_cst_date_converts_utc_back_to_china_date() -> None:
    """timestamptz 读回来是 UTC：00:30 CST 必须算作当天，而不是前一天。"""
    # 2026-09-24 00:30 CST == 2026-09-23 16:30 UTC
    assert _cst_date(datetime(2026, 9, 23, 16, 30, tzinfo=UTC)) == datetime(2026, 9, 24).date()
    # naive 值按 UTC 解释，不能当作已经是 CST
    assert _cst_date(datetime(2026, 9, 23, 16, 30)) == datetime(2026, 9, 24).date()
