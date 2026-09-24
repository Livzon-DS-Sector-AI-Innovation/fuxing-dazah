# -*- coding: utf-8 -*-
"""打印今日速递总卡 GET 到的原始 content，核对 PATCH 是否生效。"""
import asyncio
import json
import sys
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
    content = item.get("body", {}).get("content", "")
    print("content 长度:", len(content))
    print("---- content 前 3000 字符 ----")
    print(content[:3000])
    print("---- 结构 keys ----")
    try:
        card = json.loads(content)
        print("顶层 keys:", list(card.keys()))
        if "elements" in card:
            print("elements 数:", len(card["elements"]))
            for i, el in enumerate(card["elements"]):
                print(f"  element[{i}] tag:", el.get("tag"))
    except Exception as exc:
        print("JSON 解析失败:", exc)


asyncio.run(main())
