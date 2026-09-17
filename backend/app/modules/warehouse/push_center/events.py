"""事件推送入口（V3.0 分期A Ticket 08）：业务钩子 → 事件型任务 → 目标推送。

与定时路径（engine.run_due_tasks）共用任务配置/目标回退链/推送日志/失败
告警；区别在触发方式：业务事件（如成品出库登记快递号）即时调用
``fire_push_event``，不走到期判断。事件卡片由 payload 即时渲染
（EVENT_RENDERERS 注册表，无 DB 依赖）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import WarehousePushLog
from app.modules.warehouse.push_center import engine as _engine_mod
from app.modules.warehouse.push_center import registry

# 同包内部复用引擎执行件（发送落库/互斥锁/失败告警；与 reports 复用
# intelligence._material_stock_totals 同款先例）
from app.modules.warehouse.push_center.engine import (  # noqa: SLF001
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_SKIPPED_BUSY,
    STATUS_SKIPPED_DISABLED,
    STATUS_SKIPPED_NO_TARGET,
    PushRunResult,
    _fire_failure,
    _lock_for,
    _send_and_log,
)

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

# 事件卡片渲染器：payload → 飞书卡片 dict（无 DB 依赖，纯函数）
EventRenderer = Callable[[dict[str, Any]], dict[str, Any]]
EVENT_RENDERERS: dict[str, EventRenderer] = {}


def register_event_renderer(scene: str, renderer: EventRenderer) -> None:
    """注册事件渲染器；重复注册抛错。"""
    if scene in EVENT_RENDERERS:
        raise ValueError(f"事件渲染器重复注册: {scene}")
    EVENT_RENDERERS[scene] = renderer


def get_event_renderer(scene: str) -> EventRenderer | None:
    return EVENT_RENDERERS.get(scene)


def render_express_notify_card(payload: dict[str, Any]) -> dict[str, Any]:
    """快递发货通知卡（品名/批号/数量/客户/快递号/出库日期，窄屏排版）。"""
    from app.modules.warehouse.agent.cards import build_card

    def _text(key: str) -> str:
        value = payload.get(key)
        return str(value).strip() if value is not None else ""

    lines = [
        f"**产品** {_text('product_name') or '-'}"
        f"　**批号** {_text('product_batch_no') or '-'}",
        f"**数量** {_text('quantity') or '-'} {_text('unit')}"
        f"　**客户** {_text('customer') or '-'}",
        f"**快递号** {_text('express_no') or '-'}",
    ]
    if _text("outbound_date"):
        lines.append(f"**出库日期** {_text('outbound_date')}")
    if _text("remark"):
        lines.append(f"**备注** {_text('remark')}")
    return build_card(
        title="📦 发货通知",
        template="green",
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


register_event_renderer("express_notify", render_express_notify_card)


async def fire_push_event(
    db: AsyncSession,
    scene: str,
    payload: dict[str, Any],
    *,
    dry_run: bool | None = None,
) -> list[PushRunResult]:
    """触发一次事件推送：匹配 trigger=event 且启用的任务，渲染 payload 推送目标。

    返回每个匹配任务的执行结果（含 skipped_disabled/skipped_no_target）；
    单任务失败记日志并告警，不影响其他任务。不 commit（调用方上下文统一提交）。
    """
    results: list[PushRunResult] = []
    now = datetime.now(CN_TZ)
    for info in registry.iter_tasks():
        if info.trigger != "event" or info.scene != scene:
            continue
        # 经 engine 模块属性取 store（与定时路径共用同一替换点/缓存失效语义）
        view = _engine_mod.push_store.get_task_view(info.task_name)
        if not view.enabled:
            results.append(PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_DISABLED))
            continue
        lock = _lock_for(view.task_name)
        if lock.locked():
            results.append(PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_BUSY))
            continue
        async with lock:
            results.append(
                await _execute_event(db, view, payload, now, dry_run=dry_run)
            )
    return results


async def _execute_event(
    db: AsyncSession,
    view: Any,
    payload: dict[str, Any],
    now: datetime,
    *,
    dry_run: bool | None,
) -> PushRunResult:
    """执行单事件任务：渲染 → 逐目标发送 → 日志（trigger=event）。"""
    targets = list(view.targets)
    if not targets:
        db.add(
            WarehousePushLog(
                task_name=view.task_name,
                scene=view.scene,
                trigger="event",
                run_at=now,
                slot=None,
                target=None,
                status="skipped",
                error="未配置推送目标（DB 与 env 均为空），已跳过",
            )
        )
        await db.flush()
        return PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_NO_TARGET, None, 1)

    renderer = get_event_renderer(view.scene)
    if renderer is None:
        error = f"未注册事件渲染器: {view.scene}"
        db.add(
            WarehousePushLog(
                task_name=view.task_name,
                scene=view.scene,
                trigger="event",
                run_at=now,
                slot=None,
                target=None,
                status="failed",
                error=error,
            )
        )
        await db.flush()
        _fire_failure(view, error)
        return PushRunResult(view.task_name, view.scene, STATUS_FAILED, None, 1)

    card = renderer(payload)
    log_count, ok_count = await _send_and_log(
        db, view, card, targets, now,
        trigger="event", slot=None, dry_run=dry_run,
    )
    if ok_count < log_count:
        _fire_failure(view, f"事件推送部分目标发送失败（{view.task_name}）")
    return PushRunResult(view.task_name, view.scene, STATUS_EXECUTED, None, log_count)
