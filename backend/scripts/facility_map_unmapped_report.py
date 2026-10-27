"""facility_map_unmapped_report.py — 近 N 天各源地点映射覆盖摸底。

用法（backend 下）：
    .venv/bin/python -m scripts.facility_map_unmapped_report           # 默认近 7 天
    .venv/bin/python -m scripts.facility_map_unmapped_report --days 14

输出逐日：作业票/消防/中控/关键风险/超储/隐患/消防设施到期各路命中与未映射
事件数、未映射率（事件口径）；末尾汇总 + 未映射文本 Top20（补充同义词/
AI 建议映射的输入料）。超储/未整改隐患/消防设施到期为当前态快照，仅当日行
有数（历史日零贡献）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import async_session_factory  # noqa: E402
from app.modules.safety.service.facility_map.service import (  # noqa: E402
    bj_today,
    open_pins_service,
)

_KINDS = (
    ("job", "作业票"),
    ("fire", "消防"),
    ("central", "中控"),
    ("key_risk", "关键风险作业"),
    ("over_limit", "超储物料"),
    ("hazard_new", "今日新增隐患"),
    ("hazard_open", "未整改隐患"),
    ("fire_ext_due", "消防设施到期"),
)
# 各 kind 对应 DistrictPin 计数字段（命中口径）
_COUNT_FIELD = {
    "job": lambda p: sum(p["jobs"].values()),
    "fire": lambda p: p["alarms"]["fire"],
    "central": lambda p: p["alarms"]["central"],
    "key_risk": lambda p: p.get("key_risks", 0),
    "over_limit": lambda p: p.get("over_limits", 0),
    "hazard_new": lambda p: p.get("hazard_news", 0),
    "hazard_open": lambda p: p.get("hazard_opens", 0),
    "fire_ext_due": lambda p: p.get("fire_ext_dues", 0),
}


async def main(days: int) -> None:
    today = bj_today()
    unmapped_texts: Counter[str] = Counter()
    tot: dict[str, list[int]] = {kind: [0, 0] for kind, _ in _KINDS}  # [mapped, unmapped]

    async with async_session_factory() as session:
        svc = open_pins_service(session=session)
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            payload = await svc.get_pins(day)
            if payload["errors"]:
                print(f"{day} 数据源降级: {payload['errors']}")
            mapped = {
                kind: sum(_COUNT_FIELD[kind](p) for p in payload["pins"])
                for kind, _ in _KINDS
            }
            per_kind: dict[str, int] = {kind: 0 for kind, _ in _KINDS}
            for u in payload["unmapped"]:
                for kind in u["kinds"]:
                    per_kind[kind] += u["count"]
                unmapped_texts[u["text"]] += u["count"]
            parts = []
            for kind, _ in _KINDS:
                tot[kind][0] += mapped[kind]
                tot[kind][1] += per_kind[kind]
                if mapped[kind] or per_kind[kind]:
                    parts.append(f"{kind} {mapped[kind]}+{per_kind[kind]}未")
            total_events = sum(mapped.values()) + sum(per_kind.values())
            unmapped_all = sum(per_kind.values())
            rate = f"{unmapped_all / total_events * 100:.0f}%" if total_events else "—"
            print(f"{day}: {' | '.join(parts)} | 未映射率 {rate}")

    print(f"\n=== 近 {days} 天汇总（命中+未映射；超储/未整改隐患/消防设施到期=当日当前态） ===")
    for kind, label in _KINDS:
        hit, miss = tot[kind]
        all_events = hit + miss
        rate = f"{miss / all_events * 100:.0f}%" if all_events else "—"
        print(f"{label}: 命中 {hit} / 未映射 {miss} / 未映射率 {rate}")
    all_hit = sum(v[0] for v in tot.values())
    all_miss = sum(v[1] for v in tot.values())
    all_events = all_hit + all_miss
    print(
        f"合计: 命中 {all_hit} / 未映射 {all_miss} / 总未映射率 "
        f"{all_miss / all_events * 100:.0f}%" if all_events else "无事件"
    )
    print("\n未映射文本 Top20:")
    for text, count in unmapped_texts.most_common(20):
        print(f"  {count:4d}  {text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="近 N 天地点映射覆盖摸底")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    asyncio.run(main(args.days))
