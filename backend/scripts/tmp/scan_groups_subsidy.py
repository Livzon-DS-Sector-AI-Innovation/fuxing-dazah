"""全群扫描 09-25~10-26：补贴/监护相关消息与文件（经 lark-cli，只读）。"""

from __future__ import annotations

import asyncio
import json
import sys

CHATS = [
    ("oc_6ee1f8bc933c6ef9ceb431c387eb74ca", "各部门安全员群"),
    ("oc_4ab4a89f7bbb2450f5e0e341bf0f5f10", "特殊作业报备及日报表群"),
    ("oc_ae9c3a305430cb196e42130f69b052bc", "危险品日报"),
    ("oc_d102e1a11eaaa9a1de3b41859de9d0c1", "特殊作业自动分配"),
    ("oc_41750d940a9f37ad022cdd2df57c0ce7", "安全信息化平台试用群"),
    ("oc_726a990558082daafa08acd2452099dd", "机器人测试群"),
    ("oc_f05532603bd7682fc520929c01aca88d", "安全AI创新交流群"),
    ("oc_33f4a492463430d0963deddeeff89402", "福兴安全隐患排查治理"),
]
KEYS = ("补贴", "监护")


async def main() -> int:
    for chat_id, name in CHATS:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "+chat-messages-list",
            "--chat-id", chat_id,
            "--start", "2026-09-25T00:00:00+08:00",
            "--end", "2026-10-26T23:59:59+08:00",
            "--format", "json", "--page-all",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        try:
            data = json.loads(out)
        except Exception:
            print(f"[{name}] parse fail")
            continue
        msgs = (data.get("data") or {}).get("messages") or []
        hits = []
        for m in msgs:
            content = m.get("content") or ""
            if m.get("msg_type") == "file":
                hits.append((m.get("create_time"), "FILE",
                             m.get("sender", {}).get("name"), content[:150]))
            elif any(k in content for k in KEYS):
                hits.append((m.get("create_time"), m.get("msg_type"),
                             m.get("sender", {}).get("name"), content[:150]))
        print(f"[{name}] total={len(msgs)} hits={len(hits)}")
        for h in hits:
            print("  ", *h)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
