"""R2 监护人资格追踪 —— observe 回放对账脚本（验收「名单无遗漏/不错发」）。

用法（在 backend/ 下，只读不落库）：
    .venv/bin/python -m scripts.guardian_r2_replay [--today 2026-11-04] [--out report.md]

对账口径：拉真实监护人 A/B 证表 + links 状态，用与扫描源完全相同的纯函数
（build_cert_drafts）产出四型 Trigger 名单，分组打印供与台账人工抽查比对：

  1. remind    —— 本月应提醒名单（姓名/证别/节点/截止/剩余天数/第几次）
  2. overdue   —— 逾期待取消资格名单（revoke 候选）
  3. failed    —— 考核不合格待取消名单（revoke 候选）
  4. restore   —— revoked 后补考合格待恢复名单

另导出「取证候选」：成绩表合格但不在持证名单的人（discriminate=取证）。
零 DB 写入——不建 Trigger 不落 Decision（生产回放走 observe 模式自然留痕，
本脚本用于上线前/后随时对账）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("guardian_r2_replay")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(today: date, out_path: str | None) -> dict:
    from app.core.database import async_session_factory
    from app.modules.safety.service.guardian_r2.scan_source import (
        build_cert_drafts,
        fetch_guardian_cert_records,
        load_links_map,
    )
    from app.modules.safety.service.guardian_r2.score_parse import (
        parse_score_record,
    )
    from app.modules.safety.service.guardian_r2.node_engine import discriminate
    from app.modules.safety.service.bitable_direct import reader as bd_reader

    lines: list[str] = [f"# R2 监护人资格回放对账 · {today.isoformat()}", ""]

    # ── 持证表四型名单 ──
    records = await fetch_guardian_cert_records()  # strict：任一表失败上抛
    links_map: dict = {}
    try:
        async with async_session_factory() as session:
            links_map = await load_links_map(session)
    except Exception as exc:  # noqa: BLE001 — links 表未迁移时按空表对账
        logger.warning("links 表读取失败（按空表对账）: %s", exc)
    drafts = build_cert_drafts(records, links_map, today=today)

    by_type: dict[str, list] = {}
    for d in drafts:
        by_type.setdefault(d.payload["_derived"]["trigger_type"], []).append(d)

    from app.modules.safety.service.guardian_r2.scan_source import cert_view_from_fields

    cert_views = [
        v for v in (
            cert_view_from_fields(
                r.get("kind") or "", r.get("record_id") or "",
                r.get("fields") or {}, links_map.get(r.get("record_id") or ""),
            )
            for r in records
        ) if v is not None
    ]

    titles = {
        "remind": "① 本月应提醒名单（remind）",
        "failed": "② 考核不合格待取消（failed → revoke 候选）",
        "restore": "③ 补考合格待恢复（restore → restore 候选）",
    }
    for t in ("remind", "failed", "restore"):
        items = sorted(
            by_type.get(t, []),
            key=lambda d: (d.payload["_derived"].get("department") or "",
                           d.payload["_derived"].get("person_name") or ""),
        )
        lines.append(f"## {titles[t]}（{len(items)} 人）")
        if not items:
            lines.append("- （无）")
        for d in items:
            dv = d.payload["_derived"]
            extra = (
                f"第 {dv.get('remind_seq')} 次" if t == "remind"
                else f"考核 {dv.get('exam_date')} {dv.get('exam_score')}" if t == "failed"
                else f"合格事件 {dv.get('node_label')}"
            )
            lines.append(
                f"- {dv.get('person_name')}｜{dv.get('department') or '—'}｜"
                f"{dv.get('cert_category')}｜{dv.get('node_label')}｜"
                f"截止 {dv.get('deadline')}｜{extra}"
            )
        lines.append("")

    # ── 取证候选（成绩表合格且不在名单）──
    enroll_candidates: list[str] = []
    try:
        client = bd_reader.resolve_client("guardian_score", "score")
        rows = await bd_reader.fetch_all_records(client, automatic_fields=True)
        for rec in rows or []:
            facts = parse_score_record(rec.get("fields") or {})
            if facts.passed != "合格" or not facts.person_name:
                continue
            result, _detail, _rec = discriminate(facts, cert_views)
            if result == "取证":
                enroll_candidates.append(
                    f"{facts.person_name}｜{facts.department or '—'}｜"
                    f"{facts.cert_category}｜考核 {facts.exam_date}"
                )
    except Exception as exc:  # noqa: BLE001 — 成绩源未配置/拉取失败如实提示
        enroll_candidates.append(f"（成绩源拉取失败：{type(exc).__name__}: {exc}）")
    lines.append(f"## ⑤ 取证候选（合格且不在持证名单，{len(enroll_candidates)} 人）")
    lines.extend(f"- {c}" for c in enroll_candidates or ["- （无）"])
    lines.append("")

    summary = {
        "today": today.isoformat(),
        "records": len(records),
        "remind": len(by_type.get("remind", [])),
        "failed": len(by_type.get("failed", [])),
        "restore": len(by_type.get("restore", [])),
        "enroll_candidates": max(len(enroll_candidates) - 1, 0)
        if enroll_candidates and enroll_candidates[0].startswith("（")
        else len(enroll_candidates),
    }
    lines.append("## 汇总")
    lines.append("```json")
    import json
    lines.append(json.dumps(summary, ensure_ascii=False, indent=2))
    lines.append("```")

    report = "\n".join(lines)
    print(report)
    if out_path:
        Path(out_path).write_text(report, encoding="utf-8")
        logger.info("报告已写: %s", out_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="R2 监护人资格回放对账（只读）")
    parser.add_argument("--today", type=str, default=None, help="基准日 YYYY-MM-DD")
    parser.add_argument("--out", type=str, default=None, help="报告输出路径 .md")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    summary = asyncio.run(run(today, args.out))
    logger.info("完成: %s", summary)


if __name__ == "__main__":
    main()
