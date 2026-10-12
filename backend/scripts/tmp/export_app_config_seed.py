"""导出本地 safety.app_config_entries 活行为 JSON（Mac 迁移种子，一次性）。

输出 backend/scripts/tmp/app_config_seed_20261010.json，由
import_app_config_seed.py 在新环境导入（only-missing）。
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.safety.models import AppConfigEntry


async def main() -> None:
    async with async_session_factory() as s:
        rows = (
            await s.execute(
                select(AppConfigEntry).where(AppConfigEntry.is_deleted.is_(False))
            )
        ).scalars().all()
        data = [
            {"key": r.key, "value": r.value, "note": r.note}
            for r in sorted(rows, key=lambda x: x.key)
        ]
    out = Path(__file__).parent / "app_config_seed_20261010.json"
    out.write_text(
        json.dumps({"exported_at": "2026-10-10", "rows": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"exported {len(data)} rows -> {out}")


asyncio.run(main())
