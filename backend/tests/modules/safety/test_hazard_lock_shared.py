"""T06 B4 统一写锁单测（RED 先行）。

验收：①②③⑤ 共用 bitable_repo.WRITE_LOCK；不存在各自新建的进程内锁，
且不同链路的写回在共享锁下串行（Bitable 单表写不支持并发）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.modules.safety.service.hazard_direct import (
    ai_analysis,
    bitable_repo,
    review,
    supervision,
)


def test_review_and_supervision_use_shared_writer_lock() -> None:
    assert review._WRITE_LOCK is bitable_repo.WRITE_LOCK
    assert supervision._WRITE_LOCK is bitable_repo.WRITE_LOCK
    # ① 在 P0-A 已收编，此处一并锁定，防回归
    assert ai_analysis._WRITE_LOCK is bitable_repo.WRITE_LOCK


class _FakeBitable:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def update_record(self, record_id: str, fields: dict[str, Any]) -> bool:
        self.calls.append((record_id, fields))
        return True


async def test_supervision_write_serializes_against_shared_lock() -> None:
    """③ 写回在写锁释放前，其他链路（①/⑤）不得进入临界区。"""
    client = _FakeBitable()
    events: list[tuple[str, float]] = []

    async def probe() -> None:
        events.append(("probe_wait", time.monotonic()))
        async with bitable_repo.WRITE_LOCK:
            events.append(("probe_enter", time.monotonic()))

    async def delayed_probe() -> None:
        await asyncio.sleep(0.05)
        await probe()

    started = time.monotonic()
    await asyncio.gather(
        supervision.writeback_supervision_label(client, "rec1", "红色预警"),
        delayed_probe(),
    )
    assert client.calls == [("rec1", {"督办等级": "红色预警"})]
    probe_enter = dict(events)["probe_enter"]
    # ③ 写锁内固定 sleep 0.5s（Bitable 串行写规避 1254291）；若两链各用一把锁，
    # probe 会在 0.05s 就进入临界区。要求明显晚于 0.05s。
    assert probe_enter - started >= 0.4, (
        "probe 在 supervision 持锁期间进入了临界区 —— 两根链路未共用同一把写锁"
    )
