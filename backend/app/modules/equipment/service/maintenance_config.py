"""Maintenance config service."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment import repository as repo
from app.modules.equipment.schemas.maintenance_config import (
    AdvanceDaysConfig,
    AdvanceDaysUpdateRequest,
    ClaimTimeoutConfig,
    ClaimTimeoutUpdateRequest,
)

_TIMEOUT_KEYS = [
    "claim_timeout_emergency",
    "claim_timeout_high",
    "claim_timeout_medium",
    "claim_timeout_low",
]


async def get_claim_timeout_config(
    db: AsyncSession,
) -> ClaimTimeoutConfig:
    configs = await repo.get_configs(db, _TIMEOUT_KEYS)
    return ClaimTimeoutConfig(
        emergency=int(configs.get("claim_timeout_emergency", 15)),
        high=int(configs.get("claim_timeout_high", 30)),
        medium=int(configs.get("claim_timeout_medium", 60)),
        low=int(configs.get("claim_timeout_low", 120)),
    )


async def update_claim_timeout_config(
    db: AsyncSession, data: ClaimTimeoutUpdateRequest
) -> ClaimTimeoutConfig:
    updates = {}
    for key, field in [
        ("claim_timeout_emergency", "emergency"),
        ("claim_timeout_high", "high"),
        ("claim_timeout_medium", "medium"),
        ("claim_timeout_low", "low"),
    ]:
        value = getattr(data, field)
        if value is not None:
            updates[key] = str(value)

    if updates:
        await repo.upsert_configs(db, updates)

    return await get_claim_timeout_config(db)


_ADVANCE_DAYS_KEY = "maintenance_plan_advance_days"
_AUTO_EXECUTE_KEY = "maintenance_plan_auto_execute"


async def get_advance_days_config(
    db: AsyncSession,
) -> AdvanceDaysConfig:
    """获取维护计划自动创建配置。advance_days 默认 0，auto_execute 默认 true。"""
    configs = await repo.get_configs(db, [_ADVANCE_DAYS_KEY, _AUTO_EXECUTE_KEY])
    return AdvanceDaysConfig(
        advance_days=int(configs.get(_ADVANCE_DAYS_KEY, 0)),
        auto_execute=configs.get(_AUTO_EXECUTE_KEY, "true") == "true",
    )


async def update_advance_days_config(
    db: AsyncSession, data: AdvanceDaysUpdateRequest
) -> AdvanceDaysConfig:
    """更新维护计划自动创建配置。"""
    await repo.upsert_configs(
        db,
        {
            _ADVANCE_DAYS_KEY: str(data.advance_days),
            _AUTO_EXECUTE_KEY: "true" if data.auto_execute else "false",
        },
    )
    return await get_advance_days_config(db)
