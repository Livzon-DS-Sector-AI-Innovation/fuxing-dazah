"""special_op_direct.bitable_repo 单测（Ticket 03 验收）。

覆盖：正常记录 / 缺发起时间 / 被排除 / 各风险等级 / 接口报错 /
      映射与既有镜像映射一致 / 视图对象与同一份数据的 ORM 对象判定一致。

不依赖真实 Bitable、真实 DB、真实大模型：拉取接缝用替身，
字段映射、风险判定、Markdown 渲染全部用真货。共用夹具见 tests/factories.py。
"""

from __future__ import annotations

import uuid
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.bitable_client import BitableQueryError
from app.modules.safety.schemas.special_op_daily import RiskAssessmentResult
from app.modules.safety.service.special_op_direct import bitable_repo
from app.modules.safety.service.special_op_direct.tests.factories import (
    CREATED_MS,
    DAY,
    FALLBACK_FIELDS,
    HIGH_FIELDS,
    LOW_FIELDS,
    MEDIUM_FIELDS,
    FakeReader,
    orm_from_view,
    record,
)
from app.modules.safety.service.special_operation_daily_report import (
    ReportBuilder,
    RiskAssessmentEngine,
    SpecialOperationDailyReportService,
)

# 映射一致性


def test_to_view_matches_mirror_mapping() -> None:
    item = record()
    view = bitable_repo.to_view(item)
    mirror = SpecialOperationDailyReportService.map_bitable_fields(item["fields"])

    assert set(mirror) <= {f.name for f in dataclass_fields(view)}
    for key, expected in mirror.items():
        if isinstance(expected, datetime):
            expected = bitable_repo.to_utc(expected)
        if key == "feishu_record_id":
            expected = item["record_id"]
        assert getattr(view, key) == expected, key


def test_view_identity_and_created_at_fallback() -> None:
    item = record("recABC")
    view = bitable_repo.to_view(item)

    assert view.record_id == "recABC"
    assert view.feishu_record_id == "recABC"
    assert view.source == "bitable"
    assert isinstance(view.id, uuid.UUID)
    assert view.created_at == datetime.fromtimestamp(CREATED_MS / 1000.0, tz=UTC)
    assert view.created_at_known is True


def test_missing_submitted_at_falls_back_to_system_created_time() -> None:
    item = record(created_time=CREATED_MS)
    item["fields"].pop("发起时间")

    view = bitable_repo.to_view(item)

    assert view.submitted_at is None
    assert view.created_at == datetime.fromtimestamp(CREATED_MS / 1000.0, tz=UTC)
    assert view.created_at_known is True


def test_missing_both_times_is_flagged_and_not_counted_as_new() -> None:
    item = record(created_time=None)
    item["fields"].pop("发起时间")

    view = bitable_repo.assess_view(bitable_repo.to_view(item))
    markdown = ReportBuilder.build(DAY, "afternoon", [view], {"total": 1})

    assert view.created_at == bitable_repo.UNKNOWN_CREATED_AT
    assert view.created_at_known is False
    assert "今日新增计划外作业: 0 项" in markdown


# 批量取数


async def test_fetch_day_views_uses_single_batch_query_for_bjt_day() -> None:
    reader = FakeReader(records=[record("rec001"), record("rec002")])

    views = await bitable_repo.fetch_day_views(DAY, client=reader)

    assert len(reader.calls) == 1
    call = reader.calls[0]
    assert call["strict"] is True
    assert call["automatic_fields"] is True
    conditions = call["filter_info"]["conditions"]
    assert [c["field_name"] for c in conditions] == [bitable_repo.F_START_TIME] * 2
    assert [c["operator"] for c in conditions] == ["isGreater", "isLess"]
    start, end = bitable_repo.day_window(DAY)
    assert [c["value"] for c in conditions] == [
        ["ExactDate", str(int(start.timestamp() * 1000))],
        ["ExactDate", str(int(end.timestamp() * 1000))],
    ]
    assert len(views) == 2
    assert all(v.daily_risk_level for v in views)


async def test_fetch_day_views_raises_on_api_error() -> None:
    reader = FakeReader(error=BitableQueryError(1254001, "table not found"))

    with pytest.raises(BitableQueryError):
        await bitable_repo.fetch_day_views(DAY, client=reader)


async def test_fetch_day_views_raises_when_connection_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "get_connection", lambda *a, **kw: None)

    with pytest.raises(bitable_repo.SpecialOpDirectError):
        await bitable_repo.fetch_day_views(DAY)


# 判定与 ORM 等价


@pytest.mark.parametrize(
    ("fields", "expected_level"),
    [
        (HIGH_FIELDS, "high"),
        (MEDIUM_FIELDS, "medium"),
        (LOW_FIELDS, "low"),
        (FALLBACK_FIELDS, "low"),
    ],
)
def test_assessment_matches_orm_and_expected_level(
    fields: dict[str, Any], expected_level: str,
) -> None:
    item = record(**fields)
    view = bitable_repo.assess_view(bitable_repo.to_view(item))
    result = RiskAssessmentEngine.assess(orm_from_view(view, item))

    assert view.daily_risk_level == result.risk_level == expected_level
    assert view.daily_risk_reason == (
        "; ".join(result.matched_rules) if result.matched_rules else None
    )
    assert view.inferred_operation_types == (result.inferred_types or None)
    assert view.is_excluded is result.is_excluded
    assert view.exclusion_reason == result.exclusion_reason


def test_engine_exclusion_flag_is_carried_onto_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_assess(
        cls: type[RiskAssessmentEngine], report: bitable_repo.SpecialOpView,
    ) -> RiskAssessmentResult:
        return RiskAssessmentResult(
            risk_level="low",
            matched_rules=["测试排除"],
            is_excluded=True,
            exclusion_reason="非特殊作业",
        )

    monkeypatch.setattr(RiskAssessmentEngine, "assess", classmethod(fake_assess))

    view = bitable_repo.assess_view(bitable_repo.to_view(record()))

    assert view.is_excluded is True
    assert view.exclusion_reason == "非特殊作业"
    assert view.daily_risk_level == "low"
    assert view.daily_risk_reason == "测试排除"


def test_fire_work_method_reads_real_column() -> None:
    """动火方式：读生产表真实列名「动火作业方式」（多选），旧列名不存在。"""
    item = record("rec-fire", **HIGH_FIELDS)          # 动火作业 + 罐区
    item["fields"]["动火作业方式"] = ["电焊/气割（焊）/等离子切割机"]
    view = bitable_repo.assess_view(bitable_repo.to_view(item))

    assert view.fire_work_method == "电焊/气割（焊）/等离子切割机"
    # V3.5 高风险规则 7：高风险动火方式 + 受限空间/罐区环境
    assert "高风险动火方式+受限空间/罐区环境" in (view.daily_risk_reason or "")


def test_fire_work_method_joins_multi_select_and_defaults_none() -> None:
    item = record("rec-fire", **HIGH_FIELDS)
    item["fields"]["动火作业方式"] = ["氩弧焊", "切割机/角磨机"]
    view = bitable_repo.to_view(item)
    assert view.fire_work_method == "氩弧焊、切割机/角磨机"

    plain = bitable_repo.to_view(record("rec-plain", **HIGH_FIELDS))
    assert plain.fire_work_method is None  # 空值仍是 None（不写空串进镜像列）


def test_report_markdown_identical_for_view_and_orm() -> None:
    items = [record("rec001", **HIGH_FIELDS), record("rec002", **LOW_FIELDS)]
    views = [bitable_repo.assess_view(bitable_repo.to_view(i)) for i in items]
    orms = [orm_from_view(v, i) for v, i in zip(views, items, strict=True)]
    stats = {
        "total": 2, "effective_total": 2,
        "high": 1, "medium": 0, "low": 1, "excluded": 0,
    }

    for mode in ("today", "afternoon"):
        assert ReportBuilder.build(DAY, mode, views, stats) == ReportBuilder.build(
            DAY, mode, orms, stats
        )
