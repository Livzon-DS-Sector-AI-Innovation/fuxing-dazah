"""本地播种 + 校验脚本（一次性，.scratch 不入库）。

把 backend/.env.development 当前 SAFETY_ 值固化进 safety.app_config_entries
（only-missing 幂等），供 .env 收尾（清空迁移键）前先行落库。
"""

import asyncio

from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.safety.app_config.store import store
from app.modules.safety.models import AppConfigEntry


async def main() -> None:
    seeded = await store.seed_from_env()
    print("seeded:", seeded)
    async with async_session_factory() as s:
        rows = (
            await s.execute(
                select(AppConfigEntry).where(AppConfigEntry.is_deleted.is_(False))
            )
        ).scalars().all()
        print("active rows:", len(rows))
        for r in sorted(rows, key=lambda x: x.key):
            v = r.value[:24] + "…" if len(r.value) > 24 else r.value
            print(f"  {r.key} = {v}  (note={r.note})")


asyncio.run(main())
