"""special_op_direct.daily 单测（Ticket 04 验收：直读编排主接缝）。

覆盖：渲染与镜像链路逐字相同（today / afternoon）、推送标题与目标群、
      替身注入（假读取器 + 假推送器 + 假 AI）、拉取抛错不推送、
      推送失败向上抛、不写日报日期字段、AI 增强与失败回退。

内部跑真实的字段映射、风险判定与 Markdown 渲染，只有 I/O 被替换。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.safety.feishu.bitable_client import BitableQueryError
from app.modules.safety.schemas.special_op_daily import AIDailyAnalysisResult
from app.modules.safety.service.special_op_contract import SpecialOpRecord
from app.modules.safety.service.special_op_direct import bitable_repo, daily
from app.modules.safety.service.special_op_direct.tests.factories import (
    DAY,
    HIGH_FIELDS,
    LOW_FIELDS,
    MEDIUM_FIELDS,
    FakeAnalyst,
    FakePusher,
    FakeReader,
    orm_from_view,
    record,
)
from app.modules.safety.service.special_operation_daily_report import (
    DAILY_REPORT_CHAT_ID,
    ReportBuilder,
    RiskAssessmentEngine,
)

ITEMS: list[dict[str, Any]] = [
    record("rec-high", **HIGH_FIELDS),
    record("rec-medium", **MEDIUM_FIELDS),
    record("rec-low", **LOW_FIELDS),
]


def _mirror_objects(
    items: list[dict[str, Any]],
) -> tuple[list[bitable_repo.SpecialOpView], list[Any]]:
    """同一份数据在镜像路径下的视图对象与 ORM 对象。"""
    views = [bitable_repo.assess_view(bitable_repo.to_view(i)) for i in items]
    orms = [orm_from_view(v, i) for v, i in zip(views, items, strict=True)]
    return views, orms


# 主路径


async def test_run_renders_pushes_and_returns_stats() -> None:
    reader = FakeReader(records=ITEMS)
    pusher = FakePusher()

    result = await daily.run(
        DAY, "today", reader=reader, pusher=pusher, analyst=FakeAnalyst(), writeback=False,
    )

    assert len(reader.calls) == 1
    assert (result.total, result.excluded) == (3, 0)
    assert (result.high_risk, result.medium_risk, result.low_risk) == (1, 1, 1)
    assert "重点关注（高风险 1 项）" in result.markdown_report
    assert "高风险: 1 项" in result.markdown_report

    assert len(pusher.calls) == 1
    call = pusher.calls[0]
    assert call["chat_id"] == DAILY_REPORT_CHAT_ID
    assert call["title"] == "特殊作业日报 - 2026-09-11"
    assert call["content"] == result.markdown_report
    assert result.push_results == [{
        "chat_id": DAILY_REPORT_CHAT_ID, "success": True, "message_id": "om_test",
    }]
    assert len(result.logs_analyzed) == 3


@pytest.mark.parametrize("mode", ["today", "afternoon"])
async def test_run_markdown_identical_to_mirror_path(mode: str) -> None:
    reader = FakeReader(records=ITEMS)

    result = await daily.run(
        DAY, mode, push=False, reader=reader, analyst=FakeAnalyst(), writeback=False,
    )

    views, orms = _mirror_objects(ITEMS)
    stats = {
        "total": 3, "effective_total": 3,
        "high": 1, "medium": 1, "low": 1, "excluded": 0,
    }
    assert result.markdown_report == ReportBuilder.build(DAY, mode, orms, stats)
    assert result.markdown_report == ReportBuilder.build(DAY, mode, views, stats)


async def test_run_honours_target_chats_and_push_flag() -> None:
    pusher = FakePusher()
    result = await daily.run(
        DAY, "afternoon", target_chats=["oc_a", "oc_b"],
        reader=FakeReader(records=ITEMS), pusher=pusher, analyst=FakeAnalyst(), writeback=False,
    )
    assert [c["chat_id"] for c in pusher.calls] == ["oc_a", "oc_b"]
    assert all(r["success"] for r in result.push_results)
    assert result.mode == "afternoon"

    silent_pusher = FakePusher()
    result2 = await daily.run(
        DAY, "afternoon", push=False,
        reader=FakeReader(records=ITEMS), pusher=silent_pusher, analyst=FakeAnalyst(), writeback=False,
    )
    assert silent_pusher.calls == []
    assert result2.push_results == []


async def test_run_raises_when_fetch_fails_and_does_not_push() -> None:
    pusher = FakePusher()
    reader = FakeReader(error=BitableQueryError(1254001, "boom"))

    with pytest.raises(BitableQueryError):
        await daily.run(DAY, "today", reader=reader, pusher=pusher, analyst=FakeAnalyst())

    assert pusher.calls == []


async def test_run_raises_when_push_fails() -> None:
    with pytest.raises(RuntimeError, match="日报推送失败"):
        await daily.run(
            DAY, "today", reader=FakeReader(records=ITEMS),
            pusher=FakePusher(message_id=None), analyst=FakeAnalyst(), writeback=False,
        )


# 决策边界


async def test_run_does_not_stamp_daily_report_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[bitable_repo.SpecialOpView]] = []
    real_fetch = bitable_repo.fetch_day_views

    async def spy_fetch(
        target_date: date, *, client: bitable_repo.BitableRecordsReader | None = None,
    ) -> list[bitable_repo.SpecialOpView]:
        views = await real_fetch(target_date, client=client)
        captured.append(views)
        return views

    monkeypatch.setattr(daily, "fetch_day_views", spy_fetch)

    await daily.run(
        DAY, "today", push=False,
        reader=FakeReader(records=ITEMS), analyst=FakeAnalyst(), writeback=False,
    )

    assert captured and all(v.daily_report_date is None for v in captured[0])


async def test_excluded_records_counted_but_not_rendered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_assess = RiskAssessmentEngine.assess

    def fake_assess(
        cls: type[RiskAssessmentEngine], report: SpecialOpRecord,
    ) -> Any:
        result = real_assess(report)
        if (report.work_description or "").startswith("排除"):
            result.is_excluded = True
            result.exclusion_reason = "测试排除"
        return result

    monkeypatch.setattr(RiskAssessmentEngine, "assess", classmethod(fake_assess))
    excluded_fields = dict(LOW_FIELDS)
    excluded_fields["作业内容"] = "排除：非特殊作业"

    result = await daily.run(
        DAY, "today", push=False,
        reader=FakeReader(records=[record("rec-ok", **LOW_FIELDS),
                                   record("rec-ex", **excluded_fields)]),
        analyst=FakeAnalyst(),
    )

    assert (result.total, result.excluded, result.low_risk) == (2, 1, 1)
    assert "排除: 1 条" in result.markdown_report
    assert "排除：非特殊作业" not in result.markdown_report


async def test_run_uses_ai_result_and_falls_back_on_failure() -> None:
    ai = AIDailyAnalysisResult(
        summary="高风险作业集中在生产部动火作业", enhanced_tips=["加强动火监护"],
    )
    analyst = FakeAnalyst(result=ai)

    result = await daily.run(
        DAY, "today", push=False, reader=FakeReader(records=ITEMS), analyst=analyst, writeback=False
    )

    assert analyst.calls == 1
    assert "高风险作业集中在生产部动火作业" in result.markdown_report
    assert "加强动火监护" in result.markdown_report

    failing = FakeAnalyst(error=RuntimeError("ai down"))
    result2 = await daily.run(
        DAY, "today", push=False, reader=FakeReader(records=ITEMS), analyst=failing, writeback=False
    )

    assert failing.calls == 1
    assert "加强动火监护" not in result2.markdown_report
    assert "重点关注（高风险 1 项）" in result2.markdown_report
    assert result2.high_risk == 1


def test_zone_summary_order_is_deterministic() -> None:
    """「中风险作业集中在 」排序规则：条数降序 -> 同条数按名称升序（与输入顺序无关）。"""
    def view(record_id: str, dept: str) -> Any:
        fields = dict(MEDIUM_FIELDS)
        fields["申请部门"] = dept
        return bitable_repo.assess_view(bitable_repo.to_view(record(record_id, **fields)))

    power = view("rec-1", "动力部")
    power2 = view("rec-2", "动力部")
    equip = view("rec-3", "设备工程部")
    stats = {
        "total": 3, "effective_total": 3,
        "high": 0, "medium": 3, "low": 0, "excluded": 0,
    }

    md_a = ReportBuilder.build(DAY, "afternoon", [power, power2, equip], stats)
    md_b = ReportBuilder.build(DAY, "afternoon", [equip, power2, power], stats)

    assert md_a == md_b                      # 输入顺序不影响输出
    assert md_a.index("动力部") < md_a.index("设备工程部")   # 条数多的在前
