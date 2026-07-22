"""Scheduled task engine — asyncio loop stub.

Scheduled tasks module was removed in refactor (a985172).
This stub remains to satisfy the import in app/main.py lifespan.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# Stop flag, set during app shutdown
stop_scheduled_task_flag = asyncio.Event()

# Tick interval in seconds
TICK_INTERVAL = 30


async def scheduled_task_loop():
    """Main scheduler loop stub — no-op after scheduled tasks removal.

    Launched in the FastAPI lifespan, runs until stop_scheduled_task_flag is set.
    """
    logger.info("Scheduled task loop started (tick=%ds) [stub]", TICK_INTERVAL)

    while not stop_scheduled_task_flag.is_set():
        try:
            await asyncio.wait_for(stop_scheduled_task_flag.wait(), timeout=TICK_INTERVAL)
        except asyncio.TimeoutError:
            pass  # Normal tick timeout, loop continues

    logger.info("Scheduled task loop stopped")
