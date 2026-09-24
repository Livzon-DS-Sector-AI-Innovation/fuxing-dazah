# -*- coding: utf-8 -*-
"""验证撤回票排除：今天(09-22)真机数据 dry-run 日报（不推送、不回写）。"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TARGET = date(2026, 9, 22)


async def main() -> None:
    from app.modules.safety.service.special_op_direct import daily

    result = await daily.run(TARGET, "today", push=False, writeback=False)
    print("report_date:", result.report_date)
    print("total:", result.total)
    print("excluded:", result.excluded)
    print("high / medium / low:", result.high_risk, result.medium_risk, result.low_risk)
    print("effective:", result.total - result.excluded)
    print("logs_analyzed:", len(result.logs_analyzed))
    print("--- markdown 概况段 ---")
    for line in result.markdown_report.splitlines()[:12]:
        print(line)


asyncio.run(main())
