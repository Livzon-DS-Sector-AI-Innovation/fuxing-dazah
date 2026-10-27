"""facility_map_unmapped_report.py — 近 N 天作业票/报警映射覆盖摸底。

用法（backend 下）：
    .venv/bin/python -m scripts.facility_map_unmapped_report           # 默认近 7 天
    .venv/bin/python -m scripts.facility_map_unmapped_report --days 14

输出逐日：作业票/消防/中控三路命中与未映射事件数、未映射率（事件口径）；
末尾汇总 + 未映射文本 Top20（补充同义词/AI 建议映射的输入料）。
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


async def main(days: int) -> None:
    today = bj_today()
    unmapped_texts: Counter[str] = Counter()
    tot = {
        "job": [0, 0],
        "fire": [0, 0],
        "central": [0, 0],
        "key_risk": [0, 0],
    }  # [mapped, unmapped]

    async with async_session_factory() as session:
        svc = open_pins_service(session=session)
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            payload = await svc.get_pins(day)
            if payload["errors"]:
                print(f"{day} 数据源降级: {payload['errors']}")
            mapped_jobs = sum(sum(p["jobs"].values()) for p in payload["pins"])
            mapped_fire = sum(p["alarms"]["fire"] for p in payload["pins"])
            mapped_central = sum(p["alarms"]["central"] for p in payload["pins"])
            mapped_kr = sum(p.get("key_risks", 0) for p in payload["pins"])
            per_kind = {"job": 0, "fire": 0, "central": 0, "key_risk": 0}
            for u in payload["unmapped"]:
                for kind in u["kinds"]:
                    per_kind[kind] += u["count"]
                unmapped_texts[u["text"]] += u["count"]
            tot["job"][0] += mapped_jobs
            tot["job"][1] += per_kind["job"]
            tot["fire"][0] += mapped_fire
            tot["fire"][1] += per_kind["fire"]
            tot["central"][0] += mapped_central
            tot["central"][1] += per_kind["central"]
            tot["key_risk"][0] += mapped_kr
            tot["key_risk"][1] += per_kind["key_risk"]
            total_events = mapped_jobs + mapped_fire + mapped_central + mapped_kr + sum(per_kind.values())
            unmapped_all = sum(per_kind.values())
            rate = f"{unmapped_all / total_events * 100:.0f}%" if total_events else "—"
            print(
                f"{day}: 票 {mapped_jobs}+{per_kind['job']}未 | 消防 {mapped_fire}+{per_kind['fire']}未"
                f" | 中控 {mapped_central}+{per_kind['central']}未"
                f" | 关键风险 {mapped_kr}+{per_kind['key_risk']}未 | 未映射率 {rate}"
            )

    print(f"\n=== 近 {days} 天汇总（命中+未映射） ===")
    for kind, label in (
        ("job", "作业票"),
        ("fire", "消防"),
        ("central", "中控"),
        ("key_risk", "关键风险作业"),
    ):
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
