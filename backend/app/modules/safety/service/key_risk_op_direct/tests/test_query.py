"""直读内存查询/统计单测（Ticket 03）——两套过滤语义各自口径。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.service.key_risk_op_direct.query import (
    compute_stats,
    find_by_record_id,
    list_reports,
    query_ops_for_agent,
)
from app.modules.safety.service.key_risk_operation_report import (
    _day_bounds_utc,
    _month_bounds_utc,
)


def _bj_date_of(dt: datetime) -> date:
    return (dt + timedelta(hours=8)).date()


def _view(vid: str, *, dept: str | None = "提炼六部", area: str | None = "一号车间",
          content: str | None = "乙醇检修", status: str | None = "已通过",
          report_no: str | None = None, start: datetime | None = None) -> Any:
    from app.modules.safety.service.key_risk_op_direct.views import KeyRiskOpView

    return KeyRiskOpView(
        id=vid, feishu_record_id=vid,
        report_no=report_no or f"NO-{vid}",
        department=dept, area=area, operation_content=content,
        apply_status=status, start_time=start,
    )


START_A = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)   # 北京 9/10 10:00
START_B = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)   # 北京 9/20 14:00


class TestListReportsRepoSemantics:
    def _views(self) -> list[Any]:
        return [
            _view("r1", start=START_A),
            _view("r2", dept="QC", content="取样", area="化验室", start=START_B),
            _view("r3", dept="仓储部", status="审批中", start=None),
        ]

    async def test_exact_filters(self) -> None:
        items, total = await list_reports(self._views(), 0, 10, department="提炼六部")
        assert [v.id for v in items] == ["r1"]  # 精确等值：QC 不匹配
        assert total == 1

    async def test_apply_status(self) -> None:
        items, total = await list_reports(self._views(), 0, 10, apply_status="审批中")
        assert [v.id for v in items] == ["r3"]

    async def test_keyword_four_fields(self) -> None:
        """keyword 覆盖 report_no/作业内容/区域/部门 四字段（大小写不敏感子串）。"""
        items, total = await list_reports(self._views(), 0, 10, keyword="化验室")
        assert [v.id for v in items] == ["r2"]
        items, _ = await list_reports(self._views(), 0, 10, keyword="no-r1")
        assert [v.id for v in items] == ["r1"]

    async def test_date_bounds_and_closed_end(self) -> None:
        """from 端 >= 当日北京零点；to 端 <= 次日北京零点（repo 闭端口径逐字复刻）。"""
        d = _bj_date_of(START_A)
        day_start, next_start = _day_bounds_utc(d)
        # 恰在 to 闭端（次日北京零点整）的行：repo 口径计入
        edge = _view("edge", start=next_start)
        items, total = await list_reports(
            [*self._views(), edge], 0, 10, date_from=d, date_to=d)
        assert total == 2
        assert {v.id for v in items} == {"r1", "edge"}
        assert day_start.tzinfo is not None

    async def test_pagination(self) -> None:
        page1, total = await list_reports(self._views(), 0, 2)
        page2, _ = await list_reports(self._views(), 2, 2)
        assert total == 3
        assert len(page1) == 2 and len(page2) == 1


class TestAgentSemantics:
    def _views(self) -> list[Any]:
        return [
            _view("r1", dept="提炼六部", start=START_A),
            _view("r2", dept="QC", content="取样", area="化验室", start=START_B),
            _view("r3", start=None),
        ]

    async def test_department_fuzzy(self) -> None:
        """Agent 口径 department 模糊子串（与 API 精确等值不同）。"""
        items, total = await query_ops_for_agent(
            self._views(), department="提炼六")
        # r3 dept 默认也是 提炼六部（start None → NULLS FIRST 排最前）
        assert [v.id for v in items] == ["r3", "r1"]
        assert total == 2

    async def test_keyword_two_fields_only(self) -> None:
        """Agent 口径 keyword 仅 作业内容/区域（report_no 不参与）。"""
        items, _ = await query_ops_for_agent(self._views(), keyword="no-r1")
        assert items == []
        items, _ = await query_ops_for_agent(self._views(), keyword="化验室")
        assert [v.id for v in items] == ["r2"]

    async def test_order_desc_nulls_first_and_pagination_cap(self) -> None:
        """Agent 排序 start_time DESC NULLS FIRST（PG 默认），page_size 封顶 100。"""
        extra = [_view(f"x{i:02d}", start=START_A - timedelta(hours=i)) for i in range(120)]
        items, total = await query_ops_for_agent(
            [*self._views(), *extra], page=1, page_size=200)
        assert total == 123
        assert len(items) == 100  # 封顶
        assert items[0].id == "r3"  # NULLS FIRST
        assert items[1].id == "r2"  # 然后 start_time DESC

    async def test_date_exclusive_end(self) -> None:
        """Agent 端 end 为半开区间（< end_exclusive）；边界为 UTC 午夜
        （复刻 read_tools 裸 date 直传 DB 会话时区的语义，与 API 北京日界不同）。"""
        inside = _view("inside", start=datetime(2026, 9, 10, 2, 0, tzinfo=UTC))
        edge = _view("edge", start=datetime(2026, 9, 11, 0, 0, tzinfo=UTC))
        items, total = await query_ops_for_agent(
            [*self._views(), inside, edge],
            start=date(2026, 9, 10), end_exclusive=date(2026, 9, 11))
        assert total == 2  # r3 start None 被日期过滤排除；r2 在窗外
        assert {v.id for v in items} == {"r1", "inside"}  # edge 恰在端点 → 排除


class TestStatsAndFind:
    async def test_compute_stats_four_kpi(self) -> None:
        today = date.today()
        t0, t1 = _day_bounds_utc(today)
        m0, m1 = _month_bounds_utc(today)
        views = [
            _view("today_ok", start=t0 + timedelta(hours=1)),
            _view("today_pending", status="审批中", start=t0 + timedelta(hours=2)),
            _view("month_ok", start=m0 + timedelta(days=1)),
            _view("old_ok", start=m0 - timedelta(days=1)),
            _view("ok_no_start", start=None),  # start 空不参与今日/本月，计入累计
        ]
        stats = await compute_stats(views, t0, t1, m0, m1)
        assert stats == {
            "today_approved": 1, "in_progress": 1,
            "month_approved": 2, "total": 5,
        }

    async def test_find_by_record_id(self) -> None:
        views = [_view("r1"), _view("r2")]
        assert find_by_record_id(views, "r2").id == "r2"  # type: ignore[union-attr]
        assert find_by_record_id(views, "zz") is None
