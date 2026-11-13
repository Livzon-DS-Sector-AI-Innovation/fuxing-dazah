"""R3 L2 一键执行服务核心 —— REST 端点与卡片回调的单一判定路径。

双入口（REST extend-window / 卡片回调 window_extend）共用的会话内核心：
终态检查 → job 提取 → 当日幂等（进程 dict + DB 留痕双层）→ 覆写 →
decisions 留痕 → 结果卡。2026-11-13 审查修复：此前两端点各自实现已现
行为漂移（回调丢处方值/失败发成功样式卡），抽同源防再漂。

时区口径：当日/窗口判定统一 Asia/Shanghai（对齐 scan_source._TZ）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.modules.safety.service.ops_selfheal_r3 import signals

logger = logging.getLogger(__name__)


def _hm(hm: tuple[int, int]) -> str:
    return f"{hm[0]:02d}:{hm[1]:02d}"


async def today_extended_job(session: Any, job_name: str) -> bool:
    """DB 侧当日已改 job 查询（跨进程幂等兜底）。

    进程内 dict 只在各自进程一致——REST worker 与回调 worker 可能异进程。
    agent_inputs 的 ok=true l2_window_extend 行是全入口共享的权威留痕，
    当日同 job 命中即拒绝。payload 是不可信数据：仅作幂等键比对，不参与
    任何授权判定（授权由 RequireAdmin / 回调侧权限校验承担）。
    """
    from app.platform.superagent.models import AgentInput

    from app.modules.safety.service.ops_selfheal_r3.scan_source import _TZ

    now = datetime.now(_TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        await session.execute(
            select(AgentInput.payload).where(
                AgentInput.kind == "system",
                AgentInput.delivered_at >= day_start,
            )
        )
    ).scalars().all()
    for p in rows:
        p = p or {}
        if (p.get("type") == "l2_window_extend" and p.get("ok") is True
                and p.get("job_name") == job_name):
            return True
    return False


async def execute_window_extend(
    session: Any,
    task: Any,
    args: dict[str, Any] | None,
    *,
    operator: str,
) -> dict[str, Any]:
    """一键执行核心（session 由调用方提供；调用方负责 commit/40x 映射）。

    Returns:
        ok=True: {ok, job_name, old_window, new_window, ticket_id}
        ok=False: {ok, reason, job_name, current_window?, ticket_id}
        （reason 语义：not_open / no_job / already_extended_today / apply 失败原因）
    """
    from app.modules.safety.service.ops_selfheal_r3 import (
        cards,
        window_override,
    )
    from app.modules.safety.service.ops_selfheal_r3.scan_source import (
        _TZ,
        job_window_end,
    )
    from app.platform.superagent.effects import enqueue_effect
    from app.platform.superagent.models import AgentInput

    def _bj_date():
        return datetime.now(_TZ).date()

    if task.status != "open":
        return {"ok": False, "reason": f"工单已终态（{task.outcome or 'ended'}）",
                "job_name": "", "ticket_id": str(task.id)}
    r3 = signals.r3_facts(task.stage_facts)
    job_name = str(r3.get("job_name") or "")
    if not job_name:
        return {"ok": False, "reason": "no_job", "job_name": "",
                "ticket_id": str(task.id)}

    # 跨入口当日幂等（进程 dict 只管本进程；DB 留痕管全入口）
    if await today_extended_job(session, job_name):
        current = job_window_end(job_name, _bj_date())
        return {"ok": False, "reason": "already_extended_today", "job_name": job_name,
                "current_window": _hm((current.hour, current.minute)),
                "ticket_id": str(task.id)}

    # 处方值优先：调用方未给 args 时取工单处方（回调路径天然带处方值）
    if not args:
        args = dict(
            next(
                (
                    p.get("args") or {}
                    for p in (r3.get("prescriptions") or [])
                    if p.get("action") == "job_window_extend"
                ),
                {},
            )
        )
    current = job_window_end(job_name, _bj_date())
    cur_hm = (current.hour, current.minute)
    ok, reason, new_hm = window_override.apply_override(job_name, cur_hm, args)

    # decisions 留痕（复用 AgentInput system 记录；不 UPDATE agent_tasks 行——红线）
    session.add(AgentInput(
        task_id=task.id, kind="system",
        payload={
            "type": "l2_window_extend", "job_name": job_name,
            "operator": operator, "ok": ok, "reason": reason,
            "old_window": _hm(cur_hm),
            "new_window": _hm(new_hm) if new_hm else None,
            "at": datetime.now(UTC).isoformat(),
        },
        delivered_at=datetime.now(UTC),
    ))

    if ok:
        await enqueue_effect(
            session, "dm_admin",
            {"text": cards.build_window_extend_card(job_name, cur_hm, new_hm)},
            dedupe_key=f"r3:extwin:{task.id}:{datetime.now(UTC).isoformat()[:19]}",
        )
        return {"ok": True, "job_name": job_name,
                "old_window": _hm(cur_hm), "new_window": _hm(new_hm),
                "ticket_id": str(task.id)}

    # 失败也发结果卡（spec L62：失败带原因——当日已改过/工单非 open 等）
    await enqueue_effect(
        session, "dm_admin",
        {"text": "\n".join([
            "【R3 L2 窗口延长 ❌】一键执行未生效",
            f"任务：{job_name}",
            f"原因：{reason}（现截止 {_hm(cur_hm)}）",
            "说明：同 job 当日仅允许延长 1 次（防反复拉长）；如需再调请人工改配置",
        ])},
        dedupe_key=f"r3:extwin:{task.id}:fail:{datetime.now(UTC).isoformat()[:19]}",
    )
    return {"ok": False, "reason": reason, "job_name": job_name,
            "current_window": _hm(cur_hm), "ticket_id": str(task.id)}
