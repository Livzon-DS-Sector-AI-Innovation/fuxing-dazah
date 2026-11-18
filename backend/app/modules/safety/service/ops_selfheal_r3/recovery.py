"""R3 恢复判定 —— 工单级全清条件助手（三期 T2，质询 Round1 拍板范式）。

scan 侧 ``_scan_recoveries`` 与 executor verify 分支共用本模块（同源防漂移，
window_guard 教训）。两类清除语义（spec D1）：

- **正向证据**（有恢复信号源）：ai_call=该 scenario 存在 created_at 晚于最后
  一条 failed 的 success 行；parked=该组件无 failed effect 残留；deadletter=
  死信清零（Redis 不可达=未清，fail-closed——错误地收口比多等一轮更糟）。
- **安静窗口**（无正向证据，push/ragflow/event 及 ai_call 无正向时）：
  ``now − r3.last_signal_at ≥ RECOVERY_QUIET_MINUTES`` **且** 现势条件不再
  firing（复用 scan_source 扫描器同源复测，当日口径）。last_signal_at 仅由
  故障类输入经诊断推进（恢复类输入走 verify 不动它）——零新增状态位。

时间界（dropped 全表累积教训同源）：正向查询限近 48h；firing 复测即扫描器
当日口径；安静锚=工单自身时钟（非日切重置，无午夜假恢复）。

已知限制（spec D10）：同日恢复后再故障被 daily eid 幂等吸收，次日才能再开单；
event 无失败表，同日再失败对系统不可见，唯一可用锚是 last_signal_at。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.service.ops_selfheal_r3 import signals

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")

#: 安静窗口分钟数（质询拍板：常量不进 registry，对齐二期硬编码阈值风格）
RECOVERY_QUIET_MINUTES = 60

#: 正向证据查询回看上限（防全表扫；daily eid 范式下故障至多当日）
_POSITIVE_LOOKBACK_HOURS = 48

#: 可恢复信号集（恢复扫描与全清判定的圈定边界；job/rag/dep 走各自既有分支）
RECOVERABLE_SIGNALS = frozenset({
    signals.SIGNAL_AICALL_FAILED,
    signals.SIGNAL_PUSH_FAILED,
    signals.SIGNAL_RAGFLOW_FAILED,
    signals.SIGNAL_EVENT_FAILED,
    signals.SIGNAL_PARKED,
    signals.SIGNAL_DEADLETTER,
})

#: 四新信号集（executor verify 分派表引用——单一事实源，新增信号免三处同步）
MISC_SIGNALS = frozenset({
    signals.SIGNAL_AICALL_FAILED,
    signals.SIGNAL_PUSH_FAILED,
    signals.SIGNAL_RAGFLOW_FAILED,
    signals.SIGNAL_EVENT_FAILED,
})


def signals_of(r3: dict[str, Any]) -> list[str]:
    """工单已见信号集：signals_seen 回退 [r3.signal]（老工单/混合单收编口径）。"""
    seen = [str(x) for x in (r3.get("signals_seen") or []) if x]
    if not seen and r3.get("signal"):
        seen = [str(r3["signal"])]
    return seen


def _parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    return dt


def _quiet_ok(r3: dict[str, Any], now: datetime) -> bool:
    """安静门：距最后一次故障输入 ≥ RECOVERY_QUIET_MINUTES（缺锚=视为已久）。"""
    last = _parse_dt(r3.get("last_signal_at"))
    return True if last is None else (now - last) >= timedelta(minutes=RECOVERY_QUIET_MINUTES)


async def _firing_drafts(fn_name: str, session: Any) -> list[Any]:
    """复用 scan_source 扫描器同源复测（lazy import 防 scan 侧反向 import 环）。"""
    from app.modules.safety.service.ops_selfheal_r3 import scan_source

    try:
        drafts = await getattr(scan_source, fn_name)(session)
    except Exception:  # noqa: BLE001 — fail-open 红线（扫描器自带），异常=未清
        logger.warning("R3 恢复复测 %s 异常（按未清处理）", fn_name)
        return ["<error>"]
    return list(drafts or [])


async def ai_call_cleared(session: Any, r3: dict[str, Any], *, now: datetime) -> bool:
    """正向：scenario 存在晚于最后 failed 的 success；否则安静门 + 现势不 firing。

    firing 复测取**类级**（任一 scenario 在故障即不收口）——聚合日常单的
    r3.scenario 只留最新一条（审查 Spec(c)1：组件级过滤会漏掉已见其他
    scenario 的现势故障致误收口）。
    """
    from sqlalchemy import select

    from app.modules.safety.ai_audit.models import AICallAudit

    scenario = str(r3.get("scenario") or "")
    lookback = now - timedelta(hours=_POSITIVE_LOOKBACK_HOURS)
    if scenario:
        rows = (
            await session.execute(
                select(AICallAudit.status, AICallAudit.created_at)
                .where(
                    AICallAudit.scenario == scenario,
                    AICallAudit.created_at >= lookback,
                )
            )
        ).all()
        last_failed = max(
            (c for st, c in rows if st == "failed"), default=None,
        )
        if last_failed is not None and any(
            st == "success" and c > last_failed for st, c in rows
        ):
            return True  # 正向证据快路（充值恢复等场景立即收口）
    return _quiet_ok(r3, now) and not await _firing_drafts("_scan_ai_calls", session)


async def push_cleared(session: Any, r3: dict[str, Any], *, now: datetime) -> bool:
    """安静门 + 现势不 firing（**类级**：outbox/dm_admin 任一当日新增即不收口）。

    组件级过滤的坑同 ai_call_cleared docstring（聚合单 r3.component 只留最新）。
    """
    return _quiet_ok(r3, now) and not await _firing_drafts("_scan_push_failures", session)


async def ragflow_cleared(session: Any, r3: dict[str, Any], *, now: datetime) -> bool:
    """安静门 + 当日无新增 FAIL（doc_map / ingest_runs，类级无组件维度）。"""
    return _quiet_ok(r3, now) and not await _firing_drafts("_scan_ragflow", session)


async def event_cleared(session: Any, r3: dict[str, Any], *, now: datetime) -> bool:
    """纯安静门（无失败表可复测——D10 已知限制）。"""
    return _quiet_ok(r3, now)


async def parked_cleared(session: Any, r3: dict[str, Any], *, now: datetime) -> bool:
    """正向：现势无 parked 残留（**类级**任一组件；自愈不自我修复排除集在扫描器内）。"""
    return not await _firing_drafts("_scan_parked", session)


async def deadletter_cleared(session: Any, r3: dict[str, Any], *, now: datetime) -> bool:
    """正向：死信清零（fail-closed：Redis 不可达=未清——复测异常不收口）。"""
    try:
        from app.modules.safety.service.hazard_direct.failure_ledger import (
            list_dead_letters,
        )

        return not await list_dead_letters(limit=10)
    except Exception:  # noqa: BLE001 — 恢复判定 fail-closed（与扫描侧 fail-open 相反）
        logger.warning("R3 恢复死信核对失败（按未清处理）")
        return False


_CLEARERS: dict[str, Any] = {
    signals.SIGNAL_AICALL_FAILED: ai_call_cleared,
    signals.SIGNAL_PUSH_FAILED: push_cleared,
    signals.SIGNAL_RAGFLOW_FAILED: ragflow_cleared,
    signals.SIGNAL_EVENT_FAILED: event_cleared,
    signals.SIGNAL_PARKED: parked_cleared,
    signals.SIGNAL_DEADLETTER: deadletter_cleared,
}


async def ticket_all_clear(
    session: Any, r3: dict[str, Any], *, now: datetime | None = None,
) -> tuple[bool, list[str]]:
    """工单级全清：已见可恢复信号逐个判定，返回 (全清?, 未清信号清单)。

    非可恢复信号（job/rag/dep/batch 本体）不在此判定——它们走各自 verify 分支；
    batch 单的子信号经 signals_seen 累积进入本判定（spec D4）。
    """
    now = now or datetime.now(_TZ)
    pending = [
        sig for sig in signals_of(r3)
        if sig in _CLEARERS and not await _CLEARERS[sig](session, r3, now=now)
    ]
    return (not pending, pending)
