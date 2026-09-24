# -*- coding: utf-8 -*-
"""验证今日安全速递总卡中消防报警周报格子是否写入。"""
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def main() -> None:
    from app.core.redis import get_redis

    store = await get_redis()
    key = f"safety:daily_digest:{date.today().isoformat()}"
    raw = await store.hget(key, "fire_alarm_weekly")
    if raw is None:
        print("未找到 fire_alarm_weekly 格子!")
        print("已有格子:", await store.hkeys(key))
        return
    cell = json.loads(raw)
    print("✅ 格子已写入今日总卡")
    print("title:", cell.get("title"))
    print("stats:", cell.get("stats"))
    print("zone:", cell.get("zone"))
    print("detail 长度:", len(cell.get("detail", "")), "字符")
    msg_id = await store.get(f"safety:daily_digest:card:{date.today().isoformat()}")
    print("总卡 message_id:", msg_id)


asyncio.run(main())
