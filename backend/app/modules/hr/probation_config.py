"""试用期时长配置（hr.system_settings KV + 进程内缓存）。

computed_probation_end 是同步 property，无法在属性访问时查库，因此用
进程级缓存：启动（main lifespan）、每日提醒任务、转正发起时刷新；
配置变更后最迟次日生效，满足"极少调整"的时长配置场景。
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import SystemSetting

logger = logging.getLogger(__name__)

KEY_STANDARD = "probation.duration_months.standard"
KEY_KEY_POSITION = "probation.duration_months.key_position"

DEFAULT_STANDARD_MONTHS = 3
DEFAULT_KEY_MONTHS = 6

_cache: dict[str, int] = {
    "standard": DEFAULT_STANDARD_MONTHS,
    "key_position": DEFAULT_KEY_MONTHS,
}


def probation_months(is_key_position: bool | None) -> int:
    """按是否重点岗位取试用期月数（同步读缓存，供 ORM property 使用）。"""
    return _cache["key_position"] if is_key_position else _cache["standard"]


async def reload_probation_config(session: AsyncSession) -> None:
    """从 system_settings 重读时长配置进缓存（缺省回落默认值）。"""
    global _cache
    rows = (await session.execute(
        select(SystemSetting.key, SystemSetting.value).where(
            SystemSetting.key.in_((KEY_STANDARD, KEY_KEY_POSITION)),
            SystemSetting.is_deleted.is_(False),
        )
    )).all()
    loaded: dict[str, str] = {k: v for k, v in rows}
    standard = _parse_months(loaded.get(KEY_STANDARD), DEFAULT_STANDARD_MONTHS)
    key_position = _parse_months(loaded.get(KEY_KEY_POSITION), DEFAULT_KEY_MONTHS)
    _cache = {"standard": standard, "key_position": key_position}
    logger.info("试用期时长配置已加载：一般 %d 个月 / 重点岗位 %d 个月", standard, key_position)


def _parse_months(raw: str | None, default: int) -> int:
    try:
        months = int(str(raw or "").strip())
    except (TypeError, ValueError):
        return default
    return months if 1 <= months <= 12 else default
