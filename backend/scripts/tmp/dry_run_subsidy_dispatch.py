"""监护补贴月报真实链路 dry 验证：真拉台账+真解析收件人，截获发送不外发。"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.modules.safety.service import subsidy_dispatch  # noqa: E402


async def main() -> int:
    intercepted_cards: list = []
    intercepted_files: list = []

    async def fake_card(open_id, title, content, **kw):
        intercepted_cards.append((open_id, title, content[:120]))
        return "om_dry"

    async def fake_file(uid, data, name, **kw):
        intercepted_files.append((uid, len(data), name))
        return True

    subsidy_dispatch.send_user_card = fake_card
    subsidy_dispatch.send_file_to_chat = fake_file

    stats = await subsidy_dispatch.run_monthly_subsidy_dispatch(year=2026, month=9)
    print("stats =", stats)
    for uid, title, content in intercepted_cards:
        print(f"[CARD] {uid} | {title}\n       {content}")
    for uid, size, name in intercepted_files:
        print(f"[FILE] {uid} | {size}B | {name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
