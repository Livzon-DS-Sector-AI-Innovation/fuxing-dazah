"""ragplus 检索 10 问抽检 — 一期质量验收（命中质量 + 耗时 P95<2s）。

走与三壳完全相同的通道（RagplusClient + dataset 名单 + 重排），逐问
记录 top1/top3 命中（法规名+条款定位+相似度）与耗时，结果落档
仓库 .scratch/ragplus-switch-p1/抽检10问.md。

用法（backend 目录，需已完成入库且 token 已入 app_config）：

    PYTHONPATH=. uv run python scripts/tmp/ragplus_smoke_10q.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

QUESTIONS: list[dict[str, str]] = [
    {"q": "动火作业前需要满足什么条件才能开工？", "expect": "GB 30871 特殊作业"},
    {"q": "受限空间作业的气体检测氧含量合格范围是多少？", "expect": "GB 30871 受限空间"},
    {"q": "隐患整改的期限一般隐患和重大隐患分别是多少天？", "expect": "隐患排查治理规定"},
    {"q": "危险化学品重大危险源如何辨识分级？", "expect": "GB 18218 / 危化品重大危险源辨识"},
    {"q": "高处作业分级标准中几米以上属于高处作业？", "expect": "GB 30871 / 高处作业"},
    {"q": "临时用电作业需要办理什么手续？", "expect": "GB 30871 临时用电"},
    {"q": "吊装作业按起重量如何分级管理？", "expect": "GB 30871 吊装"},
    {"q": "生产经营单位的安全生产主体责任主要包括哪些？", "expect": "安全生产法"},
    {"q": "职业健康体检岗前岗中离岗有什么要求？", "expect": "职业病防治法"},
    {"q": "动火作业分级中固定动火区和一级二级动火如何区分？", "expect": "GB 30871 动火分级"},
]

SCRATCH_DIR = Path(__file__).resolve().parents[3] / ".scratch" / "ragplus-switch-p1"


async def main() -> int:
    from app.modules.safety.knowledge.ragplus_client import get_ragplus_client

    client = get_ragplus_client()
    rows: list[dict] = []
    latencies: list[float] = []

    for item in QUESTIONS:
        t0 = time.perf_counter()
        try:
            hits = await client.search(item["q"], top_k=5)
        except Exception as exc:
            latencies.append(time.perf_counter() - t0)
            rows.append({**item, "error": str(exc)[:200], "hits": []})
            continue
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)
        rows.append({
            **item,
            "elapsed_ms": round(elapsed * 1000),
            "n_hits": len(hits),
            "hits": [
                {
                    "doc": h.doc_name,
                    "ref": (h.content[:60] + "…") if h.content else "",
                    "page": h.page,
                    "similarity": round(h.similarity, 3),
                }
                for h in hits[:3]
            ],
        })
        top = hits[0] if hits else None
        print(
            f"  [{elapsed*1000:6.0f}ms] {item['q'][:24]}… → "
            f"{len(hits)} 命中 | top1: {top.doc_name[:44] if top else '（无）'}"
        )
    await client.aclose()

    lat = sorted(latencies)
    p95 = lat[int(len(lat) * 0.95) - 1] if lat else 0
    mean = sum(lat) / len(lat) if lat else 0

    lines = [
        "# ragplus 检索 10 问抽检（一期质量验收）",
        "",
        f"- 耗时：mean={mean*1000:.0f}ms / P95={p95*1000:.0f}ms（出口标准 P95<2000ms）",
        "",
        "| # | 问题 | 期望 | 耗时ms | 命中数 | top1 法规 | top1 相似度 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        top = (r.get("hits") or [{}])[0]
        lines.append(
            f"| {i} | {r['q']} | {r['expect']} | {r.get('elapsed_ms', '-')} "
            f"| {r.get('n_hits', 0)} | {top.get('doc', r.get('error', '')[:40])} "
            f"| {top.get('similarity', '-')} |"
        )
    lines += ["", "## 命中明细（top3）", ""]
    lines.append("```json")
    lines.append(json.dumps(rows, ensure_ascii=False, indent=1))
    lines.append("```")
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    out = SCRATCH_DIR / "抽检10问.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"落档：{out}  P95={p95*1000:.0f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
