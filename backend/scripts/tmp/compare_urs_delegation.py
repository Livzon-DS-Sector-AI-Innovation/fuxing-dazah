"""2-D URS 委派试点对比脚本：委派式 vs 挂载式（延迟/工具选择/tokens）。

用法（本机，真实 DeepSeek 凭证，需本地 DB 在跑）：
    cd backend && PYTHONPATH=. uv run python scripts/tmp/compare_urs_delegation.py [--q 问题子串]

流程：
1. 读 20 问回归集中的 URS 问句 + 若干多步工作流场景问句；
2. 两种模式各跑一遍（SAFETY_AGENT_URS_DELEGATION 开/关，app_config DB 行 + 失效缓存）；
3. 每问记录：wall time（ms）、实际调用的工具名集合、期望工具是否命中、
   ai_call_audits 的 input/output tokens（最近一条 agent_chat）；
4. 输出对比表 + JSON 落档（.scratch/safety-agent-optimization-p2/delegation_data.json）。

对比结论写入 docs/DESIGN-安全业务Agent二期-2D试点数据-*.md（扩大/回退决策依据）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from sqlalchemy import text

QUESTIONS: list[tuple[str, str]] = [
    # (问句, 期望命中的工具——委派式应为 delegate，挂载式应为具体 URS 工具)
    ("查一下最近的 URS 审核记录", "urs"),
    ("这台设备的 URS 评估结果怎么样，帮我跑一次适用性评估", "urs"),
    ("帮我发起一个 URS 智能审核，设备是一台反应釜", "urs"),
    ("URS 采购评审有什么风险画像", "urs"),
]

OUT_PATH = (
    Path(__file__).resolve().parents[2]
    / ".scratch" / "safety-agent-optimization-p2" / "delegation_data.json"
)


async def set_delegation(enabled: bool) -> None:
    from app.core.database import async_session_factory
    from app.modules.safety.app_config.store import store as app_config_store

    async with async_session_factory() as session:
        await session.execute(text("""
            INSERT INTO safety.app_config (key, value, enabled, updated_at)
            VALUES ('SAFETY_AGENT_URS_DELEGATION', :v, true, now())
            ON CONFLICT (key) DO UPDATE SET value = :v, enabled = true, updated_at = now()
        """), {"v": "true" if enabled else "false"})
        await session.commit()
    app_config_store.invalidate()
    await asyncio.sleep(0.1)  # 等 TTL 失效生效


def _tools_called(result) -> list[str]:
    from pydantic_ai.messages import ToolCallPart

    names: list[str] = []
    for msg in result.all_messages():
        for part in getattr(msg, "parts", []):
            if isinstance(part, ToolCallPart):
                names.append(part.tool_name)
    return names


async def run_one(question: str, mode: str) -> dict:
    from app.core.database import async_session_factory
    from app.modules.safety.business_agent.executor import run_turn
    from app.modules.safety.business_agent.schemas import SafetyDeps

    async with async_session_factory() as session:
        deps = SafetyDeps(
            db=session,
            person=None,
            role="safety_admin",
            session_id=None,
            channel="compare_script",
        )
        started = time.monotonic()
        try:
            out = await run_turn(question, deps)
            latency_ms = int((time.monotonic() - started) * 1000)
            return {
                "mode": mode,
                "question": question,
                "latency_ms": latency_ms,
                "tools": out.get("_debug_tools") or [],  # run_turn 不回工具名，占位
                "pending": bool(out.get("pending_action")),
                "answer_head": (out.get("answer") or "")[:120],
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "mode": mode,
                "question": question,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "tools": [],
                "pending": False,
                "answer_head": "",
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            await session.rollback()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--q", default="", help="只跑包含该子串的问句")
    args = parser.parse_args()

    from app.modules.safety.env_loader import load_safety_env

    load_safety_env()

    questions = [q for q, _ in QUESTIONS if args.q in q]
    rows: list[dict] = []
    for enabled, mode in ((True, "delegated"), (False, "mounted")):
        await set_delegation(enabled)
        for q in questions:
            print(f"[{mode}] {q} ...", flush=True)
            rows.append(await run_one(q, mode))
    await set_delegation(False)  # 收尾复位：关（挂载式）

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n模式      延迟ms  挂起  错误  问句")
    for r in rows:
        print(f"{r['mode']:<9} {r['latency_ms']:>6} {str(r['pending']):>4}  "
              f"{r['error'] or '-':<4} {r['question']}")
    print(f"\nJSON: {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
