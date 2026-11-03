"""R1 links 瘦身表仓储测试（B 层，真 PG 回滚式 db_session）。

links 表迁移未执行时由 fixture 在事务内自建（PG 事务 DDL，rollback 即
消失）——测试自包含，不依赖开发库迁移状态，也不污染库。
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.schema import CreateTable

from app.modules.safety.models.alarm_hazard_link import AlarmHazardLink
from app.modules.safety.service.alarm_hazard_r1.links import get_or_create_link


@pytest_asyncio.fixture
async def links_table(db_session):
    """事务内自建 links 表+索引（若迁移已执行则 IF NOT EXISTS 静默跳过）。"""
    from sqlalchemy.schema import CreateIndex

    await db_session.execute(CreateTable(AlarmHazardLink.__table__, if_not_exists=True))
    for idx in AlarmHazardLink.__table__.indexes:
        await db_session.execute(CreateIndex(idx, if_not_exists=True))
    await db_session.flush()
    yield


_SNAPSHOT = {"报警性质": "泄漏报警", "报警原因分类": "氨水引发", "处理情况": "已通知仪表"}


async def test_create_then_get_is_idempotent(db_session, links_table) -> None:
    """同 (domain, record_id) 二次 get_or_create 返回同一行、快照不覆盖。"""
    row1, created1 = await get_or_create_link(
        db_session,
        alarm_domain="fire_alarm", alarm_record_id="recX1",
        alarm_fingerprint="fp1", alarm_snapshot=_SNAPSHOT,
    )
    assert created1 is True
    assert row1.hazard_record_id is None

    row2, created2 = await get_or_create_link(
        db_session,
        alarm_domain="fire_alarm", alarm_record_id="recX1",
        alarm_fingerprint="fp2",  # 新指纹不回退首见事实
        alarm_snapshot={"报警性质": "误报"},
    )
    assert created2 is False
    assert row2.id == row1.id
    assert row2.alarm_fingerprint == "fp1"
    assert row2.alarm_snapshot == _SNAPSHOT

    rows = (
        await db_session.execute(
            select(AlarmHazardLink).where(AlarmHazardLink.alarm_record_id == "recX1")
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_unique_index_blocks_direct_duplicates(db_session, links_table) -> None:
    """部分唯一索引兜底：绕过 get_or_create 直接插同键两行 → 唯一冲突。"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(AlarmHazardLink).values(
        alarm_domain="fire_alarm", alarm_record_id="recDup",
        alarm_snapshot=_SNAPSHOT, is_deleted=False,
    ).on_conflict_do_nothing()
    first = (await db_session.execute(stmt.returning(AlarmHazardLink.id))).scalar_one_or_none()
    second = (await db_session.execute(stmt.returning(AlarmHazardLink.id))).scalar_one_or_none()
    assert first is not None
    assert second is None  # 第二次被唯一索引吞掉（第三道幂等保险）


async def test_soft_deleted_row_allows_recreate(db_session, links_table) -> None:
    """软删后允许重建（部分唯一索引 WHERE is_deleted=false 语义）。"""
    row, _ = await get_or_create_link(
        db_session,
        alarm_domain="fire_alarm", alarm_record_id="recSoft",
        alarm_fingerprint="fp", alarm_snapshot=_SNAPSHOT,
    )
    row.is_deleted = True
    await db_session.flush()

    row2, created2 = await get_or_create_link(
        db_session,
        alarm_domain="fire_alarm", alarm_record_id="recSoft",
        alarm_fingerprint="fp", alarm_snapshot=_SNAPSHOT,
    )
    assert created2 is True
    assert row2.id != row.id
