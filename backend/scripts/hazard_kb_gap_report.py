"""① KB 缺失清单 — 57 失败样本聚类 → 缺失法规补录清单（P1-1 R3a，只读）。

输入：
- 评测快照（``hazard_retrieval_eval.py --build-snapshot`` 产物）：57 失败样本
  （含聚类建议弱标签，标注「待业务复核」）；
- 评测 per-entry dump（``hazard_retrieval_eval.py --dump`` 产物）：多路是否命中
  目标法规 —— 命中说明法规在库，未命中才是「库缺法规」候选。

输出 Markdown 报告：
1. 缺失法规清单（法规名 → 样本条数 + 代表描述 + 建议补录形态）；
2. 保洁类/无对应条文形态说明（正确失败形态，非 KB 缺口）；
3. 与设计 §C12 已知缺口交叉核对（GB 30871、受限空间、消防水、防台风、PPE 表格式）。

安全边界：纯读本地快照/dump 文件，无网络 / DB / Bitable。

用法（cwd=backend）::

    .venv/bin/python scripts/hazard_kb_gap_report.py \
        --snapshot ../.scratch/hazard-retrieval-quality/eval/snapshot.jsonl \
        --dump ../.scratch/hazard-retrieval-quality/eval/dump-failure57.json \
        --out ../.scratch/hazard-retrieval-quality/eval/gap-report.md
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# 设计 §C12 / 优化方案 C-12 已知缺口（交叉核对用）
KNOWN_GAPS: tuple[str, ...] = (
    "GB 30871",
    "受限空间",
    "消防水",
    "防台风",
    "PPE",
)


def load_failure_entries(snapshot: Path) -> list[dict[str, Any]]:
    """快照 → 失败样本条目（有/无标签都保留，供形态统计）。"""
    entries: list[dict[str, Any]] = []
    for line in snapshot.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(item, dict) and item.get("source") == "failure_57":
            entries.append(item)
    return entries


def load_multi_hits(dump: Path) -> dict[str, bool]:
    """评测 dump → record_id → 多路是否命中弱标签。dump 缺 record 按未命中（保守）。"""
    if not dump.exists():
        return {}
    data = json.loads(dump.read_text(encoding="utf-8"))
    return {
        str(item.get("record_id")): bool(item.get("hit"))
        for item in data.get("multi", [])
    }


def collect_missing(
    entries: list[dict[str, Any]], multi_hits: dict[str, bool]
) -> dict[str, list[str]]:
    """未命中条目的弱标签 → 法规 → 代表描述清单（命中条目的标签不算缺失）。"""
    missing: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        labels = entry.get("weak_labels") or []
        if not labels:
            continue
        if multi_hits.get(str(entry.get("record_id"))):
            continue  # 多路已命中 → 法规在库，非缺口
        description = str(entry.get("description") or "")[:60]
        for label in labels:
            if description not in missing[label]:
                missing[label].append(description)
    return missing


def build_gap_report(snapshot: Path, dump: Path) -> str:
    """缺失清单报告（Markdown）。"""
    entries = load_failure_entries(snapshot)
    multi_hits = load_multi_hits(dump)
    missing = collect_missing(entries, multi_hits)
    unlabeled = [e for e in entries if not e.get("weak_labels")]
    labeled = len(entries) - len(unlabeled)
    hit_count = sum(1 for e in entries if multi_hits.get(str(e.get("record_id"))))

    lines = [
        "# ① 知识库缺失法规清单（P1-1 R3a，失败样本聚类）",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 输入：失败样本 {len(entries)} 条（可行动族 {labeled} / 保洁类无条文 "
        f"{len(unlabeled)}）；多路命中 {hit_count} 条",
        "- 标签口径：聚类建议弱标签（**待业务复核**）；「缺失」= 多路检索仍未"
        "命中该法规 → 库缺候选（区别于「在库但检索没找到」）",
        "",
        "## 缺失法规清单（建议补录；PDF 源由业务确认）",
        "",
        "| 法规/制度 | 样本描述数 | 代表描述 | 建议补录形态 |",
        "|---|---|---|---|",
    ]
    for label in sorted(missing, key=lambda k: -len(missing[k])):
        samples = missing[label]
        form = "表格型 → 上传前预处理（条文上下文前缀）" if any(
            marker in label for marker in ("PPE", "个体防护", "配备")
        ) else "PDF 常规入库"
        lines.append(
            f"| {label} | {len(samples)} | {samples[0]} | {form} |"
        )
    if not missing:
        lines.append("| (无——可行动族均已被多路检索命中) | | | |")

    lines += [
        "",
        "## 保洁类/无对应条文形态（正确失败，非 KB 缺口）",
        "",
        f"- 共 {len(unlabeled)} 条：门锁损坏、杂物堆放、水龙头漏水等现场保洁"
        "类问题，知识库本无对应条文——AI 输出占位属正确形态（闸门拦截符合预期），"
        "不建议为它们补录法规。",
        "",
        "## 与设计 §C12 已知缺口交叉核对",
        "",
    ]
    missing_text = "、".join(missing)
    for known in KNOWN_GAPS:
        status = "✅ 已在缺失清单" if known in missing_text else "—（未出现）"
        lines.append(f"- {known}：{status}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="① KB 缺失清单（P1-1 R3a，只读）")
    parser.add_argument(
        "--snapshot", default="../.scratch/hazard-retrieval-quality/eval/snapshot.jsonl"
    )
    parser.add_argument(
        "--dump", default="../.scratch/hazard-retrieval-quality/eval/dump-failure57.json"
    )
    parser.add_argument(
        "--out", default="../.scratch/hazard-retrieval-quality/eval/gap-report.md"
    )
    args = parser.parse_args(argv)
    report = build_gap_report(Path(args.snapshot), Path(args.dump))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"缺失清单已写入: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
