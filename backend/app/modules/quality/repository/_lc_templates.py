"""Quality 模块数据读写。只负责查询与持久化，不做业务判断。"""


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
