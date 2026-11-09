"""P1-3 T1 —— 例外复核：判据/捞取/rescued 判定/报告 schema（纯函数 + fake ledger）。

覆盖 ticket 01 验收：
- classify_exception：既有失败分类全集 → 例外标签；未知兜底；人工指定单独标签；
- pick_exceptions：死信捞取 + 人工指定合并去重 + 上限截断；ledger 异常 fail-open；
- judge_rescued：非空非占位 且 引用可验证 → True；占位/空/引用不可验证 → False；
- ExceptionReviewReport schema：必填/枚举校验、JSON 往返（Redis hash 存取口径）；
- summarize_exception_metrics：例外率/rescued 率纯函数（零分母安全）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
    EvidenceEntry,
)
from app.modules.safety.service.hazard_direct import failure_ledger
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    ExceptionItem,
    ExceptionReviewReport,
    classify_exception,
    judge_rescued,
    pick_exceptions,
    summarize_exception_metrics,
)


class FakeRedis:
    """最小 RedisLike 假件（对齐 test_hazard_failure_ledger 模式）。"""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def get(self, key: str) -> Any:
        self._check()
        return self.store.get(key)

    async def set(
        self, key: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> Any:
        self._check()
        self.store[key] = value
        return True

    async def incr(self, key: str) -> int:
        self._check()
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> Any:
        self._check()
        return True

    async def hset(self, key: str, field: str, value: str) -> Any:
        self._check()
        self.store.setdefault(key, {})[field] = value
        return 1

    async def hgetall(self, key: str) -> dict[str, str]:
        self._check()
        bucket = self.store.get(key)
        return dict(bucket) if isinstance(bucket, dict) else {}

    async def hget(self, key: str, field: str) -> Any:
        self._check()
        bucket = self.store.get(key)
        if not isinstance(bucket, dict):
            return None
        return bucket.get(field)

    async def hdel(self, key: str, field: str) -> Any:
        self._check()
        bucket = self.store.get(key)
        if isinstance(bucket, dict):
            bucket.pop(field, None)
        return 1

    async def delete(self, key: str) -> Any:
        self._check()
        self.store.pop(key, None)
        return 1


def _seed_dead_letter(
    redis: FakeRedis,
    record_id: str,
    *,
    category: str = "json_invalid",
    attempts: int = 5,
    reason: str = "视觉输出持续非法",
    dead_at: float = 1000.0,
) -> None:
    payload = {
        "record_id": record_id,
        "attempts": attempts,
        "last_round": 42,
        "next_round": None,
        "category": category,
        "last_reason": reason,
        "dead": True,
        "dead_at": dead_at,
    }
    redis.store.setdefault(failure_ledger.DEAD_LETTERS_KEY, {})[record_id] = json.dumps(
        payload, ensure_ascii=False
    )


# ── classify_exception ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("retrieval_degraded", "rag_degraded"),
        ("no_chunks", "no_chunks"),
        ("empty_basis", "basis_missing"),
        ("placeholder_basis", "basis_missing"),
        ("no_citation", "citation_unverified"),
        ("invalid_citation", "citation_unverified"),
        ("json_invalid", "json_invalid"),
        ("validation_failed", "validation_failed"),
        ("writeback_error", "writeback_error"),
        ("api_error", "other"),
        ("从未见过的分类", "other"),
        (None, "other"),
    ],
)
def test_classify_exception_maps_failure_categories(
    category: str | None, expected: str
) -> None:
    assert classify_exception(category) == expected


def test_classify_exception_manual_pick() -> None:
    """人工指定（无失败状态）单独标签，不复用失败分类。"""
    assert classify_exception(None, manual=True) == "manual_pick"
    assert classify_exception("json_invalid", manual=True) == "manual_pick"


# ── pick_exceptions ─────────────────────────────────────────────────────────


async def test_pick_exceptions_dead_letters_and_manual_merge() -> None:
    redis = FakeRedis()
    _seed_dead_letter(redis, "recD1", category="json_invalid", dead_at=2000.0)
    _seed_dead_letter(redis, "recD2", category="invalid_citation", dead_at=1000.0)

    items = await pick_exceptions(redis=redis)

    # 死信按 dead_at 倒序；标签由分类映射
    assert [item.record_id for item in items] == ["recD1", "recD2"]
    assert items[0].source == "dead_letter"
    assert items[0].label == "json_invalid"
    assert items[0].attempts == 5
    assert items[0].category == "json_invalid"
    assert items[1].label == "citation_unverified"


async def test_pick_exceptions_manual_ids_first_and_dedupe() -> None:
    redis = FakeRedis()
    _seed_dead_letter(redis, "recDead", dead_at=1000.0)
    _seed_dead_letter(redis, "recOther", dead_at=900.0)

    items = await pick_exceptions(
        manual_record_ids=["recManual", "recDead"], redis=redis
    )

    # 人工指定优先；与死信重合的 record_id 去重（死信上下文保留，只出一条）
    assert [item.record_id for item in items] == ["recManual", "recDead", "recOther"]
    manual = items[0]
    assert manual.source == "manual"
    assert manual.label == "manual_pick"
    assert manual.category is None
    deduped = [i for i in items if i.record_id == "recDead"]
    assert len(deduped) == 1
    assert deduped[0].source == "dead_letter"


async def test_pick_exceptions_limit_truncates() -> None:
    redis = FakeRedis()
    for i in range(5):
        _seed_dead_letter(redis, f"rec{i}", dead_at=float(i))

    items = await pick_exceptions(
        manual_record_ids=["recManual"], limit=3, redis=redis
    )
    # 人工指定占额度；上限截断（死信保留最近）
    assert [item.record_id for item in items] == ["recManual", "rec4", "rec3"]


async def test_pick_exceptions_ledger_failure_fail_open() -> None:
    redis = FakeRedis()
    redis.fail = True

    items = await pick_exceptions(manual_record_ids=["recM"], redis=redis)

    assert [item.record_id for item in items] == ["recM"]


def test_exception_item_is_frozen_dataclass() -> None:
    item = ExceptionItem(
        record_id="r",
        source="manual",
        category=None,
        reason="",
        attempts=0,
        label="manual_pick",
    )
    with pytest.raises(Exception):  # frozen：不可变
        item.record_id = "other"  # type: ignore[misc]


# ── judge_rescued ───────────────────────────────────────────────────────────


def _evidence() -> CitationEvidence:
    return CitationEvidence(
        entries=(
            EvidenceEntry(
                doc_name="消防法",
                source_article="第10条",
                chunk_text="应设置防护栏杆。",
            ),
        )
    )


def test_judge_rescued_true_on_verified_citation() -> None:
    basis = "《消防法》第10条：'应设置防护栏杆'"
    assert judge_rescued(basis, evidence=_evidence()) is True


def test_judge_rescued_false_on_placeholder() -> None:
    basis = "知识库中无相应条文，无法给出判定依据"
    assert judge_rescued(basis, evidence=_evidence()) is False


def test_judge_rescued_false_on_empty() -> None:
    assert judge_rescued("", evidence=_evidence()) is False
    assert judge_rescued("   ", evidence=_evidence()) is False


def test_judge_rescued_false_on_unverifiable_citation() -> None:
    basis = "《不存在的法规》第99条：'编造的原文'"
    assert judge_rescued(basis, evidence=_evidence()) is False


def test_judge_rescued_false_on_empty_evidence() -> None:
    assert judge_rescued("《消防法》第10条：'应设置防护栏杆'", evidence=None) is False
    assert (
        judge_rescued("《消防法》第10条：'应设置防护栏杆'", evidence=CitationEvidence())
        is False
    )


# ── ExceptionReviewReport schema ────────────────────────────────────────────


def _report(**overrides: Any) -> ExceptionReviewReport:
    payload: dict[str, Any] = {
        "record_id": "recD1",
        "exception_label": "json_invalid",
        "failure_category": "json_invalid",
        "failure_reason": "视觉输出持续非法",
        "review_source": "dead_letter",
        "evidence": [
            {
                "doc_name": "消防法",
                "source_article": "第10条",
                "quote": "应设置防护栏杆",
                "chunk_id": "c1",
            }
        ],
        "ai_conclusion": {
            "classification": "unsafe_condition",
            "hazard_level": "general",
            "major_hazard_basis": "《消防法》第10条：'应设置防护栏杆'",
            "rectification_suggestion": "补装防护栏杆",
        },
        "manual_conclusion": {
            "classification": "unsafe_condition",
            "hazard_level": "general",
            "major_hazard_basis": "",
        },
        "diff": [
            {"field": "hazard_level", "ai_value": "general", "manual_value": "general", "agree": True}
        ],
        "proposed_action": "adopt_ai",
        "rescued": True,
        "observed_at": "2026-11-09T02:00:00+00:00",
    }
    payload.update(overrides)
    return ExceptionReviewReport.model_validate(payload)


def test_report_schema_valid_payload() -> None:
    report = _report()
    assert report.record_id == "recD1"
    assert report.rescued is True
    assert report.diff[0].agree is True


def test_report_schema_rejects_missing_required() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExceptionReviewReport.model_validate(
            {"record_id": "recD1", "exception_label": "json_invalid"}
        )


def test_report_schema_rejects_bad_enum() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _report(review_source="nonsense")
    with pytest.raises(ValidationError):
        _report(proposed_action="直接写回")


def test_report_schema_json_roundtrip() -> None:
    report = _report()
    revived = ExceptionReviewReport.model_validate_json(report.model_dump_json())
    assert revived == report


def test_report_schema_label_matches_classification() -> None:
    """exception_label 必须是判据函数产出集合内的值（枚举语义）。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _report(exception_label="不存在的标签")


# ── summarize_exception_metrics ─────────────────────────────────────────────


def test_summarize_exception_metrics_rates() -> None:
    metrics = summarize_exception_metrics(
        exception_count=8, analyzed_count=100, reviewed_count=10, rescued_count=7
    )
    assert metrics["exception_rate"] == pytest.approx(0.08)
    assert metrics["reviewed"] == 10
    assert metrics["rescued"] == 7
    assert metrics["rescued_rate"] == pytest.approx(0.7)


def test_summarize_exception_metrics_zero_denominators() -> None:
    metrics = summarize_exception_metrics(
        exception_count=0, analyzed_count=0, reviewed_count=0, rescued_count=0
    )
    assert metrics["exception_rate"] == 0.0
    assert metrics["rescued_rate"] == 0.0
