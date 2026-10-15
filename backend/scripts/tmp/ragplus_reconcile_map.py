"""ragplus_doc_map 对账工具 — 引擎真实状态 → 映射表归位。

背景：入库脚本每轮只等待 30 分钟，引擎慢解析期未完成的行会被标
failed("轮询超时")；且 ragplus 文档列表 API 每次只回最新 100 条
（KBDocument.id desc），大库 (>100) 下脚本无法经 API 看到全部文档
状态。本工具直读引擎 MySQL（只读）按 file_name↔document.name 对齐，
把 DONE 归位 active、FAIL 标真失败、非终态行注明「非失败」。
配合 ragplus-overview 的 parsing/failed 拆分，页面统计恒真。

用法（backend 目录下；引擎 MySQL 经 docker exec 只读，容器名可覆盖）：

    PYTHONPATH=. uv run python scripts/tmp/ragplus_reconcile_map.py            # 干跑预览
    PYTHONPATH=. uv run python scripts/tmp/ragplus_reconcile_map.py --apply    # 写入归位
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

# RAGFlow document.run 数字码（DocRunStatus）
RUN_MAP = {"3": "DONE", "4": "FAIL", "1": "RUNNING", "0": "UNSTART", "2": "CANCEL"}

DEFAULT_MYSQL_CONTAINER = "docker-mysql-1"


def _load_engine_status(mysql_container: str, dataset_id: str) -> dict[str, str]:
    """引擎 MySQL 只读：{name: 归一状态}。密码取 ragflow 部署目录 .env。"""
    env_path = Path.home() / "Agent work/ragflow-src/docker/.env"
    pw = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("MYSQL_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
                break
    if not pw:
        raise SystemExit("未找到 ragflow MYSQL_PASSWORD（ragflow-src/docker/.env）")
    q = f"SELECT name, run FROM rag_flow.document WHERE kb_id='{dataset_id}';"
    raw = subprocess.run(
        [
            "docker", "exec", mysql_container, "mysql", "-uroot", f"-p{pw}", "-N",
            "--default-character-set=utf8mb4", "-e", q,
        ],
        capture_output=True,
    ).stdout.decode("utf-8", errors="replace")
    status: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        name, _, run = line.rpartition("\t")
        status[name.strip()] = RUN_MAP.get(run.strip(), run.strip())
    return status


async def main(apply: bool, mysql_container: str, domain: str) -> int:
    from app.core.database import async_session_factory
    from app.modules.safety.knowledge.ragplus_client import get_ragplus_client
    from app.modules.safety.models import RagplusDocMap

    # 名单内第一个库即目标 dataset（regulation 域对应「安全法规标准」）
    client = get_ragplus_client()
    kbs = await client.list_datasets()
    await client.aclose()
    from app.modules.safety.app_config.store import store as app_store

    names = [n.strip() for n in (app_store.get_str("SAFETY_RAGPLUS_DATASET_NAMES") or "").replace("，", ",").split(",") if n.strip()]
    target = "MSDS" if domain == "msds" else "安全法规标准"
    if target not in names:
        print(f"名单 {names} 不含 {target}")
        return 2
    ds = next(kb["id"] for kb in kbs if kb.get("name") == target)

    engine_status = _load_engine_status(mysql_container, ds)
    print(f"引擎 {target}: {len(engine_status)} 文档 | DONE={sum(1 for v in engine_status.values() if v == 'DONE')}")

    stats = {"flipped": 0, "in_flight": 0, "fails": 0, "kept": 0, "missing": 0, "no_doc": 0}
    async with async_session_factory() as s:
        rows = (await s.execute(select(RagplusDocMap).where(
            RagplusDocMap.domain == domain, RagplusDocMap.is_deleted.is_(False),
        ))).scalars().all()
        for r in rows:
            if not r.kb_doc_id:
                stats["no_doc"] += 1
                continue
            run = engine_status.get((r.file_name or "").strip())
            if run == "DONE":
                if r.status != "active":
                    if apply:
                        r.status = "active"
                        r.synced_at = datetime.now(UTC)
                        r.last_error = None
                    stats["flipped"] += 1
                else:
                    stats["kept"] += 1
            elif run == "FAIL":
                if apply:
                    r.status = "failed"
                    r.last_error = "引擎解析失败（扫描件 OCR 阶段，重试或人工处理）"
                stats["fails"] += 1
            elif run in ("RUNNING", "UNSTART", "CANCEL"):
                label = {"RUNNING": "引擎解析中", "UNSTART": "引擎排队中", "CANCEL": "已取消"}[run]
                if apply:
                    r.last_error = f"{label}（非失败，完成后对账归位）"
                stats["in_flight"] += 1
            else:
                stats["missing"] += 1
        if apply:
            await s.commit()
    print(
        f"对账({'APPLY' if apply else 'DRY-RUN'}): 新归位={stats['flipped']} "
        f"解析中/排队={stats['in_flight']} 真失败={stats['fails']} "
        f"原active={stats['kept']} 无记录={stats['missing']} 无档待重传={stats['no_doc']}"
    )
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ragplus_doc_map 引擎状态对账归位")
    ap.add_argument("--apply", action="store_true", help="写入（默认 dry-run）")
    ap.add_argument("--domain", choices=["regulation", "msds"], default="regulation")
    ap.add_argument("--mysql-container", default=DEFAULT_MYSQL_CONTAINER)
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.apply, args.mysql_container, args.domain)))
