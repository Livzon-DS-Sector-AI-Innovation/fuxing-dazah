"""中控报警日报私发 — 单测（无 DB / 无飞书依赖）。

覆盖（2026-09-30 需求 + 2026-10-08 表级归属映射）：
- TABLE_DEPT_MAP / dept_for_record / group_records_by_dept：14 张分表全覆盖、
  同车间不同产线分属不同部门、未命中映射（历史脏行）单列
- build_dm_card：蓝头日报卡带部门标识、正文=部门过滤版 markdown
- dm_recipient_names：名单顺序去重
- send_daily_central_alarm_dms：开关关闭跳过；按部门取过滤版 markdown、
  同部门同内容；当日无报警部门不私发（dept_empty）；解析/发送成败统计（stub）
- build_dept_daily_reports（service）：直读替身下按映射分组渲染、
  未命中映射告警、无报警部门缺席
- run_daily_central_alarm_dm：开关关闭返回 None；启用后全流程（mock）
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.safety.service.central_alarm import reader as ca_reader
from app.modules.safety.service.central_alarm.daily_dm import (
    DM_RECIPIENTS,
    TABLE_DEPT_MAP,
    build_dm_card,
    dept_for_record,
    dm_recipient_names,
    group_records_by_dept,
    send_daily_central_alarm_dms,
)
from app.modules.safety.service.central_alarm.reader import CentralAlarmView
from app.modules.safety.service.central_alarm.service import (
    CentralAlarmService,
    run_daily_central_alarm_dm,
)

D = date(2026, 10, 8)


# ═══════════════════════════════════════════════════════════════════════════
# 映射与分组
# ═══════════════════════════════════════════════════════════════════════════


class _Rec:
    """最小记录替身（workshop/line 两字段即够映射用）。"""

    def __init__(self, workshop: str | None, line: str | None) -> None:
        self.workshop = workshop
        self.line = line


class TestDeptMapping:
    def test_map_covers_all_14_tables(self):
        assert len(TABLE_DEPT_MAP) == 14

    def test_dept_table_counts(self):
        depts = {
            "提炼工程四部": 8, "提炼工程五部": 4, "提炼工程六部": 2,
        }
        counts: dict[str, int] = {}
        for dept in TABLE_DEPT_MAP.values():
            counts[dept] = counts.get(dept, 0) + 1
        assert counts == depts

    def test_same_workshop_different_lines_split(self):
        # 车间一：达托/达巴→五部，雷帕→四部（同车间产线分属不同部门）
        assert dept_for_record(_Rec("车间一", "达托")) == "提炼工程五部"
        assert dept_for_record(_Rec("车间一", "达巴")) == "提炼工程五部"
        assert dept_for_record(_Rec("车间一", "雷帕")) == "提炼工程四部"
        # 车间二：5 张分表三部门混布
        assert dept_for_record(_Rec("车间二", "达巴、非达")) == "提炼工程五部"
        assert dept_for_record(_Rec("车间二", "莫西")) == "提炼工程四部"
        assert dept_for_record(_Rec("车间二", "替考")) == "提炼工程六部"

    def test_tank_and_recycle_areas_to_dept4(self):
        for workshop in ("新罐区", "酒精回收和旧罐区", "异丙醇回收", "乙腈回收"):
            assert dept_for_record(_Rec(workshop, None)) == "提炼工程四部"

    def test_unmapped_and_dirty_rows(self):
        # 车间缺产线 → 未命中；历史脏行（workshop=table_id）经分表名兜底还原
        assert dept_for_record(_Rec("车间一", None)) is None
        assert dept_for_record(_Rec("", None)) is None
        assert dept_for_record(_Rec("tblHvWwh2NRcgk2A", None)) == "提炼工程五部"
        assert dept_for_record(_Rec("tblvWbXdrx282OAw", None)) == "提炼工程六部"
        assert dept_for_record(_Rec("tblIST5RYnGGz1zc", None)) == "提炼工程四部"
        # 未知 table_id 仍未命中
        assert dept_for_record(_Rec("tblUnknown", None)) is None

    def test_whitespace_tolerant(self):
        assert dept_for_record(_Rec(" 车间一 ", " 达托 ")) == "提炼工程五部"

    def test_group_records_by_dept_counts_unmapped(self):
        records = [
            _Rec("车间一", "达托"), _Rec("车间二", "达巴、非达"),
            _Rec("车间二", "替考"), _Rec("tblX", None),
        ]
        by_dept, unmapped = group_records_by_dept(records)
        assert unmapped == 1
        assert set(by_dept) == {"提炼工程五部", "提炼工程六部"}
        assert len(by_dept["提炼工程五部"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# build_dm_card / 名单
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildDmCard:
    def test_full_card_with_dept(self):
        content, card = build_dm_card("提炼工程四部", D, "部门过滤版正文")
        assert content == "部门过滤版正文"
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "blue"
        assert card["header"]["title"]["content"] == (
            "📊 中控报警日报 · 提炼工程四部 · 2026-10-08"
        )
        assert card["body"]["elements"][0] == {
            "tag": "markdown", "content": "部门过滤版正文",
        }

    def test_recipient_names_order_and_dedup(self):
        assert dm_recipient_names() == ["杨昆", "林锴彬", "蔡嘉旺", "陈美丽"]
        # 名单部门与映射部门一致（有表归属才有过滤版日报可发）
        assert set(DM_RECIPIENTS) <= set(TABLE_DEPT_MAP.values())


# ═══════════════════════════════════════════════════════════════════════════
# send_daily_central_alarm_dms — 编排统计（stub 解析器 / 发送器）
# ═══════════════════════════════════════════════════════════════════════════


def _resolver(names):
    async def resolve(names_arg):
        return {n: f"ou_{n}" for n in names_arg}
    return resolve


class TestSendDailyCentralAlarmDms:
    def test_disabled_by_switch(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.central_alarm.daily_dm.DM_ENABLED", False,
        )
        stats = asyncio.run(send_daily_central_alarm_dms(
            D, {"提炼工程四部": "md"}, resolver=_resolver([]), sender=AsyncMock(),
        ))
        assert stats == {"disabled": 1, "sent": 0, "skipped": 0, "errors": 0,
                         "unresolved": 0, "dept_empty": 0}

    def test_dept_filtered_one_card_per_person(self, monkeypatch):
        """同部门同内容、跨部门不同内容；无报警部门不私发。"""
        monkeypatch.setattr(
            "app.modules.safety.service.central_alarm.daily_dm.DM_ENABLED", True,
        )
        sender = AsyncMock(return_value=True)
        dept_markdowns = {
            "提炼工程四部": "四部正文", "提炼工程五部": "五部正文",
            # 提炼工程六部当日无报警 → 不在 dict
        }

        stats = asyncio.run(send_daily_central_alarm_dms(
            D, dept_markdowns, resolver=_resolver(None), sender=sender,
        ))
        assert stats == {"sent": 3, "skipped": 0, "errors": 0,
                         "unresolved": 0, "dept_empty": 1}
        calls = sender.await_args_list
        assert len(calls) == 3
        # 四部两人同内容，五部一人；六部（陈美丽）无卡
        by_content = {c.kwargs["content"] for c in calls}
        assert by_content == {"四部正文", "五部正文"}
        recipients = {c.kwargs["open_id"] for c in calls}
        assert recipients == {"ou_杨昆", "ou_林锴彬", "ou_蔡嘉旺"}
        titles = {c.kwargs["title"] for c in calls}
        assert titles == {
            "📊 中控报警日报 · 提炼工程四部 · 2026-10-08",
            "📊 中控报警日报 · 提炼工程五部 · 2026-10-08",
        }

    def test_empty_markdown_dept_counts_empty(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.central_alarm.daily_dm.DM_ENABLED", True,
        )
        sender = AsyncMock(return_value=True)
        stats = asyncio.run(send_daily_central_alarm_dms(
            D, {"提炼工程六部": ""}, resolver=_resolver(None), sender=sender,
        ))
        # 六部空串 + 四部/五部缺席，三个部门收件人都计入 dept_empty
        assert stats["sent"] == 0
        assert stats["dept_empty"] == 4
        assert sender.await_count == 0

    def test_unresolved_open_id_counts(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.central_alarm.daily_dm.DM_ENABLED", True,
        )

        async def partial(names_arg):
            return {n: f"ou_{n}" for n in names_arg if n != "林锴彬"}

        stats = asyncio.run(send_daily_central_alarm_dms(
            D, {"提炼工程四部": "md"}, resolver=partial,
            sender=AsyncMock(return_value=True),
        ))
        # 林锴彬未解析；五部/六部当日无报警不计发送对象
        assert stats == {"sent": 1, "skipped": 0, "errors": 0,
                         "unresolved": 1, "dept_empty": 2}

    def test_send_failure_and_exception_counts(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.central_alarm.daily_dm.DM_ENABLED", True,
        )
        stats = asyncio.run(send_daily_central_alarm_dms(
            D, {"提炼工程五部": "md"}, resolver=_resolver(None),
            sender=AsyncMock(return_value=False),
        ))
        assert stats["skipped"] == 1 and stats["sent"] == 0

        stats2 = asyncio.run(send_daily_central_alarm_dms(
            D, {"提炼工程五部": "md"}, resolver=_resolver(None),
            sender=AsyncMock(side_effect=RuntimeError("boom")),
        ))
        assert stats2["errors"] == 1 and stats2["sent"] == 0

    def test_resolver_failure_all_unresolved(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.central_alarm.daily_dm.DM_ENABLED", True,
        )

        async def broken(names_arg):
            raise RuntimeError("contact api down")

        stats = asyncio.run(send_daily_central_alarm_dms(
            D, {"提炼工程四部": "md"}, resolver=broken,
            sender=AsyncMock(return_value=True),
        ))
        assert stats == {"sent": 0, "skipped": 0, "errors": 0,
                         "unresolved": 2, "dept_empty": 2}


# ═══════════════════════════════════════════════════════════════════════════
# build_dept_daily_reports — 部门过滤编排（直读替身，零 DB）
# ═══════════════════════════════════════════════════════════════════════════


class FakeReader:
    """替身：预置滚动窗口数据。"""

    def __init__(self, views: list[CentralAlarmView]) -> None:
        self._views = views

    async def fetch_window_records(
        self, *, start_utc: datetime, end_utc: datetime, strict: bool = False,
    ) -> list[CentralAlarmView]:
        return [v for v in self._views
                if v.alarm_date and start_utc <= v.alarm_date < end_utc]

    async def get_records_by_rolling_window(
        self, target_date: date, *, strict: bool = False,
    ) -> tuple[list[CentralAlarmView], datetime, datetime]:
        start, end = ca_reader.rolling_window(target_date)
        views = await self.fetch_window_records(start_utc=start, end_utc=end)
        return views, start, end


class FakeAnalyst:
    """替身：不调 AI，直接回填分析与部门前缀汇总。"""

    def __init__(self) -> None:
        self.history_index: Any = None
        self.summaries: list[str] = []

    async def analyze_per_records(
        self, records: Any, *, channel: str = "system",
    ) -> dict[str, Any]:
        for r in records:
            r.ai_alarm_type = "高高压"
            r.ai_pattern = "repeated"
            r.ai_dimension = "equipment"
            r.ai_reason_analysis = f"分析-{r.id}"
            r.ai_analyzed_at = datetime.now(UTC)
        return {}

    async def analyze_daily_summary(
        self, agg: Any, per: list[Any], *, channel: str,
    ) -> dict[str, Any]:
        dept_workshops = "、".join(sorted(agg.workshop_distribution))
        self.summaries.append(dept_workshops)
        return {"summary": f"{dept_workshops} 汇总", "key_issues": [],
                "rectification_suggestions": []}


_BJ = timedelta(hours=8)


def _view(record_id: str, workshop: str, line: str | None,
          bj_dt: datetime, *, desc: str = "V0407 储罐 高高压报警") -> CentralAlarmView:
    return CentralAlarmView(
        id=record_id, feishu_record_id=record_id,
        alarm_date=bj_dt - _BJ,
        workshop=workshop, line=line, post="DCS 内操", alarm_description=desc,
    )


def _service(reader: FakeReader) -> tuple[CentralAlarmService, FakeAnalyst]:
    svc = CentralAlarmService.__new__(CentralAlarmService)
    svc.session = cast(Any, None)  # 直读路径不触 DB；误用会立刻暴露
    svc._reader = reader  # noqa: SLF001
    analyst = FakeAnalyst()
    svc.analyst = cast(Any, analyst)  # noqa: SLF001
    return svc, analyst


class TestBuildDeptDailyReports:
    async def test_groups_by_mapping_and_skips_empty(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
        bj_dt = datetime(2026, 10, 8, 2, tzinfo=UTC)
        views = [
            # 五部两条（车间一达托 + 车间二达巴非达）
            _view("r1", "车间一", "达托", bj_dt),
            _view("r2", "车间二", "达巴、非达", bj_dt),
            # 四部一条（乙腈回收）
            _view("r3", "乙腈回收", None, bj_dt),
            # 六部当日无 → 缺席；脏行不计入任何部门
            _view("r4", "tblX", None, bj_dt),
            # 非高高报警 → 整条被筛选掉
            _view("r5", "车间二", "替考", bj_dt, desc="常规低报"),
        ]
        svc, analyst = _service(FakeReader(views))

        out = await svc.build_dept_daily_reports(D)

        assert set(out) == {"提炼工程四部", "提炼工程五部"}
        # 部门内只含本部门车间；AI 分析与部门级汇总都跑了
        assert "车间一" in out["提炼工程五部"]
        assert "车间二" in out["提炼工程五部"]
        assert "乙腈回收" in out["提炼工程四部"]
        assert "替考" not in out["提炼工程五部"]
        assert "汇总" in out["提炼工程四部"]
        # 部门级汇总 AI：按分组顺序（五部先、四部后）各跑一次，车间列表排序稳定
        assert analyst.summaries == ["车间一、车间二", "乙腈回收"]

    async def test_all_filtered_out_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
        bj_dt = datetime(2026, 10, 8, 2, tzinfo=UTC)
        svc, _ = _service(FakeReader([
            _view("r1", "车间二", "替考", bj_dt, desc="常规低报"),
        ]))
        assert await svc.build_dept_daily_reports(D) == {}


# ═══════════════════════════════════════════════════════════════════════════
# run_daily_central_alarm_dm — 定时任务入口（mock session / 编排 / 私发）
# ═══════════════════════════════════════════════════════════════════════════


class _AsyncSessionCtx:
    """async_session_factory 的 async 上下文替身（返回预置 session）。"""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class TestRunDailyCentralAlarmDm:
    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.central_alarm.daily_dm.DM_ENABLED", False,
        )
        assert asyncio.run(run_daily_central_alarm_dm()) is None

    def test_enabled_full_flow(self, monkeypatch):
        monkeypatch.setattr(
            "app.modules.safety.service.central_alarm.daily_dm.DM_ENABLED", True,
        )
        stats = {"sent": 3, "skipped": 0, "errors": 0, "unresolved": 0,
                 "dept_empty": 1}
        session = AsyncMock()
        factory = MagicMock(return_value=_AsyncSessionCtx(session))
        dept_markdowns = {"提炼工程四部": "四部正文", "提炼工程五部": "五部正文"}
        with (
            patch("app.core.database.async_session_factory", new=factory),
            patch.object(
                CentralAlarmService, "build_dept_daily_reports",
                AsyncMock(return_value=dept_markdowns),
            ),
            patch(
                "app.modules.safety.service.central_alarm.daily_dm"
                ".send_daily_central_alarm_dms",
                AsyncMock(return_value=stats),
            ),
        ):
            result = asyncio.run(run_daily_central_alarm_dm(D))
        assert result == stats
