"""R2 监护人资格 links 瘦身表仓储测试（真 PG 回滚式 db_session）。

links 表 = R2 资格状态权威源：提醒计数、资格状态流转（revoke/restore）、
考核事件流（exam_history 顺序消费依据）。迁移未执行时 fixture 事务内自建。
"""

from __future__ import annotations

from datetime import date, datetime, UTC

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.schema import CreateTable, CreateIndex

from app.modules.safety.models.guardian_qualification_link import (
    GuardianQualificationLink,
)
from app.modules.safety.service.guardian_r2.links import (
    append_score_event,
    bump_reminder,
    get_or_create_link,
    list_revoked,
    mark_restored,
    mark_revoked,
)


@pytest_asyncio.fixture
async def links_table(db_session):
    """事务内自建 links 表+索引（迁移已执行则 IF NOT EXISTS 静默跳过）。"""
    await db_session.execute(
        CreateTable(GuardianQualificationLink.__table__, if_not_exists=True)
    )
    for idx in GuardianQualificationLink.__table__.indexes:
        await db_session.execute(CreateIndex(idx, if_not_exists=True))
    await db_session.flush()
    yield


async def _make(db_session, record_id="recA1", **kw) -> GuardianQualificationLink:
    base = dict(
        record_id=record_id, person_name="张三", department="提炼工程一部",
        cert_category="guardian_a",
        snapshot={"issue_date": "2026-01-10"},
    )
    base.update(kw)
    row, _ = await get_or_create_link(db_session, **base)
    return row


async def test_get_or_create_idempotent(db_session, links_table) -> None:
    """同 record_id 二次 get_or_create 返回同一行、快照不覆盖（首见事实）。"""
    row1, created1 = await get_or_create_link(
        db_session, record_id="recX1", person_name="张三",
        department="提炼工程一部", cert_category="guardian_a",
        snapshot={"node": "第一次复审"},
    )
    assert created1 is True
    assert row1.qualification_status == "active"
    assert row1.remind_count == 0

    row2, created2 = await get_or_create_link(
        db_session, record_id="recX1", person_name="张三",
        department="提炼工程一部", cert_category="guardian_a",
        snapshot={"node": "换证"},
    )
    assert created2 is False
    assert row2.id == row1.id
    assert row2.snapshot == {"node": "第一次复审"}


async def test_bump_reminder_counts_and_months(db_session, links_table) -> None:
    row = await _make(db_session, "recB1")
    row = await bump_reminder(db_session, "recB1", "2026-08")
    assert row.remind_count == 1
    assert row.last_reminded_month == "2026-08"
    row = await bump_reminder(db_session, "recB1", "2026-09")
    assert row.remind_count == 2
    assert row.last_reminded_month == "2026-09"


async def test_mark_revoked_then_restore(db_session, links_table) -> None:
    """revoke 记 reason/at；幂等（已 revoked 不重复流转）；restore 记确认人。"""
    await _make(db_session, "recC1")
    row = await mark_revoked(db_session, "recC1", reason="逾期未复审")
    assert row.qualification_status == "revoked"
    assert row.revoked_reason == "逾期未复审"
    assert row.revoked_at is not None
    first_at = row.revoked_at

    row = await mark_revoked(db_session, "recC1", reason="考核不合格")
    assert row.revoked_reason == "逾期未复审"  # 幂等：首见 reason/at 不覆盖
    assert row.revoked_at == first_at

    row = await mark_restored(db_session, "recC1", confirmed_by="ou_admin")
    assert row.qualification_status == "restored"
    assert row.restored_at is not None
    assert row.confirmed_by == "ou_admin"


async def test_append_score_event_builds_history(db_session, links_table) -> None:
    """考核事件追加 exam_history（顺序消费依据）并刷新 last_score_event。"""
    await _make(db_session, "recD1")
    e1 = {"exam_type": "复审", "passed": "合格", "exam_date": "2025-06-01",
          "discriminated": "复审"}
    row = await append_score_event(db_session, "recD1", e1)
    assert row.exam_history == [e1]
    assert row.last_score_event == e1

    e2 = {"exam_type": "复审", "passed": "合格", "exam_date": "2026-06-01",
          "discriminated": "复审"}
    row = await append_score_event(db_session, "recD1", e2)
    assert row.exam_history == [e1, e2]
    assert row.last_score_event == e2


async def test_list_revoked_only_returns_revoked(db_session, links_table) -> None:
    """津贴联动读 revoked 名单：只含 revoked（active/restored 排除）。"""
    await _make(db_session, "recE1", person_name="张三")
    await _make(db_session, "recE2", person_name="李四")
    await _make(db_session, "recE3", person_name="王五")
    await mark_revoked(db_session, "recE2", reason="考核不合格")
    await mark_revoked(db_session, "recE3", reason="逾期未复审")
    await mark_restored(db_session, "recE3", confirmed_by="ou_admin")

    revoked = await list_revoked(db_session)
    names = [r.person_name for r in revoked]
    assert names == ["李四"]
    assert revoked[0].revoked_reason == "考核不合格"


async def test_unique_index_blocks_duplicate_active(db_session, links_table) -> None:
    """部分唯一索引：同 record_id 两活行触发 IntegrityError（幂等第三道保险）。"""
    from sqlalchemy.exc import IntegrityError

    await _make(db_session, "recF1")
    db_session.add(GuardianQualificationLink(
        record_id="recF1", person_name="张三", cert_category="guardian_a",
        snapshot={},
    ))
    with __import__("pytest").raises(IntegrityError):
        await db_session.flush()
