"""R3 漏审日判定 + 补跑 adapter（一期作业票审核 + 二期中控报警日报）。

漏审日判定（§4.4 纯程序推导，扫描源 ``ops:job:<job>:<D>:missed`` trigger
即权威定局——窗口耗尽仍 failed 且当日重试不计）：

- 作业票：run_on D 审 D-1（scheduler.py:891 语义）→ 漏审 run 日 D 的补跑
  审核日 = D-1（``missed_review_date``）；
- 中控报警日报：D 日报当日（无 D-1 偏移）→ 补跑生成日 = D；
- 恢复恰逢当日任务运行期不并发补当日（D=今日且窗口未耗尽 → scan 不产
  missed，天然不补）；
- 每事件 ≤5 日（拍板 #4；超出的上卡标 needs_human）；
- 跨工单去重：以 r3_repair job_backfill effect（dedupe 含 run_day 集合）
  为准——同集合幂等，后续工单只见增量。

补跑核心：
- 作业票 ``WorkTicketReviewService.run_review(D-1, push=False)``——
  与 POST /workticket-review/run 同核心；
- 中控报警 ``CentralAlarmService.generate_daily_report(target_date=D, push=False)``
  （天然带日期参数；push=False 不进当日速递格，结果走 R3 修复结果卡）；
- push=False（补跑历史日不进推送通道）；逐日失败重试 1 次再败记录继续其余日。
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Any

from sqlalchemy import select

from app.modules.safety.service.ops_selfheal_r3 import signals
from app.modules.safety.service.ops_selfheal_r3.scan_source import missed_review_date

logger = logging.getLogger(__name__)

#: 补跑 adapter 注册表（job_name → 标识；其余 job 上卡需人工）
BACKFILL_ADAPTERS: dict[str, str] = {
    "作业票审核": "workticket",
    "中控报警日报": "central_alarm",  # 二期 D：矩阵化第二列
}


async def determine_missed_days(
    session: Any, job_name: str, *, cap: int = 5,
) -> tuple[list[str], bool]:
    """漏审 run 日清单（missed trigger 权威定局；最近优先 ≤cap）。

    Returns:
        (run_days, overflow)——overflow=True 表示超 cap 需人工关注。
    """
    from app.modules.safety.service.ops_selfheal_r3.rule import R3_SCAN_SOURCE_NAME
    from app.platform.superagent.models import AgentSource, AgentTrigger

    src = (
        await session.execute(
            select(AgentSource).where(AgentSource.name == R3_SCAN_SOURCE_NAME)
        )
    ).scalar_one_or_none()
    if src is None:
        return [], False
    prefix = f"ops:job:{job_name}:"
    suffix = ":missed"
    rows = (
        await session.execute(
            select(AgentTrigger.external_id).where(
                AgentTrigger.source_id == src.id,
                AgentTrigger.external_id.like(f"{prefix}%{suffix}"),
            )
        )
    ).scalars().all()
    days = sorted({
        eid[len(prefix):-len(suffix)]
        for eid in rows
        if eid.startswith(prefix) and eid.endswith(suffix)
    }, reverse=True)
    return days[:cap], len(days) > cap


async def backfilled_run_days(session: Any, job_name: str) -> dict[str, set[str]]:
    """已有 job_backfill 修复 effect 覆盖的 run 日（按状态分组；跨工单去重口径）。

    Returns:
        {"pending": {run_day…}, "done": {run_day…}}——done=已终态（成功/失败
        皆终态，失败项在修复结果卡中呈报）；pending=执行中（repair_done 回注）。
    """
    from app.platform.superagent.models import AgentEffect

    rows = (
        await session.execute(
            select(AgentEffect.payload, AgentEffect.status).where(
                AgentEffect.kind == "r3_repair",
                AgentEffect.status.in_(("pending", "done")),
            )
        )
    ).all()
    covered: dict[str, set[str]] = {"pending": set(), "done": set()}
    for payload, status in rows:
        p = payload or {}
        if p.get("action") == "job_backfill" and p.get("job_name") == job_name:
            covered.setdefault(status if status in covered else "pending", set()).update(
                str(d) for d in (p.get("run_days") or [])
            )
    return covered


async def backfill_workticket_days(run_days: list[str]) -> list[dict[str, Any]]:
    """逐日补跑作业票审核（review=D-1、push=False；失败重试 1 次再败记录继续）。"""
    from app.modules.safety.workticket_review.service import WorkTicketReviewService

    results: list[dict[str, Any]] = []
    for run_day in run_days:
        try:
            review_date = date_type.fromisoformat(missed_review_date(run_day))
        except ValueError:
            results.append({"run_day": run_day, "review_date": None,
                            "status": "failed", "error": "run_day 非法日期"})
            continue
        outcome: dict[str, Any] | None = None
        last_error: str | None = None
        for _attempt in (1, 2):  # 失败重试 1 次（§4.5）
            from app.core.database import async_session_factory

            try:
                async with async_session_factory() as session:
                    service = WorkTicketReviewService(session)
                    stats = await service.run_review(review_date, push=False)
                outcome = {
                    "run_day": run_day, "review_date": review_date.isoformat(),
                    "status": "done",
                    "total": stats.get("total"),
                    "reviewed": stats.get("reviewed"),
                    "violation_count": stats.get("violation_count"),
                }
                break
            except Exception as exc:  # noqa: BLE001 — 逐日隔离
                last_error = f"{type(exc).__name__}: {exc}"[:300]
                logger.warning("R3 补跑失败（run_day=%s attempt=%d）: %s",
                               run_day, _attempt, last_error)
        if outcome is None:
            outcome = {
                "run_day": run_day, "review_date": review_date.isoformat(),
                "status": "failed", "error": last_error,
            }
        results.append(outcome)
    return results


async def backfill_central_alarm_days(run_days: list[str]) -> list[dict[str, Any]]:
    """逐日补跑中控报警日报（target_date=D 当日无偏移、push=False；失败重试 1 次）。

    日报语义 = 生成 D 日报告（rolling 窗口 D-1 17:00 ~ D 17:00）；漏跑日 D 的
    报告缺失即补 D。push=False 不进群推送，结果走 R3 修复结果卡（管理员可
    从观测页回看，如需群补发走人工）。
    """
    results: list[dict[str, Any]] = []
    for run_day in run_days:
        try:
            target_date = date_type.fromisoformat(run_day)
        except ValueError:
            results.append({"run_day": run_day, "review_date": None,
                            "status": "failed", "error": "run_day 非法日期"})
            continue
        outcome: dict[str, Any] | None = None
        last_error: str | None = None
        for _attempt in (1, 2):  # 失败重试 1 次（§4.5）
            from app.core.database import async_session_factory

            try:
                async with async_session_factory() as session:
                    from app.modules.safety.service.central_alarm.service import (
                        CentralAlarmService,
                    )

                    service = CentralAlarmService(session)
                    report = await service.generate_daily_report(
                        target_date=target_date, push=False, channel="system",
                        rolling=True,
                    )
                outcome = {
                    "run_day": run_day, "review_date": run_day,
                    "status": "done",
                    "total": getattr(report, "total", None),
                    "reviewed": None,
                    "violation_count": None,
                    "pushed": sum(
                        1 for p in (getattr(report, "push_results", None) or [])
                        if p.get("success")
                    ),
                }
                break
            except Exception as exc:  # noqa: BLE001 — 逐日隔离
                last_error = f"{type(exc).__name__}: {exc}"[:300]
                logger.warning("R3 中控日报补跑失败（run_day=%s attempt=%d）: %s",
                               run_day, _attempt, last_error)
        if outcome is None:
            outcome = {
                "run_day": run_day, "review_date": run_day,
                "status": "failed", "error": last_error,
            }
        results.append(outcome)
    return results
