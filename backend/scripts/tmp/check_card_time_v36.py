# -*- coding: utf-8 -*-
"""只读今日速递总卡的 create_time / update_time，确认原地 PATCH。"""
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MSG_ID = "om_x100b6428174eacb4b4cba0df9c83034"


async def main() -> None:
    import httpx

    from app.modules.safety.feishu.client import get_safety_tenant_token

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{MSG_ID}?msg_type=interactive",
            headers={"Authorization": f"Bearer {token}"},
        )
    d = resp.json()
    item = d["data"]["items"][0]
    bjt = timedelta(hours=8)

    def to_bjt(ms: str) -> str:
        return (datetime.fromtimestamp(int(ms) / 1000, tz=UTC) + bjt).strftime(
            "%m-%d %H:%M:%S"
        )

    print("创建(北京):", to_bjt(item["create_time"]))
    print("更新(北京):", to_bjt(item["update_time"]))


asyncio.run(main())
