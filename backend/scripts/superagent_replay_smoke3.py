"""冒烟③ —— 消防报警候选规则 observe 历史回放（初始一致率基线）。

用法（在 backend/ 下）：
    .venv/bin/python -m scripts.superagent_replay_smoke3 [--days 7] [--out /path/report.md]

行为：
- 只读消防 Bitable（近 N 天），逐条按指纹幂等落 Trigger（replay 源），
  evaluate_trigger(replay=True)——只记 Decision（would_accept）不执行、
  不开任务、不写业务表；replay 标注使其不污染在线 observe 计数。
- 产出：候选数/命中分布/逐条清单（供人工比对一致率）。
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
logger = logging.getLogger("smoke3_replay")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(days: int, out_path: str | None) -> dict:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.superagent_bridge import (
        seed_baseline_policy_if_absent,
    )
    from app.platform.superagent.bitable_poll import relevant_fingerprint
    from app.platform.superagent.ingest import ingest_draft
    from app.platform.superagent.models import AgentSource
    from app.platform.superagent.policy import evaluate_trigger, get_current_policy
    from app.platform.superagent.sources import TriggerDraft

    await seed_baseline_policy_if_absent()

    async with async_session_factory() as session:
        # replay 专用源行（enabled=false：不参与在线轮询，仅本次脚本写入）
        replay_name = "safety.fire_alarm.replay"
        src = (
            await session.execute(
                select(AgentSource).where(AgentSource.name == replay_name)
            )
        ).scalar_one_or_none()
        if src is None:
            src = AgentSource(
                kind="bitable_poll", name=replay_name,
                config={"fetcher": "fire_alarm_ledger", "thread_prefix": "fire_alarm_replay",
                        "relevant_fields": ["报警性质", "原因分类", "处理情况", "报警类型", "部门"],
                        "evaluate": True},
                enabled=False,
            )
            session.add(src)
            await session.flush()

        # 回放窗口按业务时间（报警时间）取近 N 天；修改水位传 0（全量进窗）
        from app.modules.safety.superagent_bridge import _fire_alarm_ledger_fetcher

        records = await _fire_alarm_ledger_fetcher(0)
        records = [
            r for r in records
            if _in_days(r.get("fields", {}).get("报警时间"), days)
        ]
        logger.info("近 %d 天消防记录 %d 条", days, len(records))

        policy = await get_current_policy(session)
        assert policy is not None, "基线 Policy 播种失败"

        accepted: list[dict] = []
        rejected: list[dict] = []
        for rec in records:
            fields = rec.get("fields") or {}
            rid = rec.get("record_id") or ""
            if not rid:
                continue
            fp = relevant_fingerprint(fields, src.config["relevant_fields"])
            _, trigger = await ingest_draft(session, src, TriggerDraft(
                external_id=f"{rid}:{fp}",
                thread_key=f"bitable:fire_alarm_replay:{rid}",
                actor={"id": rid, "type": "bitable_record"},
                payload={"record_id": rid, "fields": fields},
            ))
            decisions = await evaluate_trigger(
                session, trigger, policy=policy, source_name="safety.fire_alarm",
                replay=True,
            )
            summary = {
                "record_id": rid,
                "报警性质": _plain(fields.get("报警性质")),
                "原因分类": _plain(fields.get("原因分类")),
                "部门": _plain(fields.get("部门")),
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
            "by_cause": Counter(x["原因分类"] for x in accepted),
            "accepted": accepted,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        _write_report(report, out_path)
        return report


def _in_days(value, days: int) -> bool:
    """报警时间（富文本/毫秒）落在近 N 天（北京时间）。"""
    import re
    from zoneinfo import ZoneInfo

    if value is None:
        return False
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # Bitable 日期字段返回 epoch 毫秒
            ts /= 1000.0
    else:
        m = re.search(r"\d{4}-\d{2}-\d{2}", _plain(value))
        if not m:
            return False
        ts = datetime.fromisoformat(m.group(0)).timestamp()
    now = datetime.now(ZoneInfo("Asia/Shanghai")).timestamp()
    return now - days * 86400 <= ts <= now + 86400


def _plain(value) -> str:
    if isinstance(value, list):
        return "".join(
            str(i.get("text") or i.get("name") or "") if isinstance(i, dict) else str(i)
            for i in value
        )
    return str(value or "")


def _write_report(report: dict, out_path: str | None) -> None:
    text = [
        "# 冒烟③ observe 回放（消防候选规则）——初始一致率基线",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 回放窗口：近 {report['window_days']} 天",
        f"- 总记录：{report['total']}；候选（would_accept）：{report['candidates']}",
        f"- 候选性质分布：{dict(report['by_nature'])}",
        f"- 候选原因分布：{dict(report['by_cause'])}",
        "",
        "## 候选清单（供人工比对：逐条标注 真/误报 → 一致率 = 真报数/候选数）",
        "",
    ]
    for x in report["accepted"]:
        text.append(
            f"- [ ] `{x['record_id'][:16]}…` {x['报警性质']}｜{x['原因分类']}｜{x['部门']}"
            f"｜处理: {x['处理情况'] or '—'}"
        )
    body = "\n".join(text) + "\n"
    if out_path:
        Path(out_path).write_text(body, encoding="utf-8")
        print(f"报告已写入 {out_path}")
    else:
        print(body)
    Path("/tmp/smoke3_replay.json").write_text(
        json.dumps({k: v for k, v in report.items() if k != "accepted"}, ensure_ascii=False,
                   default=str) + f"\naccepted={len(report['accepted'])}",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()
    asyncio.run(run(args.days, args.out))
