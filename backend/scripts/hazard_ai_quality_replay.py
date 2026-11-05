"""① 隐患 AI 识别 —— 离线质量回归重放（只读，A1/A3 验收证据脚本）。

用途（A 组验收）：
    重放 ``safety.ai_call_audits`` 中近 N 天 ``scenario='hazard_identification'`` 的
    ``output_text``，用当前代码里的**本地 JSON 修复链**（``ai_audit.json_repair``）
    与**质量闸门**（``hazard_direct.quality_gate``）离线判定，输出：
      - JSON 合法率：现状（仅剥围栏 + json.loads）vs 修复后（A1），总体/视觉/文本；
      - 修复阶段分布（trailing_comma / slice_object / fullwidth_quotes …）；
      - A3 质量闸门通过/拒绝分类（placeholder_basis / no_citation / …）；
      - 占位依据率与按天趋势；
      - 重跑窗口（调用数最多的一天）按 record 聚合的闸门判定；
      - 存在 ``/tmp/rerun_results.jsonl`` 时附 197 条 ground truth 一致性对照。

安全边界：
    - **只读**：连接后 `SET default_transaction_read_only = on`；
    - 只 SELECT，不写库、不调 AI、不访问 Bitable、无其它网络请求；
    - 不依赖 /tmp 历史文件（存在时仅作额外样本）。

口径说明（T3）：
    本脚本「现状合法」= 剥 markdown 围栏后 `json.loads`，**不等于**审计
    `extra.json_valid`（审计口径是「原文可直接解析、不剥围栏」），也不等于
    「修复后合法」；三套口径不可直接互比，看板/报告引用时须注明。

用法（cwd=backend）：:

    .venv/bin/python scripts/hazard_ai_quality_replay.py --days 30
    .venv/bin/python scripts/hazard_ai_quality_replay.py --days 30 --json
    .venv/bin/python scripts/hazard_ai_quality_replay.py --out /tmp/replay.md

DSN 解析顺序：``--dsn`` > ``DATABASE_URL`` 环境变量 > ``backend/.env.development``
中的 ``DATABASE_URL``。``postgresql+asyncpg://`` 会自动转成 asyncpg 可用 DSN。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# 允许从 backend/ 目录直接运行（与 /tmp 重跑脚本同款）
sys.path.insert(0, os.getcwd())

from app.modules.safety.ai_audit.json_repair import (  # noqa: E402
    repair_json_object,
    strip_fences,
)
from app.modules.safety.ai_hazard_identification.citations import (  # noqa: E402
    is_placeholder_basis,
)
from app.modules.safety.service.hazard_direct.quality_gate import (  # noqa: E402
    QualityGateError,
    ensure_output,
)

SCENARIO = "hazard_identification"
GROUND_TRUTH_FILE = Path("/tmp/rerun_results.jsonl")
VISION_MARKER = "[附图"


# ═══════════════════════════════════════════════════════════════
# 纯函数（可单测，不碰 DB）
# ═══════════════════════════════════════════════════════════════


def strict_parse(output_text: str | None) -> dict | None:
    """「现状」解析口径：剥 markdown 围栏 + json.loads（无本地修复）。"""
    if not output_text:
        return None
    try:
        parsed = json.loads(strip_fences(output_text))
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def gate_decision(parsed: dict | None) -> tuple[bool | None, str | None]:
    """A3 输出质量闸门判定：返回 (是否通过, 拒绝分类)。无法解析时分类 json_invalid。"""
    if parsed is None:
        return None, "json_invalid"
    try:
        ensure_output({"major_hazard_basis": parsed.get("major_hazard_basis", "")})
    except QualityGateError as exc:
        return False, exc.category
    return True, None


def analyze_output(output_text: str | None) -> dict[str, Any]:
    """单条 output_text 的 A1/A3 指标。"""
    strict = strict_parse(output_text)
    repair = repair_json_object(output_text or "")
    repaired_data = repair.data if isinstance(repair.data, dict) else None
    parsed = strict if strict is not None else repaired_data

    gate_pass, gate_category = gate_decision(parsed)
    basis = str((parsed or {}).get("major_hazard_basis") or "")
    return {
        "json_valid_before": strict is not None,
        "json_valid_after": parsed is not None,
        "repaired": strict is None and repaired_data is not None,
        "repair_stages": list(repair.stages),
        "parse_error": repair.error,
        "gate_pass": gate_pass,
        "gate_category": gate_category,
        "placeholder": is_placeholder_basis(basis),
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def analyze_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """对审计行集合做 A1/A3 汇总（纯函数）。

    Args:
        rows: 每行含 ``created_at``(str/date)、``input_text``、``output_text``、
              ``status``、``degradation_level``、``extra``（dict 或 JSON 字符串）。
    """
    totals = {
        "calls": len(rows),
        "vision_calls": 0,
        "text_calls": 0,
        "json_valid_before": 0,
        "json_valid_after": 0,
        "repaired_recovered": 0,
        "gate_pass_calls": 0,
        "gate_fail_calls": 0,
        "gate_unparseable_calls": 0,
        "placeholder_calls": 0,
        "degraded_calls": 0,
    }
    stage_counter: Counter[str] = Counter()
    gate_categories: Counter[str] = Counter()
    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "calls": 0,
            "json_before": 0,
            "json_after": 0,
            "repaired": 0,
            "gate_pass": 0,
            "placeholder": 0,
        }
    )
    # 重跑窗口自动识别：按天聚合并取调用数最多的一天
    day_calls: Counter[str] = Counter()
    record_calls: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        created = str(row.get("created_at") or "")
        day = created[:10]
        day_calls[day] += 1
        input_text = str(row.get("input_text") or "")
        is_vision = VISION_MARKER in input_text
        metrics = analyze_output(row.get("output_text"))
        totals["vision_calls" if is_vision else "text_calls"] += 1
        if metrics["json_valid_before"]:
            totals["json_valid_before"] += 1
        if metrics["json_valid_after"]:
            totals["json_valid_after"] += 1
        if metrics["repaired"]:
            totals["repaired_recovered"] += 1
            for stage in metrics["repair_stages"]:
                stage_counter[stage] += 1
        if metrics["gate_pass"] is True:
            totals["gate_pass_calls"] += 1
        elif metrics["gate_pass"] is False:
            totals["gate_fail_calls"] += 1
            gate_categories[str(metrics["gate_category"])] += 1
        else:
            totals["gate_unparseable_calls"] += 1
        if metrics["placeholder"]:
            totals["placeholder_calls"] += 1
        degradation = row.get("degradation_level")
        if degradation not in (None, "", "ragplus"):
            totals["degraded_calls"] += 1
        slot = by_day[day]
        slot["calls"] += 1
        slot["json_before"] += int(metrics["json_valid_before"])
        slot["json_after"] += int(metrics["json_valid_after"])
        slot["repaired"] += int(metrics["repaired"])
        slot["gate_pass"] += int(metrics["gate_pass"] is True)
        slot["placeholder"] += int(metrics["placeholder"])
        record_id = _record_id(row.get("extra"))
        if record_id:
            record_calls[record_id].append((day, metrics))

    rerun_day = ""
    if day_calls:
        rerun_day = day_calls.most_common(1)[0][0]
    rerun_record_ids = {
        record_id
        for record_id, calls in record_calls.items()
        if any(day == rerun_day for day, _ in calls)
    }
    gate_records_pass = sum(
        1
        for record_id in rerun_record_ids
        if any(
            day == rerun_day and metrics["gate_pass"] is True
            for day, metrics in record_calls[record_id]
        )
    )
    summary = {
        "totals": {
            **totals,
            "json_valid_before_rate": _rate(
                totals["json_valid_before"], totals["calls"]
            ),
            "json_valid_after_rate": _rate(
                totals["json_valid_after"], totals["calls"]
            ),
            "gate_pass_rate": _rate(totals["gate_pass_calls"], totals["calls"]),
            "placeholder_rate": _rate(totals["placeholder_calls"], totals["calls"]),
        },
        "vision": _chain_summary(rows, vision=True),
        "text": _chain_summary(rows, vision=False),
        "repair_stages": dict(stage_counter),
        "gate_categories": dict(gate_categories),
        "by_day": {day: dict(slot) for day, slot in sorted(by_day.items())},
        "rerun_day": rerun_day,
        "rerun_records": {
            "records": len(rerun_record_ids),
            "calls": day_calls.get(rerun_day, 0),
            "gate_pass_records": gate_records_pass,
            "gate_fail_records": len(rerun_record_ids) - gate_records_pass,
        },
    }
    return summary


def _chain_summary(rows: list[dict[str, Any]], *, vision: bool) -> dict[str, Any]:
    subset = [
        row
        for row in rows
        if (VISION_MARKER in str(row.get("input_text") or "")) is vision
    ]
    before = after = repaired = 0
    for row in subset:
        metrics = analyze_output(row.get("output_text"))
        before += int(metrics["json_valid_before"])
        after += int(metrics["json_valid_after"])
        repaired += int(metrics["repaired"])
    return {
        "calls": len(subset),
        "json_valid_before": before,
        "json_valid_after": after,
        "repaired": repaired,
        "json_valid_before_rate": _rate(before, len(subset)),
        "json_valid_after_rate": _rate(after, len(subset)),
    }


def _record_id(extra: Any) -> str:
    """从审计 extra（dict 或 JSON 字符串）取 bitable_record_id。"""
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (json.JSONDecodeError, ValueError):
            return ""
    if isinstance(extra, dict):
        return str(extra.get("bitable_record_id") or "")
    return ""


def compare_ground_truth(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """与 197 条重跑 ground truth 做一致性对照（存在 /tmp 样本时）。"""
    if not GROUND_TRUTH_FILE.exists():
        return None
    try:
        raw_lines = GROUND_TRUTH_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    truths: dict[str, str] = {}
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        record_id = str(item.get("record_id") or "")
        if record_id:
            truths[record_id] = str(item.get("status") or "")
    if not truths:
        return None

    gate_by_record: dict[str, bool] = {}
    rescue_by_record: dict[str, bool] = {}
    # ground truth 是「重跑窗口」的结论：只取调用数最多的一天的行，避免历史调用
    # （同一记录在重跑前也有审计）污染一致性对照
    day_calls: Counter[str] = Counter(
        str(row.get("created_at") or "")[:10] for row in rows
    )
    rerun_day = day_calls.most_common(1)[0][0] if day_calls else ""
    for row in rows:
        if str(row.get("created_at") or "")[:10] != rerun_day:
            continue
        record_id = _record_id(row.get("extra"))
        if not record_id or record_id not in truths:
            continue
        metrics = analyze_output(row.get("output_text"))
        if metrics["gate_pass"] is True:
            gate_by_record[record_id] = True
            if metrics["repaired"]:
                rescue_by_record[record_id] = True
        else:
            gate_by_record.setdefault(record_id, False)

    wrong_accept = [
        record_id
        for record_id, passed in gate_by_record.items()
        if passed and truths.get(record_id) != "success"
    ]
    wrong_reject = [
        record_id
        for record_id, passed in gate_by_record.items()
        if not passed and truths.get(record_id) == "success"
    ]
    # 误收归因：历史因 JSON 畸形判失败、A1 本地修复后可解析且引用合规的救援样本，
    # 属预期收益（不是闸门口径差异）；其余才算真正的语义不一致。
    rescued = [record_id for record_id in wrong_accept if rescue_by_record.get(record_id)]
    genuine = [record_id for record_id in wrong_accept if record_id not in rescued]
    return {
        "ground_truth_records": len(truths),
        "replayed_records": len(gate_by_record),
        "wrong_accept": len(wrong_accept),
        "wrong_reject": len(wrong_reject),
        "wrong_accept_repaired_rescue": len(rescued),
        "wrong_accept_genuine": len(genuine),
        "wrong_accept_ids": rescued + genuine,
        "wrong_reject_ids": wrong_reject[:10],
    }


def rule_regression_from_ground_truth() -> dict[str, Any] | None:
    """对 197 条 ground truth 的成功样本跑当前 RuleEngine（A4 验收证据）。

    只用重跑结果里的 ``basis_new`` + 三个枚举字段重建输出，其余字段给固定合法
    值（只影响非依据类规则）；用于验证「新引用口径下 140 条历史成功样本规则
    error = 0」。存在 /tmp 样本时生效，纯只读。
    """
    if not GROUND_TRUTH_FILE.exists():
        return None
    try:
        raw_lines = GROUND_TRUTH_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    latest: dict[str, dict[str, Any]] = {}
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        record_id = str(item.get("record_id") or "")
        if record_id:
            latest[record_id] = item
    successes = [item for item in latest.values() if item.get("status") == "success"]
    if not successes:
        return None

    from app.modules.safety.ai_hazard_identification.rules import RuleEngine
    from app.modules.safety.ai_hazard_identification.schemas import (
        DefectSubstanceEnum,
        HazardCategoryEnum,
        HazardIdentificationInput,
        HazardIdentificationOutput,
        HazardLevelEnum,
        HazardTypeEnum,
        RectificationSuggestion,
    )

    engine = RuleEngine()
    rule_errors = 0
    error_examples: list[str] = []
    checked = 0
    for item in successes:
        basis = str(item.get("basis_new") or "").strip()
        if not basis:
            continue
        checked += 1
        try:
            output = HazardIdentificationOutput(
                key_defect="合规的隐患描述示例文本用于规则校验",
                hazard_type=HazardTypeEnum(str(item.get("hazard_type") or "unsafe_condition")),
                hazard_category=HazardCategoryEnum(
                    str(item.get("hazard_category") or "equipment")
                ),
                hazard_level=HazardLevelEnum(str(item.get("hazard_level") or "general")),
                rectification_suggestion=RectificationSuggestion(
                    corrective="由责任部门在3日内完成整改并组织复查验收，记录留档备查。",
                    preventive="将该部位纳入班组日常巡检清单，每月复核一次并开展专项培训。",
                ),
                major_hazard_basis=basis,
                defect_substance=DefectSubstanceEnum.SUBSTANTIVE,
                defect_substance_reasoning="推断链不超过2步，属直接物理风险，判定为实质缺陷。",
            )
            result = engine.validate(
                HazardIdentificationInput(
                    description="隐患描述", department="生产部", location="合成车间"
                ),
                output,
            )
        except Exception:  # noqa: BLE001 — 枚举异常的样本单独计为不通过
            rule_errors += 1
            if len(error_examples) < 5:
                error_examples.append(f"{item.get('record_id')}: schema/enum error")
            continue
        if result.errors:
            rule_errors += 1
            if len(error_examples) < 5:
                error_examples.append(f"{item.get('record_id')}: {result.errors[0][:100]}")
    return {
        "checked_records": checked,
        "rule_errors": rule_errors,
        "error_examples": error_examples,
    }


# ═══════════════════════════════════════════════════════════════
# Markdown 渲染
# ═══════════════════════════════════════════════════════════════


def render_markdown(stats: dict[str, Any], *, days: int) -> str:
    totals = stats["totals"]
    vision = stats["vision"]
    text = stats["text"]
    lines = [
        "# ① 隐患 AI 识别离线质量回归（只读重放）",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 数据源：`safety.ai_call_audits`（scenario=`{SCENARIO}`，近 {days} 天，只读）",
        f"- 样本：{totals['calls']} 次调用（视觉 {vision['calls']} / 文本 {text['calls']}）",
        "",
        "## JSON 合法率（A1 本地修复，零额外调用）",
        "",
        "> 口径（T3）：「现状合法」= 剥 markdown 围栏后 `json.loads`；审计",
        "> `extra.json_valid` 是「原文可直接解析、不剥围栏」，两者不可直接对比。",
        "",
        "| 链路 | 调用数 | 现状合法 | 修复后合法 | 修复后提升 | 本地修复数 |",
        "|---|---|---|---|---|---|",
        f"| 视觉 | {vision['calls']} | {vision['json_valid_before_rate']}% | "
        f"{vision['json_valid_after_rate']}% | "
        f"+{round(vision['json_valid_after_rate'] - vision['json_valid_before_rate'], 1)}pp | "
        f"{vision['repaired']} |",
        f"| 文本 | {text['calls']} | {text['json_valid_before_rate']}% | "
        f"{text['json_valid_after_rate']}% | "
        f"+{round(text['json_valid_after_rate'] - text['json_valid_before_rate'], 1)}pp | "
        f"{text['repaired']} |",
        f"| 合计 | {totals['calls']} | {totals['json_valid_before_rate']}% | "
        f"{totals['json_valid_after_rate']}% | "
        f"+{round(totals['json_valid_after_rate'] - totals['json_valid_before_rate'], 1)}pp | "
        f"{totals['repaired_recovered']} |",
        "",
        f"- 修复阶段分布：`{json.dumps(stats['repair_stages'], ensure_ascii=False)}`",
        "",
        "## 质量闸门（A3）",
        "",
        f"- 通过：**{totals['gate_pass_calls']}**（{totals['gate_pass_rate']}%）",
        f"- 拒绝：**{totals['gate_fail_calls']}**（分类：`{json.dumps(stats['gate_categories'], ensure_ascii=False)}`）",
        f"- 不可解析（json_invalid）：{totals['gate_unparseable_calls']}",
        f"- 占位依据调用：{totals['placeholder_calls']}（{totals['placeholder_rate']}%）",
        f"- RAG 降级调用（degradation_level 非 ragplus）：{totals['degraded_calls']}",
        "",
        "## 重跑窗口（调用数最多的一天，按记录聚合）",
        "",
        f"- 日期：{stats['rerun_day'] or '(无数据)'}",
        f"- 记录数：{stats['rerun_records']['records']}；调用数：{stats['rerun_records']['calls']}",
        f"- 闸门通过记录：**{stats['rerun_records']['gate_pass_records']}** / "
        f"拒绝记录：**{stats['rerun_records']['gate_fail_records']}**",
        "",
    ]
    truth = stats.get("ground_truth")
    if truth:
        lines += [
            "## 197 条 ground truth 一致性（/tmp/rerun_results.jsonl）",
            "",
            f"- ground truth 记录：{truth['ground_truth_records']}；重放命中：{truth['replayed_records']}",
            f"- 误拒（truth=success 但闸门拒绝，语义差异）：**{truth['wrong_reject']}**",
            f"- 误收（truth=failed 但闸门通过）：**{truth['wrong_accept']}**"
            f"（其中 A1 修复救援 {truth.get('wrong_accept_repaired_rescue', 0)} 条、"
            f"真正语义不一致 {truth.get('wrong_accept_genuine', 0)} 条）",
            "",
        ]
    rules = stats.get("rule_regression")
    if rules:
        lines += [
            "## A4 规则回归（197 条 ground truth 成功样本）",
            "",
            f"- 校验样本：{rules['checked_records']}；规则 error 记录：**{rules['rule_errors']}**",
        ]
        for example in rules["error_examples"]:
            lines.append(f"  - {example}")
        lines.append("")

    lines += [
        "## 按天趋势",
        "",
        "| 日期 | 调用 | 现状合法 | 修复后合法 | 修复 | 闸门通过 | 占位 |",
        "|---|---|---|---|---|---|---|",
    ]
    for day, slot in stats["by_day"].items():
        lines.append(
            f"| {day} | {slot['calls']} | {slot['json_before']} | {slot['json_after']} | "
            f"{slot['repaired']} | {slot['gate_pass']} | {slot['placeholder']} |"
        )
    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# DB（只读）
# ═══════════════════════════════════════════════════════════════


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


def _to_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def fetch_rows(dsn: str, *, days: int, scenario: str, limit: int) -> list[dict[str, Any]]:
    """只读查询审计行（显式 read-only 事务）。"""
    import asyncpg

    conn = await asyncpg.connect(_to_asyncpg_dsn(dsn))
    try:
        await conn.execute("SET default_transaction_read_only = on")
        await conn.execute("SET statement_timeout = '120s'")
        records = await conn.fetch(
            """
            SELECT id::text AS id,
                   created_at,
                   status,
                   degradation_level,
                   input_text,
                   output_text,
                   extra::text AS extra
            FROM safety.ai_call_audits
            WHERE scenario = $1
              AND output_text IS NOT NULL
              AND created_at > now() - ($2 || ' days')::interval
            ORDER BY created_at
            LIMIT $3
            """,
            scenario,
            str(max(1, days)),
            limit,
        )
        return [dict(record) for record in records]
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="① 隐患 AI 识别离线质量回归（只读）")
    parser.add_argument("--days", type=int, default=30, help="回看天数（默认 30）")
    parser.add_argument("--scenario", default=SCENARIO, help="审计场景（默认 hazard_identification）")
    parser.add_argument("--dsn", default="", help="PG DSN（默认读 DATABASE_URL / .env.development）")
    parser.add_argument("--limit", type=int, default=5000, help="最多读取行数（默认 5000）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    parser.add_argument("--out", default="", help="写入文件（默认 stdout）")
    args = parser.parse_args(argv)

    dsn = args.dsn or _dsn_from_env()
    if not dsn:
        print("未找到数据库 DSN（--dsn / DATABASE_URL / .env.development）", file=sys.stderr)
        return 2

    rows = asyncio.run(
        fetch_rows(dsn, days=args.days, scenario=args.scenario, limit=args.limit)
    )
    stats = analyze_rows(rows)
    truth = compare_ground_truth(rows)
    if truth is not None:
        stats["ground_truth"] = truth
    rule_regression = rule_regression_from_ground_truth()
    if rule_regression is not None:
        stats["rule_regression"] = rule_regression

    if args.json:
        payload = json.dumps(stats, ensure_ascii=False, indent=2)
    else:
        payload = render_markdown(stats, days=args.days)

    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"已写入 {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
