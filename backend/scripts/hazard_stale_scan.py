"""P3-1 T02 —— 隐患登记表 stale 候选全表只读扫描（dry-run，零写）。

取数全表 + 分类全走 ``stale_state`` 纯逻辑（双指纹 vs Redis 基线），产出
分组报告：input_changed（可重算）/ ai_edited（人工保护）/ fresh / no_baseline。
无基线的存量记录不判定——stale 治理只覆盖部署后 ① 写回过的记录。

用法（cwd=backend）::

    .venv/bin/python scripts/hazard_stale_scan.py \
        --out ../.scratch/hazard-stale-c7/evidence/stale-scan-report.md
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.getcwd())


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="../.scratch/hazard-stale-c7/evidence/stale-scan-report.md",
        help="Markdown 报告输出路径",
    )
    args = parser.parse_args()

    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard_direct import stale_state

    client = SafetyBitableClient()
    records = await client.list_all_records(strict=True)
    result = await stale_state.scan_records(records)

    lines = [
        "# P3-1 stale 候选扫描报告（只读 dry-run）",
        "",
        f"- 扫描时间：{datetime.now(UTC).isoformat()}｜全表 {result.total} 条",
        f"- fresh {result.fresh}｜no_baseline {result.no_baseline}"
        f"（无基线不判定=历史存量/Redis 清空）",
        "",
        f"## input_changed（人工改输入→可重算，{len(result.input_changed)} 条）",
        "",
        "| record_id | 编号 | 描述 |",
        "|---|---|---|",
    ]
    for c in result.input_changed:
        desc = c.description.replace("|", "／")
        lines.append(f"| {c.record_id} | {c.hazard_no or '—'} | {desc} |")
    lines += [
        "",
        f"## ai_edited（人工改 AI 列→保护清单，永不自动重跑，"
        f"{len(result.ai_edited)} 条）",
        "",
        "| record_id | 编号 | 描述 |",
        "|---|---|---|",
    ]
    for c in result.ai_edited:
        desc = c.description.replace("|", "／")
        lines.append(f"| {c.record_id} | {c.hazard_no or '—'} | {desc} |")
    lines.append("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {out.resolve()}")
    print(
        f"全表 {result.total}｜fresh={result.fresh} "
        f"input_changed={len(result.input_changed)} "
        f"ai_edited={len(result.ai_edited)} no_baseline={result.no_baseline}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
