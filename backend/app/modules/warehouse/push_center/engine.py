"""推送执行引擎（单泵轮询）：到期判断 → 内容生成 → 逐目标发送 → 日志落库。

- **返回语义**：只有「实际尝试执行」的任务出现在结果里
  （executed / failed / skipped_no_target / skipped_busy）；
  未到期与停用任务静默跳过（tick 每分钟轮询，不产生噪音）。
- **事务语义**：单任务在 savepoint 内生成内容（失败回滚该任务，不影响同批
  其他任务）；调用方（tick 包装 / 手动触发 API）负责整体 commit。
- **到期判重**：日历型按 push_logs.slot（当日窗口内仅一次，重启不重复）；
  interval 按 push_logs.run_at 冷却。手动触发在窗口内会占用当日槽位
  （视为已送达），窗口外不占用（slot 为空）。
- **互斥**：进程内 per-task asyncio.Lock（单进程部署，与平台调度引擎一致）。
- **后置钩子**：SCENE_POST_SEND_HOOKS（发送成功后执行，如清单推送挂确认门
  Ticket 07）；钩子失败不影响推送结果（记日志+告警）。
"""

from __future__ import annotations

import asyncio
import calendar as _calendar
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.ai_audit import failure_notifier
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehousePushLog
from app.modules.warehouse.push_center import generators
from app.modules.warehouse.push_center.registry import PushTaskInfo
from app.modules.warehouse.push_center.store import PushTaskView, push_store

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_WINDOW_MINUTES = 60

# 结果状态（对外语义见模块 docstring）
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"
STATUS_SKIPPED_NO_TARGET = "skipped_no_target"
STATUS_SKIPPED_BUSY = "skipped_busy"
STATUS_SKIPPED_DISABLED = "skipped_disabled"
STATUS_SKIPPED_NOT_SCHEDULED = "skipped_not_scheduled"

# 场景后置钩子：推送发送成功后执行（如清单推送挂确认门，Ticket 07）。
# 仿 draft_flow.SCENE_CONFIG 注册模式：confirm_integrations 模块导入即注册。
class PostSendHook(Protocol):
    """钩子协议：dry_run 关键字传参（与发送件同款注入约定）。"""

    async def __call__(
        self,
        db: AsyncSession,
        view: PushTaskView,
        now: datetime,
        *,
        dry_run: bool | None = None,
    ) -> Any: ...


SCENE_POST_SEND_HOOKS: dict[str, PostSendHook] = {}


def register_post_send_hook(scene: str, hook: PostSendHook) -> None:
    """注册场景后置钩子；重复注册抛错。"""
    if scene in SCENE_POST_SEND_HOOKS:
        raise ValueError(f"推送后置钩子重复注册: {scene}")
    SCENE_POST_SEND_HOOKS[scene] = hook


@dataclass(frozen=True)
class PushRunResult:
    """单任务一次执行的结果。"""

    task_name: str
    scene: str
    status: str
    slot: datetime | None = None
    log_count: int = 0


_task_locks: dict[str, asyncio.Lock] = {}


def _lock_for(task_name: str) -> asyncio.Lock:
    return _task_locks.setdefault(task_name, asyncio.Lock())


def _fire_failure(view: PushTaskView, error: str) -> None:
    """推送失败告警（fire-and-forget；failure_notifier 内部吞异常）。"""
    try:
        failure_notifier.fire_notify_failure(
            scenario="push_center",
            model=view.task_name,
            error=error,
            trace_id=str(uuid.uuid4()),
        )
    except Exception:  # noqa: BLE001 — 告警失败不影响主流程
        logger.exception("推送失败告警触发异常（task=%s）", view.task_name)


async def _send_to_target(
    target: str, card: dict[str, Any], dry_run: bool | None
) -> str | None:
    """按目标类型分发（ou_ 私聊/否则群聊）；返回 message_id（None=失败）。"""
    return await notification.send_card_to_target(target, card, dry_run=dry_run)


async def _send_and_log(
    db: AsyncSession,
    view: PushTaskView,
    card: dict[str, Any],
    targets: list[str],
    now: datetime,
    *,
    trigger: str,
    slot: datetime | None,
    dry_run: bool | None,
) -> tuple[int, int]:
    """逐目标发送 + 逐目标写推送日志（定时/事件路径共用）。

    返回 (日志条数, 成功条数)；发送失败（返回 None）记 failed 日志不抛异常。
    """
    log_count = 0
    ok_count = 0
    for target in targets:
        started = time.monotonic()
        message_id = await _send_to_target(target, card, dry_run)
        duration_ms = int((time.monotonic() - started) * 1000)
        ok = message_id is not None
        if ok:
            ok_count += 1
        db.add(
            WarehousePushLog(
                task_name=view.task_name,
                scene=view.scene,
                trigger=trigger,
                run_at=now,
                slot=slot,
                target=target,
                status="success" if ok else "failed",
                message_id=message_id,
                error=None if ok else "飞书发送失败（返回空 message_id）",
                duration_ms=duration_ms,
            )
        )
        log_count += 1
    await db.flush()
    return log_count, ok_count


def _parse_hhmm(value: Any) -> tuple[int, int]:
    hh, mm = str(value).strip().split(":")
    return int(hh), int(mm)


def _calendar_slot(schedule: dict[str, Any], now: datetime) -> tuple[datetime, int]:
    """日历型调度 → (最近一个计划槽位, 窗口分钟数)。

    槽位取 now 所在周期或最近一个已过去的周期（weekly 取本周目标周几、
    monthly 取本月或上月目标日），配合窗口判断「是否处于应执行窗口内」。
    """
    window = int(schedule.get("window_minutes", DEFAULT_WINDOW_MINUTES))
    hh, mm = _parse_hhmm(schedule["time"])
    stype = schedule["type"]
    if stype == "daily":
        base = now.date()
    elif stype == "weekly":
        target_weekday = int(schedule["weekday"])
        delta = (now.weekday() - target_weekday) % 7
        base = now.date() - timedelta(days=delta)
    elif stype == "monthly":
        day = int(schedule["day"])
        year, month = now.year, now.month
        clamped = min(day, _calendar.monthrange(year, month)[1])
        if now.day >= clamped:
            base = date(year, month, clamped)
        else:
            prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
            base = date(
                prev_year, prev_month, min(day, _calendar.monthrange(prev_year, prev_month)[1])
            )
    else:
        raise ValueError(f"非日历型调度: {stype}")
    slot = datetime.combine(base, dtime(hh, mm), tzinfo=CN_TZ)
    return slot, window


async def _check_due(
    db: AsyncSession, view: PushTaskView, now: datetime
) -> tuple[bool, datetime | None]:
    """判断任务是否到期；返回 (是否到期, 日历槽位)。"""
    schedule = view.schedule or {}
    stype = schedule.get("type")
    if stype == "interval":
        last = (
            await db.execute(
                select(func.max(WarehousePushLog.run_at)).where(
                    WarehousePushLog.task_name == view.task_name
                )
            )
        ).scalar_one_or_none()
        if last is None:
            return True, None
        if last.tzinfo is None:  # 防御：裸时间按北京时间补时区
            last = last.replace(tzinfo=CN_TZ)
        seconds = int(schedule["seconds"])
        return (now - last).total_seconds() >= seconds, None

    slot, window = _calendar_slot(schedule, now)
    if not slot <= now < slot + timedelta(minutes=window):
        return False, slot
    count = (
        await db.execute(
            select(func.count()).where(
                WarehousePushLog.task_name == view.task_name,
                WarehousePushLog.slot == slot,
            )
        )
    ).scalar_one()
    return count == 0, slot


async def _execute(
    db: AsyncSession,
    view: PushTaskView,
    now: datetime,
    *,
    trigger: str,
    slot: datetime | None,
    dry_run: bool | None,
) -> PushRunResult:
    """执行单任务：互斥 → 目标解析 → 生成（savepoint）→ 逐目标发送 → 日志。"""
    lock = _lock_for(view.task_name)
    if lock.locked():
        return PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_BUSY, slot)
    async with lock:
        targets = list(view.targets)
        if not targets:
            db.add(
                WarehousePushLog(
                    task_name=view.task_name,
                    scene=view.scene,
                    trigger=trigger,
                    run_at=now,
                    slot=slot,
                    target=None,
                    status="skipped",
                    error="未配置推送目标（DB 与 env 均为空），已跳过",
                )
            )
            await db.flush()
            return PushRunResult(
                view.task_name, view.scene, STATUS_SKIPPED_NO_TARGET, slot, 1
            )

        generator = generators.get_push_generator(view.scene)
        try:
            if generator is None:
                raise LookupError(f"未注册内容生成器: {view.scene}")
            async with db.begin_nested():  # savepoint：失败只回滚本任务
                card = await generator(db, now)
        except Exception as exc:  # noqa: BLE001 — 生成失败记日志+告警，不中断其他任务
            error = f"{type(exc).__name__}: {exc}"[:512]
            logger.exception("推送内容生成失败（task=%s）", view.task_name)
            db.add(
                WarehousePushLog(
                    task_name=view.task_name,
                    scene=view.scene,
                    trigger=trigger,
                    run_at=now,
                    slot=slot,
                    target=None,
                    status="failed",
                    error=error,
                )
            )
            await db.flush()
            _fire_failure(view, error)
            return PushRunResult(view.task_name, view.scene, STATUS_FAILED, slot, 1)

        log_count, ok_count = await _send_and_log(
            db, view, card, targets, now,
            trigger=trigger, slot=slot, dry_run=dry_run,
        )
        if ok_count < log_count:
            _fire_failure(view, f"部分目标发送失败（{view.task_name}，{log_count - ok_count} 条）")
        # 后置钩子：清单推送发送成功后挂确认门（Ticket 07）等；
        # 失败不影响推送结果（记日志+告警），清单卡未送达任何目标时不挂。
        if ok_count > 0:
            hook = SCENE_POST_SEND_HOOKS.get(view.scene)
            if hook is not None:
                try:
                    await hook(db, view, now, dry_run=dry_run)
                except Exception:  # noqa: BLE001 — 钩子失败不回滚已完成的推送
                    logger.exception("推送后置钩子执行失败（scene=%s）", view.scene)
                    _fire_failure(view, f"后置钩子执行失败（{view.scene}）")
        return PushRunResult(
            view.task_name, view.scene, STATUS_EXECUTED, slot, log_count
        )


async def run_due_tasks(
    db: AsyncSession, now: datetime, *, dry_run: bool | None = None
) -> list[PushRunResult]:
    """tick 入口：遍历启用的 scheduled 任务，执行全部到期任务。

    未到期/停用任务静默跳过（返回结果只含实际尝试的任务）。
    """
    results: list[PushRunResult] = []
    for info in _iter_scheduled_infos():
        view = push_store.get_task_view(info.task_name)
        if not view.enabled:
            continue
        due, slot = await _check_due(db, view, now)
        if not due:
            continue
        results.append(
            await _execute(db, view, now, trigger="scheduled", slot=slot, dry_run=dry_run)
        )
    return results


async def run_task(
    db: AsyncSession,
    task_name: str,
    now: datetime,
    *,
    trigger: str = "manual",
    dry_run: bool | None = None,
) -> PushRunResult:
    """单任务执行（手动触发 / 事件入口复用）：绕过到期判断，仍走互斥与日志。

    手动触发在窗口内会占用当日槽位（视为已送达），窗口外不占用。
    """
    view = push_store.get_task_view(task_name)  # 未知任务抛 ValueError（404 语义）
    if not view.enabled:
        return PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_DISABLED)
    if view.trigger != "scheduled":
        return PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_NOT_SCHEDULED)

    slot: datetime | None = None
    schedule = view.schedule or {}
    if schedule.get("type") != "interval":
        candidate, window = _calendar_slot(schedule, now)
        if candidate <= now < candidate + timedelta(minutes=window):
            slot = candidate
    return await _execute(db, view, now, trigger=trigger, slot=slot, dry_run=dry_run)


def _iter_scheduled_infos() -> tuple[PushTaskInfo, ...]:
    from app.modules.warehouse.push_center import registry

    return tuple(
        info for info in registry.iter_tasks() if info.trigger == "scheduled"
    )


# 场景后置钩子注册（导入即注册，仿 draft_flow.SCENE_CONFIG 模式）。
# 置于模块尾部：confirm_integrations 依赖本模块的注册函数与类型，
# 此时它们均已定义（部分初始化安全）。
from app.modules.warehouse.push_center import confirm_integrations  # noqa: E402,F401

__all__ = [
    "PushRunResult",
    "PostSendHook",
    "SCENE_POST_SEND_HOOKS",
    "push_store",
    "register_post_send_hook",
    "run_due_tasks",
    "run_task",
]
