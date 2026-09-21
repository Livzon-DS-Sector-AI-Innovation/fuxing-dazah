"""推送任务配置 store — 任务行的运行时大脑（仿 ops_config.scheduler_store）。

- **读（热路径，全同步）**：``get_task_view`` / ``iter_task_views``；
- **回退链**：targets = DB 活行（非空）→ env（registry.target_env_var）→ 空；
  enabled/schedule = DB 活行 → registry 默认（schedule 空值 = 恢复默认）；
  缺行 = 按注册表默认（启用）。
- **写（async，API 层传入 session）**：``set_task`` 校验（daily/weekly/monthly/
  yearly/interval 五态 schedule）→ 软删行恢复 → before/after 审计 → flush → 失效。
- **测试接缝**：构造函数 ``row_loader`` 注入预设行；生产不传走同步会话工厂。
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.models import (
    WarehousePushTask,
    WarehousePushTaskAudit,
)
from app.modules.warehouse.push_center import registry

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60.0

_TARGET_SPLIT_RE = re.compile(r"[，,\s]+")
_TARGET_MAX_COUNT = 20
_TARGET_MAX_LEN = 64
_TARGETS_MAX_LEN = 512
_NOTE_MAX_LEN = 255
_WINDOW_MINUTES_RANGE = (5, 720)
_INTERVAL_MIN_SECONDS = 30

PushSource = Literal["db", "default"]
PushRowLoader = Callable[[str], Any]


@dataclass(frozen=True)
class PushTaskView:
    """单任务合并视图。"""

    task_name: str
    scene: str
    label: str
    description: str
    trigger: str
    enabled: bool
    schedule: dict[str, Any] | None
    targets: tuple[str, ...]
    source: PushSource


def split_targets(text: str | None) -> tuple[str, ...]:
    """目标文本 → 去重后的目标元组（逗号/空白分隔，兼容中文逗号）。"""
    if not text:
        return ()
    seen: dict[str, None] = {}
    for part in _TARGET_SPLIT_RE.split(text):
        part = part.strip()
        if part:
            seen.setdefault(part, None)
    return tuple(seen)


class PushConfigStore:
    """模块级单例。热路径全同步（内存缓存），写操作 async（DB + 审计 + 失效）。"""

    def __init__(self, row_loader: PushRowLoader | None = None) -> None:
        self._cache: dict[
            str, tuple[bool, dict[str, Any] | None, tuple[str, ...], PushSource]
        ] = {}
        self._loaded_at: dict[str, float] = {}
        self._ttl_seconds: float = _TTL_SECONDS
        self._row_loader = row_loader

    # ═══════════════════════════════════════════════════════════
    # 读（热路径，同步）
    # ═══════════════════════════════════════════════════════════

    def get_task_view(self, task_name: str) -> PushTaskView:
        """某任务合并视图；未知任务抛 ValueError（404 语义）。"""
        info = registry.get_task(task_name)  # 未知任务抛 ValueError
        enabled, schedule, targets, source = self._state(task_name)
        return PushTaskView(
            task_name=info.task_name,
            scene=info.scene,
            label=info.label,
            description=info.description,
            trigger=info.trigger,
            enabled=enabled,
            schedule=schedule,
            targets=targets,
            source=source,
        )

    def iter_task_views(self) -> tuple[PushTaskView, ...]:
        """遍历全部任务（供 GET 总览 / 引擎遍历）。"""
        return tuple(self.get_task_view(info.task_name) for info in registry.iter_tasks())

    # ═══════════════════════════════════════════════════════════
    # 缓存维护
    # ═══════════════════════════════════════════════════════════

    def invalidate(self, task_name: str | None = None) -> None:
        """失效缓存；None = 全部失效。"""
        if task_name is None:
            self._cache.clear()
            self._loaded_at.clear()
            return
        self._cache.pop(task_name, None)
        self._loaded_at.pop(task_name, None)

    async def warmup(self) -> None:
        """启动预热（失败仅告警，读路径回退注册表默认）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                rows = (
                    await session.execute(
                        select(WarehousePushTask).where(WarehousePushTask.is_deleted.is_(False))
                    )
                ).scalars().all()
                by_name = {r.task_name: r for r in rows}
                now = time.monotonic()
                for info in registry.iter_tasks():
                    row = by_name.get(info.task_name)
                    if row is not None and row.is_deleted:
                        row = None
                    self._cache[info.task_name] = self._state_from_row(info, row)
                    self._loaded_at[info.task_name] = now
        except Exception:
            logger.exception("推送任务配置启动预热失败（读路径将以注册表默认兜底）")

    # ═══════════════════════════════════════════════════════════
    # 写（async；API 层传入 session）
    # ═══════════════════════════════════════════════════════════

    async def set_task(
        self,
        db: AsyncSession,
        task_name: str,
        payload: dict[str, Any],
        operator_name: str | None = None,
    ) -> PushTaskView:
        """更新任务行（事务 + 审计 + 失效）。

        - 未知任务抛 ValueError（404 语义）；
        - enabled 必须 bool；schedule 须为 daily/weekly/monthly/yearly/interval
          五态或 null（null = 恢复 registry 默认）；targets 逗号分隔，条目数与长度受限；
        - targets 空串/None = 清空覆盖（回落 env）。
        """
        info = registry.get_task(task_name)
        values = self._validate_payload(payload)

        row = await self._find_row(db, task_name)
        before = self._compact(row) if row is not None else None
        if row is None:
            row = WarehousePushTask(
                task_name=task_name,
                enabled=True,
                schedule=info.default_schedule,
            )
            db.add(row)
        if row.is_deleted:
            row.is_deleted = False
        if "enabled" in values:
            row.enabled = values["enabled"]
        if "schedule" in values:
            row.schedule = values["schedule"]
        if "targets" in values:
            row.targets = values["targets"]
        if "note" in values:
            row.note = values["note"]

        after = self._compact(row)
        before_enabled = before.get("enabled") if before else None
        action = (
            "enable" if (row.enabled and before_enabled is False)
            else "disable" if (not row.enabled and before_enabled is not False)
            else "update"
        )
        db.add(
            WarehousePushTaskAudit(
                task_name=task_name,
                action=action,
                before_json=before,
                after_json=after,
                operator_name=operator_name,
            )
        )
        await db.flush()

        fresh = (
            await db.execute(
                select(WarehousePushTask).where(
                    WarehousePushTask.task_name == task_name,
                    WarehousePushTask.is_deleted.is_(False),
                )
            )
        ).scalars().first()
        self.invalidate(task_name)
        return self._build_view(info, fresh, "db") if fresh is not None else self.get_task_view(task_name)

    # ═══════════════════════════════════════════════════════════
    # 内部：解析与校验
    # ═══════════════════════════════════════════════════════════

    def _state(
        self, task_name: str
    ) -> tuple[bool, dict[str, Any] | None, tuple[str, ...], PushSource]:
        info = registry.get_task(task_name)
        now = time.monotonic()
        cached = self._cache.get(task_name)
        if cached is not None and now - self._loaded_at.get(task_name, 0.0) < self._ttl_seconds:
            return cached
        row = self._fetch_row(task_name)
        if row is not None and row.is_deleted:
            row = None
        state = self._state_from_row(info, row)
        self._cache[task_name] = state
        self._loaded_at[task_name] = now
        return state

    def _state_from_row(
        self, info: registry.PushTaskInfo, row: Any | None
    ) -> tuple[bool, dict[str, Any] | None, tuple[str, ...], PushSource]:
        if row is None:
            return True, info.default_schedule, self._env_targets(info), "default"
        schedule = row.schedule or info.default_schedule
        targets = split_targets(row.targets) or self._env_targets(info)
        return bool(row.enabled), schedule, targets, "db"

    def _env_targets(self, info: registry.PushTaskInfo) -> tuple[str, ...]:
        if not info.target_env_var:
            return ()
        value = getattr(get_settings(), info.target_env_var, None)
        return split_targets(value)

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if "enabled" in payload:
            if not isinstance(payload["enabled"], bool):
                raise ValueError("enabled 必须为布尔值")
            values["enabled"] = payload["enabled"]
        if "schedule" in payload:
            values["schedule"] = _validate_schedule(payload["schedule"])
        if "targets" in payload:
            raw = payload["targets"]
            text = str(raw).strip() if raw is not None else ""
            if len(text) > _TARGETS_MAX_LEN:
                raise ValueError(f"targets 总长度不能超过 {_TARGETS_MAX_LEN}")
            entries = split_targets(text)
            if len(entries) > _TARGET_MAX_COUNT:
                raise ValueError(f"targets 条目数不能超过 {_TARGET_MAX_COUNT}")
            for entry in entries:
                if len(entry) > _TARGET_MAX_LEN:
                    raise ValueError(f"单个目标长度不能超过 {_TARGET_MAX_LEN}: {entry[:16]}…")
            values["targets"] = text or None
        if "note" in payload:
            raw = payload["note"]
            if raw is not None and len(str(raw)) > _NOTE_MAX_LEN:
                raise ValueError(f"note 长度不能超过 {_NOTE_MAX_LEN}")
            values["note"] = str(raw).strip() if raw is not None else None
        if not values:
            raise ValueError("缺少可更新字段（enabled/schedule/targets/note）")
        return values

    @staticmethod
    def _compact(row: WarehousePushTask) -> dict[str, Any]:
        return {
            "enabled": row.enabled,
            "schedule": row.schedule,
            "targets": row.targets,
            "note": row.note,
        }

    def _fetch_row(self, task_name: str) -> WarehousePushTask | None:
        try:
            if self._row_loader is not None:
                return cast("WarehousePushTask | None", self._row_loader(task_name))
            from app.modules.warehouse.ai_config._db import make_sync_session_factory

            with make_sync_session_factory()() as session:
                row = session.execute(
                    select(WarehousePushTask).where(
                        WarehousePushTask.task_name == task_name,
                        WarehousePushTask.is_deleted.is_(False),
                    )
                ).scalars().first()
                return row
        except Exception:
            logger.exception("推送任务配置 DB 读取失败（task=%s），回退注册表默认", task_name)
            return None

    @staticmethod
    async def _find_row(db: AsyncSession, task_name: str) -> WarehousePushTask | None:
        stmt = (
            select(WarehousePushTask)
            .where(WarehousePushTask.task_name == task_name)
            .order_by(WarehousePushTask.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()

    def _build_view(
        self, info: registry.PushTaskInfo, row: Any, source: PushSource
    ) -> PushTaskView:
        enabled, schedule, targets, _ = self._state_from_row(info, row)
        return PushTaskView(
            task_name=info.task_name,
            scene=info.scene,
            label=info.label,
            description=info.description,
            trigger=info.trigger,
            enabled=enabled,
            schedule=schedule,
            targets=targets,
            source=source,
        )


def _validate_hhmm(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("schedule 的 time 必须为 HH:MM 字符串")
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("schedule 的 time 必须为 HH:MM 格式")
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError("schedule 的 time 必须为 HH:MM 格式") from exc
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("schedule 的 time 超出合法范围")
    return f"{hh:02d}:{mm:02d}"


def _validate_window(schedule: dict[str, Any]) -> None:
    window = schedule.get("window_minutes", 60)
    if isinstance(window, bool) or not isinstance(window, int):
        raise ValueError("window_minutes 必须为整数")
    lo, hi = _WINDOW_MINUTES_RANGE
    if not (lo <= window <= hi):
        raise ValueError(f"window_minutes 必须在 {lo}-{hi} 分钟之间")


def _validate_schedule(schedule: Any) -> dict[str, Any] | None:
    """schedule 五态校验：daily / weekly / monthly / yearly / interval；null = 恢复默认。"""
    if schedule is None:
        return None
    if not isinstance(schedule, dict):
        raise ValueError("schedule 必须为对象或 null")
    stype = schedule.get("type")
    if stype == "daily":
        out: dict[str, Any] = {"type": "daily", "time": _validate_hhmm(schedule.get("time"))}
        _validate_window(schedule)
        out["window_minutes"] = schedule.get("window_minutes", 60)
        return out
    if stype == "weekly":
        weekday = schedule.get("weekday")
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise ValueError("weekly schedule 的 weekday 必须为 0-6 整数（0=周一）")
        out = {"type": "weekly", "weekday": weekday, "time": _validate_hhmm(schedule.get("time"))}
        _validate_window(schedule)
        out["window_minutes"] = schedule.get("window_minutes", 60)
        return out
    if stype == "monthly":
        day = schedule.get("day")
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
            raise ValueError("monthly schedule 的 day 必须为 1-31 整数")
        out = {"type": "monthly", "day": day, "time": _validate_hhmm(schedule.get("time"))}
        _validate_window(schedule)
        out["window_minutes"] = schedule.get("window_minutes", 60)
        return out
    if stype == "yearly":
        month = schedule.get("month")
        day = schedule.get("day")
        if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
            raise ValueError("yearly schedule 的 month 必须为 1-12 整数")
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
            raise ValueError("yearly schedule 的 day 必须为 1-31 整数")
        out = {
            "type": "yearly", "month": month, "day": day,
            "time": _validate_hhmm(schedule.get("time")),
        }
        _validate_window(schedule)
        out["window_minutes"] = schedule.get("window_minutes", 60)
        return out
    if stype == "interval":
        seconds = schedule.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < _INTERVAL_MIN_SECONDS:
            raise ValueError(f"interval schedule 的 seconds 必须为 >={_INTERVAL_MIN_SECONDS} 的整数")
        return {"type": "interval", "seconds": seconds}
    raise ValueError("schedule.type 仅支持 daily/weekly/monthly/yearly/interval（null = 恢复默认）")


push_store = PushConfigStore()

__all__ = ["PushConfigStore", "PushTaskView", "push_store", "split_targets"]
