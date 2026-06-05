"""Maintenance config repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models.maintenance_config import MaintenanceConfig


async def get_configs(
    db: AsyncSession, keys: list[str]
) -> dict[str, str]:
    result = await db.execute(
        select(MaintenanceConfig).where(
            MaintenanceConfig.config_key.in_(keys),
            MaintenanceConfig.is_deleted == False,  # noqa: E712
        )
    )
    configs = result.scalars().all()
    return {c.config_key: c.config_value for c in configs}


async def upsert_configs(
    db: AsyncSession, data: dict[str, str]
) -> None:
    existing = await get_configs(db, list(data.keys()))
    for key, value in data.items():
        if key in existing:
            result = await db.execute(
                select(MaintenanceConfig).where(
                    MaintenanceConfig.config_key == key,
                    MaintenanceConfig.is_deleted == False,  # noqa: E712
                )
            )
            config = result.scalar_one()
            config.config_value = value
        else:
            config = MaintenanceConfig(config_key=key, config_value=value)
            db.add(config)
    await db.flush()
