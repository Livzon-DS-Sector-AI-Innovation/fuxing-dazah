"""R1 links 仓储 —— 查/建幂等（第三道幂等保险的落点）。

执行器入口先 get_or_create：已有 hazard_record_id 即跳过 create_record
（重试安全）；失败也留行（error_message 留痕，重试成功后清空）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models.alarm_hazard_link import AlarmHazardLink


async def get_or_create_link(
    session: AsyncSession,
    *,
    alarm_domain: str,
    alarm_record_id: str,
    alarm_fingerprint: str | None,
    alarm_snapshot: dict[str, Any],
    task_id: uuid.UUID | None = None,
) -> tuple[AlarmHazardLink, bool]:
    """查/建 links 行。

    Returns:
        (行, created)。已存在（含 failed 留痕行）返回既有行——快照不覆盖、
        task_id/指纹不回退（首见即历史事实）。
    """
    existing = (
        await session.execute(
            select(AlarmHazardLink).where(
                AlarmHazardLink.alarm_domain == alarm_domain,
                AlarmHazardLink.alarm_record_id == alarm_record_id,
                AlarmHazardLink.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    row = AlarmHazardLink(
        alarm_domain=alarm_domain,
        alarm_record_id=alarm_record_id,
        alarm_fingerprint=alarm_fingerprint,
        alarm_snapshot=alarm_snapshot,
        task_id=task_id,
    )
    session.add(row)
    await session.flush()
    return row, True
