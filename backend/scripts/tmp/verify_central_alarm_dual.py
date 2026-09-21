"""Ticket 06 验证套件：双路径逐字比对 + 零回写探针（只读 + AI 降级口径）。

对最近 N 天逐日：
  - 直读路径：open_reader().get_records_by_rolling_window(D) → 过滤 → 聚合 → 渲染
  - 镜像路径：CentralAlarmService._get_records_by_rolling_window(D) → 同上
  - 两份 markdown（ai_summary=None，纯数据版）逐字比对；
  - 零回写探针：SafetyBitableClient 全部写方法替换为哨兵，任何写调用即失败退出。

已知可解释差异（比对时人工归因，不算失败）：
  - 镜像表同步延迟/事件丢失导致的记录数差异（首行 total 打印用于归因）；
  - 镜像记录带历史 ai_* 值（渲染不使用 → 不影响纯数据版 markdown）。

用法（backend 目录）：.venv/Scripts/python.exe scripts/tmp/verify_central_alarm_dual.py --days 3
退出码：0 全部一致；1 存在差异；2 探针触发写调用。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

from app.modules.safety.service.central_alarm.aggregator import (  # noqa: E402
    aggregate_daily,
)
from app.modules.safety.service.central_alarm.reader import (  # noqa: E402
    open_reader,
    rolling_window,
)
from app.modules.safety.service.central_alarm.renderer import (  # noqa: E402
    render_daily_report,
)
from app.modules.safety.service.central_alarm.service import (  # noqa: E402
    CentralAlarmService,
    _filter_high_high_alarms,
)

# ── 零回写探针：写方法哨兵 ──
_WRITE_CALLS: list[str] = []
_WRITE_METHODS = (
    "update_records", "create_records", "batch_create_records",
    "batch_update_records", "update_record", "create_record",
    "delete_records", "batch_delete_records", "create_field", "update_field",
)


def _install_write_sentry() -> None:
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    def _make(name: str) -> object:
        async def _sentry(*args: object, **kwargs: object) -> object:
            _WRITE_CALLS.append(name)
            raise RuntimeError(f"零回写探针：直读路径调用了写方法 {name}")
        return _sentry

    for name in _WRITE_METHODS:
        setattr(SafetyBitableClient, name, _make(name))  # type: ignore[attr-defined]


def _strip_ai(records: list) -> list:
    """归一化：清零历史 AI 字段（直读恒 None；已拍板 AI 不落盘，两侧同口径比对原生字段）；
    并按记录键排序（镜像 ORM 查询无 ORDER BY、顺序不定；直读表内倒序——
    集合内容一致时明细顺序差异属可解释，排序后比对内容）。"""
    out = []
    for r in records:
        r.ai_alarm_type = None
        r.ai_pattern = None
        r.ai_dimension = None
        out.append(r)
    out.sort(key=lambda r: (
        r.alarm_date or datetime.min.replace(tzinfo=UTC),
        r.workshop or "", r.post or "", r.alarm_description or "",
    ))
    return out


async def _direct_markdown(day) -> tuple[str, int, set[str]]:
    reader = open_reader()
    start, end = rolling_window(day)
    records = await reader.fetch_window_records(start_utc=start, end_utc=end)
    ids = {r.id for r in records}
    records = _strip_ai(_filter_high_high_alarms(records))
    agg = aggregate_daily(records, day)
    return render_daily_report(
        agg, None,
        window_start_utc=start.astimezone(UTC),
        window_end_utc=end.astimezone(UTC),
    ), agg.total, ids


async def _mirror_markdown(day) -> tuple[str, int, set[str]]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        service = CentralAlarmService(session)
        records, ws, we = await service._get_records_by_rolling_window(day)
        ids = {str(r.feishu_record_id) for r in records}
        records = _strip_ai(_filter_high_high_alarms(records))
        agg = aggregate_daily(records, day)
        return render_daily_report(
            agg, None, window_start_utc=ws, window_end_utc=we,
        ), agg.total, ids


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()

    _install_write_sentry()

    today = (datetime.now(UTC) + timedelta(hours=8)).date()
    mismatch = 0
    for offset in range(1, args.days + 1):
        day = today - timedelta(days=offset)
        try:
            dm, dt_total, d_ids = await _direct_markdown(day)
        except Exception as exc:
            print(f"[{day}] 直读路径失败: {exc!r}")
            mismatch += 1
            continue
        try:
            mm, mm_total, m_ids = await _mirror_markdown(day)
        except Exception as exc:
            print(f"[{day}] 镜像路径失败: {exc!r}")
            mismatch += 1
            continue
        if d_ids != m_ids:
            print(f"[{day}] 记录集差异: 直读多={sorted(d_ids - m_ids)}"
                  f" 镜像多={sorted(m_ids - d_ids)}")
        if dm == mm:
            print(f"[{day}] OK  total={dt_total}（直读与镜像一致）")
        else:
            mismatch += 1
            print(f"[{day}] DIFF direct_total={dt_total} mirror_total={mm_total}")
            dl, ml = dm.splitlines(), mm.splitlines()
            shown = 0
            for i in range(max(len(dl), len(ml))):
                a = dl[i] if i < len(dl) else "<EOF>"
                b = ml[i] if i < len(ml) else "<EOF>"
                if a != b:
                    print(f"    line {i + 1}:")
                    print(f"      D: {a[:120]}")
                    print(f"      M: {b[:120]}")
                    shown += 1
                    if shown >= 3:
                        break

    if _WRITE_CALLS:
        print(f"[x] 零回写探针触发：写调用 {_WRITE_CALLS}")
        return 2
    print(f"零回写探针通过（直读路径写调用=0），比对完成：{args.days} 天，差异 {mismatch} 天")
    return 0 if mismatch == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
