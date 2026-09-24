"""撤回票排除单测（2026-09-22 口径决策：日报只统计有效票）。

覆盖：申请状态映射与撤回标记、日报统计含撤回票但渲染排除、
      存量「日报风险等级（AI）」列不能让撤回票复活、回写跳过撤回票。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.special_op_direct import (
    bitable_repo,
    contract,
    daily,
    query,
)
from app.modules.safety.service.special_op_direct.tests.factories import (
    DAY,
    HIGH_FIELDS,
    LOW_FIELDS,
    MEDIUM_FIELDS,
    FakeAnalyst,
    FakeReader,
    record,
)


def _views(items: list[dict[str, Any]]) -> list[bitable_repo.SpecialOpView]:
    return [bitable_repo.assess_view(bitable_repo.to_view(i)) for i in items]


# 映射与标记


def test_to_view_maps_application_status() -> None:
    view = bitable_repo.to_view(record("rec-wd", **LOW_FIELDS, 申请状态="已撤回"))
    assert view.application_status == "已撤回"

    view_ok = bitable_repo.to_view(record("rec-ok", **LOW_FIELDS, 申请状态="审批中"))
    assert view_ok.application_status == "审批中"

    view_missing = bitable_repo.to_view(record("rec-no", **LOW_FIELDS))
    assert view_missing.application_status is None


def test_mark_withdrawn_excludes_and_is_idempotent() -> None:
    (view,) = _views([record("rec-wd", **LOW_FIELDS, 申请状态="已撤回")])
    assert view.is_excluded is True
    assert view.exclusion_reason == bitable_repo.WITHDRAWN_EXCLUSION_REASON

    bitable_repo.mark_withdrawn(view)
    assert view.exclusion_reason == bitable_repo.WITHDRAWN_EXCLUSION_REASON

    (view_ok,) = _views([record("rec-ok", **LOW_FIELDS, 申请状态="已通过")])
    assert view_ok.is_excluded is False
    assert view_ok.exclusion_reason is None


# 日报主路径


async def test_withdrawn_records_counted_but_excluded_from_report() -> None:
    withdrawn_fields = dict(LOW_FIELDS, 申请状态="已撤回", 作业内容="撤回旧票不应出现")
    items = [
        record("rec-high", **HIGH_FIELDS),
        record("rec-medium", **MEDIUM_FIELDS),
        record("rec-wd", **withdrawn_fields),
    ]

    result = await daily.run(
        DAY, "today", push=False, reader=FakeReader(records=items),
        analyst=FakeAnalyst(), writeback=False,
    )

    assert (result.total, result.excluded, result.low_risk) == (3, 1, 0)
    assert result.logs_analyzed and len(result.logs_analyzed) == 2
    assert "撤回旧票不应出现" not in result.markdown_report
    assert "排除: 1 条" in result.markdown_report


# 查询路径（存量列兜底）


def test_query_view_stored_risk_column_does_not_revive_withdrawn() -> None:
    withdrawn_with_column = record(
        "rec-wd", **LOW_FIELDS, 申请状态="已撤回",
        **{contract.RISK_FIELD_NAME: "低风险"},
    )

    view = query.to_query_view(withdrawn_with_column)

    assert view.daily_risk_level == "low"  # 存量列仍被读取
    assert view.is_excluded is True
    assert view.exclusion_reason == bitable_repo.WITHDRAWN_EXCLUSION_REASON


def test_query_view_stored_risk_column_keeps_effective_record() -> None:
    effective_with_column = record(
        "rec-ok", **LOW_FIELDS, 申请状态="审批中",
        **{contract.RISK_FIELD_NAME: "低风险"},
    )

    view = query.to_query_view(effective_with_column)

    assert view.is_excluded is False


# 回写


class FakeWriter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def update_record(
        self, record_id: str, fields: dict[str, Any], table_id: str | None = None,
    ) -> bool:
        self.calls.append({"record_id": record_id, "fields": fields})
        return True


class FakeSleep:
    async def __call__(self, seconds: float) -> None:
        return None


async def test_writeback_skips_withdrawn() -> None:
    views = _views([
        record("rec-ok", **LOW_FIELDS),
        record("rec-wd", **MEDIUM_FIELDS, 申请状态="已撤回"),
    ])
    writer = FakeWriter()

    result = await bitable_repo.writeback_risk_levels(
        views, writer=writer, sleep=FakeSleep()
    )

    assert [c["record_id"] for c in writer.calls] == ["rec-ok"]
    assert result.skipped == 1
