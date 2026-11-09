"""P2-1 T1 —— 例外复核写回执行器：schema 扩展 + exception_reviewer 写链 +
``execute_writeback``（P0 闸门 → 白名单 → CAS → 写 AI 六列 → 清死信/回写报告）。

全部 fake（FakeReader/FakeWriter/FakeRedis）；验收钉子：
- 白名单恰 AI 六列（人工列混入立即 ``FieldAuthorityError``、零写入）；
- 占位/引用不可验证 → gate_blocked 零写；CAS 冲突 → cas_conflict 零 PUT；
- 成功 → record_success 清死信 + 报告状态回写 Redis + ai_audit 行；
- 瞬时失败重试一次仍失败 → writeback=failed、死信不清。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.modules.safety.service.hazard_direct import failure_ledger
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    REVIEWS_KEY,
    EvidenceSnippet,
    ExceptionReviewReport,
    ProposedAction,
    ReviewConclusion,
    ReviewSource,
)
from app.modules.safety.service.hazard_direct.exception_writeback import (
    WritebackDeps,
    execute_writeback,
)
from app.modules.safety.service.hazard_direct.field_authority import (
    FieldAuthorityError,
    assert_write_allowed,
    writer_whitelist,
)
from tests.modules.safety.test_hazard_exception_reviewer import FakeRedis


class _NoopAuditFactory:
    """审计写入桩：记录调用、绝不触真实 DB（防测试真写 dev 库）。"""

    def __init__(self) -> None:
        self.commits = 0

    def __call__(self) -> _NoopAuditFactory:
        return self

    async def __aenter__(self) -> _NoopAuditFactory:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def add(self, row: object) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture(autouse=True)
def _stub_audit_session(monkeypatch: pytest.MonkeyPatch) -> _NoopAuditFactory:
    import app.core.database as core_db

    factory = _NoopAuditFactory()
    monkeypatch.setattr(core_db, "async_session_factory", factory)
    return factory


# ── fake 依赖 ───────────────────────────────────────────────────────────────


class FakeReader:
    """记录读取假件：按 record_id 返回 fields；可注入读取异常（CAS fail-open 用）。"""

    def __init__(
        self,
        fields: dict[str, dict[str, Any]] | None = None,
        *,
        raise_on_get: bool = False,
    ) -> None:
        self.fields = fields or {}
        self.raise_on_get = raise_on_get
        self.get_calls: list[str] = []

    async def get_fields(self, record_id: str) -> dict[str, Any] | None:
        self.get_calls.append(record_id)
        if self.raise_on_get:
            raise ConnectionError("bitable read down")
        return self.fields.get(record_id)

    async def defect_images(self, record_id: str) -> list[str]:
        return []


class FakeWriter:
    """Bitable 写假件：update_record 返回 bool；记录全部调用。"""

    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def update_record(
        self, record_id: str, fields: dict[str, Any]
    ) -> bool:
        self.calls.append((record_id, dict(fields)))
        return self.ok


def _report(
    *,
    record_id: str = "recW",
    basis: str = "《消防法》第10条：'应设置防护栏杆'",
    level: str | None = "general",
    classification: str | None = "unsafe_condition",
    suggestion: str | None = "补装防护栏杆",
    rescued: bool = True,
    ai_snapshot: dict[str, Any] | None = None,
) -> ExceptionReviewReport:
    return ExceptionReviewReport(
        record_id=record_id,
        exception_label="basis_missing",
        review_source=ReviewSource.DEAD_LETTER,
        evidence=[
            EvidenceSnippet(
                doc_name="消防法",
                source_article="第10条",
                quote="应设置防护栏杆。",
                chunk_id="chunk-1",
            )
        ],
        ai_conclusion=ReviewConclusion(
            classification=classification,
            hazard_level=level,
            major_hazard_basis=basis,
            rectification_suggestion=suggestion,
        ),
        proposed_action=ProposedAction.ADOPT_AI,
        rescued=rescued,
        observed_at=datetime(2026, 11, 9, 8, 0),
        ai_snapshot=ai_snapshot
        if ai_snapshot is not None
        else {
            "隐患级别（AI）": None,
            "隐患分类（AI）": None,
            "隐患类别（AI）": None,
            "隐患描述（AI）": None,
            "隐患判定依据（AI）": None,
            "整改建议（AI）": None,
        },
    )


def _deps(
    *,
    reader: FakeReader | None = None,
    writer: FakeWriter | None = None,
    redis: FakeRedis | None = None,
) -> WritebackDeps:
    return WritebackDeps(
        reader=reader or FakeReader(),
        writer=writer or FakeWriter(),
        redis=redis or FakeRedis(),
    )


def _seed_dead_letter(redis: FakeRedis, record_id: str) -> None:
    redis.store[failure_ledger.DEAD_LETTERS_KEY] = {
        record_id: f'{{"record_id": "{record_id}", "dead": true}}'
    }


def _load_report(redis: FakeRedis, record_id: str) -> ExceptionReviewReport:
    raw = redis.store.get(REVIEWS_KEY, {}).get(record_id)
    assert raw is not None, "报告未回写 Redis"
    return ExceptionReviewReport.model_validate_json(raw)


# ── schema 扩展 ─────────────────────────────────────────────────────────────


def test_report_new_fields_default_and_backward_compat() -> None:
    report = _report()
    assert report.writeback == "not_attempted"
    assert report.writeback_at is None
    assert report.writeback_note == ""
    assert report.human_feedback == ""
    assert report.human_feedback_at is None
    # 旧 JSON（无新键）可解析——向后兼容
    legacy = report.model_dump_json()
    import json

    payload = json.loads(legacy)
    for key in (
        "ai_snapshot", "writeback", "writeback_at", "writeback_note",
        "human_feedback", "human_feedback_at",
    ):
        payload.pop(key, None)
    restored = ExceptionReviewReport.model_validate(payload)
    assert restored.writeback == "not_attempted"


def test_effective_rescued_human_overrides_program() -> None:
    report = _report(rescued=False)
    report.human_feedback = "useful"
    assert report.effective_rescued is True
    report.human_feedback = "useless"
    assert report.effective_rescued is False
    rescued_true = _report(rescued=True)
    rescued_true.human_feedback = "useless"
    assert rescued_true.effective_rescued is False
    plain = _report(rescued=True)
    assert plain.effective_rescued is True


def test_summary_carries_writeback_and_feedback_keys() -> None:
    report = _report()
    report.human_feedback = "useful"
    row = report.summary()
    assert row["writeback"] == "not_attempted"
    assert row["human_feedback"] == "useful"
    assert row["effective_rescued"] is True


# ── field_authority 写链 ────────────────────────────────────────────────────


def test_exception_reviewer_whitelist_exactly_six_ai_columns() -> None:
    assert writer_whitelist("exception_reviewer") == frozenset(
        {
            "隐患描述（AI）",
            "隐患级别（AI）",
            "隐患分类（AI）",
            "隐患类别（AI）",
            "隐患判定依据（AI）",
            "整改建议（AI）",
        }
    )


def test_exception_reviewer_rejects_human_columns() -> None:
    with pytest.raises(FieldAuthorityError, match="隐患级别"):
        assert_write_allowed(
            "exception_reviewer", {"隐患级别（AI）", "隐患级别"}
        )


# ── execute_writeback 路径 ──────────────────────────────────────────────────


async def test_writeback_success_writes_ai_columns_and_clears_dead_letter() -> None:
    redis = FakeRedis()
    _seed_dead_letter(redis, "recW")
    redis.store[REVIEWS_KEY] = {}
    writer = FakeWriter(ok=True)
    reader = FakeReader(fields={"recW": dict(_report().ai_snapshot)})
    outcome = await execute_writeback(_report(), deps=_deps(reader=reader, writer=writer, redis=redis))
    assert outcome.status == "success"
    # 只写非空结论字段；级别/分类经 EN→CN 反转
    record_id, fields = writer.calls[0]
    assert record_id == "recW"
    assert fields["隐患级别（AI）"] == "一般隐患"
    assert fields["隐患分类（AI）"] == "物的不安全状态"
    assert fields["隐患判定依据（AI）"].startswith("《消防法》")
    assert fields["整改建议（AI）"] == "补装防护栏杆"
    # 人工列/白名单外列绝不在写负载中
    assert not (set(fields) - writer_whitelist("exception_reviewer"))
    # 死信已清
    assert failure_ledger.DEAD_LETTERS_KEY in redis.store
    assert "recW" not in redis.store[failure_ledger.DEAD_LETTERS_KEY]
    # 报告状态已回写
    persisted = _load_report(redis, "recW")
    assert persisted.writeback == "success"
    assert persisted.writeback_at is not None


async def test_writeback_gate_blocked_on_placeholder_basis() -> None:
    writer = FakeWriter()
    outcome = await execute_writeback(
        _report(basis="知识库暂无对应法规条文"), deps=_deps(writer=writer)
    )
    assert outcome.status == "gate_blocked"
    assert writer.calls == []


async def test_writeback_gate_blocked_on_unverifiable_citation() -> None:
    writer = FakeWriter()
    report = _report(basis="《不存在的法》第99条：'编造条文'")
    outcome = await execute_writeback(report, deps=_deps(writer=writer))
    assert outcome.status == "gate_blocked"
    assert writer.calls == []


async def test_writeback_cas_conflict_zero_put() -> None:
    # 写前回读：AI 级别列已被并发修改（快照 None → 现值有值）
    reader = FakeReader(
        fields={"recW": {**(_report().ai_snapshot), "隐患级别（AI）": {"text": "较大隐患"}}}
    )
    writer = FakeWriter()
    outcome = await execute_writeback(
        _report(), deps=_deps(reader=reader, writer=writer)
    )
    assert outcome.status == "cas_conflict"
    assert writer.calls == []


async def test_writeback_cas_read_failure_fail_open_still_writes() -> None:
    reader = FakeReader(raise_on_get=True)
    writer = FakeWriter()
    outcome = await execute_writeback(
        _report(), deps=_deps(reader=reader, writer=writer)
    )
    assert outcome.status == "success"
    assert len(writer.calls) == 1


async def test_writeback_transient_failure_retries_once_then_marks_failed() -> None:
    redis = FakeRedis()
    _seed_dead_letter(redis, "recW")
    writer = FakeWriter(ok=False)
    outcome = await execute_writeback(
        _report(), deps=_deps(writer=writer, redis=redis)
    )
    assert outcome.status == "failed"
    assert len(writer.calls) == 2  # 重试一次
    # 死信不清（回 observe 池）
    assert "recW" in redis.store[failure_ledger.DEAD_LETTERS_KEY]
    persisted = _load_report(redis, "recW")
    assert persisted.writeback == "failed"


async def test_writeback_no_eligible_fields_marks_gate_blocked() -> None:
    # 结论全空（级别/分类/建议 None、依据空）→ 闸门拦截（依据为锚）
    report = _report(basis="", level=None, classification=None, suggestion=None)
    writer = FakeWriter()
    outcome = await execute_writeback(report, deps=_deps(writer=writer))
    assert outcome.status == "gate_blocked"
    assert writer.calls == []
