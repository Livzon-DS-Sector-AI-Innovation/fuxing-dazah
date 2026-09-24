# -*- coding: utf-8 -*-
"""真机验证：今日安全速递总卡内容是否已是 V3.6 新规则版。"""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MSG_KEY = "safety:daily_digest:card:2026-09-22"


async def main() -> None:
    import httpx

    from app.core.redis import get_redis
    from app.modules.safety.feishu.client import get_safety_tenant_token

    store = await get_redis()
    msg_id = await store.get(MSG_KEY)
    print("Redis 中的总卡 message_id:", msg_id)

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{msg_id}?msg_type=interactive",
            headers={"Authorization": f"Bearer {token}"},
        )
    d = resp.json()
    if d.get("code") != 0:
        print("API 错误:", d.get("code"), d.get("msg"))
        return
    item = d["data"]["items"][0]
    print("卡片创建时间(毫秒时间戳):", item.get("create_time"), "更新时间:", item.get("update_time"))
    content = item.get("body", {}).get("content", "")
    print("包含新统计「高风险 **9**」:", "高风险 **9**" in content)
    print("包含 RTO 明细(新规则命中项):", "RTO现场" in content)
    print("包含 V3.6 理由文案:", "动火作业涉及高风险区域" in content)
    card = json.loads(content)
    print("卡片元素数:", len(card.get("elements", [])))


asyncio.run(main())
