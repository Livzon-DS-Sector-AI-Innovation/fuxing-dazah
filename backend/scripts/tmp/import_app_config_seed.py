"""导入应用配置中心种子（Mac/新环境迁移，only-missing 幂等）。

数据源 app_config_seed_20261010.json = Windows 开发机 2026-10-10 导出的
safety.app_config_entries 活行（env→DB 迁移基线：直读开关/推送群/平台
凭证等，.env 中已不再保留这些键）。

用法：cd backend && uv run python scripts/tmp/import_app_config_seed.py
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.safety.models import AppConfigAudit, AppConfigEntry

SEED = Path(__file__).parent / "app_config_seed_20261010.json"


async def main() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    rows = payload["rows"]
    async with async_session_factory() as s:
        existing = {
            r.key
            for r in (
                await s.execute(
                    select(AppConfigEntry).where(AppConfigEntry.is_deleted.is_(False))
                )
            ).scalars()
        }
        created = 0
        for row in rows:
            if row["key"] in existing:
                continue
            s.add(
                AppConfigEntry(
                    key=row["key"],
                    value=row["value"],
                    enabled=True,
                    note=row.get("note") or "迁移种子导入",
                )
            )
            s.add(
                AppConfigAudit(
                    key=row["key"],
                    action="seed",
                    before_json=None,
                    after_json={"value": row["value"], "enabled": True},
                    operator_name="migration-import",
                )
            )
            created += 1
        await s.commit()
    print(f"seed rows={len(rows)} created={created} skipped={len(rows) - created}")


asyncio.run(main())
