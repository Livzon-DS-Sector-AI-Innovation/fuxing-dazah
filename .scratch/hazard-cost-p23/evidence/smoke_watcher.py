#!/usr/bin/env python3
"""P2-2 灰度冒烟值守 watcher（单进程版）。

等下一条自然 ① 写回的 agent_triggers 行出现（thread_key=bitable:hazard:*，
近 10 分钟窗口），捕获 triggers/history 端点证据 + 该次审计 token，然后自动
关 trace 开关。用法：uv run python smoke_watcher.py <最长等待秒>。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.getcwd())

BACKEND = Path("/Users/cheris/Agent work/fuxing-dazah/backend")
EV = Path("/Users/cheris/Agent work/fuxing-dazah/.scratch/hazard-cost-p23/evidence")


async def _find_recent_trigger() -> str | None:
    from app.core.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as db:
        row = (
            await db.execute(
                text(
                    """
                    SELECT thread_key FROM superagent.agent_triggers
                    WHERE thread_key LIKE 'bitable:hazard:%'
                      AND received_at >= now() - interval '10 minutes'
                    ORDER BY received_at DESC LIMIT 1
                    """
                )
            )
        ).mappings().first()
        return row["thread_key"] if row else None


async def _recent_audit_lines() -> str:
    from app.core.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT created_at, status, input_tokens, output_tokens,
                           extra->>'bitable_record_id' AS rid
                    FROM safety.ai_call_audits
                    WHERE scenario='hazard_identification'
                      AND created_at >= now() - interval '10 minutes'
                    ORDER BY created_at DESC LIMIT 3
                    """
                )
            )
        ).mappings().all()
        return "\n".join(str(dict(r)) for r in rows)


async def _turn_trace_off() -> str:
    from app.core.database import async_session_factory
    from app.modules.safety.app_config.store import store

    async with async_session_factory() as db:
        await store.set_value(
            db,
            "SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED",
            "false",
            note="P2-2 灰度冒烟值守结束（已捕获写回留痕）",
        )
        await db.commit()
    return "[trace] OFF by watcher"


async def main() -> int:
    max_wait = int(sys.argv[1]) if len(sys.argv) > 1 else 14400
    started = time.monotonic()
    log = EV / "smoke-watcher.log"
    while True:
        hit = await _find_recent_trigger()
        if hit and hit.startswith("bitable:hazard:"):
            import urllib.request

            record_id = hit.split(":", 2)[-1]
            lines = [f"=== {datetime.now(UTC).isoformat()} captured thread_key={hit} ==="]
            for label, url in (
                ("triggers", f"http://localhost:8000/api/v1/platform/superagent/triggers?thread_key={hit}&limit=20"),
                ("history", f"http://localhost:8000/api/v1/platform/superagent/threads/{hit}/history"),
            ):
                try:
                    req = urllib.request.Request(url, headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                        body = resp.read().decode("utf-8", "replace")
                        code = resp.status
                except Exception as exc:  # noqa: BLE001
                    body, code = f"ERROR: {exc}", 0
                out = EV / f"{label}-curl-raw.json"
                out.write_text(body, encoding="utf-8")
                lines.append(f"{label}_http={code} -> {out.name} ({len(body)}B)")
            lines.append("recent audits:")
            lines.append(await _recent_audit_lines())
            lines.append(await _turn_trace_off())
            with open(log, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print("\n".join(lines))
            return 0
        if time.monotonic() - started > max_wait:
            msg = f"WATCH_TIMEOUT after {max_wait}s（trace 仍开，回话处理）"
            with open(log, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
            print(msg)
            return 2
        await asyncio.sleep(60)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
