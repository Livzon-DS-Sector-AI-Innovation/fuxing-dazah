# -*- coding: utf-8 -*-
import asyncio, json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\Agent Work\fuxing-dazah\backend")

async def main():
    from app.core.redis import get_redis
    store = await get_redis()
    raw = await store.hget("safety:daily_digest:2026-09-21", "fire_alarm_weekly")
    cell = json.loads(raw)
    d = cell["detail"]
    print("含明细板块:", "**各部门报警明细与整改要求**" in d)
    print("含AI覆盖行:", "AI 分析覆盖" in d)
    print("----")
    print(d)

asyncio.run(main())
