"""液相计算表模板配置数据访问。"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    LcTemplateConfig,
)

# ─── 液相计算表模板配置 ───


async def get_lc_template_by_table_no(
    db: AsyncSession, table_no: str
) -> LcTemplateConfig | None:
    """按表号查模板配置（EX-xx-xxxx-vvv）。"""
    stmt = select(LcTemplateConfig).where(
        LcTemplateConfig.table_no == table_no,
        LcTemplateConfig.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_lc_template_configs(db: AsyncSession) -> list[LcTemplateConfig]:
    stmt = select(LcTemplateConfig).where(
        LcTemplateConfig.is_deleted == False,  # noqa: E712
    ).order_by(LcTemplateConfig.table_no)
    return list((await db.execute(stmt)).scalars())


async def create_lc_template_config(
    db: AsyncSession, table_no: str, product_name: str,
    sop_no: str | None, description: str | None, config: dict[str, Any],
) -> LcTemplateConfig:
    """新增液相模板配置。INSERT 后 flush 返回。"""
    cfg = LcTemplateConfig(
        table_no=table_no, product_name=product_name,
        sop_no=sop_no, description=description, config=config,
    )
    db.add(cfg)
    await db.flush()
    return cfg


async def update_lc_template_config(
    db: AsyncSession, cfg_id: uuid.UUID, **kwargs: Any
) -> LcTemplateConfig | None:
    """更新液相模板配置字段。"""
    stmt = select(LcTemplateConfig).where(
        LcTemplateConfig.id == cfg_id,
        LcTemplateConfig.is_deleted == False,  # noqa: E712
    )
    cfg = (await db.execute(stmt)).scalar_one_or_none()
    if not cfg:
        return None
    for key, val in kwargs.items():
        if hasattr(cfg, key) and val is not None:
            setattr(cfg, key, val)
    await db.flush()
    return cfg


async def delete_lc_template_config(db: AsyncSession, cfg_id: uuid.UUID) -> bool:
    """软删除液相模板配置。"""
    stmt = select(LcTemplateConfig).where(
        LcTemplateConfig.id == cfg_id,
        LcTemplateConfig.is_deleted == False,  # noqa: E712
    )
    cfg = (await db.execute(stmt)).scalar_one_or_none()
    if not cfg:
        return False
    cfg.is_deleted = True
    await db.flush()
    return True
