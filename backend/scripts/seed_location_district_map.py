"""seed_location_district_map.py — location_district_map 初灌（幂等）。

用法（backend 下，需先 alembic upgrade head）：
    .venv/bin/python -m scripts.seed_location_district_map            # 灌入
    .venv/bin/python -m scripts.seed_location_district_map --dry-run  # 只打印计划

数据源：docs/assets/tiji-risk-districts-20261026.json（64 分区名原文）
      + service/facility_map/seed_data.py SEED_SYNONYMS（人工同义词）。
幂等：location_text 上的 partial 唯一索引 + ON CONFLICT DO NOTHING——
重跑零重复、不覆盖既有行（含未来 ai_confirmed 行）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import async_session_factory  # noqa: E402
from app.modules.safety.models.location_district_map import (  # noqa: E402
    LocationDistrictMap,
)
from app.modules.safety.service.facility_map.seed_data import (  # noqa: E402
    seed_rows_from_asset,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_PATH = REPO_ROOT / "docs" / "assets" / "tiji-risk-districts-20261026.json"


async def main(dry_run: bool) -> None:
    doc = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
    rows = seed_rows_from_asset(doc)
    print(f"资产分区 {len(doc.get('districts') or [])} 个 → seed 行 {len(rows)} 行")

    if dry_run:
        for row in rows:
            print(f"  {row['location_text']} -> dist {row['dist_id']}")
        print("dry-run：未写库")
        return

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async with async_session_factory() as session:
        # 逐行 insert（64+ 行量级）＋ ON CONFLICT DO NOTHING：
        # 与唯一索引 (location_text WHERE is_deleted=false) 对齐，幂等重跑。
        inserted = 0
        for row in rows:
            stmt = (
                pg_insert(LocationDistrictMap.__table__)
                .values(
                    id=uuid.uuid4(),
                    location_text=row["location_text"],
                    dist_id=row["dist_id"],
                    source=row["source"],
                )
                .on_conflict_do_nothing(
                    index_elements=["location_text"],
                    index_where=text("is_deleted = false"),
                )
            )
            result = await session.execute(stmt)
            inserted += result.rowcount or 0
        await session.commit()
    print(f"完成：新插入 {inserted} 行（既有文本行保持不动）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="location_district_map 初灌")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划不写库")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
