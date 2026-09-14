"""定时任务/告警目标配置 store — 任务行的运行时大脑。

- **读（热路径，全同步）**：``get_job_view`` / ``iter_job_views`` / ``get_alert_target``；
- **回退链**：target = DB 活行（非空）→ env（registry.target_env_var）→ 空；
  enabled/schedule = DB 活行 → registry 默认；缺行 = 按注册表默认（启用）。
- **写（async，API 层传入 session）**：``set_job`` 校验（schedule 二态格式）→
  软删行恢复 → before/after 审计 → flush → re-fetch → invalidate。
- **测试接缝**：构造函数 ``row_loader`` 注入预设行；生产不传走同步会话工厂。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.models import SchedulerConfigAudit, SchedulerTaskConfig
from app.modules.warehouse.ops_config import scheduler_registry

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60.0

JobSource = Literal["db", "default"]
JobRowLoader = Callable[[str], Any]


@dataclass(frozen=True)
class JobView:
    """单任务合并视图。"""

    job_name: str
    label: str
    description: str
    enabled: bool
    schedule: dict[str, Any] | None
    target_chat_id: str | None
    source: JobSource


class SchedulerConfigStore:
    """模块级单例。热路径全同步（内存缓存），写操作 async（DB + 审计 + 失效）。"""

    def __init__(self, row_loader: JobRowLoader | None = None) -> None:
        self._cache: dict[str, tuple[bool, dict[str, Any] | None, str | None, JobSource]] = {}
        self._loaded_at: dict[str, float] = {}
        self._ttl_seconds: float = _TTL_SECONDS
        self._row_loader = row_loader

    # ═══════════════════════════════════════════════════════════
    # 读（热路径，同步）
    # ═══════════════════════════════════════════════════════════

    def get_job_view(self, job_name: str) -> JobView:
        """某任务合并视图；未知任务抛 ValueError（404 语义）。"""
        info = scheduler_registry.get_task(job_name)  # 未知任务抛 ValueError
        enabled, schedule, target, source = self._state(job_name)
        return JobView(
            job_name=info.job_name,
            label=info.label,
            description=info.description,
            enabled=enabled,
            schedule=schedule,
            target_chat_id=target,
            source=source,
        )

    def iter_job_views(self) -> tuple[JobView, ...]:
        """遍历全部任务（供 GET 总览）。"""
        return tuple(self.get_job_view(info.job_name) for info in scheduler_registry.iter_tasks())

    def get_alert_target(self) -> str | None:
        """系统告警目标：system_alert 行 target → env 兜底 → None（失败通知消费）。"""
        try:
            return self.get_job_view("system_alert").target_chat_id or None
        except Exception:
            logger.exception("告警目标读取失败，回退 env 兜底")
            return self._env_target("system_alert")

    # ═══════════════════════════════════════════════════════════
    # 缓存维护
    # ═══════════════════════════════════════════════════════════

    def invalidate(self, job_name: str | None = None) -> None:
        """失效缓存；None = 全部失效。"""
        if job_name is None:
            self._cache.clear()
            self._loaded_at.clear()
            return
        self._cache.pop(job_name, None)
        self._loaded_at.pop(job_name, None)

    async def warmup(self) -> None:
        """启动预热（失败仅告警，读路径回退注册表默认）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                rows = (
                    await session.execute(
                        select(SchedulerTaskConfig).where(
                            SchedulerTaskConfig.is_deleted.is_(False)
                        )
                    )
                ).scalars().all()
                by_name = {r.job_name: r for r in rows}
                now = time.monotonic()
                for info in scheduler_registry.iter_tasks():
                    row = by_name.get(info.job_name)
                    if row is not None and row.is_deleted:
                        row = None
                    self._cache[info.job_name] = self._state_from_row(info, row)
                    self._loaded_at[info.job_name] = now
        except Exception:
            logger.exception("任务配置启动预热失败（读路径将以注册表默认兜底）")

    # ═══════════════════════════════════════════════════════════
    # 写（async；API 层传入 session）
    # ═══════════════════════════════════════════════════════════

    async def set_job(
        self,
        db: AsyncSession,
        job_name: str,
        payload: dict[str, Any],
        operator_name: str | None = None,
    ) -> JobView:
        """更新任务行（事务 + 审计 + 失效）。

        - 未知任务抛 ValueError（404 语义）；
        - enabled 必须 bool；schedule 须为 interval/cron 二态或 null（清空=默认）；
        - target_chat_id 空串/None = 清空覆盖（回落 env）。
        """
        info = scheduler_registry.get_task(job_name)
        values = self._validate_payload(payload)

        row = await self._find_row(db, job_name)
        before = self._compact(row) if row is not None else None
        if row is None:
            row = SchedulerTaskConfig(
                job_name=job_name,
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
        if "target_chat_id" in values:
            row.target_chat_id = values["target_chat_id"]
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
            SchedulerConfigAudit(
                job_name=job_name,
                action=action,
                before_json=before,
                after_json=after,
                operator_name=operator_name,
            )
        )
        await db.flush()

        fresh = (
            await db.execute(
                select(SchedulerTaskConfig).where(
                    SchedulerTaskConfig.job_name == job_name,
                    SchedulerTaskConfig.is_deleted.is_(False),
                )
            )
        ).scalars().first()
        self.invalidate(job_name)
        return self.get_job_view(job_name) if fresh is None else self._build_view(info, fresh, "db")

    # ═══════════════════════════════════════════════════════════
    # 内部：解析与校验
    # ═══════════════════════════════════════════════════════════

    def _state(
        self, job_name: str
    ) -> tuple[bool, dict[str, Any] | None, str | None, JobSource]:
        info = scheduler_registry.get_task(job_name)
        now = time.monotonic()
        cached = self._cache.get(job_name)
        if cached is not None and now - self._loaded_at.get(job_name, 0.0) < self._ttl_seconds:
            return cached
        row = self._fetch_row(job_name)
        if row is not None and row.is_deleted:
            row = None
        state = self._state_from_row(info, row)
        self._cache[job_name] = state
        self._loaded_at[job_name] = now
        return state

    def _state_from_row(
        self, info: scheduler_registry.TaskInfo, row: Any | None
    ) -> tuple[bool, dict[str, Any] | None, str | None, JobSource]:
        if row is None:
            return True, info.default_schedule, self._env_target(info.job_name), "default"
        target = (row.target_chat_id or "").strip() or self._env_target(info.job_name)
        return bool(row.enabled), row.schedule, target or None, "db"

    def _env_target(self, job_name: str) -> str | None:
        info = scheduler_registry.get_task(job_name)
        if not info.target_env_var:
            return None
        value = getattr(get_settings(), info.target_env_var, None)
        return value or None

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if "enabled" in payload:
            if not isinstance(payload["enabled"], bool):
                raise ValueError("enabled 必须为布尔值")
            values["enabled"] = payload["enabled"]
        if "schedule" in payload:
            values["schedule"] = _validate_schedule(payload["schedule"])
        if "target_chat_id" in payload:
            raw = payload["target_chat_id"]
            text = str(raw).strip() if raw is not None else ""
            if len(text) > 64:
                raise ValueError("target_chat_id 长度不能超过 64")
            values["target_chat_id"] = text or None
        if "note" in payload:
            raw = payload["note"]
            if raw is not None and len(str(raw)) > 255:
                raise ValueError("note 长度不能超过 255")
            values["note"] = str(raw).strip() if raw is not None else None
        if not values:
            raise ValueError("缺少可更新字段（enabled/schedule/target_chat_id/note）")
        return values

    @staticmethod
    def _compact(row: SchedulerTaskConfig) -> dict[str, Any]:
        return {
            "enabled": row.enabled,
            "schedule": row.schedule,
            "target_chat_id": row.target_chat_id,
            "note": row.note,
        }

    def _fetch_row(self, job_name: str) -> SchedulerTaskConfig | None:
        try:
            if self._row_loader is not None:
                return cast("SchedulerTaskConfig | None", self._row_loader(job_name))
            from app.modules.warehouse.ai_config._db import make_sync_session_factory

            with make_sync_session_factory()() as session:
                row = session.execute(
                    select(SchedulerTaskConfig).where(
                        SchedulerTaskConfig.job_name == job_name,
                        SchedulerTaskConfig.is_deleted.is_(False),
                    )
                ).scalars().first()
                return row
        except Exception:
            logger.exception("任务配置 DB 读取失败（job=%s），回退注册表默认", job_name)
            return None

    @staticmethod
    async def _find_row(db: AsyncSession, job_name: str) -> SchedulerTaskConfig | None:
        stmt = (
            select(SchedulerTaskConfig)
            .where(SchedulerTaskConfig.job_name == job_name)
            .order_by(SchedulerTaskConfig.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()

    def _build_view(
        self, info: scheduler_registry.TaskInfo, row: Any, source: JobSource
    ) -> JobView:
        enabled, schedule, target, _ = self._state_from_row(info, row)
        return JobView(
            job_name=info.job_name,
            label=info.label,
            description=info.description,
            enabled=enabled,
            schedule=schedule,
            target_chat_id=target,
            source=source,
        )


def _validate_schedule(schedule: Any) -> dict[str, Any] | None:
    """schedule 二态校验：interval（seconds 正整数）/ cron（expr 字符串）/ null。"""
    if schedule is None:
        return None
    if not isinstance(schedule, dict):
        raise ValueError("schedule 必须为对象或 null")
    stype = schedule.get("type")
    if stype == "interval":
        seconds = schedule.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 30:
            raise ValueError("interval schedule 的 seconds 必须为 >=30 的整数")
        return {"type": "interval", "seconds": seconds}
    if stype == "cron":
        expr = schedule.get("expr")
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError("cron schedule 必须包含非空 expr")
        return {"type": "cron", "expr": expr.strip()}
    raise ValueError("schedule.type 仅支持 interval / cron（null = 恢复默认）")


scheduler_store = SchedulerConfigStore()

__all__ = ["JobView", "SchedulerConfigStore", "scheduler_store"]
