"""seed_standard_check.py — 主安全库建「体系标准核查表」+ 播 55 条标准 + 登记连接。

用法（backend 下）：
    .venv/bin/python -m scripts.seed_standard_check            # 建表+播种+登记连接
    .venv/bin/python -m scripts.seed_standard_check --dry-run  # 只打印计划不动飞书

幂等：
- 表按名查找，已存在复用（不重复建）；
- 行按「标准编号」upsert（已有行更新条款/依据等字段，缺失行新增）；
- 连接按 goals/standard_check 覆写（app_token=主安全库）。

清单事实源：app/modules/safety/service/standard_check/seed_data.py（DESIGN 附录 A）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402
from app.modules.safety.service.standard_check import seed_data  # noqa: E402

# 主安全库（隐患/外来人员等 6 个连接共用的 base；2026-10-21 用户拍板）
MAIN_APP_TOKEN = "Ea0abVsMzacU5VsF4K5cBH0kngb"


def _bj_year() -> str:
    return str((datetime.now(UTC) + timedelta(hours=8)).year)


async def ensure_table(client: SafetyBitableClient, *, dry_run: bool) -> str | None:
    tables = await client.list_tables()
    existing = next((t for t in tables if t.get("name") == seed_data.TABLE_NAME), None)
    if existing:
        print(f"[1/3] 表已存在，复用: {existing['table_id']}")
        return str(existing["table_id"])
    if dry_run:
        print("[1/3] dry-run：将新建表（15 列）")
        return None
    created = await client.create_table(seed_data.table_schema())
    if not created or not created.get("table_id"):
        raise SystemExit("建表失败（见上方日志）")
    print(f"[1/3] 建表成功: {created['table_id']}")
    return str(created["table_id"])


async def seed_rows(client: SafetyBitableClient, table_id: str, *, dry_run: bool) -> None:
    year = _bj_year()
    client.table_id = table_id
    existing = await client.list_all_records(
        field_names=["标准编号"], strict=True
    )
    by_no = {
        (r.get("fields") or {}).get("标准编号"): r.get("record_id")
        for r in existing
        if (r.get("fields") or {}).get("标准编号")
    }
    to_create = [s for s in seed_data.STANDARDS if s["no"] not in by_no]
    to_update = [s for s in seed_data.STANDARDS if s["no"] in by_no]
    print(f"[2/3] 播种 {year} 年清单：新增 {len(to_create)} / 更新 {len(to_update)}"
          f"（表内已有 {len(by_no)} 行）")
    if dry_run:
        return
    for s in to_create:
        await client.create_record(fields=seed_data.row_fields(s, year))
    for s in to_update:
        await client.update_record(
            record_id=str(by_no[s["no"]]),
            fields=seed_data.row_fields(s, year),
        )


async def register_connection(table_id: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[3/3] dry-run：将登记连接 goals/standard_check → {MAIN_APP_TOKEN}/{table_id}")
        return
    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        await store.set_connection(
            db,
            seed_data.DOMAIN,
            seed_data.KIND,
            {
                "app_token": MAIN_APP_TOKEN,
                "table_id": table_id,
                "note": f"体系标准核查表（播种脚本 {datetime.now(UTC).date()} 建立与登记）",
            },
            operator_name="seed_standard_check",
        )
        await db.commit()
    store.invalidate(seed_data.DOMAIN)
    print(f"[3/3] 连接已登记: goals/standard_check → {MAIN_APP_TOKEN}/{table_id}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不动飞书/DB")
    args = parser.parse_args()

    client = SafetyBitableClient(app_token=MAIN_APP_TOKEN, table_id=None)
    table_id = await ensure_table(client, dry_run=args.dry_run)
    if table_id is None and not args.dry_run:
        return
    if table_id:
        await seed_rows(client, table_id, dry_run=args.dry_run)
        await register_connection(table_id, dry_run=args.dry_run)
    print("完成：goals 页将自动转 live（刷新即出数）")


if __name__ == "__main__":
    asyncio.run(main())
