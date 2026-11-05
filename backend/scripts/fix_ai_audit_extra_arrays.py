"""AI 审计 ``extra`` 数组脏行一次性修复（B0 配套工具，默认 dry-run）。

背景
----
B0：``_mark_parse_outcome`` 旧合并式 ``coalesce(extra, cast("{}", JSONB)) || patch``
在 ``extra`` 为 SQL NULL / JSON null（``'null'::jsonb``）时，会把该行 ``extra``
写成数组（``["{}", {...}]`` / ``[null, {...}]``）。代码侧已改为
``jsonb_typeof`` 守护（新回写自愈），**本脚本只用于其它环境已存在的数组脏行**，
做保留式归一：把数组里的 dict 元素按顺序折叠成一个对象（后者覆盖前者），
丢弃 ``null`` / 字符串 / 嵌套数组（它们不承载键值信息）。

安全边界
--------
- **默认 dry-run（只读）**：只 SELECT + 以 JSON 打印统计与样本摘要（便于人工复核）；
- 必须显式 ``--apply`` 才在单事务内 UPDATE（``WHERE jsonb_typeof(extra) = 'array'``
  幂等护栏）；执行前请自行确认已备份 / 有快照；
- 不调 AI、不访问 Bitable、无其它网络请求。

用法（cwd=backend）::

    .venv/bin/python scripts/fix_ai_audit_extra_arrays.py            # dry-run（默认）
    .venv/bin/python scripts/fix_ai_audit_extra_arrays.py --apply    # 执行写库

DSN 解析顺序：``--dsn`` > ``DATABASE_URL`` 环境变量 > ``backend/.env.development``。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

TABLE = "safety.ai_call_audits"
APPLY_SQL = (
    f"UPDATE {TABLE} "
    "SET extra = $2::jsonb "
    "WHERE id = $1::uuid AND jsonb_typeof(extra) = 'array'"
)


# ═══════════════════════════════════════════════════════════════
# 纯函数（可单测，不碰 DB）
# ═══════════════════════════════════════════════════════════════


def fold_extra_array(value: Any) -> dict[str, Any]:
    """把错误写成数组的 ``extra`` 保留式折叠为对象。

    规则：按数组顺序折叠 ``dict`` 元素（后者覆盖前者）；``None`` / 字符串 /
    嵌套数组一律丢弃（不含键值信息）；空数组 → ``{}``；非数组输入 → ``{}``。
    """
    if not isinstance(value, list):
        return {}
    folded: dict[str, Any] = {}
    for item in value:
        if isinstance(item, dict):
            folded.update(item)
    return folded


def plan_fixes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SELECT 结果 → 待修复清单（只保留 ``extra`` 确实是数组的行）。

    Args:
        rows: ``[{"id": str, "extra": <JSON 文本/对象>}, ...]``

    Returns:
        ``[{"id", "before": list, "after": dict}, ...]``
    """
    plans: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get("extra")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                continue
        else:
            parsed = raw
        if not isinstance(parsed, list):
            continue
        plans.append(
            {
                "id": str(row["id"]),
                "before": parsed,
                "after": fold_extra_array(parsed),
            }
        )
    return plans


def _resolve_dsn(explicit: str = "") -> str:
    """DSN：显式参数 > DATABASE_URL 环境变量 > backend/.env.development。

    与 ``scripts/hazard_ai_quality_replay.py`` 的 DSN 链保持同一优先级；
    两个脚本刻意各自独立（不互相 import，避免脚本运行入口耦合），
    改动优先级/转换规则时须两处同步。
    """
    if explicit:
        return explicit
    env_url = os.environ.get("DATABASE_URL", "").strip()
    if env_url:
        return env_url
    env_file = Path(".env.development")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return ""


def _to_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ═══════════════════════════════════════════════════════════════
# DB 访问（dry-run 只读 / --apply 单事务写）
# ═══════════════════════════════════════════════════════════════


async def fetch_array_rows(dsn: str, *, limit: int) -> list[dict[str, Any]]:
    """只读查询 ``jsonb_typeof(extra)='array'`` 的审计行。"""
    import asyncpg  # type: ignore[import-untyped]

    conn = await asyncpg.connect(_to_asyncpg_dsn(dsn))
    try:
        await conn.execute("SET default_transaction_read_only = on")
        records = await conn.fetch(
            f"""
            SELECT id::text AS id, extra::text AS extra, created_at
            FROM {TABLE}
            WHERE jsonb_typeof(extra) = 'array'
            ORDER BY created_at
            LIMIT $1
            """,
            limit,
        )
        return [dict(record) for record in records]
    finally:
        await conn.close()


async def apply_fixes(dsn: str, plans: list[dict[str, Any]]) -> int:
    """单事务执行修复（带 ``jsonb_typeof='array'`` 幂等护栏），返回更新行数。"""
    import asyncpg

    conn = await asyncpg.connect(_to_asyncpg_dsn(dsn))
    try:
        updated = 0
        async with conn.transaction():
            for plan in plans:
                payload = json.dumps(plan["after"], ensure_ascii=False)
                status = await conn.execute(APPLY_SQL, plan["id"], payload)
                # asyncpg execute 返回 "UPDATE <rows>"
                updated += int(status.rsplit(" ", 1)[-1])
        return updated
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI 审计 extra 数组脏行一次性修复（默认 dry-run，只读）"
    )
    parser.add_argument("--apply", action="store_true", help="实际写库（默认只读演练）")
    parser.add_argument("--dsn", default="", help="PG DSN（默认读 DATABASE_URL / .env.development）")
    parser.add_argument("--limit", type=int, default=1000, help="最多扫描行数（默认 1000）")
    args = parser.parse_args(argv)

    dsn = _resolve_dsn(args.dsn)
    if not dsn:
        print("未找到数据库 DSN（--dsn / DATABASE_URL / .env.development）", file=sys.stderr)
        return 2

    rows = asyncio.run(fetch_array_rows(dsn, limit=max(1, args.limit)))
    plans = plan_fixes(rows)
    applied = asyncio.run(apply_fixes(dsn, plans)) if (args.apply and plans) else 0
    report: dict[str, Any] = {
        "table": TABLE,
        "mode": "apply" if args.apply else "dry-run",
        "array_rows_scanned": len(rows),
        "fixable_rows": len(plans),
        "updated_rows": applied,
        "samples": [
            {"id": plan["id"], "before": plan["before"], "after": plan["after"]}
            for plan in plans[:3]
        ],
        "note": (
            "运行期已由 jsonb_typeof 守护自愈；本脚本用于其它环境既存数组脏行的保留式归一。"
        ),
    }
    if len(rows) >= max(1, args.limit):
        report["warning"] = (
            "扫描行数达到 --limit 上限，可能仍有未处理的数组脏行；请增大 --limit 重跑"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
