"""手动刷新安全速递总卡的隐患督办格子（一次性，直读多维表格现算）。"""

import asyncio
import json

CHAT_ID = "oc_f05532603bd7682fc520929c01aca88d"  # 安全AI创新交流群


async def main() -> None:
    from app.modules.safety.service.hazard_direct.bulletin import send_bulletin

    stats = await send_bulletin(CHAT_ID)
    print("send_bulletin stats:", json.dumps(stats, ensure_ascii=False))


asyncio.run(main())
