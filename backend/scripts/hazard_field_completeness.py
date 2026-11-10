"""P2-4 T02 —— 隐患登记表全表只读扫描：①②⑤字段完整率+重大误判分层报告。

只读零写：全表拉取 + 指标全走 ``hazard_field_metrics`` 纯函数 +
``ai_call_audits`` 只读交叉（P2 窗口圈定 / 机械补跑候选 / trace 估算）。
产出 Markdown 报告（默认落 .scratch/hazard-p2-closeout/evidence/）。

口径：.scratch/hazard-p2-closeout/spec.md §4.1/4.2。
- 督办豁免开关默认读 app_config（③督办轮询开启 → ①督办列豁免）；
- P2 窗口 = 2026-11-05（golden v2.0 上线）后 ai_call_audits 成功处理过的记录；
- 机械补跑候选 = ①列缺值记录 ∩ 30 天窗口内有该 record 成功输出。

用法（cwd=backend）::

    .venv/bin/python scripts/hazard_field_completeness.py \
        --out ../.scratch/hazard-p2-closeout/evidence/field-metrics-report.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime  # noqa: DTZ001 — p2_start 显式带 +00:00
from pathlib import Path
from typing import Any

sys.path.insert(0, os.getcwd())

from app.modules.safety.service.hazard_direct import hazard_field_metrics as hfm  # noqa: E402
from app.modules.safety.service.hazard_direct.field_authority import (  # noqa: E402
    F_LEVEL_AI,
)

P2_WINDOW_START = "2026-11-05"  # golden v2.0 上线日（fewshot 3 例）


def _to_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


async def _fetch_audits(dsn: str, p2_start: str) -> dict[str, Any]:
    """只读审计交叉数据：①成功输出（record_id→row）、各链 P2 窗口圈集、scenario 计数。"""
    import asyncpg

    conn = await asyncpg.connect(_to_asyncpg_dsn(dsn))
    try:
        ident = await conn.fetch(
            """
            SELECT extra->>'bitable_record_id' AS rid, output_text, created_at
            FROM safety.ai_call_audits
            WHERE scenario = 'hazard_identification'
              AND status = 'success'
              AND output_text IS NOT NULL
              AND extra->>'bitable_record_id' IS NOT NULL
              AND created_at > now() - interval '30 days'
            """
        )
        # 各链 P2 窗口独立圈定（②⑤在窗口内处理但①识别早于窗口的记录不漏计）
        chain_rows = await conn.fetch(
            """
            SELECT scenario, extra->>'bitable_record_id' AS rid
            FROM safety.ai_call_audits
            WHERE scenario IN ('hazard_identification', 'rectification_review',
                               'hazard_scoring')
              AND status = 'success'
              AND extra->>'bitable_record_id' IS NOT NULL
              AND created_at >= $1::timestamptz
            """,
            datetime.fromisoformat(f"{p2_start}T00:00:00+00:00"),
        )
        scenario_to_chain = {
            "hazard_identification": "ai",
            "rectification_review": "review",
            "hazard_scoring": "scoring",
        }
        p2_rids: dict[str, set[str]] = {"ai": set(), "review": set(), "scoring": set()}
        for r in chain_rows:
            chain = scenario_to_chain[r["scenario"]]
            if r["rid"]:
                p2_rids[chain].add(r["rid"])
        scenarios = await conn.fetch(
            """
            SELECT scenario, count(*) AS n, round(avg(input_tokens)) AS avg_in
            FROM safety.ai_call_audits
            WHERE created_at > now() - interval '30 days'
            GROUP BY scenario ORDER BY n DESC
            """
        )
        trig = await conn.fetchrow(
            "SELECT count(*) AS n FROM superagent.agent_triggers"
        )
        return {
            "ident_success": {r["rid"]: r["output_text"] for r in ident},
            "p2_rids": p2_rids,
            "scenarios": [dict(r) for r in scenarios],
            "triggers_total": trig["n"],
        }
    finally:
        await conn.close()


def _render(
    stats: dict[str, hfm.CompletenessStat],
    p2_stats: dict[str, hfm.CompletenessStat],
    layers: hfm.MisjudgementLayers,
    p2_layers: hfm.MisjudgementLayers,
    *,
    backfillable: list[str],
    field_count: int,
    supervision_exempt: bool,
    p2_start: str,
    audits: dict[str, Any],
    total: int,
) -> str:
    chain_names = {
        hfm.CHAIN_AI: "① AI 识别",
        hfm.CHAIN_REVIEW: "② AI 初审",
        hfm.CHAIN_SCORING: "⑤ AI 评分",
    }
    p2_counts = audits["p2_rids"]
    lines = [
        "# P2-4 双指标量化报告（全表只读扫描）",
        "",
        f"- 扫描时间：{datetime.now(UTC).isoformat()}｜全表 {total} 条｜列数 {field_count}"
        f"（治理清单口径 50→44）",
        f"- 督办豁免：{'开（③督办轮询开启，①督办列豁免单列）' if supervision_exempt else '关（督办列计入必填）'}",
        f"- P2 窗口 = {p2_start}（golden v2.0 上线）后各链 ai_call_audits 成功处理的记录"
        f"（按链独立圈定：① {len(p2_counts['ai'])} / ② {len(p2_counts['review'])} / "
        f"⑤ {len(p2_counts['scoring'])} 条）",
        "",
        "## 一、①②⑤字段完整率（必填格率+条件豁免）",
        "",
        "| 链 | 全表分母 | 全表总率 | P2 窗口分母 | P2 窗口总率 |",
        "|---|---|---|---|---|",
    ]
    for chain, name in chain_names.items():
        s = stats[chain]
        p2s = p2_stats[chain]
        lines.append(
            f"| {name} | {s.denominator} | **{_pct(s.overall_rate)}** | "
            f"{p2s.denominator} | **{_pct(p2s.overall_rate)}** |"
        )
    lines += ["", "### 逐列明细与缺值清单", ""]
    for chain, name in chain_names.items():
        s = stats[chain]
        lines.append(f"**{name}**（豁免：{s.exempt or '无'}）")
        lines += ["", "| 列 | 必填格 | 已填 | 完整率 | 缺值记录 |", "|---|---|---|---|---|"]
        for col in s.columns.values():
            missing = ", ".join(col.missing_records[:20]) or "—"
            if len(col.missing_records) > 20:
                missing += f" …等 {len(col.missing_records)} 条"
            lines.append(
                f"| {col.name} | {col.required_cells} | {col.filled_cells} | "
                f"{_pct(col.rate)} | {missing} |"
            )
        lines.append("")

    lines += [
        "## 二、重大误判分层（人工为真值，多值取最高归一）",
        "",
        "| 层 | 定义 | 全表 | P2 窗口（11-05 后 AI 处理） |",
        "|---|---|---|---|",
        f"| L1 致命 | AI=重大且人工≠重大 | {len(layers.l1_fatal)} | {len(p2_layers.l1_fatal)} |",
        f"| L2 升格 | AI>人工其余 | {len(layers.l2_upgrades)} | {len(p2_layers.l2_upgrades)} |",
        f"| L3 降格 | AI<人工（只列清单） | {len(layers.l3_downgrades)} | {len(p2_layers.l3_downgrades)} |",
        f"| 一致 | — | {layers.agreed} | {p2_layers.agreed} |",
        f"| 跳过（单侧空） | — | {layers.skipped_missing} | {p2_layers.skipped_missing} |",
        "",
    ]
    for title, rows, cap in (
        ("L1 致命（全表）", layers.l1_fatal, 0),
        ("L2 升格（全表，前 30 条）", layers.l2_upgrades, 30),
        ("L3 降格（全表）", layers.l3_downgrades, 0),
    ):
        shown = rows[:cap] if cap else rows
        lines.append(f"### {title}（{len(rows)} 条）")
        lines += ["", "| record_id | AI | 人工 | 整改状态 | 描述 |", "|---|---|---|---|---|"]
        for row in shown:
            desc = row.description[:30].replace("|", "／")
            lines.append(
                f"| {row.record_id} | {row.ai_level} | {row.manual_level} | "
                f"{row.rectify_status or '—'} | {desc} |"
            )
        lines.append("")

    lines += [
        "## 三、机械补跑候选（①列缺值 ∩ 30 天审计有成功输出，零新增 AI 调用）",
        "",
        f"- 共 {len(backfillable)} 条：{', '.join(backfillable[:30]) or '无'}"
        + (f" …等 {len(backfillable)} 条" if len(backfillable) > 30 else ""),
        "- 其余缺值记录走「清单裁决」（需 AI 重判或人工裁决）",
        "",
        "## 四、trace 常开数据量估算素材",
        "",
        "| scenario | 30 天调用数 | avg input tokens |",
        "|---|---|---|",
    ]
    for row in audits["scenarios"]:
        lines.append(f"| {row['scenario']} | {row['n']} | {row['avg_in'] or '—'} |")
    lines += [
        "",
        f"- agent_triggers 现有量：{audits['triggers_total']} 行",
        "- 写回留痕行增长 ≈ ①成功写回/天 + ②初审+autopass/天（+⑤开启时）×"
        " payload ~700B/行；详细估算见收口档 trace-decision.md",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="../.scratch/hazard-p2-closeout/evidence/field-metrics-report.md",
    )
    parser.add_argument(
        "--supervision-exempt",
        choices=["auto", "on", "off"],
        default="auto",
        help="①督办列豁免（auto=读 app_config ③督办轮询开关）",
    )
    parser.add_argument(
        "--p2-start", default=P2_WINDOW_START,
        help=f"P2 窗口起点日期（默认 {P2_WINDOW_START}=golden v2.0 上线）",
    )
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.modules.safety.app_config.store import store as config_store
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    if args.supervision_exempt == "auto":
        supervision_exempt = config_store.get_bool(
            "SAFETY_HAZARD_SUPERVISION_POLL_ENABLED", False
        )
    else:
        supervision_exempt = args.supervision_exempt == "on"

    client = SafetyBitableClient()
    records = await client.list_all_records(strict=True)
    fields = await client.list_fields()
    audits = await _fetch_audits(str(get_settings().DATABASE_URL), args.p2_start)

    stats = hfm.completeness_report(records, supervision_exempt=supervision_exempt)
    layers = hfm.misjudgement_layers(records)

    # 各链 P2 窗口独立圈定（misjudgement 沿①圈集——级别判据只来自①识别输出）
    chain_key = {
        hfm.CHAIN_AI: "ai",
        hfm.CHAIN_REVIEW: "review",
        hfm.CHAIN_SCORING: "scoring",
    }
    p2_stats: dict[str, hfm.CompletenessStat] = {}
    for chain, key in chain_key.items():
        subset = [
            r for r in records if r.get("record_id") in audits["p2_rids"][key]
        ]
        p2_stats[chain] = hfm.completeness_report(
            subset, supervision_exempt=supervision_exempt
        )[chain]
    p2_layers = hfm.misjudgement_layers(
        [r for r in records if r.get("record_id") in audits["p2_rids"]["ai"]]
    )

    # 机械补跑候选（①列缺值 ∩ 30 天审计有成功输出）
    missing_rids: set[str] = set()
    for col in stats[hfm.CHAIN_AI].columns.values():
        missing_rids.update(col.missing_records)
    backfillable = sorted(missing_rids & set(audits["ident_success"]))

    report = _render(
        stats,
        p2_stats,
        layers,
        p2_layers,
        backfillable=backfillable,
        field_count=len(fields),
        supervision_exempt=supervision_exempt,
        p2_start=args.p2_start,
        audits=audits,
        total=len(records),
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"报告已写入 {out.resolve()}（全表 {len(records)} 条，列 {len(fields)}）")
    print(f"①分母 {stats[hfm.CHAIN_AI].denominator}｜总率 {_pct(stats[hfm.CHAIN_AI].overall_rate)}")
    print(f"L1={len(layers.l1_fatal)} L2={len(layers.l2_upgrades)} L3={len(layers.l3_downgrades)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
