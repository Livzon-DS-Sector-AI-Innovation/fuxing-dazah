"""④ 督办通报值守轮询的单元测试。

纯内存桩验证，不依赖 Redis / 飞书网络：
- 窗口判定（周四 13:00 含 - 18:00 不含，北京时间）；
- 值守轮次：窗口外 / 总卡关闭不动作；内容与速递格子一致不投递；
  有差异或格子缺失才投递（复用 deliver_bulletin，不重复拉表）。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.modules.safety.feishu import daily_digest
from app.modules.safety.service.hazard_direct import bulletin, bulletin_watch

# 2026-10-15 是周四
_THU = datetime(2026, 10, 15)


def _bj(d: datetime) -> datetime:
    return d


# ── 窗口判定 ─────────────────────────────────────────────────────


def test_in_window_thursday_afternoon() -> None:
    assert bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 15, 13, 0)))
    assert bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 15, 15, 30)))
    assert bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 15, 17, 59)))


def test_outside_window() -> None:
    assert not bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 15, 12, 59)))
    assert not bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 15, 18, 0)))
    assert not bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 15, 18, 1)))
    assert not bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 15, 9, 0)))
    # 非周四（2026-10-14 周三 / 2026-10-16 周五）
    assert not bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 14, 15, 0)))
    assert not bulletin_watch.in_watch_window(_bj(datetime(2026, 10, 16, 15, 0)))


# ── 值守轮次 ─────────────────────────────────────────────────────


def _patch_watch_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    content: str = "【隐患督办通报】新内容",
    cell_detail_value: str | None = None,
    digest_on: bool = True,
) -> tuple[list[str], list[tuple[str, dict]]]:
    """桩掉拉表/Redis/投递；返回（build 调用记录, deliver 调用记录）。"""
    build_calls: list[str] = []
    deliver_calls: list[tuple[str, dict]] = []

    async def fake_build() -> tuple[str, dict]:
        build_calls.append(content)
        return content, {"total": 7, "sent": False}

    async def fake_cell_detail(d: object, key: str, **kw: object) -> str | None:
        assert key == bulletin_watch.CELL_KEY
        return cell_detail_value

    async def fake_deliver(
        c: str, stats: dict, chat_id: str | None = None,
    ) -> dict:
        deliver_calls.append((c, stats))
        return {**stats, "sent": True}

    monkeypatch.setattr(bulletin, "build_bulletin", fake_build)
    monkeypatch.setattr(bulletin, "deliver_bulletin", fake_deliver)
    monkeypatch.setattr(daily_digest, "cell_detail", fake_cell_detail)
    monkeypatch.setattr(daily_digest, "digest_enabled", lambda: digest_on)
    return build_calls, deliver_calls


async def test_watch_once_skips_outside_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_calls, deliver_calls = _patch_watch_deps(monkeypatch)
    result = await bulletin_watch.run_bulletin_watch_once(
        now=datetime(2026, 10, 15, 12, 30),
    )
    assert result is None
    assert build_calls == [] and deliver_calls == []


async def test_watch_once_skips_when_digest_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_calls, deliver_calls = _patch_watch_deps(monkeypatch, digest_on=False)
    result = await bulletin_watch.run_bulletin_watch_once(
        now=datetime(2026, 10, 15, 14, 0),
    )
    assert result is None
    assert build_calls == [] and deliver_calls == []


async def test_watch_once_no_change_no_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_calls, deliver_calls = _patch_watch_deps(
        monkeypatch, content="内容A", cell_detail_value="内容A",
    )
    result = await bulletin_watch.run_bulletin_watch_once(
        now=datetime(2026, 10, 15, 14, 0),
    )
    assert result is None
    assert build_calls == ["内容A"]
    assert deliver_calls == []


async def test_watch_once_change_delivers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_calls, deliver_calls = _patch_watch_deps(
        monkeypatch, content="内容B", cell_detail_value="内容A",
    )
    result = await bulletin_watch.run_bulletin_watch_once(
        now=datetime(2026, 10, 15, 14, 0),
    )
    assert result == {"total": 7, "sent": True}
    assert build_calls == ["内容B"]
    assert deliver_calls == [("内容B", {"total": 7, "sent": False})]


async def test_watch_once_missing_cell_delivers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """格子不存在（如 13:00 周任务失败）→ 值守首轮补投。"""
    _, deliver_calls = _patch_watch_deps(
        monkeypatch, content="内容A", cell_detail_value=None,
    )
    result = await bulletin_watch.run_bulletin_watch_once(
        now=datetime(2026, 10, 15, 13, 1),
    )
    assert result is not None and result["sent"] is True
    assert len(deliver_calls) == 1


# ── daily_digest.cell_detail ─────────────────────────────────────


class _FakeStore:
    def __init__(self, raw: str | None) -> None:
        self.raw = raw

    async def hget(self, key: str, field: str) -> str | None:
        return self.raw


async def test_cell_detail_roundtrip_and_missing() -> None:
    cell = json.dumps({"detail": "通报正文", "title": "隐患督办通报"})
    got = await daily_digest.cell_detail(
        _bj(datetime(2026, 10, 15)).date(), "hazard_bulletin",
        store=_FakeStore(cell),
    )
    assert got == "通报正文"
    assert await daily_digest.cell_detail(
        _bj(datetime(2026, 10, 15)).date(), "hazard_bulletin",
        store=_FakeStore(None),
    ) is None
    assert await daily_digest.cell_detail(
        _bj(datetime(2026, 10, 15)).date(), "hazard_bulletin",
        store=_FakeStore("{bad json"),
    ) is None
