"""参训人明细落库（链3 扩展）——build_attendee_rows 纯函数 + persist 幂等。

纯函数覆盖：无法识别不落、名单去重保序、unrecognized 单独成行、分数按名
匹配（非法丢弃）、培训行快照映射；persist 覆盖：软删旧重插幂等（部分唯一
索引外不冲突）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.modules.safety.ai_training_record_parsing import (
    DOC_SIGN_IN,
    DOC_UNKNOWN,
    TrainingRecordParseOutput,
)
from app.modules.safety.models import TrainingAttendee
from app.modules.safety.service.training_behavior import record_parsing


def _output(**kw) -> TrainingRecordParseOutput:
    base = dict(
        doc_type=DOC_SIGN_IN, attendance_count=3, names=["张三", "李四"],
        passed_count=None, scores=[], confidence="high",
        unrecognized=[], notes="",
    )
    base.update(kw)
    return TrainingRecordParseOutput(**base)


def _fields(**kw) -> dict:
    held_ms = int(datetime(2026, 10, 23, 16, 0, tzinfo=UTC).timestamp() * 1000)
    base = {
        "培训名称": "动火作业安全培训",
        "应到人数": "20",
        "考核方式": "考试",
        "培训类别": "专项培训",
        "培训形式": "线下",
        "实施日期": held_ms,  # 北京 2026-10-24 00:00
        "培训学时": "4",
        "组织部门": ["安全工程中心", "提炼一部"],
    }
    base.update(kw)
    return base


# ── build_attendee_rows（纯函数）───────────────────────────────────


def test_unknown_doc_type_returns_empty() -> None:
    assert record_parsing.build_attendee_rows(
        "recX", _fields(), _output(doc_type=DOC_UNKNOWN, names=[], scores=[])
    ) == []


def test_names_dedupe_and_unrecognized_flagged() -> None:
    rows = record_parsing.build_attendee_rows(
        "recX", _fields(),
        _output(names=["张三", "张三", "李四"], unrecognized=["王五", "赵六"]),
    )
    # 名单去重保序；unrecognized 且不在 names → 单独成行（原样转录灰显）
    assert [r.person_name for r in rows] == ["张三", "李四", "王五", "赵六"]
    assert [r.unrecognized for r in rows] == [False, False, True, True]


def test_name_also_in_unrecognized_keeps_name_row_flagged() -> None:
    rows = record_parsing.build_attendee_rows(
        "recX", _fields(), _output(names=["张三"], unrecognized=["张三"])
    )
    assert len(rows) == 1
    assert rows[0].unrecognized is True


def test_scores_matched_invalid_dropped() -> None:
    rows = record_parsing.build_attendee_rows(
        "recX", _fields(),
        _output(
            names=["张三", "李四"],
            scores=[
                {"name": "张三", "score": "92"},
                {"name": "李四", "score": "缺考"},  # 非法分数丢弃不推算
                {"name": "", "score": "88"},        # 无名明细丢弃
            ],
        ),
    )
    by_name = {r.person_name: r for r in rows}
    assert by_name["张三"].score == 92.0
    assert by_name["李四"].score is None


def test_snapshot_fields_mapped() -> None:
    rows = record_parsing.build_attendee_rows("recX", _fields(), _output())
    r = rows[0]
    assert r.training_record_id == "recX"
    assert r.training_name == "动火作业安全培训"
    assert r.category == "专项培训"
    assert r.form == "线下"
    assert r.held_at == datetime(2026, 10, 23, 16, 0, tzinfo=UTC)
    assert r.hours == 4.0
    assert r.assessment == "考试"
    assert r.training_department == "安全工程中心、提炼一部"
    assert r.confidence == "high"
    assert r.source == "ai_parse"


def test_snapshot_missing_values_are_none() -> None:
    rows = record_parsing.build_attendee_rows(
        "recX", {"培训名称": "x"}, _output(names=["张三"])
    )
    r = rows[0]
    assert r.category is None and r.form is None and r.held_at is None
    assert r.hours is None and r.training_department is None


# ── persist_attendees（db_session，事务内回滚不落库）───────────────


async def test_persist_then_replace_is_idempotent(db_session) -> None:
    first = record_parsing.build_attendee_rows(
        "recP", _fields(), _output(names=["张三", "李四"])
    )
    await record_parsing.persist_attendees(db_session, "recP", first)
    await db_session.flush()
    live = (await db_session.execute(
        select(TrainingAttendee).where(
            TrainingAttendee.training_record_id == "recP",
            TrainingAttendee.is_deleted == False,  # noqa: E712
        )
    )).scalars().all()
    assert sorted(r.person_name for r in live) == ["张三", "李四"]

    # 重跑解析名单变化：旧行软删、新行顶上（部分唯一索引外不冲突）
    second = record_parsing.build_attendee_rows(
        "recP", _fields(), _output(names=["张三", "王五"])
    )
    await record_parsing.persist_attendees(db_session, "recP", second)
    await db_session.flush()
    live = (await db_session.execute(
        select(TrainingAttendee).where(
            TrainingAttendee.training_record_id == "recP",
            TrainingAttendee.is_deleted == False,  # noqa: E712
        )
    )).scalars().all()
    assert sorted(r.person_name for r in live) == ["张三", "王五"]
    dead = (await db_session.execute(
        select(TrainingAttendee).where(
            TrainingAttendee.training_record_id == "recP",
            TrainingAttendee.is_deleted == True,  # noqa: E712
        )
    )).scalars().all()
    assert len(dead) == 2
