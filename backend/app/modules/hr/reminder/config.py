"""人事提醒统一配置读取：SystemSetting KV，键前缀 hr_reminder.<type>.。

每类提醒三个键（均可缺省）：
- hr_reminder.<type>.enabled    "true"/"false"，缺省 true（关闭后任务空转只记日志）
- hr_reminder.<type>.open_ids   接收人，逗号分隔，支持「姓名」或「open_id」两种填法
- hr_reminder.<type>.days_ahead 提前提醒天数（各提醒类型自带业务缺省值）

发送前经 resolve_receivers() 把姓名解析成 open_id（identity 优先、员工档案
兜底），解析失败的条目原样当 open_id 直发——兼容纯 open_id 配置，与旧键
probation_reminder.open_ids 的填法保持一致。
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import SystemSetting

logger = logging.getLogger(__name__)

KEY_PREFIX = "hr_reminder"


@dataclass(slots=True)
class ReminderConfig:
    """单类提醒的运行配置（缺省值兜底，库里没配也能跑）。"""

    enabled: bool = True
    receivers: list[str] = field(default_factory=list)
    days_ahead: int | None = None


async def load_reminder_config(
    db: AsyncSession, reminder_type: str, *, default_days_ahead: int | None = None
) -> ReminderConfig:
    """读 hr_reminder.<type>.* 三个 KV 键，缺省兜底。"""
    prefix = f"{KEY_PREFIX}.{reminder_type}."
    rows = (await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.like(f"{prefix}%"),
            SystemSetting.is_deleted.is_(False),
        )
    )).scalars().all()
    kv = {r.key.removeprefix(prefix): (r.value or "") for r in rows}

    receivers = [x.strip() for x in kv.get("open_ids", "").split(",") if x.strip()]
    days_ahead = default_days_ahead
    if kv.get("days_ahead", "").strip().isdigit():
        days_ahead = int(kv["days_ahead"].strip())

    return ReminderConfig(
        enabled=kv.get("enabled", "true").strip().lower() != "false",
        receivers=receivers,
        days_ahead=days_ahead,
    )


async def resolve_receivers(db: AsyncSession, entries: list[str]) -> list[str]:
    """把配置里的接收人条目解析成 open_id 列表。

    姓名 → open_id 复用职称评审的解析口径（identity 优先、同名多人宁可不发）；
    解析不到的条目原样保留（视为直接填的 open_id，交给发送层试发）。
    """
    if not entries:
        return []

    from app.modules.hr.title_review.notify import _lookup_open_id

    resolved: list[str] = []
    for entry in entries:
        # open_id 形如 ou_xxxxx（长度明显长于中文姓名），直接收录
        if entry.startswith(("ou_", "un_", "on_")):
            resolved.append(entry)
            continue
        open_id = await _lookup_open_id(entry)
        if open_id:
            resolved.append(open_id)
        else:
            logger.warning("提醒接收人按姓名解析失败，按 open_id 原样发送: %s", entry)
            resolved.append(entry)
    return resolved
