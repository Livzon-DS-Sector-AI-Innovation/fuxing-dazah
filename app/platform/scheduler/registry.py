"""Scheduler domain types, registry, and action handler infrastructure."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# ═══════════════════════════════════════════════════════════════
# Schedule strategy
# ═══════════════════════════════════════════════════════════════


class ScheduleStrategy(str, enum.Enum):
    """How a scheduled task determines its next fire time."""

    CRON = "cron"
    INTERVAL = "interval"
    FIXED_TIME = "fixed_time"


# ═══════════════════════════════════════════════════════════════
# Schedule config — immutable value object
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    """Scheduling parameters for a task or generator.

    Which fields are meaningful depends on ``strategy``::

        CRON        → ``expression`` (e.g. ``"0 9 * * *"``)
        INTERVAL    → ``interval_seconds`` (e.g. 300)
        FIXED_TIME  → ``time_of_day`` (e.g. ``"00:05"``)

    ``timezone`` is shared across all strategies.
    """

    strategy: ScheduleStrategy = ScheduleStrategy.INTERVAL
    expression: str = ""  # cron expression
    interval_seconds: int = 60
    time_of_day: str = ""  # "HH:MM" in local time
    timezone: str = "Asia/Shanghai"


# ═══════════════════════════════════════════════════════════════
# TaskDefinition — a code-defined static scheduled task
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    """A static (code-defined) scheduled task.

    Registered once at application startup.  The engine invokes
    ``coro()`` each time the task is due.
    """

    name: str
    schedule: ScheduleConfig
    # Zero-argument async callable.  Tasks that need a DB session
    # acquire one internally via ``async_session_factory()``.
    coro: Callable[[], Awaitable[None]] = field(
        compare=False, hash=False, repr=False,
    )
    settings_toggle_key: str = ""
    timeout_seconds: int = 300
    enabled: bool = True
    module: str = ""


# ═══════════════════════════════════════════════════════════════
# TaskGenerator — DB-driven dynamic work scanner
# ═══════════════════════════════════════════════════════════════


class TaskGenerator(ABC):
    """Base for generators that scan the database for due work items.

    Each generator is a stateless blueprint.  The engine opens a fresh
    session per tick, calls ``find_due()``, then invokes
    ``execute_one()`` for each returned item, and commits once.

    Subclasses must set a ``name`` class attribute and implement both
    abstract methods.
    """

    name: str = ""
    schedule: ScheduleConfig = ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=30,
    )
    settings_toggle_key: str = ""
    timeout_seconds: int = 300
    enabled: bool = True

    @abstractmethod
    async def find_due(self, session: Any) -> list[Any]:
        """Return items whose scheduled time has arrived."""

    @abstractmethod
    async def execute_one(self, session: Any, item: Any) -> None:
        """Process a single due item inside the session."""


# ═══════════════════════════════════════════════════════════════
# SchedulerRegistry — central collection of tasks & generators
# ═══════════════════════════════════════════════════════════════


class SchedulerRegistry:
    """Holds all registered static tasks and dynamic generators.

    Instantiate once at application startup and pass to
    :class:`SchedulerEngine`.  Modules populate the registry via
    ``register_task()`` / ``register_generator()``.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskDefinition] = {}
        self._generators: dict[str, TaskGenerator] = {}

    # ── registration ──────────────────────────────────────────

    def register_task(self, task: TaskDefinition) -> None:
        """Register a static task.  Raises ValueError on duplicate name."""
        if task.name in self._tasks:
            raise ValueError(f"Duplicate task name: {task.name}")
        self._tasks[task.name] = task

    def register_generator(self, gen: TaskGenerator) -> None:
        """Register a dynamic generator.  Raises ValueError on duplicate name."""
        if not gen.name:
            raise ValueError("TaskGenerator.name must be set before registration")
        if gen.name in self._generators:
            raise ValueError(f"Duplicate generator name: {gen.name}")
        self._generators[gen.name] = gen

    # ── read-only access ──────────────────────────────────────

    @property
    def tasks(self) -> dict[str, TaskDefinition]:
        """Shallow copy of the static task map."""
        return dict(self._tasks)

    @property
    def generators(self) -> dict[str, TaskGenerator]:
        """Shallow copy of the generator map."""
        return dict(self._generators)


# ═══════════════════════════════════════════════════════════════
# Action handler registry — for future ScheduledJob DB table
# ═══════════════════════════════════════════════════════════════

_ACTION_HANDLERS: dict[str, Callable[..., Awaitable[Any]]] = {}


def register_action_handler(
    action_type: str, handler: Callable[..., Awaitable[Any]],
) -> None:
    """Register a named action handler for DB-driven scheduled jobs.

    Raises ValueError if *action_type* is already registered.
    """
    if action_type in _ACTION_HANDLERS:
        raise ValueError(
            f"Action handler '{action_type}' is already registered"
        )
    _ACTION_HANDLERS[action_type] = handler


def get_action_handler(
    action_type: str,
) -> Callable[..., Awaitable[Any]] | None:
    """Return the handler registered for *action_type*, or None."""
    return _ACTION_HANDLERS.get(action_type)
