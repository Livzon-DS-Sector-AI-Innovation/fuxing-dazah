"""危险源辨识 Executor 协议收编（P2-2 G3）—— Task/Report 留痕，驱动不动。

设计（docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md §4.6，2026-11-09 拍板）：
orchestrator+script1~8 是确定性 workflow 状态机，与 superagent 的唯一正确合并点是
**Executor 协议**——一条辨识记录=一个 Task（经 subscription 挂 thread），每步脚本
执行=program executor（注册名 ``hazard_id_script``），人工 gate=Report(waiting)
仅落库不外发。用于统一留痕/观测面；不改 Plugin、不改 tool-calling、不改 7 步语义。

- 协议层收编：步骤执行仍在原入口同步发生（ORM 流 service.run_script /
  Bitable 流 handler→runner），本模块只按 ``run_task_once`` 同 shape 落
  stage_facts（latest_report/attention_pending/last_attention + reports 历史）；
  不依赖 SUPERAGENT_ENABLED/task_runner（底座关也能全量留痕）。
- 双流 thread：Bitable 流与 ORM 镜像记录=``bitable:hazard_id:{record_id}``，
  ORM 纯平台记录=``hazard_id:{hid}``。
- mandate.policy_version 护栏：建 Task 时写当前 Policy version_hash，防未来
  底座开启后 apply_new_policy 向 mandate 落后任务投 policy_changed 误输入。
- 重放执行器（``hazard_id_script``）：按输入描述经既有可重入入口重放
  （Bitable=advance_bitable_record(skip_dedup=True)，与 agent 补触发工具同款；
  ORM=SafetyService.run_script），幂等由既有门控保证（节点不匹配/AI 输出已
  存在即跳过）。同步模式不调用它。

开关 ``SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED``（与写回留痕同键）；关=零 DB 写
零行为变化。全部留痕调用 try/except 吞异常——绝不拖垮辨识链路。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.modules.safety.service.hazard_direct.writeback_trace import (
    trace_enabled,
)
from app.platform.superagent.models import AgentTask, AgentTaskSubscription

logger = logging.getLogger(__name__)

EXECUTOR_NAME = "hazard_id_script"
BITABLE_THREAD_PREFIX = "bitable:hazard_id"
ORM_THREAD_PREFIX = "hazard_id"

_REVIEW_ATTENTION_FIELD = "review_status"
# stage_facts.reports 水位（防重放/补触发的重复事件无界增长）
MAX_REPORT_ENTRIES = 50


def thread_key(record_key: str, *, flow: str) -> str:
    """记录键 → thread_key（bitable=飞书记录 / orm=平台记录）。"""
    if flow == "bitable":
        return f"{BITABLE_THREAD_PREFIX}:{record_key}"
    return f"{ORM_THREAD_PREFIX}:{record_key}"


def orm_thread_key(item: Any) -> tuple[str, str]:
    """ORM 记录 → (record_key, flow)：镜像记录（feishu_record_id）与 Bitable 流同 thread。"""
    frid = (getattr(item, "feishu_record_id", None) or "").strip()
    if frid:
        return frid, "bitable"
    return str(item.id), "orm"


async def ensure_task(session: Any, *, record_key: str, flow: str) -> AgentTask:
    """懒建/复用该记录的 open Task（+subscription 挂 thread）。"""
    key = thread_key(record_key, flow=flow)
    existing: AgentTask | None = (
        await session.execute(
            select(AgentTask)
            .join(
                AgentTaskSubscription,
                AgentTaskSubscription.task_id == AgentTask.id,
            )
            .where(
                AgentTaskSubscription.thread_key == key,
                AgentTask.status == "open",
            )
            .order_by(AgentTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    mandate: dict[str, Any] = {"record_key": record_key, "flow": flow}
    try:
        from app.platform.superagent.policy import get_current_policy

        policy: Any = await get_current_policy(session)
        if policy is not None:
            mandate["policy_version"] = policy.version_hash
    except Exception:  # noqa: BLE001 — 护栏失败不阻断留痕
        logger.debug("辨识 Task mandate 护栏读取 Policy 失败", exc_info=True)

    task = AgentTask(
        short_name=f"hazard_id:{record_key}"[:120],
        title=f"危险源辨识 {record_key}",
        executor=EXECUTOR_NAME,
        mandate=mandate,
    )
    session.add(task)
    await session.flush()
    session.add(AgentTaskSubscription(task_id=task.id, thread_key=key))
    await session.flush()
    return task


def report_step(
    task: AgentTask,
    *,
    kind: str,
    note: str = "",
    attention: dict[str, Any] | None = None,
    script: int | float | None = None,
    flow: str | None = None,
    end_task: bool = False,
) -> None:
    """按 run_task_once 同 shape 落一条 Report 到 stage_facts（纯内存变更）。"""
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    entry: dict[str, Any] = {"kind": kind, "at": now}
    if note:
        entry["note"] = note[:200]
    if attention is not None:
        entry["attention"] = attention
    if script is not None:
        entry["script"] = script
    if flow:
        entry["flow"] = flow

    facts = dict(task.stage_facts or {})
    reports = list(facts.get("reports") or [])
    reports.append(entry)
    # 水位护栏（平台 MAX_DISPOSITION_STEPS 同款思路）：重放/补触发的重复事件
    # 不让 JSONB 无界增长；超限丢最旧（latest_* 字段始终反映最新一条）
    if len(reports) > MAX_REPORT_ENTRIES:
        reports = reports[-MAX_REPORT_ENTRIES:]
    facts["reports"] = reports
    facts.update(
        {
            "latest_report": kind,
            "latest_report_at": now,
            "attention_pending": kind == "waiting" and attention is not None,
            "last_attention": attention,
        }
    )
    task.stage_facts = facts
    if end_task or kind == "dropped":
        task.status = "ended"
        task.outcome = kind
        task.ended_at = now_dt


def _review_attention(script: int | float) -> dict[str, Any]:
    return {
        "question": f"请人工审核脚本{script}输出",
        "field": _REVIEW_ATTENTION_FIELD,
    }


async def _with_task(
    session: Any | None,
    record_key: str,
    flow: str,
) -> tuple[Any, AgentTask, Any] | None:
    """开（或复用）会话并 ensure Task；返回 (session, task, own) 或 None（关/失败）。

    自管短会话由调用方在写完 stage_facts 后 commit（own 标记）；复用会话
    事务边界归调用方。
    """
    if not trace_enabled():
        return None
    try:
        if session is not None:
            task = await ensure_task(session, record_key=record_key, flow=flow)
            return session, task, None
        from app.core.database import async_session_factory

        own = async_session_factory()
        task = await ensure_task(own, record_key=record_key, flow=flow)
        return own, task, own
    except Exception:  # noqa: BLE001 — 留痕失败不影响业务链路
        logger.exception(
            "辨识 Task 留痕失败（不影响业务链路）: record=%s", record_key
        )
        return None


async def _finish(pair: tuple[Any, AgentTask, Any]) -> None:
    """自管会话 commit（复用会话不 commit，边界归调用方）。"""
    if pair[2] is not None:
        await pair[2].commit()


async def record_script_run(
    *,
    record_key: str,
    flow: str,
    script: int | float,
    ok: bool,
    error: str = "",
    session: Any | None = None,
    is_auxiliary: bool = False,
) -> bool:
    """一次脚本执行落 Report：成功→waiting（人工 gate），失败→failed。

    is_auxiliary（脚本3.5 等附属评估）：成功记 progress（无人工 gate，
    不产 attention）。
    """
    pair = await _with_task(session, record_key, flow)
    if pair is None:
        return False
    task = pair[1]
    try:
        if not ok:
            report_step(
                task, kind="failed", note=error or "脚本执行失败",
                script=script, flow=flow,
            )
        elif is_auxiliary:
            report_step(
                task, kind="progress", note=f"附属评估{script}完成",
                script=script, flow=flow,
            )
        else:
            report_step(
                task,
                kind="waiting",
                note=f"脚本{script}执行完成，待人工审核",
                attention=_review_attention(script),
                script=script,
                flow=flow,
            )
        await _finish(pair)
        return True
    except Exception:  # noqa: BLE001
        logger.exception(
            "辨识脚本留痕失败（不影响业务链路）: record=%s script=%s",
            record_key, script,
        )
        return False


async def record_flow_completed(
    *, record_key: str, flow: str, session: Any | None = None
) -> bool:
    """全流程完成（节点=AI 流程结束 / 脚本7 审核通过）→ end_task(outcome=ready)。

    该 thread 已有任何 Task（含 ended）时 no-op——防 completed 记录的后续
    事件（审核指纹变化/手动重试）反复新建 ended Task。
    """
    if not trace_enabled():
        return False
    try:
        if session is None:
            from app.core.database import async_session_factory

            async with async_session_factory() as own:
                return await _complete_task(own, record_key, flow, commit=True)
        return await _complete_task(session, record_key, flow)
    except Exception:  # noqa: BLE001
        logger.exception(
            "辨识完成留痕失败（不影响业务链路）: record=%s", record_key
        )
        return False


async def _complete_task(
    own: Any, record_key: str, flow: str, *, commit: bool = False
) -> bool:
    key = thread_key(record_key, flow=flow)
    existing: AgentTask | None = (
        await own.execute(
            select(AgentTask)
            .join(
                AgentTaskSubscription,
                AgentTaskSubscription.task_id == AgentTask.id,
            )
            .where(AgentTaskSubscription.thread_key == key)
            .order_by(AgentTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is None or existing.status == "ended":
        # 无 Task=异常时序（完成先于执行）不补建；已 ended=重复完成事件 no-op
        return False
    report_step(
        existing, kind="ready", note="辨识流程完成", flow=flow, end_task=True
    )
    if commit:
        await own.commit()
    return True


async def record_orm_script_run(
    *,
    item: Any,
    script_no: int,
    ok: bool,
    error: str = "",
    session: Any | None = None,
) -> bool:
    """ORM 流脚本执行留痕（thread 由 item 解析：镜像记录与 Bitable 流同 thread）。"""
    record_key, flow = orm_thread_key(item)
    return await record_script_run(
        record_key=record_key,
        flow=flow,
        script=script_no,
        ok=ok,
        error=error,
        session=session,
    )


async def record_orm_review(
    *,
    item: Any,
    script_no: int,
    action: str,
    completed: bool = False,
    session: Any | None = None,
) -> bool:
    """ORM 流人工审核留痕：approved/rejected 记 progress；脚本7 通过即 end_task。"""
    record_key, flow = orm_thread_key(item)
    if completed:
        # 脚本7 通过=流程终态：走 completed 路径（含 ended no-op 防重复增殖）
        return await record_flow_completed(
            record_key=record_key, flow=flow, session=session
        )
    pair = await _with_task(session, record_key, flow)
    if pair is None:
        return False
    task = pair[1]
    try:
        report_step(
            task,
            kind="progress",
            note=f"脚本{script_no}人工审核：{action}",
            script=script_no,
            flow=flow,
        )
        await _finish(pair)
        return True
    except Exception:  # noqa: BLE001
        logger.exception(
            "辨识审核留痕失败（不影响业务链路）: record=%s", record_key
        )
        return False


def traced_run_script(record_id: str, *, runner: Any = None) -> Any:
    """Bitable 流 runner 包装：透传执行结果，旁挂脚本留痕（关=纯透传）。

    runner 缺省惰性构建生产 ``HazardIdentificationScriptRunner``（与
    handler._build_service 现状一致）。
    """
    if runner is None:
        from app.modules.safety.service.hazard_identification_runner import (
            HazardIdentificationScriptRunner,
        )

        runner = HazardIdentificationScriptRunner()

    async def _wrapped(script: int | float, effective: dict[str, Any]) -> Any:
        output = await runner(script, effective)
        # 失败原因从 runner 吞掉的异常不可得，记通用失败。
        # 脚本3.5（福建附属评估）是自动评估无人工 gate → 记 progress 无 attention
        ok = output is not None
        if float(script) == 3.5:
            await record_script_run(
                record_key=record_id, flow="bitable", script=script,
                ok=ok, error="" if ok else "附属评估未产出",
                is_auxiliary=True,
            )
        else:
            await record_script_run(
                record_key=record_id, flow="bitable", script=script,
                ok=ok, error="" if ok else "脚本执行未产出（AI 失败或被拦截）",
            )
        return output

    _wrapped._hazard_id_traced = True  # type: ignore[attr-defined]
    return _wrapped


# ═══════════════════════════════════════════════════════════════
# 重放执行器（未来底座运行时驱动用；同步模式不调用）
# ═══════════════════════════════════════════════════════════════


async def _replay_run_script(
    task_dict: dict[str, Any], inputs: list[dict[str, Any]],
) -> Any:
    """按输入描述经既有可重入入口重放一步（幂等由既有门控保证）。"""
    from app.platform.superagent.executors import Report

    payload = inputs[-1] if inputs else {}
    action = payload.get("action")
    if action != "run_script":
        return Report(
            kind="dropped", note=f"未识别的动作: {action!r}",
        )
    flow = payload.get("flow")
    record_key = str(payload.get("record_key") or "")
    script_no = int(payload.get("script_no") or 0)
    if not record_key or not script_no:
        return Report(kind="dropped", note="输入缺少 record_key/script_no")

    if flow == "bitable":
        from app.modules.safety.feishu.hazard_identification_bitable_handler import (
            advance_bitable_record,
        )

        result = await advance_bitable_record(
            record_key, channel="agent", skip_dedup=True
        )
        if result.get("status") == "advanced":
            return Report(
                kind="waiting",
                note=f"脚本{script_no}重放完成，待人工审核",
                attention=_review_attention(script_no),
            )
        if result.get("reason") == "completed":
            return Report(
                kind="ready", note="辨识流程已结束", end_task=True
            )
        return Report(
            kind="blocked",
            note=f"未推进（原因：{result.get('reason', 'unknown')}）",
        )

    if flow == "orm":
        from app.core.database import async_session_factory
        from app.modules.safety.service.safety import SafetyService

        async with async_session_factory() as session:
            orm_result: Any = await SafetyService(session).run_script(
                UUID(record_key), script_no
            )
        if orm_result is not None:
            return Report(
                kind="waiting",
                note=f"脚本{script_no}重放完成，待人工审核",
                attention=_review_attention(script_no),
            )
        return Report(kind="blocked", note="未执行（状态不匹配或前置未通过）")

    return Report(kind="dropped", note=f"未识别的流: {flow!r}")


def register_hazard_id_executor() -> None:
    """幂等注册重放执行器（同步留痕模式不依赖它；供未来运行时驱动）。"""
    from app.platform.superagent.executors import get_executor, register_executor

    if get_executor(EXECUTOR_NAME) is not None:
        return
    register_executor(EXECUTOR_NAME, _replay_run_script)
