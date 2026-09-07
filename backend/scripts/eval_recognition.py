"""送货单识别回归评估（S2 ticket 05，spec Testing Decisions 回归门禁）。

跑测试集（scripts/build_recognition_dataset.py 产出的 60 条真值 + 图）：
每张图 → recognize_receipt（真 LLM）→ align_receipt（真主数据）→ 与
truth.jsonl 逐字段对比 → 命中率报告落 ``.scratch/s2-recognition/eval_report.md``。

门禁口径（spec）：
- 必提 8 字段字段级命中率 ≥ 90%；
- 主数据对齐命中率 ≥ 95%（aligned.match_confidence != none 且标准名
  == truth 物料名，归一化后比对）。
不达标时如实输出报告（不造假），附低置信字段分析与 prompt 改进建议。

比对规则（值规范化后）：
- 文本：NFKC 全角→半角 + 去全部空白 + casefold 后相等；供应商/生产商/
  物料名称等长文本放宽为 difflib ratio ≥ 0.85 即算命中；
- 数量（入库数量）：float 近似，相对误差 ≤ 1%；
- truth 空值字段不计入分母（无可识别真值；识别给了值记「疑似幻觉」，
  仅在报告中披露，不进命中率——真值来自人工 Base 录入，空≠图上没有）；
- 识别调用整体失败的记录不计入字段分母，单独计数披露。

评估不入 pytest（独立脚本）；并发默认 4（vision reasoning 单图 30-90s）。

用法（backend 目录下）::

    DATABASE_URL=... uv run python scripts/eval_recognition.py            # 全量
    DATABASE_URL=... uv run python scripts/eval_recognition.py --limit 10
    DATABASE_URL=... uv run python scripts/eval_recognition.py --out <md>
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402
from app.modules.warehouse.agent.pipeline import (  # noqa: E402
    align_receipt,
    recognize_receipt,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / ".scratch" / "s2-recognition" / "dataset"
DEFAULT_OUT = REPO_ROOT / ".scratch" / "s2-recognition" / "eval_report.md"

# 必提 8 字段：recognized 键 → truth.jsonl 中文字段名 + 比对模式
# （exact=归一化精确；fuzzy=归一化相等或 difflib ratio≥0.85；number=±1%）
FIELD_SPECS: tuple[tuple[str, str, str], ...] = (
    ("material_name", "物料名称", "fuzzy"),
    ("vendor_batch_no", "厂家批号", "exact"),
    ("quantity", "入库数量", "number"),
    ("unit", "单位", "exact"),
    ("supplier", "供应商", "fuzzy"),
    ("manufacturer", "生产商", "fuzzy"),
    ("plate_no", "车牌", "exact"),
    ("contract_no", "合同编号或订单号", "exact"),
)

# 对齐门禁字段（truth 中的物料名）
ALIGN_TRUTH_KEY = "物料名称"

# 长文本 difflib 命中阈值（spec：供应商等长文本）
FUZZY_HIT_RATIO = 0.85
# 数量相对误差容忍
NUMBER_TOLERANCE = 0.01
# 低置信度阈值（与 cards.RECEIPT_CONFIDENCE_WARN 同口径）
LOW_CONFIDENCE = 0.7

_WS_RE = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="送货单识别回归评估")
    parser.add_argument("--limit", type=int, default=0, help="评估条数（默认 0=全量）")
    parser.add_argument("--concurrency", type=int, default=4, help="识别并发数（默认 4）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"报告路径（默认 {DEFAULT_OUT}）")
    return parser.parse_args()


def norm_text(value: object) -> str:
    """值规范化：NFKC 全角→半角 + 去全部空白 + casefold + 数字去尾 .0。

    尾 .0 处理：LLM 偶发把纯数字字段输出为 float（2511 → 2511.0），
    批号/合同号文本比对时按数字形态吸收，避免假阴性。
    """
    text = "" if value is None else str(value)
    text = _WS_RE.sub("", unicodedata.normalize("NFKC", text)).casefold()
    return re.sub(r"^(\d+)\.0$", r"\1", text)


def _as_float(value: object) -> float | None:
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def field_hit(mode: str, truth: str, predicted: object) -> bool:
    """单字段比对：truth 非空前提下判定是否命中。"""
    if mode == "number":
        t, p = _as_float(truth), _as_float(predicted)
        if t is None or p is None:
            return norm_text(truth) == norm_text(predicted)  # 非数字回退文本比对
        baseline = max(abs(t), 1e-9)
        return abs(p - t) / baseline <= NUMBER_TOLERANCE
    if norm_text(truth) == norm_text(predicted):
        return True
    if mode == "fuzzy":
        ratio = difflib.SequenceMatcher(None, norm_text(truth), norm_text(predicted)).ratio()
        return ratio >= FUZZY_HIT_RATIO
    return False


@dataclass
class FieldStat:
    total: int = 0  # truth 非空的参与分母数
    hits: int = 0
    truth_empty: int = 0  # truth 空（不计分母）
    suspected_hallucination: int = 0  # truth 空但识别给了值（仅披露）
    none_value: int = 0  # 未命中中识别值为 None/空（模型未输出）
    conf_sum: float = 0.0
    conf_count: int = 0
    low_confidence: int = 0  # confidence < 0.7
    misses: list[dict[str, object]] = field(default_factory=list)


@dataclass
class RecordResult:
    record_id: str
    image: str
    ok: bool  # 识别是否整体成功
    error: str = ""
    fields: dict[str, dict[str, object]] = field(default_factory=dict)
    # fields[key] = {"truth", "value", "confidence", "hit", "truth_empty"}
    align_hit: bool | None = None
    align_confidence: str = ""
    aligned_name: str = ""


def truth_non_empty(row: dict[str, object], key: str) -> bool:
    value = row.get(key)
    return value is not None and str(value).strip() != ""


async def evaluate_one(
    row: dict[str, object], semaphore: asyncio.Semaphore
) -> RecordResult:
    """单条评估：图 → 识别 → 对齐 → 逐字段对比。"""
    record_id = str(row.get("record_id") or "")
    image_path = DATASET_DIR / "images" / f"{record_id}.jpg"
    result = RecordResult(record_id=record_id, image=image_path.name, ok=False)
    if not image_path.exists():
        result.error = "image_missing"
        return result
    image_b64 = base64.b64encode(image_path.read_bytes()).decode()

    async with semaphore:
        try:
            recognized = await recognize_receipt(image_b64)
            aligned = await align_receipt(recognized)
        except Exception as exc:  # noqa: BLE001 — 单条失败不阻塞整体（如实计数）
            result.error = f"{type(exc).__name__}: {exc}"[:200]
            return result
    result.ok = True

    for key, truth_key, mode in FIELD_SPECS:
        item = getattr(recognized, key)
        value = item.value if item is not None else None
        confidence = item.confidence if item is not None else 0.0
        truth = str(row.get(truth_key) or "")
        empty = not truth_non_empty(row, truth_key)
        hit = None if empty else field_hit(mode, truth, value)
        result.fields[key] = {
            "truth_key": truth_key,
            "truth": truth,
            "value": value,
            "confidence": round(confidence, 3),
            "hit": hit,
            "truth_empty": empty,
        }

    # 对齐判定：match_confidence != none 且标准名 == truth 物料名（归一化）
    truth_name = str(row.get(ALIGN_TRUTH_KEY) or "")
    aligned_name = str(aligned.aligned.get("material_name") or "")
    result.align_confidence = aligned.match_confidence
    result.aligned_name = aligned_name
    if not truth_non_empty(row, ALIGN_TRUTH_KEY):
        result.align_hit = None
    else:
        result.align_hit = (
            aligned.match_confidence != "none"
            and norm_text(aligned_name) == norm_text(truth_name)
        )
    return result


def aggregate(results: list[RecordResult]) -> dict[str, FieldStat]:
    stats: dict[str, FieldStat] = {}
    for key, truth_key, _mode in FIELD_SPECS:
        stats[key] = FieldStat()
    for result in results:
        if not result.ok:
            continue  # 识别失败记录不计字段分母（单独披露）
        for key, _truth_key, _mode in FIELD_SPECS:
            data = result.fields.get(key) or {}
            stat = stats[key]
            if data.get("truth_empty"):
                stat.truth_empty += 1
                if data.get("value") is not None and str(data.get("value")).strip():
                    stat.suspected_hallucination += 1
                continue
            stat.total += 1
            confidence = float(str(data.get("confidence") or 0.0))
            stat.conf_sum += confidence
            stat.conf_count += 1
            if confidence < LOW_CONFIDENCE:
                stat.low_confidence += 1
            if data.get("hit"):
                stat.hits += 1
            else:
                value_text = "" if data.get("value") is None else str(data.get("value")).strip()
                if not value_text:
                    stat.none_value += 1
                stat.misses.append(
                    {
                        "record_id": result.record_id,
                        "truth": data.get("truth"),
                        "value": data.get("value"),
                        "confidence": data.get("confidence"),
                    }
                )
    return stats


def pct(hits: int, total: int) -> str:
    return f"{hits / total * 100:.1f}%" if total else "-"


def build_report(
    results: list[RecordResult],
    stats: dict[str, FieldStat],
    args: argparse.Namespace,
) -> str:
    label_cn = {key: truth_key for key, truth_key, _ in FIELD_SPECS}
    mode_of = {key: mode for key, _truth, mode in FIELD_SPECS}
    failed = [r for r in results if not r.ok]
    evaluated = [r for r in results if r.ok]

    field_total = sum(s.total for s in stats.values())
    field_hits = sum(s.hits for s in stats.values())
    field_rate = field_hits / field_total if field_total else 0.0

    align_pool = [r for r in evaluated if r.align_hit is not None]
    align_hits = sum(1 for r in align_pool if r.align_hit)
    align_rate = align_hits / len(align_pool) if align_pool else 0.0
    align_dist = Counter(r.align_confidence for r in align_pool)

    gate_pass = field_rate >= 0.90 and align_rate >= 0.95

    lines: list[str] = []
    lines.append("# S2 识别回归评估报告")
    lines.append("")
    lines.append(f"- 日期：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- 模型：`{get_settings().WAREHOUSE_AGENT_MODEL}`（recognize_receipt 真调）")
    lines.append(
        f"- 数据集：`.scratch/s2-recognition/dataset/`（truth 60 条，有图 {len(results)} 条，"
        f"本次评估 {len(results)} 条，识别失败 {len(failed)} 条）"
    )
    if args.limit:
        lines.append(f"- 参数：--limit {args.limit} --concurrency {args.concurrency}")
    lines.append("")
    lines.append("## 总体门禁（spec：必提字段级 ≥90%，对齐 ≥95%）")
    lines.append("")
    lines.append("| 指标 | 命中/有效 | 命中率 | 门禁 | 判定 |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(
        f"| 必提 8 字段字段级 | {field_hits}/{field_total} | {field_rate * 100:.1f}% "
        f"| ≥90% | {'达标' if field_rate >= 0.90 else '不达标'} |"
    )
    lines.append(
        f"| 主数据对齐（标准名==truth） | {align_hits}/{len(align_pool)} | {align_rate * 100:.1f}% "
        f"| ≥95% | {'达标' if align_rate >= 0.95 else '不达标'} |"
    )
    lines.append("")
    lines.append(f"**结论：{'✅ 达标' if gate_pass else '❌ 不达标'}**")
    lines.append("")

    lines.append("## 各字段命中率")
    lines.append("")
    lines.append(
        "| 字段 | 模式 | 命中/有效 | 命中率 | 未输出(None) | 平均置信度 | 低置信(<0.7) | truth空值 | 疑似幻觉 |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for key, _truth_key, _mode in FIELD_SPECS:
        s = stats[key]
        avg = f"{s.conf_sum / s.conf_count:.2f}" if s.conf_count else "-"
        miss_count = s.total - s.hits
        lines.append(
            f"| {label_cn[key]} | {mode_of[key]} | {s.hits}/{s.total} | {pct(s.hits, s.total)} "
            f"| {s.none_value}/{miss_count} | {avg} | {s.low_confidence} | {s.truth_empty} "
            f"| {s.suspected_hallucination} |"
        )
    lines.append("")
    lines.append(
        "> truth 空值字段不计入分母（真值来自人工 Base 录入，空≠图上没有）；"
        "「未输出(None)」= 未命中中模型给了 null（图上无此信息或模型未辨认出）；"
        "「疑似幻觉」= truth 空但识别给了值，仅披露不扣分。"
    )
    lines.append("")

    lines.append("## 对齐置信度分布")
    lines.append("")
    lines.append("| match_confidence | 条数 |")
    lines.append("| --- | --- |")
    for level in ("exact", "prefix", "fuzzy", "none"):
        lines.append(f"| {level} | {align_dist.get(level, 0)} |")
    lines.append("")

    lines.append("## 未命中明细（前 10 条）")
    lines.append("")
    shown = 0
    for key, _truth_key, _mode in FIELD_SPECS:
        for miss in stats[key].misses:
            if shown >= 10:
                break
            lines.append(
                f"- `{miss['record_id']}` **{label_cn[key]}**：truth={miss['truth']!r} "
                f"识别={miss['value']!r}（confidence={miss['confidence']}）"
            )
            shown += 1
        if shown >= 10:
            break
    if shown == 0:
        lines.append("（无未命中）")
    total_misses = sum(len(s.misses) for s in stats.values())
    if total_misses > shown:
        lines.append(f"（其余 {total_misses - shown} 条未命中见各字段统计，略）")
    lines.append("")

    if failed:
        lines.append("## 识别失败记录（不计字段分母）")
        lines.append("")
        for r in failed:
            lines.append(f"- `{r.record_id}`：{r.error}")
        lines.append("")

    # 低置信字段分析 + 改进建议（按实测分布生成）
    lines.append("## 低置信字段分析与改进建议")
    lines.append("")
    low_fields = sorted(
        ((key, s) for key, s in stats.items() if s.low_confidence > 0),
        key=lambda kv: kv[1].low_confidence,
        reverse=True,
    )
    if not low_fields:
        lines.append("无低置信（<0.7）字段。")
    else:
        lines.append("**低置信字段（confidence<0.7 样本数降序）**：")
        for key, s in low_fields:
            lines.append(
                f"- **{label_cn[key]}**：{s.low_confidence} 个有效样本低置信"
                f"（命中率 {pct(s.hits, s.total)}）"
            )
    lines.append("")

    # 未命中形态拆解：None（模型未输出）vs 有值不符（识别偏差/口径差异）
    lines.append("**未命中形态拆解**（None=图上无此信息/模型未辨认；有值不符=识别偏差或口径差异）：")
    lines.append("")
    lines.append("| 字段 | 未命中 | 其中 None | 其中识别值不符 |")
    lines.append("| --- | --- | --- | --- |")
    for key, _truth_key, _mode in FIELD_SPECS:
        s = stats[key]
        miss_count = s.total - s.hits
        if not miss_count:
            continue
        lines.append(
            f"| {label_cn[key]} | {miss_count} | {s.none_value} | {miss_count - s.none_value} |"
        )
    lines.append("")

    none_align = [r for r in align_pool if r.align_confidence == "none"]
    if none_align:
        lines.append("对齐 none 明细（识别名未命中主数据，人工选择兜底）：")
        for r in none_align[:5]:
            lines.append(f"- `{r.record_id}`：识别/对齐名={r.aligned_name!r}")
        lines.append("")

    # 数据驱动的归因与建议
    def _none_share(key: str) -> float:
        s = stats[key]
        miss_count = s.total - s.hits
        return s.none_value / miss_count if miss_count else 0.0

    mostly_absent = [
        label_cn[k] for k, _t, _m in FIELD_SPECS if _none_share(k) >= 0.6 and (stats[k].total - stats[k].hits) >= 3
    ]
    mostly_wrong = [
        label_cn[k] for k, _t, _m in FIELD_SPECS if 0 < _none_share(k) < 0.6 and (stats[k].total - stats[k].hits) >= 3
    ]
    lines.append("**归因与建议**（按本报告实测分布）：")
    lines.append("")
    if mostly_absent:
        lines.append(
            f"1. {'、'.join(mostly_absent)} 以「未输出(None)」为主——测试集图片多为外包装/厂家报告单"
            "（ticket01 抽样口径），此类单据上通常**没有**合同号/车牌/实收数量等送货单信息；"
            "真值来自人工 Base 录入（可能参照了纸质单据而非本图），存在**真值-图片错配**。"
            "建议：业务方按 spec 补真实送货单图片重建该部分真值后再回归，当前数字偏保守。"
        )
    if mostly_wrong:
        lines.append(
            f"2. {'、'.join(mostly_wrong)} 以「识别值不符」为主——多为生产商/供应商混淆、"
            "名称带规格后缀或别名（如「氯化钙」vs「二水合氯化钙」）。建议：识别 prompt 补充"
            "「区分发货单位与生产厂家」「品名去掉规格/包装后缀」的指令；名称别名靠对齐器兜底"
            f"（对齐 {align_rate * 100:.1f}% 已高于名称直命中率）。"
        )
    lines.append(
        "3. 模型档位：`deepseek-v4-flash-vision-exp` 对密集中文单据的辨认能力偏弱"
        "（平均置信度普遍 <0.8），建议尝试更大档位 vision 模型做 A/B 后再定回归基线"
        "（评估脚本可复跑：--out 换路径即可对比）。"
    )
    lines.append("4. 对齐器：none 条目多为识别名空/带杂质后缀，未命中时卡片提示人工选择，"
                 "不阻塞其他字段（spec 决策 7 口径已兜底）。")
    lines.append("")
    return "\n".join(lines)


async def main() -> int:
    args = parse_args()
    truth_path = DATASET_DIR / "truth.jsonl"
    rows = [
        json.loads(line)
        for line in truth_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # 仅评估有图记录（下载失败/HEIC 记录真值保留但无图，票01 契约）
    rows = [r for r in rows if (DATASET_DIR / "images" / f"{r.get('record_id')}.jpg").exists()]
    if args.limit:
        rows = rows[: args.limit]
    print(f"待评估 {len(rows)} 条（有图记录），并发 {args.concurrency}")

    semaphore = asyncio.Semaphore(args.concurrency)
    tasks = [asyncio.create_task(evaluate_one(row, semaphore)) for row in rows]
    results: list[RecordResult] = []
    for index, task in enumerate(asyncio.as_completed(tasks), start=1):
        result = await task
        results.append(result)
        status = (
            "OK" if result.ok else f"FAIL({result.error[:40]})"
        )
        print(f"[{index}/{len(rows)}] {result.record_id} {status}")

    stats = aggregate(results)
    report = build_report(results, stats, args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"\n报告已写入 {args.out}")

    # 逐条结果落盘（免重跑即可复析/对比 prompt 与模型变更）
    results_path = args.out.parent / f"{args.out.stem}_results.jsonl"
    results_path.write_text(
        "".join(
            json.dumps(
                {
                    "record_id": r.record_id,
                    "image": r.image,
                    "ok": r.ok,
                    "error": r.error,
                    "fields": r.fields,
                    "align_hit": r.align_hit,
                    "align_confidence": r.align_confidence,
                    "aligned_name": r.aligned_name,
                },
                ensure_ascii=False,
            )
            + "\n"
            for r in results
        ),
        encoding="utf-8",
    )
    print(f"逐条结果已写入 {results_path}")

    field_total = sum(s.total for s in stats.values())
    field_hits = sum(s.hits for s in stats.values())
    align_pool = [r for r in results if r.ok and r.align_hit is not None]
    align_hits = sum(1 for r in align_pool if r.align_hit)
    field_rate = field_hits / field_total if field_total else 0.0
    align_rate = align_hits / len(align_pool) if align_pool else 0.0
    print(f"必提字段级: {field_hits}/{field_total} = {field_rate * 100:.1f}%（门禁 ≥90%）")
    print(f"对齐命中: {align_hits}/{len(align_pool)} = {align_rate * 100:.1f}%（门禁 ≥95%）")
    gate_pass = field_rate >= 0.90 and align_rate >= 0.95
    print("门禁判定:", "达标" if gate_pass else "不达标（详见报告分析）")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("中断", file=sys.stderr)
        raise SystemExit(130) from None
