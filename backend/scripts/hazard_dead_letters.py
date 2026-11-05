"""F8 死信只读查询脚本 —— 隐患AI识别失败记录的人工处理入口。

用途：
    读取 ``safety:hazard:ai:dead_letters``（HASH，field=record_id）并打印
    top-N 死信明细（record_id / 分类 / 失败次数 / 死信时间 / 最近原因），
    供运维人工排查，不必手敲 redis-cli。

安全边界（只读）：
    - 仅 HGETALL 死信 hash，**不写库、不调 AI、不访问 Bitable、无其它网络请求**；
    - 不修改 attempts/退避状态；清理死信仍需走既有 ``failure_ledger.clear``
      或运维流程（本脚本不提供写操作）。

用法（cwd=backend）::

    .venv/bin/python scripts/hazard_dead_letters.py
    .venv/bin/python scripts/hazard_dead_letters.py --limit 50
    .venv/bin/python scripts/hazard_dead_letters.py --category api_error
    .venv/bin/python scripts/hazard_dead_letters.py --json

import 期不解析 Redis 客户端（``app.core.redis`` 只在 CLI 入口惰性 import），
便于离线单测注入 FakeRedis。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

# 允许从 backend/ 目录直接运行（与既有 scripts 一致）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.safety.service.hazard_direct.failure_ledger import (  # noqa: E402
    DEAD_LETTERS_KEY,
    RedisLike,
    format_dead_letter_lines,
    list_dead_letters,
)

DEFAULT_LIMIT = 50
# 死信 hash 理论容量小（≤ 记录总数，7 天 TTL）；先全量取出再按 category 过滤，
# 避免「先截断后过滤」导致 --category 查不到已存在的死信。
_SCAN_LIMIT = 10_000


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="隐患AI识别死信只读查询（top-N 明细，不写任何数据）"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"最多展示条数（默认 {DEFAULT_LIMIT}）",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="按失败分类过滤（如 api_error / json_invalid / placeholder_basis）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 数组输出（便于管道处理）",
    )
    return parser


def render_dead_letters(items: list[dict[str, Any]], *, as_json: bool = False) -> str:
    """把死信清单渲染成 CLI 输出文本（纯函数，便于单测）。"""
    if as_json:
        return json.dumps(items, ensure_ascii=False, indent=2)
    if not items:
        return f"无死信记录（{DEAD_LETTERS_KEY} 为空）。"
    lines = [f"死信清单共 {len(items)} 条（只读，key={DEAD_LETTERS_KEY}）："]
    lines.extend(format_dead_letter_lines(items, limit=len(items)))
    return "\n".join(lines)


async def fetch_dead_letters(
    *,
    redis: RedisLike | None = None,
    limit: int = DEFAULT_LIMIT,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """只读取死信清单（category 过滤在截断前，top-N 在过滤后）。"""
    items = await list_dead_letters(limit=_SCAN_LIMIT, redis=redis)
    if category:
        items = [item for item in items if item.get("category") == category]
    return items[: max(0, int(limit))]


async def main(
    argv: Sequence[str] | None = None, *, redis: RedisLike | None = None
) -> int:
    """脚本主逻辑（``redis`` 可注入 FakeRedis 做离线单测）。"""
    args = _build_parser().parse_args(argv)
    items = await fetch_dead_letters(
        redis=redis, limit=args.limit, category=args.category
    )
    print(render_dead_letters(items, as_json=args.json))
    return 0


async def _cli() -> int:
    """CLI 入口：此处才惰性解析 Redis 客户端，import 期无连接副作用。"""
    from app.core.redis import redis_client

    try:
        return await main(redis=cast(RedisLike, redis_client))
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_cli()))
