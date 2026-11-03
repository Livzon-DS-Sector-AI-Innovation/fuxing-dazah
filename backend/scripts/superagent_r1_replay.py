"""R1 口径对齐回放 —— 修正字段名+闭环子规则的 observe replay（冒烟③基线对照）。

用法（在 backend/ 下）：
    .venv/bin/python -m scripts.superagent_r1_replay [--days 7] [--out /path/report.md]

与底座冒烟③脚本（superagent_replay_smoke3.py，历史基线 39 条→1 候选）的差异：
1. 字段名修正：规则判 fields.报警性质 / fields.报警原因分类（冒烟③用的
   「原因分类」恒 None——白名单路径全部失效，基线 1 候选是错位产物）；
2. 闭环子规则：处理情况分类（移交无回执/明示待办/空）进候选（§9.1 增量）；
3. replay 标注不污染在线 observe 计数；只记 Decision 不执行不开任务。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("r1_replay")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPLAY_SOURCE_NAME = "safety.fire_alarm.r1.replay"


async def run(days: int, out_path: str | None) -> dict:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.service.alarm_hazard_r1.closure import classify_closure
    from app.modules.safety.service.alarm_hazard_r1.scan_source import (
        fetch_fire_alarm_window,
    )
    from app.modules.safety.superagent_bridge import ensure_r1_policy
    from app.platform.superagent.bitable_poll import relevant_fingerprint
    from app.platform.superagent.ingest import ingest_draft
    from app.platform.superagent.models import AgentSource
    from app.platform.superagent.policy import evaluate_trigger, get_current_policy
    from app.platform.superagent.sources import TriggerDraft

    await ensure_r1_policy()

    async with async_session_factory() as session:
        src = (
            await session.execute(
                select(AgentSource).where(AgentSource.name == REPLAY_SOURCE_NAME)
            )
        ).scalar_one_or_none()
        if src is None:
            src = AgentSource(
                kind="cron_scan", name=REPLAY_SOURCE_NAME,
                config={
                    "window_days": days,
                    "relevant_fields": ["报警性质", "报警原因分类", "处理情况"],
                    "evaluate": True, "thread_prefix": "fire_alarm_replay",
                },
                enabled=False,
            )
            session.add(src)
            await session.flush()

        records = await fetch_fire_alarm_window(days)
        logger.info("近 %d 天消防记录 %d 条", days, len(records))

        policy = await get_current_policy(session)
        assert policy is not None, "R1 Policy ensure 失败"

        accepted: list[dict] = []
        rejected: list[dict] = []
        for rec in records:
            fields = rec.get("fields") or {}
            rid = rec.get("record_id") or ""
            if not rid:
                continue
            fp = relevant_fingerprint(fields, src.config["relevant_fields"])
            closure = classify_closure(fields.get("处理情况"))
            _, trigger = await ingest_draft(session, src, TriggerDraft(
                external_id=f"fire_alarm:{rid}:{fp}",
                thread_key=f"bitable:fire_alarm_replay:{rid}",
                actor={"id": rid, "type": "bitable_record"},
                payload={
                    "record_id": rid, "fields": fields, "fingerprint": fp,
                    "_derived": {"closure_class": closure},
                },
            ))
            decisions = await evaluate_trigger(
                session, trigger, policy=policy, source_name="safety.fire_alarm.r1",
                replay=True,
            )
            summary = {
                "record_id": rid,
                "报警性质": _plain(fields.get("报警性质")),
                "报警原因分类": _plain(fields.get("报警原因分类")),
                "部门": _plain_list(fields.get("报警部门负责人.部门")),
                "closure": closure,
                "处理情况": (_plain(fields.get("处理情况")) or "")[:60],
                "hit": any(d.would_accept for d in decisions),
            }
            (accepted if summary["hit"] else rejected).append(summary)

        await session.commit()

        report = {
            "window_days": days,
            "total": len(records),
            "candidates": len(accepted),
            "by_nature": Counter(x["报警性质"] for x in accepted),
            "by_cause": Counter(x["报警原因分类"] for x in accepted),
            "by_closure": Counter(x["closure"] for x in accepted),
            "accepted": accepted,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        _write_report(report, out_path)
        return report


def _plain(value) -> str:
    if isinstance(value, list):
        return "".join(
            str(i.get("text") or i.get("name") or "") if isinstance(i, dict) else str(i)
            for i in value
        )
    return str(value or "")


def _plain_list(value) -> str:
    if isinstance(value, list):
        return "、".join(str(i) for i in value)
    return str(value or "")


def _write_report(report: dict, out_path: str | None) -> None:
    text = [
        "# R1 口径对齐回放（修正字段名 + 闭环子规则）——observe replay",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 回放窗口：近 {report['window_days']} 天",
        f"- 总记录：{report['total']}；候选（would_accept）：{report['candidates']}",
        f"- 候选性质分布：{dict(report['by_nature'])}",
        f"- 候选原因分布：{dict(report['by_cause'])}",
        f"- 候选闭环分类分布：{dict(report['by_closure'])}",
        "",
        "## 与冒烟③基线（39 条→1 候选）的差异归因",
        "",
        "- 冒烟③规则字段 `fields.原因分类` 恒 None（表列名实为 `报警原因分类`）→",
        "  白名单四值路径全部失效、故障子规则退化为「性质=故障报警 即进」；",
        "  基线 1 候选（故障报警·原因空）是错位产物。",
        "- 本次修正后白名单路径恢复；另叠加闭环子规则（移交无回执/明示待办/空）。",
        "",
        "## 候选清单（供人工比对：逐条标注 真/误报）",
        "",
    ]
    for x in report["accepted"]:
        text.append(
            f"- [ ] `{x['record_id'][:16]}…` {x['报警性质']}｜{x['报警原因分类']}"
            f"｜{x['部门']}｜closure={x['closure']}｜处理: {x['处理情况'] or '—'}"
        )
    body = "\n".join(text) + "\n"
    if out_path:
        Path(out_path).write_text(body, encoding="utf-8")
        print(f"报告已写入 {out_path}")
    else:
        print(body)
    Path("/tmp/r1_replay.json").write_text(
        json.dumps(
            {k: v for k, v in report.items() if k != "accepted"},
            ensure_ascii=False, default=str,
        ) + f"\naccepted={len(report['accepted'])}",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.days, args.out))
