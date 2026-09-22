"""本地 emergency_drill 镜像回填（emergency-drill-direct Ticket 06）。

本地 PG 镜像可能陈旧/为空，双路径比对前先从 Bitable 直读回填：

- 按 feishu_record_id upsert（幂等，重复执行收敛）；
- 只写映射字段全集（mapped_field_keys，附件=store 路径推算）——
  「全量归一」照 contractor 教训：包含置 None，不把残留旧值带进比对；
- 平台专属列（eval_source_record_file_token/created_by 等）不碰：
  update 分支不写，insert 分支保持默认；
- 采集表（DrillCollectionRecord）不回填——业务解析态只在平台库（spec D2）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/backfill_emergency_drill_mirror.py

退出码：0 成功；2 连接未配置；3 拉取失败。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

sys.path.insert(0, ".")


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import EmergencyDrillRecord
    from app.modules.safety.service.emergency_drill_direct.reader import open_reader
    from app.modules.safety.service.emergency_drill_direct.views import (
        mapped_field_keys,
    )

    views = await open_reader().fetch_all(strict=True)
    keys = mapped_field_keys()
    print(f"直读 {len(views)} 行，映射键 {len(keys)} 个")

    inserted = updated = 0
    async with async_session_factory() as session:
        rows = list((await session.scalars(
            select(EmergencyDrillRecord).where(
                EmergencyDrillRecord.is_deleted == False,  # noqa: E712
            )
        )).all())
        by_fid = {r.feishu_record_id: r for r in rows if r.feishu_record_id}

        for view in views:
            row = by_fid.get(view.id)
            if row is None:
                row = EmergencyDrillRecord(
                    feishu_record_id=view.id,
                    is_deleted=False,
                )
                session.add(row)
                inserted += 1
            else:
                updated += 1
            for key in keys:
                setattr(row, key, getattr(view, key, None))
        await session.commit()

    print(f"回填完成：insert={inserted} update={updated}"
          f" @ {datetime.now(tz=UTC).isoformat()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"[x] {exc}")
        sys.exit(3)
