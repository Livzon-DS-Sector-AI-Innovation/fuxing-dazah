"""四/五/六部监护补贴台账端到端真实验证（拉数 → build_ledger_plan → calculate）。

只读。对每个台账源输出 2026-09 计划统计、跳过/待核对明细、按监护人汇总金额。
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.modules.safety.service.subsidy import (  # noqa: E402
    SubsidyService,
    b_cert_adjusted_total,
)
from app.modules.safety.service.subsidy_dept_ledgers import (  # noqa: E402
    LEDGER_SOURCES,
    build_ledger_plan,
    fetch_ledger_rows,
)


async def main() -> int:
    year, month = 2026, 9
    for source in LEDGER_SOURCES:
        rows = await fetch_ledger_rows(source)
        plan = build_ledger_plan(source, rows, year, month)
        print(f"\n{'=' * 70}\n[{source.department}] 总行数={plan.total_tickets} "
              f"计入={plan.matched_tickets} 待核对={plan.unmatched_tickets}"
              f"({len(plan.unmatched)}人) 跳过={plan.skipped_tickets}")

        if plan.skipped:
            print("跳过明细:")
            for s in plan.skipped:
                print(f"  - {s.ticket_no} [{s.ticket_type}] {s.reason}")
        if plan.unmatched:
            print("待核对(未登级别,暂按A证):")
            for u in plan.unmatched:
                print(f"  - {u.name} {u.ticket_count}行 {'、'.join(u.operation_types)}")

        result = SubsidyService.calculate(plan.records, year=year, month=month)
        print(f"计算后明细 {len(result.details)} 条; "
              f"B证折算后实发合计 {b_cert_adjusted_total(result.details):.2f} 元")
        print("按监护人汇总(折算前):")
        for s in result.summaries:
            print(f"  - {s.guardian_name}({s.guardian_level}) 合计 {s.total:.0f} 元")

        # 抽样 3 条明细看解析正确性
        for d in result.details[:3]:
            print(f"  样例: {d.guardian_name} {d.operation_type}{d.operation_level} "
                  f"{d.start_time[5:16]}~{d.end_time[11:16]} "
                  f"间隔{d.interval_hours}h 实算{d.adjusted_hours}h "
                  f"{d.billing_units}{d.billing_unit_label}={d.subsidy_amount}元 "
                  f"备注[{d.remark}]")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
