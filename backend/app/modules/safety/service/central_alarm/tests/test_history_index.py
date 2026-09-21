"""Ticket 03：AI 历史上下文内存索引（HistoryIndex）单测。

语义与 analyst._load_history_context 的 ORM 查询逐字一致：
- 同 workshop + 同 post（不含 line 条件，保持旧口径）；
- 本周计数不含本条；上周同期为上一完整自然周；
- 最近 5 条（按 alarm_date 倒序，含全部索引数据）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.safety.service.central_alarm.analyst import HistoryIndex
from app.modules.safety.service.central_alarm.reader import CentralAlarmView

_BJ = timedelta(hours=8)


def _view(
    record_id: str,
    *,
    alarm_date_bj: datetime,
    workshop: str = "车间一",
    post: str = "DCS 内操",
    description: str = "高高压力报警",
) -> CentralAlarmView:
    return CentralAlarmView(
        id=record_id,
        feishu_record_id=record_id,
        alarm_date=alarm_date_bj - _BJ,  # 存 UTC
        workshop=workshop,
        post=post,
        alarm_description=description,
    )


def _bj(y: int, mo: int, d: int, h: int = 8) -> datetime:
    return datetime(y, mo, d, h, tzinfo=UTC)  # 标 UTC，构造时再减 8h


async def test_context_counts_same_week_and_last_week() -> None:
    # 目标：2026-09-16（周三，北京）。本周 = 09-14 ~ 09-20；上周 = 09-07 ~ 09-13。
    target = _view("t", alarm_date_bj=datetime(2026, 9, 16, 10, tzinfo=UTC))
    records = [
        _view("a", alarm_date_bj=datetime(2026, 9, 15, 9, tzinfo=UTC)),   # 本周
        _view("b", alarm_date_bj=datetime(2026, 9, 14, 9, tzinfo=UTC)),   # 本周（周一）
        _view("c", alarm_date_bj=datetime(2026, 9, 10, 9, tzinfo=UTC)),   # 上周
        _view("d", alarm_date_bj=datetime(2026, 9, 5, 9, tzinfo=UTC)),    # 更早
        # 不同岗位 / 不同车间，不计入
        _view("e", alarm_date_bj=datetime(2026, 9, 15, 9, tzinfo=UTC),
              post="外操"),
        _view("f", alarm_date_bj=datetime(2026, 9, 15, 9, tzinfo=UTC),
              workshop="车间二"),
    ]
    index = HistoryIndex(records)
    payload: dict[str, Any] = json.loads(index.context_for(target))
    assert payload["本周同岗位报警数(不含本条)"] == 2
    assert payload["上一完整自然周报警数"] == 1
    assert payload["workshop"] == "车间一"
    assert payload["post"] == "DCS 内操"


async def test_context_recent_five_desc() -> None:
    target = _view("t", alarm_date_bj=datetime(2026, 9, 16, 10, tzinfo=UTC))
    records = [
        _view(f"r{i}", alarm_date_bj=datetime(2026, 9, 16 - i, 9, tzinfo=UTC),
              description=f"desc-{i}")
        for i in range(7)
    ]
    index = HistoryIndex(records)
    payload = json.loads(index.context_for(target))
    recent = payload["最近报警"]
    assert len(recent) == 5
    assert all("desc-" in r for r in recent)
    # 倒序：最新（09-16 09:00，desc-0）在前
    assert "desc-0" in recent[0]
    assert "desc-4" in recent[4]


async def test_context_excludes_twin_object_of_same_id() -> None:
    """直读编排里日报窗口与索引是两次拉取——同一条 Bitable 记录是两个不同对象。

    「本周计数不含本条」必须按 id 排除（对象身份比较会漏排除，审查 M1）。
    """
    dt = datetime(2026, 9, 16, 10, tzinfo=UTC)
    target = _view("twin", alarm_date_bj=dt)
    twin_in_index = _view("twin", alarm_date_bj=dt)  # 同 id 不同对象
    other = _view("o", alarm_date_bj=datetime(2026, 9, 15, 9, tzinfo=UTC))
    index = HistoryIndex([twin_in_index, other])
    payload = json.loads(index.context_for(target))
    assert payload["本周同岗位报警数(不含本条)"] == 1  # 只数 other，不含 twin


async def test_context_for_record_not_in_index() -> None:
    index = HistoryIndex([])
    target = _view("t", alarm_date_bj=datetime(2026, 9, 16, 10, tzinfo=UTC))
    payload = json.loads(index.context_for(target))
    assert payload["本周同岗位报警数(不含本条)"] == 0
    assert payload["最近报警"] == []
