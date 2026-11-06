"""① 检索评测 — P1-1 R5 检索评测基线（只读）。

对比两种检索策略在同一评测集上的表现：
- ``baseline``：描述原文单路 top_k（改造前行为）；
- ``multi``：``build_retrieval_queries`` 多路 + RRF 合并取 top_k（P1-1 新行为，
  与 ① 线上 ``_load_knowledge_context`` 同一事实源）。

指标：recall@k（弱标签命中）、平均检索路数、上下文长度代理（markdown 字符数）、
improved（基线漏检而多路命中的条目数 —— 方向目标口径）。

弱标签口径（grill.md 拍板 8）：
- 成功样本（197 GT）：``basis_new`` 引用法规 = 「应召回」弱标签（来源=模型引用）；
- 失败样本（57 条）：``suggest_weak_labels`` 聚类建议弱标签（**待业务复核**）；
- 无弱标签条目不计入 recall 分母。

安全边界：
- 只读：审计查询 ``SET default_transaction_read_only = on``；检索走生产
  ``SafetyKnowledgeRetriever``（ragplus search / 本地 SELECT），不写业务库；
- 不调 AI、不访问 Bitable。注：走生产 retriever 即含 RAG 缓存读写（Redis、
  TTL 1h；key 含 target_chunks，与线上 8-chunk 键不冲突）。

用法（cwd=backend）::

    # 1) 生成评测快照（/tmp 历史样本 + 审计描述，只读；/tmp 缺失时报错退出）
    .venv/bin/python scripts/hazard_retrieval_eval.py --build-snapshot \
        --out ../.scratch/hazard-retrieval-quality/eval/snapshot.jsonl

    # 2) 跑评测（真库只读；--limit 控量，--source 过滤来源）
    .venv/bin/python scripts/hazard_retrieval_eval.py \
        --snapshot ../.scratch/hazard-retrieval-quality/eval/snapshot.jsonl \
        --limit 60 --source failure_57
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

# 允许从 backend/ 目录直接运行（与 hazard_ai_quality_replay 同款）
sys.path.insert(0, os.getcwd())

from app.modules.safety.knowledge.retriever import (  # noqa: E402
    KnowledgeContext,
    SafetyKnowledgeRetriever,
)
from app.modules.safety.service.hazard_direct import (  # noqa: E402
    retrieval_query as rq,
)

SCENARIO = "hazard_identification"
RERUN_FILE = Path("/tmp/rerun_results.jsonl")
FAILURE_FILE = Path("/tmp/failure_retrieval.json")

# ═══════════════════════════════════════════════════════════════
# 纯函数（可单测，不碰 DB / 网络）
# ═══════════════════════════════════════════════════════════════

_DESC_LINE_RE = re.compile(r"^\s*隐患描述[：:]\s*(.+)$", re.MULTILINE)


def extract_description_from_prompt(prompt_text: str | None) -> str | None:
    """审计 prompt 文本 → 隐患描述（``隐患描述：`` 行；缺失返回 None）。"""
    if not prompt_text:
        return None
    match = _DESC_LINE_RE.search(prompt_text)
    if match is None:
        return None
    text = match.group(1).strip()
    return text or None


def normalize_name(name: str) -> str:
    """法规/文档名归一：去空白/书名号/文件后缀/下划线，小写拉丁。"""
    text = name.strip()
    text = re.sub(r"《|》", "", text)
    text = re.sub(r"\.(pdf|docx?|xlsx?)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\s_\-—·+]+", "", text)
    return text.lower()


def doc_matches_label(doc: str, labels: list[str]) -> bool:
    """弱标签命中：归一后互为包含（doc 常带年后缀，label 常为短名）。"""
    norm_doc = normalize_name(doc)
    if not norm_doc:
        return False
    for label in labels:
        norm_label = normalize_name(label)
        if not norm_label:
            continue
        if norm_label in norm_doc or norm_doc in norm_label:
            return True
    return False


_CITATION_BOOK_RE = re.compile(r"《([^》]{2,60})》")
_CITATION_BRACKET_RE = re.compile(r"\[([^\]\[]{2,80})\]")


def extract_citation_docs(basis_text: str | None) -> list[str]:
    """判定依据文本 → 引用法规名清单（书名号 + 方括号两种格式）。"""
    if not basis_text:
        return []
    docs: list[str] = []
    for match in _CITATION_BOOK_RE.finditer(basis_text):
        docs.append(match.group(1).strip())
    for match in _CITATION_BRACKET_RE.finditer(basis_text):
        name = match.group(1).strip()
        # 方括号格式常含 "编号 名称"，整段即文档名（与 KB 文档名对齐）
        if name and name not in docs:
            docs.append(name)
    return docs


# 聚类建议弱标签（规则映射；57 失败样本方向目标口径，待业务复核）。
# 2026-11-06 快照聚类补充：防爆电子产品管控 / 静电接地报警 / 仪表校验 /
# 冲淋洗眼器点检 / 管道阀门标识 —— 其余失败样本（门锁损坏、杂物清理等
# 保洁类）知识库本无对应条文，不加标签（不计 recall 分母，属「无条文」正确形态）。
_WEAK_LABEL_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("受限空间", "有限空间"), ("受限空间作业安全管理制度", "GB 30871",
                                "危险化学品企业特殊作业安全规范")),
    (("动火", "动火作业"), ("GB 30871", "危险化学品企业特殊作业安全规范",
                            "化学品生产单位特殊作业安全规范")),
    (("高处作业", "登高"), ("GB 30871", "危险化学品企业特殊作业安全规范")),
    (("吊装", "起重"), ("GB 30871", "危险化学品企业特殊作业安全规范")),
    (("临时用电",), ("GB 30871", "危险化学品企业特殊作业安全规范")),
    (("盲板",), ("GB 30871", "危险化学品企业特殊作业安全规范")),
    (("消防水", "消火栓", "消防栓", "消防泵"), ("消防给水", "GB 50974", "消防法")),
    (("防台风", "防汛", "台风", "加固"), ("防台风", "防汛防台风", "台风")),
    (("安全帽", "安全带", "防护服", "护目镜", "防毒面具", "劳保"),
     ("个体防护装备", "GB 39800", "劳动防护用品")),
    (("防爆", "非防爆"), ("防爆", "爆炸危险环境电力装置", "GB 50058")),
    (("接地", "静电", "跨接"), ("静电", "静电接地", "GB 12158")),
    (("校验", "校准", "检定"), ("校准", "计量", "检定")),
    (("冲淋洗眼器", "洗眼器", "冲淋"), ("冲淋洗眼器", "紧急冲淋", "洗眼器")),
    (("标识", "标签"), ("安全标志及其使用导则", "GB 2894", "管道标识", "GB 7231")),
)


def suggest_weak_labels(description: str) -> list[str]:
    """描述 → 聚类建议弱标签（无命中返回空 → 该条不计 recall 分母）。"""
    labels: list[str] = []
    for markers, targets in _WEAK_LABEL_RULES:
        if any(marker in description for marker in markers):
            for target in targets:
                if target not in labels:
                    labels.append(target)
    return labels


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    """评测快照 jsonl → 有效条目（有描述且有弱标签；坏行跳过）。"""
    if not path.exists():
        raise FileNotFoundError(f"评测快照不存在: {path}")
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if (
            isinstance(item, dict)
            and item.get("description")
            and item.get("weak_labels")
        ):
            entries.append(item)
    return entries


RetrieveFn = Callable[[str, int], Any]  # async (description, target_chunks) -> KnowledgeContext


async def _retrieve_baseline(
    retrieve: RetrieveFn, description: str, *, top_k: int
) -> tuple[KnowledgeContext, int, str]:
    context = await retrieve(description, top_k)
    return context, 1, description


async def _retrieve_multi(
    retrieve: RetrieveFn, description: str, *, top_k: int, candidates: int
) -> tuple[KnowledgeContext, int, str]:
    plan = rq.build_retrieval_queries(description)
    queries = list(plan.queries) or [description]
    contexts = [
        await retrieve(query, candidates) for query in queries
    ]
    merged = rq.merge_route_contexts(contexts, top_k=top_k)
    return merged, len(queries), plan.primary


async def evaluate_strategy(
    entries: list[dict[str, Any]],
    *,
    retrieve: RetrieveFn,
    strategy: str,
    top_k: int,
    candidates: int = 12,
) -> dict[str, Any]:
    """单策略评测：逐条检索 → 弱标签命中 → 汇总。

    Args:
        retrieve: async 检索函数（真库/评测注入 fake 均可），签名
            ``(description, target_chunks) -> KnowledgeContext``。
        strategy: ``baseline``（原文单路）| ``multi``（多路合并，① 新行为）。
    """
    per_entry: list[dict[str, Any]] = []
    labeled = hit = 0
    routes_sum = 0.0
    chars_sum = 0
    latency_sum = 0.0
    for entry in entries:
        description = str(entry["description"])
        labels = list(entry.get("weak_labels") or [])
        started = time.perf_counter()
        if strategy == "multi":
            context, routes, primary = await _retrieve_multi(
                retrieve, description, top_k=top_k, candidates=candidates
            )
        else:
            context, routes, primary = await _retrieve_baseline(
                retrieve, description, top_k=top_k
            )
        latency_sum += time.perf_counter() - started
        docs = [c.source_doc for c in context.chunks if c.source_doc]
        # 逐 doc 判弱标签命中（避免拼接串与归一化规则的跨界耦合）
        entry_hit = bool(labels) and any(
            doc_matches_label(doc, labels) for doc in docs
        )
        if labels:
            labeled += 1
            hit += int(entry_hit)
        routes_sum += routes
        chars_sum += len(context.markdown)
        per_entry.append(
            {
                "record_id": entry.get("record_id", ""),
                "source": entry.get("source", ""),
                "description": description,
                "labeled": bool(labels),
                "hit": entry_hit,
                "routes": routes,
                "primary_query": primary,
                "docs": docs[:8],
            }
        )
    n = len(entries)
    return {
        "strategy": strategy,
        "per_entry": per_entry,
        "aggregate": {
            "n": n,
            "labeled": labeled,
            "hit": hit,
            "recall": round(hit / labeled * 100, 1) if labeled else 0.0,
            "avg_routes": round(routes_sum / n, 2) if n else 0.0,
            # 上下文字符数 = tokens·时延代理之一；avg_latency_ms = 检索时延代理
            "avg_chars": round(chars_sum / n, 1) if n else 0.0,
            "avg_latency_ms": round(latency_sum / n * 1000, 1) if n else 0.0,
        },
    }


def count_improved(
    baseline_entries: list[dict[str, Any]],
    multi_entries: list[dict[str, Any]],
) -> int:
    """基线漏检且多路命中的条目数（方向目标口径：32 条未召回改善 ≥30%）。"""
    multi_by_id = {
        str(item.get("record_id")): item for item in multi_entries
    }
    improved = 0
    for base in baseline_entries:
        if not base.get("labeled") or base.get("hit"):
            continue
        counterpart = multi_by_id.get(str(base.get("record_id")))
        if counterpart is not None and counterpart.get("hit"):
            improved += 1
    return improved


def render_report(
    baseline: dict[str, Any], multi: dict[str, Any], *, source: str
) -> str:
    """两策略对照报告（Markdown）。"""
    b = baseline["aggregate"]
    m = multi["aggregate"]
    improved = count_improved(baseline["per_entry"], multi["per_entry"])
    lines = [
        "# ① 检索评测报告（P1-1，只读重放）",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 条目来源：{source or '全部'}；有效条目 {b['n']}（有弱标签 {b['labeled']}）",
        "- 弱标签口径：成功样本=basis_new 引用；失败样本=聚类建议（待业务复核）；"
        "无标签条目不计 recall 分母",
        "",
        "| 策略 | recall@k | 平均路数 | 上下文字符数（均值，tokens 代理） | 检索时延（均值 ms） |",
        "|---|---|---|---|---|",
        f"| 单路基线（原文单路） | {b['recall']}%（{b['hit']}/{b['labeled']}） "
        f"| {b['avg_routes']} | {b['avg_chars']} | {b['avg_latency_ms']} |",
        f"| 多路（清洗+关键词 RRF 合并） | {m['recall']}%（{m['hit']}/{m['labeled']}） "
        f"| {m['avg_routes']} | {m['avg_chars']} | {m['avg_latency_ms']} |",
        "",
        f"- **基线漏检 → 多路命中（improved）：{improved} 条**"
        "（方向目标：57 失败中 32 条未召回/弱召回改善 ≥30% = ≥10 条）",
        "",
        "## 多路命中明细（基线漏检子集）",
        "",
    ]
    multi_by_id = {str(i.get("record_id")): i for i in multi["per_entry"]}
    shown = 0
    for base in baseline["per_entry"]:
        if shown >= 30:
            break
        if not base.get("labeled") or base.get("hit"):
            continue
        counterpart = multi_by_id.get(str(base.get("record_id")))
        if counterpart is None or not counterpart.get("hit"):
            continue
        shown += 1
        lines.append(
            f"- `{base['record_id']}` {base['description'][:50]} → 命中: "
            + "、".join(counterpart.get("docs", [])[:3])
        )
    if shown == 0:
        lines.append("- (无)")
    return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════════
# 快照构建（/tmp + 审计只读）
# ═══════════════════════════════════════════════════════════════


async def build_snapshot(out: Path, *, dsn: str) -> int:
    """从 /tmp 历史样本 + 审计（只读）生成评测快照 jsonl，返回条目数。"""
    if not RERUN_FILE.exists() or not FAILURE_FILE.exists():
        raise SystemExit(
            f"/tmp 历史样本缺失（{RERUN_FILE} / {FAILURE_FILE}），无法构建快照"
        )
    import asyncpg

    # 每条 record 取最新一次调用的描述（重跑各轮描述一致；记录被改过时以最新为准）
    conn = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        await conn.execute("SET default_transaction_read_only = on")
        rows = await conn.fetch(
            """
            SELECT extra->>'bitable_record_id' AS record_id,
                   input_text
            FROM safety.ai_call_audits
            WHERE scenario = $1
              AND input_text IS NOT NULL
              AND created_at > now() - interval '40 days'
            ORDER BY created_at DESC
            """,
            SCENARIO,
        )
    finally:
        await conn.close()

    descriptions: dict[str, str] = {}
    for row in rows:
        record_id = row["record_id"]
        if not record_id or record_id in descriptions:
            continue
        prompt = _prompt_text(row["input_text"])
        description = extract_description_from_prompt(prompt)
        if description:
            descriptions[record_id] = description

    # 失败样本（57 条）：聚类建议弱标签
    failures: list[dict[str, Any]] = json.loads(FAILURE_FILE.read_text(encoding="utf-8"))
    # 重跑结果（197 条）：成功样本 basis_new 引用作弱标签。
    # 只排除显式 dry_run=True 行；失败行无 dry_run 键（None）必须保留。
    rerun: list[dict[str, Any]] = []
    seen_records: set[str] = set()
    for line in RERUN_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if item.get("dry_run") is True:
            continue
        record_id = str(item.get("record_id") or "")
        if not record_id or record_id in seen_records:
            continue
        seen_records.add(record_id)
        rerun.append(item)
    failure_ids = {str(item.get("record_id")) for item in failures}

    entries: list[dict[str, Any]] = []
    for item in rerun:
        record_id = str(item.get("record_id") or "")
        if not record_id or record_id not in descriptions:
            continue
        if str(item.get("status")) == "success":
            basis = str(item.get("basis_new") or "")
            labels = extract_citation_docs(basis)
            if not labels:
                continue
            entries.append(
                {
                    "record_id": record_id,
                    "description": descriptions[record_id],
                    "source": "success_gt",
                    "weak_labels": labels,
                    "label_provenance": "basis_new 引用（模型引用弱标签）",
                }
            )
        elif record_id in failure_ids:
            description = descriptions[record_id]
            entries.append(
                {
                    "record_id": record_id,
                    "description": description,
                    "source": "failure_57",
                    "weak_labels": suggest_weak_labels(description),
                    "label_provenance": "聚类建议（弱标签，待业务复核）",
                    "retrieval_analysis": next(
                        (
                            {
                                k: item2.get(k)
                                for k in ("top1_score", "top1_doc", "citable_chunks")
                            }
                            for item2 in failures
                            if str(item2.get("record_id")) == record_id
                        ),
                        None,
                    ),
                }
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(entries)


def _prompt_text(input_text: str | None) -> str:
    """审计 input_text（messages JSON）→ 拼接 user 文本（与 replay 同口径）。"""
    if not input_text:
        return ""
    try:
        payload = json.loads(input_text)
    except (json.JSONDecodeError, ValueError):
        return ""
    messages = payload if isinstance(payload, list) else [payload]
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content:
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# 真库评测（只读）
# ═══════════════════════════════════════════════════════════════


async def run_eval(
    snapshot: Path,
    *,
    source: str,
    limit: int,
    top_k: int,
    candidates: int,
    dump: Path | None = None,
) -> str:
    """真库只读评测：同一评测集跑 baseline / multi 两策略并渲染对照报告。

    ``dump`` 非空时把两策略 per_entry 明细写为 JSON（缺失清单脚本消费）。
    """
    from app.core.database import async_session_factory

    entries = load_snapshot(snapshot)
    if source:
        entries = [e for e in entries if e.get("source") == source]
    if limit > 0:
        entries = entries[:limit]
    if not entries:
        return f"(无有效评测条目：source={source or '全部'} limit={limit})"

    async with async_session_factory() as session:
        retriever = SafetyKnowledgeRetriever(session)

        async def retrieve(description: str, target_chunks: int) -> KnowledgeContext:
            return await retriever.retrieve(
                description=description, target_chunks=target_chunks
            )

        baseline = await evaluate_strategy(
            entries, retrieve=retrieve, strategy="baseline", top_k=top_k
        )
        multi = await evaluate_strategy(
            entries, retrieve=retrieve, strategy="multi",
            top_k=top_k, candidates=candidates,
        )
    if dump is not None:
        dump.parent.mkdir(parents=True, exist_ok=True)
        dump.write_text(
            json.dumps(
                {
                    "baseline": baseline["per_entry"],
                    "multi": multi["per_entry"],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
    return render_report(baseline, multi, source=source or "全部")


def _dsn_from_env() -> str:
    dsn = os.environ.get("DATABASE_URL", "")
    if dsn:
        return dsn
    env_file = Path(".env.development")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="① 检索评测（P1-1，只读）")
    parser.add_argument("--build-snapshot", action="store_true",
                        help="从 /tmp 历史样本 + 审计只读生成评测快照")
    parser.add_argument("--snapshot", default="", help="评测快照 jsonl 路径")
    parser.add_argument("--source", default="", help="过滤来源（failure_57 / success_gt）")
    parser.add_argument("--limit", type=int, default=0, help="最多评测条数（0=全部）")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--candidates", type=int, default=12)
    parser.add_argument("--out", default="", help="报告写入文件（默认 stdout）")
    parser.add_argument("--dump", default="",
                        help="per_entry 明细 JSON 输出路径（缺失清单脚本消费）")
    parser.add_argument("--dsn", default="", help="PG DSN（build-snapshot 用）")
    args = parser.parse_args(argv)

    if args.build_snapshot:
        out = Path(args.out or "../.scratch/hazard-retrieval-quality/eval/snapshot.jsonl")
        count = asyncio.run(build_snapshot(out, dsn=args.dsn or _dsn_from_env()))
        print(f"快照已生成: {out}（{count} 条）")
        return 0

    if not args.snapshot:
        parser.error("需要 --snapshot（或 --build-snapshot 先生成）")
    report = asyncio.run(
        run_eval(
            Path(args.snapshot),
            source=args.source,
            limit=args.limit,
            top_k=args.top_k,
            candidates=args.candidates,
            dump=Path(args.dump) if args.dump else None,
        )
    )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"报告已写入: {out_path}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
