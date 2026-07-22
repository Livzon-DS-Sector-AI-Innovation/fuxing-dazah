"""Platform scheduler — unified background task scheduling infrastructure.

Provides three scheduling primitives:

* :class:`TaskDefinition` — code-defined static tasks
* :class:`TaskGenerator` — DB-driven dynamic work scanners
* ``register_action_handler()`` — named action registry for future
  ``ScheduledJob`` table support

All are driven by a single :class:`SchedulerEngine` asyncio loop.
"""

from app.platform.scheduler.engine import SchedulerEngine
from app.platform.scheduler.registry import (
    ScheduleConfig,
    SchedulerRegistry,
    ScheduleStrategy,
    TaskDefinition,
    TaskGenerator,
    get_action_handler,
    register_action_handler,
)

__all__ = [
    "SchedulerEngine",
    "SchedulerRegistry",
    "ScheduleConfig",
    "ScheduleStrategy",
    "TaskDefinition",
    "TaskGenerator",
    "get_action_handler",
    "register_action_handler",
]
