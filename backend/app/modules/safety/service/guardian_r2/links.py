"""R2 links 仓储 —— 资格状态权威表的查/建/流转（自开 session 模式由执行器管）。

幂等语义（首见事实）：
- get_or_create：同 record_id 二次调用返回既有行，snapshot/人员信息不覆盖
- mark_revoked：已 revoked 不重复流转（reason/at 保留首见）
- mark_restored：restored 后再 restore 幂等；revoked 之外的状态不变
- append_score_event：exam_history 只追加

津贴联动读 list_revoked（qualification_status == 'revoked'）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models.guardian_qualification_link import (
    GuardianQualificationLink,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def get_active_link(
    session: AsyncSession, record_id: str
) -> GuardianQualificationLink | None:
    """按 record_id 取活行（全仓储共用的唯一查询块）。"""
    return await session.scalar(
        select(GuardianQualificationLink).where(
            GuardianQualificationLink.record_id == record_id,
            GuardianQualificationLink.is_deleted == False,  # noqa: E712
        )
    )


async def get_or_create_link(
    session: AsyncSession,
    *,
    record_id: str,
    person_name: str,
    department: str | None,
    cert_category: str,
    snapshot: dict[str, Any],
) -> tuple[GuardianQualificationLink, bool]:
    """查/建 links 行（record_id 幂等；首见 snapshot 不覆盖）。"""
    row = await get_active_link(session, record_id)
    if row is not None:
        return row, False
    row = GuardianQualificationLink(
        record_id=record_id,
        person_name=person_name,
        department=department,
        cert_category=cert_category,
        snapshot=snapshot,
    )
    session.add(row)
    await session.flush()
    return row, True


async def bump_reminder(
    session: AsyncSession, record_id: str, month_key: str
) -> GuardianQualificationLink | None:
    """提醒计数 +1 并落最后提醒月份（执行器发卡成功后调用）。"""
    row = await get_active_link(session, record_id)
    if row is None:
        return None
    row.remind_count += 1
    row.last_reminded_month = month_key
    await session.flush()
    return row


async def mark_revoked(
    session: AsyncSession,
    record_id: str,
    *,
    reason: str,
    revoked_by: str | None = None,
) -> GuardianQualificationLink | None:
    """取消资格（幂等：已 revoked 保留首见 reason/at/by）。"""
    row = await get_active_link(session, record_id)
    if row is None:
        return None
    if row.qualification_status != "revoked":
        row.qualification_status = "revoked"
        row.revoked_reason = reason
        row.revoked_at = _now()
        row.revoked_by = revoked_by
        await session.flush()
    return row


async def mark_restored(
    session: AsyncSession,
    record_id: str,
    *,
    confirmed_by: str | None,
) -> GuardianQualificationLink | None:
    """恢复资格（幂等；restored 状态重复调用保留首见 at/confirmed_by）。"""
    row = await get_active_link(session, record_id)
    if row is None:
        return None
    if row.qualification_status != "restored":
        row.qualification_status = "restored"
        row.restored_at = _now()
        row.confirmed_by = confirmed_by
        await session.flush()
    return row


async def append_score_event(
    session: AsyncSession, record_id: str, event: dict[str, Any]
) -> GuardianQualificationLink | None:
    """考核事件追加 exam_history + 刷新 last_score_event（顺序消费依据）。"""
    row = await get_active_link(session, record_id)
    if row is None:
        return None
    history = list(row.exam_history or [])
    history.append(event)
    row.exam_history = history
    row.last_score_event = event
    await session.flush()
    return row


async def list_revoked(
    session: AsyncSession,
) -> list[GuardianQualificationLink]:
    """revoked 名单（津贴联动剔除依据；active/restored 均正常计发）。"""
    rows = (
        await session.execute(
            select(GuardianQualificationLink)
            .where(
                GuardianQualificationLink.qualification_status == "revoked",
                GuardianQualificationLink.is_deleted == False,  # noqa: E712
            )
            .order_by(GuardianQualificationLink.person_name)
        )
    ).scalars().all()
    return list(rows)


async def revoked_name_map(session: AsyncSession) -> dict[str, str]:
    """津贴联动用：{姓名(去空格): 取消原因}（links 表缺失时容错空表）。

    容错原因：津贴链路先于 R2 迁移运行时（或测试库）表可能不存在——
    返回空映射 = 不剔除，行为与 R2 上线前一致。
    """
    def _norm(name: str) -> str:
        return "".join(str(name).split())

    try:
        rows = await list_revoked(session)
    except Exception:
        return {}
    return {_norm(r.person_name): r.revoked_reason or "资格已取消" for r in rows}
