"""SchedulerEngine — unified asyncio loop for all scheduled work."""

from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.platform.scheduler.registry import (
    SchedulerRegistry,
    TaskDefinition,
    TaskGenerator,
)
from app.platform.scheduler.strategies import is_due

logger = logging.getLogger(__name__)


class SchedulerEngine:
    """Single-loop engine that drives static tasks and dynamic generators.

    The engine polls all registered work on a configurable tick interval
    (default 1 second).  Static tasks are invoked directly; generators
    receive a fresh database session each tick.

    Usage::

        registry = SchedulerRegistry()
        engine = SchedulerEngine(registry)
        task = asyncio.create_task(engine.run())
        # ... application runs ...
        engine.stop()
        task.cancel()
    """

    def __init__(self, registry: SchedulerRegistry) -> None:
        self._registry = registry
        self._stop_flag = asyncio.Event()
        self._last_run: dict[str, datetime] = {}
        self._tick_interval: float = 1.0

    # ── public API ──────────────────────────────────────────────

    @property
    def tick_interval(self) -> float:
        """Seconds between loop iterations (must be > 0)."""
        return self._tick_interval

    @tick_interval.setter
    def tick_interval(self, seconds: float) -> None:
        if seconds <= 0:
            raise ValueError("tick_interval must be positive")
        self._tick_interval = seconds

    def stop(self) -> None:
        """Signal the engine to exit at the end of the current tick."""
        self._stop_flag.set()

    # ── main loop ───────────────────────────────────────────────

    async def run(self) -> None:
        """Enter the scheduling loop.  Runs until :meth:`stop` is called."""
        logger.info(
            "SchedulerEngine started (tick=%.1fs, tasks=%d, generators=%d)",
            self._tick_interval,
            len(self._registry.tasks),
            len(self._registry.generators),
        )

        while not self._stop_flag.is_set():
            iteration_start = _time.monotonic()
            settings = get_settings()

            # ── Phase 1: static tasks ──
            for task in self._registry.tasks.values():
                if self._stop_flag.is_set():
                    break
                await self._maybe_run_task(task, settings)

            # ── Phase 2: dynamic generators ──
            for gen in self._registry.generators.values():
                if self._stop_flag.is_set():
                    break
                await self._maybe_run_generator(gen, settings)

            # ── Tick wait with early-exit on stop ──
            elapsed = _time.monotonic() - iteration_start
            sleep_for = max(0.0, self._tick_interval - elapsed)
            try:
                await asyncio.wait_for(
                    self._stop_flag.wait(), timeout=sleep_for,
                )
            except TimeoutError:
                pass  # normal — next tick

        logger.info("SchedulerEngine stopped")

    # ── static task execution ───────────────────────────────────

    async def _maybe_run_task(
        self, task: TaskDefinition, settings: object,
    ) -> None:
        """Check if *task* is due and execute it."""
        if not task.enabled:
            return
        if task.settings_toggle_key:
            if not getattr(settings, task.settings_toggle_key, True):
                return

        now = datetime.now().astimezone()
        last = self._last_run.get(task.name)
        if not is_due(task.schedule, last, now):
            return

        # Mark before execution — prevents double-fire within a tick
        # and keeps cron / fixed-time from re-triggering during a long run.
        self._last_run[task.name] = now
        logger.debug("Running task: %s", task.name)

        try:
            coro = task.coro()
            await asyncio.wait_for(coro, timeout=task.timeout_seconds)
            logger.debug("Task completed: %s", task.name)
        except TimeoutError:
            logger.error(
                "Task '%s' timed out after %ds",
                task.name, task.timeout_seconds,
            )
        except Exception:
            logger.exception("Task '%s' failed with exception", task.name)

    # ── generator execution ─────────────────────────────────────

    async def _maybe_run_generator(
        self, gen: TaskGenerator, settings: object,
    ) -> None:
        """Check if *gen* is due, scan the DB, and process due items."""
        if not gen.enabled:
            return
        if gen.settings_toggle_key:
            if not getattr(settings, gen.settings_toggle_key, True):
                return

        now = datetime.now().astimezone()
        last = self._last_run.get(gen.name)
        if not is_due(gen.schedule, last, now):
            return

        self._last_run[gen.name] = now
        logger.debug("Running generator: %s", gen.name)

        try:
            async with async_session_factory() as session:
                items = await asyncio.wait_for(
                    gen.find_due(session), timeout=gen.timeout_seconds,
                )
                for item in items:
                    if self._stop_flag.is_set():
                        break
                    try:
                        await asyncio.wait_for(
                            gen.execute_one(session, item),
                            timeout=gen.timeout_seconds,
                        )
                    except TimeoutError:
                        logger.error(
                            "Generator '%s' item timed out after %ds",
                            gen.name, gen.timeout_seconds,
                        )
                    except Exception:
                        logger.exception(
                            "Generator '%s' item failed", gen.name,
                        )

                await session.commit()
                logger.debug(
                    "Generator completed: %s (items=%d)",
                    gen.name, len(items),
                )
        except TimeoutError:
            logger.error(
                "Generator '%s' find_due timed out after %ds",
                gen.name, gen.timeout_seconds,
            )
        except Exception:
            logger.exception(
                "Generator '%s' failed with exception", gen.name,
            )
