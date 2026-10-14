"""干跑外来人员保险预警（只读不推送）：直读 → 口径 → 格子预览。"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    from app.modules.safety.service.visitor_insurance.report import (
        build_warning_result,
        build_cell,
    )

    result = await build_warning_result()
    cell = build_cell(result)
    print("=" * 60)
    print(f"[{result.today}] tag={cell.tag_color}#{cell.tag_text} {cell.title}")
    print(f"stats: {cell.stats}")
    print(f"zone:   {cell.zone}")
    print("-" * 60)
    print(cell.detail)
    print("=" * 60)
    print(
        f"扫描 {result.total_notices} 条 / 在厂 {result.active_notices} 条 / "
        f"过期 {len(result.expired)} / 临期 {len(result.soon)} / "
        f"缺失 {len(result.missing)} 家单位 "
        f"{sum(g.people for g in result.missing)} 人"
    )


if __name__ == "__main__":
    asyncio.run(main())
