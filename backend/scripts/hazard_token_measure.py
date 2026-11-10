"""P2-3 T04 —— ①主链单条 token 双层度量（离线层，四象限对比）。

对同一批真实隐患描述（默认取 P1-1 评测快照 snapshot.jsonl），逐条做真实
检索（只读 ragplus），组装四象限完整 prompt 并用 tiktoken 精确计量：

    A 旧fewshot + 全量知识   ≡ P2-3 前线上行为（基线）
    B 旧fewshot + 截断知识   （隔离：检索截断的节省）
    C 新fewshot + 全量知识   （隔离：fewshot 压缩的节省）
    D 新fewshot + 截断知识   ≡ P2-3 后默认行为

旧 fewshot 从 git HEAD 的 prompt_skills/fewshot.md 读回（本脚本在压缩提交
前后均可复现历史口径）。图片 data URI 不计入（本次优化不改图片路径）。

用法（cwd=backend）::

    .venv/bin/python scripts/hazard_token_measure.py \
        --snapshot ../.scratch/hazard-retrieval-quality/eval/snapshot.jsonl \
        --limit 30 --out ../.scratch/hazard-cost-p23/evidence/token-offline.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

# 允许从 backend/ 目录直接运行（与 hazard_ai_quality_replay 同款）
sys.path.insert(0, os.getcwd())

from app.modules.safety.ai_hazard_identification import prompts  # noqa: E402
from app.modules.safety.service.hazard_direct import context_compression  # noqa: E402

# 默认与线上口径同源（registry 拍板值 200；env/DB 覆盖时自动跟随）
DEFAULT_MAX_CHARS = context_compression.knowledge_context_max_chars()

CTX_TEXT = (
    "隐患编号：HZ-20261110-001\n责任部门：生产一部\n地点/部位：三车间平台\n"
    "检查人员：张三\n检查时间：2026-11-10\n隐患描述：{description}"
)


def _load_old_fewshot() -> tuple[str, list[dict[str, dict[str, object]]]]:
    """从 git HEAD 读回压缩前的 fewshot md（marker + 5 例）。"""
    repo_root = Path(__file__).resolve().parents[2]
    blob = subprocess.run(
        ["git", "-C", str(repo_root), "show",
         "HEAD:backend/app/modules/safety/ai_hazard_identification/prompt_skills/fewshot.md"],
        capture_output=True, text=True, check=True,
    ).stdout
    import re

    m = re.search(r"^(.*?<!-- FEWSHOT_JSON -->\n)(.*?)\n?$", blob, re.S)
    if m is None:
        raise RuntimeError("HEAD fewshot.md 缺少 FEWSHOT_JSON 分隔标记")
    marker_block, body = m.group(1), m.group(2)
    marker = "## 参考示例\n\n以下为同类型化工企业的标准识别案例，供你参考风格和粒度："
    assert "## 参考示例" in marker_block
    return marker, json.loads(body)


def _build_prompt(
    ctx_text: str,
    knowledge: str,
    fewshot: tuple[str, list[dict[str, dict[str, object]]]],
) -> str:
    """以指定 fewshot 集合组装完整 prompt（复用 build_full_prompt 的拼接语义）。"""
    marker, examples = fewshot
    import json as _json

    template = prompts.text_prompt_template()
    prompt = template.format(
        context=ctx_text,
        work_rules=prompts.work_rules(),
        defect_substance_rules=prompts.defect_substance_rules(),
        output_format=prompts.OUTPUT_FORMAT,
    )
    if knowledge:
        prompt = prompt.replace(
            prompts.work_rules(), knowledge + "\n\n---\n\n" + prompts.work_rules(), 1
        )
    prompt += "\n\n" + prompts.CRITICAL_CONSTRAINTS
    prompt += "\n\n" + marker
    for i, ex in enumerate(examples, 1):
        prompt += f"\n\n**示例{i}**\n"
        prompt += f"输入描述：{ex['input']}\n"
        prompt += f"标准输出：{_json.dumps(ex['output'], ensure_ascii=False, indent=2)}"
    return prompt


def _estimate_tokens(text: str) -> int:
    from app.modules.safety.business_agent.core.compaction import estimate_tokens

    return estimate_tokens(text)


async def _retrieve(description: str) -> Any:
    from app.core.database import async_session_factory
    from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever
    from app.modules.safety.service.hazard_direct import retrieval_query

    async with async_session_factory() as session:
        retriever = SafetyKnowledgeRetriever(session)
        context = await retriever.retrieve(
            description=description,
            target_chunks=retrieval_query.retrieval_top_k(),
        )
        return context


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="评测快照 jsonl（真实描述源）")
    parser.add_argument("--limit", type=int, default=30, help="样本条数（默认 30）")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"截断上限（默认 {DEFAULT_MAX_CHARS}）")
    parser.add_argument("--out", default="", help="报告输出路径（默认 stdout）")
    args = parser.parse_args()

    descriptions: list[str] = []
    with open(args.snapshot, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            desc = (row.get("description") or row.get("query") or "").strip()
            if desc:
                descriptions.append(desc)
    descriptions = descriptions[: args.limit]
    if not descriptions:
        print("快照无可用描述", file=sys.stderr)
        return 1

    old_fewshot = _load_old_fewshot()
    new_fewshot = prompts.fewshot_pair()

    # parity 自检：本脚本 _build_prompt(新fewshot) 必须与真实组装器逐字节一致，
    # 否则 C/D 象限（乃至 A/B 的拼接基准）与线上 prompt 漂移，度量失真。
    _parity_ctx = CTX_TEXT.format(description="parity自检描述")
    assert _build_prompt(_parity_ctx, "", new_fewshot) == prompts.build_full_prompt(
        _parity_ctx, vision_mode=False, include_fewshot=True, knowledge_context=None,
    ), "度量脚本组装语义与 build_full_prompt 漂移"

    rows: list[dict[str, int]] = []
    knowledge_chars: list[int] = []
    for i, desc in enumerate(descriptions, 1):
        context = await _retrieve(desc)
        full_md = context.markdown or ""
        compressed = context_compression.compress_knowledge_context(
            context, max_chunk_chars=args.max_chars
        )
        knowledge_chars.append(len(full_md))
        ctx_text = CTX_TEXT.format(description=desc)
        quads = {
            "A_old_full": _build_prompt(ctx_text, full_md, old_fewshot),
            "B_old_trunc": _build_prompt(ctx_text, compressed, old_fewshot),
            "C_new_full": _build_prompt(ctx_text, full_md, new_fewshot),
            "D_new_trunc": _build_prompt(ctx_text, compressed, new_fewshot),
        }
        tokens = {k: _estimate_tokens(v) for k, v in quads.items()}
        tokens["knowledge_chunks"] = len(context.chunks)
        rows.append(tokens)
        print(f"[{i}/{len(descriptions)}] {desc[:24]}… A={tokens['A_old_full']} "
              f"D={tokens['D_new_trunc']}")

    def _agg(key: str) -> tuple[float, float]:
        vals = [r[key] for r in rows]
        return statistics.mean(vals), statistics.median(vals)

    lines = [
        "# P2-3 离线 token 四象限度量（①主链 text 模式，不含图片 URI）",
        "",
        f"- 样本：{len(rows)} 条真实隐患描述（{Path(args.snapshot).name}，真实 ragplus 检索）",
        f"- 截断上限：{args.max_chars} 字/chunk；知识段字符 p50={statistics.median(knowledge_chars):.0f}",
        "- 计量：tiktoken（estimate_tokens）",
        "",
        "| 象限 | 均值 tokens | p50 tokens | 相对 A 降幅 |",
        "|---|---|---|---|",
    ]
    base_mean, base_p50 = _agg("A_old_full")
    labels = {
        "A_old_full": "A 旧fewshot+全量知识（P2-3 前基线）",
        "B_old_trunc": "B 旧fewshot+截断知识",
        "C_new_full": "C 新fewshot+全量知识",
        "D_new_trunc": "D 新fewshot+截断知识（新默认）",
    }
    for key in ("A_old_full", "B_old_trunc", "C_new_full", "D_new_trunc"):
        mean, p50 = _agg(key)
        drop = (1 - mean / base_mean) * 100
        lines.append(f"| {labels[key]} | {mean:.0f} | {p50:.0f} | -{drop:.1f}% |")

    d_mean, _ = _agg("D_new_trunc")
    verdict = "✅ ≥30% 冲刺达成" if d_mean <= base_mean * 0.7 else (
        "✅ ≥28% 达标" if d_mean <= base_mean * 0.72 else "❌ <28% 未达标（回调参）"
    )
    lines += [
        "",
        f"**结论：D/A = {(d_mean / base_mean) * 100:.1f}%，总降幅 "
        f"{(1 - d_mean / base_mean) * 100:.1f}% —— {verdict}**",
        "",
        "> 注：视觉模式图片 URI token（~970/张）不在本次优化面，未计入；",
        "> 真机口径见 evidence/token-realtime.md（ai_call_audits 前后对比）。",
    ]
    report = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"已写入 {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
