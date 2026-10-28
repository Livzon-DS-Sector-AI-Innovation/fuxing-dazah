"""Agent 查询面补全一期（agent-query-p1）新工具测试。

覆盖 spec（.scratch/agent-query-p1/spec.md）交付 1-8 项的新工具：
遥测 / 设施 / 培训行为 / 外来人员保险 / 总览 / 危化品趋势 /
query_hazards 来源过滤 / query_oh monitors。

测试接缝（与 test_read_detail_tools 一致）：
- mock ``ctx.deps.db``：FakeSession 按调用序返回预设结果，并记录收到的
  statement（断言 where 骨架）；
- bitable 源工具 monkeypatch reader/client（先例 test_subsidy_tools）；
- overview 用 service 自带 collectors 注入接缝；
- 直接调用工具函数（不走 core.pipeline，避免真实审计写库）；
- 路由断言走 tool_selector.select_tool_names 纯函数。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    ROLE_VIEWER,
    allowed_tools,
)
from app.modules.safety.business_agent.tools import registry

NEW_TOOLS_P1 = [
    # T1 遥测域
    "query_telemetry_latest",
    "query_telemetry_alarms",
    # T2 设施域
    "query_facility_ledgers",
    "query_facility_tasks",
    "query_facility_inspections",
    # T3 培训域
    "query_training_behavior",
]


# ── Fake DB（按调用序返回；记录 statement）────────────────────────


class _FakeResult:
    def __init__(self, *, scalar: Any = None, rows: list[Any] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self) -> Any:
        return self._scalar

    def scalars(self) -> Any:
        return SimpleNamespace(all=lambda: self._rows)


class FakeSession:
    """依次返回预设结果；收集 execute 收到的 statement 供断言。

    scalar 同步消费预设队列（repo 层 count 常用 session.scalar）。
    """

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.statements.append(stmt)
        return self._results.pop(0)

    async def scalar(self, stmt: Any | None = None) -> Any:
        return self._results.pop(0).scalar()


def _ctx(db: FakeSession) -> SimpleNamespace:
    return SimpleNamespace(deps=SimpleNamespace(db=db))


# ═══════════════════════════════════════════════════════════════════
# T1 遥测域 — query_telemetry_latest / query_telemetry_alarms
# ═══════════════════════════════════════════════════════════════════


class TestTelemetryToolsWiring:
    def test_registry_and_groups(self) -> None:
        from app.modules.safety.business_agent.tools.telemetry_tools import (
            query_telemetry_alarms,
            query_telemetry_latest,
        )

        for name, func in [
            ("query_telemetry_latest", query_telemetry_latest),
            ("query_telemetry_alarms", query_telemetry_alarms),
        ]:
            assert registry.TOOL_KIND[name] is False
            assert registry._FUNC_BY_NAME[name] is func
            assert name not in registry.RESIDENT_TOOLS
        assert set(tool_selector.TOOL_GROUPS["telemetry"]) == {
            "query_telemetry_latest", "query_telemetry_alarms",
        }

    def test_permissions_viewer_can_query(self) -> None:
        viewer = allowed_tools(ROLE_VIEWER)
        assert "query_telemetry_latest" in viewer
        assert "query_telemetry_alarms" in viewer

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("锅炉现在压力多少", "query_telemetry_latest"),
            ("锅炉最新读数报一下", "query_telemetry_latest"),
            ("特种设备报警记录有哪些", "query_telemetry_alarms"),
            ("锅炉昨天有没有报警", "query_telemetry_alarms"),
        ],
    )
    def test_route_selects_telemetry_tools(self, message: str, expected: str) -> None:
        names = tool_selector.select_tool_names(message)
        assert expected in names, f"{message!r} → {names}"


class TestQueryTelemetryLatest:
    def test_returns_items_with_iso_timestamps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.models import TelemetrySnapshot
        from app.modules.safety.business_agent.tools.telemetry_tools import (
            query_telemetry_latest,
        )

        # 避开真实 app_config 读取：规则为空 → status 恒 normal
        monkeypatch.setattr(
            "app.modules.safety.telemetry.rules.effective_rules",
            lambda override=None: (),
        )
        row = TelemetrySnapshot(
            equipment_no="GL-01",
            metric="蒸汽压力",
            value=0.8,
            unit="MPa",
            recorded_at=datetime(2026, 10, 28, 8, 0, tzinfo=UTC),
            parse_method="manual",
        )
        db = FakeSession([_FakeResult(rows=[row])])
        result = asyncio_run(query_telemetry_latest(_ctx(db), equipment_no="GL-01"))
        assert result["success"] is True
        assert result["total"] == 1
        item = result["items"][0]
        assert item["equipment_no"] == "GL-01"
        assert item["metric"] == "蒸汽压力"
        assert item["value"] == 0.8
        assert item["status"] == "normal"
        assert item["recorded_at"] == "2026-10-28T08:00:00+00:00"
        # equipment_no 过滤进了 where 参数（先例：compile().params 渲染绑定值）
        assert "GL-01" in str(db.statements[0].compile().params)

    def test_error_fallback(self) -> None:
        from app.modules.safety.business_agent.tools.telemetry_tools import (
            query_telemetry_latest,
        )

        class _Boom:
            async def execute(self, *_a: Any, **_k: Any) -> Any:
                raise RuntimeError("db down")

        result = asyncio_run(query_telemetry_latest(_ctx(_Boom())))  # type: ignore[arg-type]
        assert result == {"success": False, "error": "查询失败: db down"}


class TestQueryTelemetryAlarms:
    def test_returns_paged_alarms(self) -> None:
        from app.modules.safety.models import TelemetryAlarmRecord
        from app.modules.safety.business_agent.tools.telemetry_tools import (
            query_telemetry_alarms,
        )

        alarm = TelemetryAlarmRecord(
            equipment_no="GL-01",
            metric="蒸汽压力",
            value=1.9,
            recorded_at=datetime(2026, 10, 27, 9, 30, tzinfo=UTC),
            rule_desc="蒸汽压力超过上限",
            level="alarm",
            status="firing",
        )
        db = FakeSession([_FakeResult(scalar=1), _FakeResult(rows=[alarm])])
        result = asyncio_run(
            query_telemetry_alarms(_ctx(db), equipment_no="GL-01", status="firing")
        )
        assert result["success"] is True
        assert result["total"] == 1
        assert result["page"] == 1
        item = result["items"][0]
        assert item["equipment_no"] == "GL-01"
        assert item["status"] == "firing"
        assert item["recorded_at"] == "2026-10-27T09:30:00+00:00"
        params = str(db.statements[0].compile().params)
        assert "firing" in params and "GL-01" in params

    def test_invalid_status_hint(self) -> None:
        from app.modules.safety.business_agent.tools.telemetry_tools import (
            query_telemetry_alarms,
        )

        db = FakeSession([])
        result = asyncio_run(query_telemetry_alarms(_ctx(db), status="boom"))
        assert result["success"] is False
        assert "status" in result["error"]


def asyncio_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════
# T2 设施域 — query_facility_ledgers / query_facility_tasks /
#            query_facility_inspections
# ═══════════════════════════════════════════════════════════════════


def _bj_today():
    from datetime import date, datetime, timedelta, timezone

    return datetime.now(timezone(timedelta(hours=8))).date()


def _ledger_view(
    record_id: str, *, biz_type: str = "fire_equipment",
    department: str | None = "生产部", name: str = "灭火器",
    location: str | None = "车间一", anchor=None, status: str = "",
) -> Any:
    from app.modules.safety.facilities.ledger import LedgerRowView

    return LedgerRowView(
        record_id=record_id, biz_type=biz_type, department=department,
        name=name, location=location, equipment_no=f"EQ-{record_id[-2:]}",
        status=status, anchor=anchor, anchor_source="next_date" if anchor else "none",
    )


class TestFacilityToolsWiring:
    def test_registry_and_groups(self) -> None:
        from app.modules.safety.business_agent.tools.facility_tools import (
            query_facility_inspections,
            query_facility_ledgers,
            query_facility_tasks,
        )

        for name, func in [
            ("query_facility_ledgers", query_facility_ledgers),
            ("query_facility_tasks", query_facility_tasks),
            ("query_facility_inspections", query_facility_inspections),
        ]:
            assert registry.TOOL_KIND[name] is False
            assert registry._FUNC_BY_NAME[name] is func
            assert name not in registry.RESIDENT_TOOLS
        assert set(tool_selector.TOOL_GROUPS["facilities"]) == {
            "query_facility_ledgers", "query_facility_tasks",
            "query_facility_inspections",
        }

    def test_permissions_viewer_can_query(self) -> None:
        viewer = allowed_tools(ROLE_VIEWER)
        for name in ("query_facility_ledgers", "query_facility_tasks",
                     "query_facility_inspections"):
            assert name in viewer

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("灭火器有效期情况", "query_facility_ledgers"),
            ("安全附件台账有多少到期", "query_facility_ledgers"),
            ("特种设备台账查一下", "query_facility_ledgers"),
            ("校验任务还有哪些没完成", "query_facility_tasks"),
            ("灭火器点检记录", "query_facility_inspections"),
        ],
    )
    def test_route_selects_facility_tools(self, message: str, expected: str) -> None:
        names = tool_selector.select_tool_names(message)
        assert expected in names, f"{message!r} → {names}"


class TestQueryFacilityLedgers:
    def _patch_reader(self, monkeypatch: pytest.MonkeyPatch, views_by_biz: dict) -> None:
        class _FakeReader:
            async def fetch_ledger(self, biz_type: str, *, strict: bool = True):
                if biz_type not in views_by_biz:
                    from app.modules.safety.service.bitable_direct.errors import (
                        BitableConfigError,
                    )

                    raise BitableConfigError(f"未配置: {biz_type}")
                return views_by_biz[biz_type]

        monkeypatch.setattr(
            "app.modules.safety.facilities.reader.open_reader", lambda: _FakeReader()
        )

    def test_due_overdue_filters_and_summary(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import timedelta

        from app.modules.safety.business_agent.tools.facility_tools import (
            query_facility_ledgers,
        )

        today = _bj_today()
        views = [
            _ledger_view("rec01", anchor=today - timedelta(days=5)),      # 已到期
            _ledger_view("rec02", anchor=today + timedelta(days=10)),     # 30 天内
            _ledger_view("rec03", anchor=today + timedelta(days=100)),    # 窗口外
            _ledger_view("rec04", department="环保部", anchor=today - timedelta(days=1)),
        ]
        self._patch_reader(monkeypatch, {"fire_equipment": views})

        result = asyncio_run(
            query_facility_ledgers(_ctx(None), ledger="灭火器", due="overdue")
        )
        assert result["success"] is True
        assert result["status"] == "live"
        # overdue 只算在用行：rec01(-5天)/rec04(-1天) 命中，按锚点升序
        assert [i["record_id"] for i in result["items"]] == ["rec01", "rec04"]
        # summary 为全量口径（4 行 2 到期）
        assert result["summary"]["fire_equipment"]["total"] == 4
        assert result["summary"]["fire_equipment"]["overdue"] == 2

    def test_department_keyword_and_soon_window(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import timedelta

        from app.modules.safety.business_agent.tools.facility_tools import (
            query_facility_ledgers,
        )

        today = _bj_today()
        views = [
            _ledger_view("rec01", department="生产部", name="干粉灭火器",
                         anchor=today + timedelta(days=7)),
            _ledger_view("rec02", department="生产部", name="二氧化碳灭火器",
                         anchor=today + timedelta(days=40)),
            _ledger_view("rec03", department="环保部", name="干粉灭火器",
                         anchor=today + timedelta(days=7)),
        ]
        self._patch_reader(monkeypatch, {"fire_equipment": views})

        result = asyncio_run(
            query_facility_ledgers(
                _ctx(None), ledger="fire_equipment",
                department="生产", keyword="干粉", due="soon:30",
            )
        )
        assert result["success"] is True
        assert [i["record_id"] for i in result["items"]] == ["rec01"]
        item = result["items"][0]
        assert item["remaining_days"] == 7
        assert item["department"] == "生产部"

    def test_not_connected_ledger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.facility_tools import (
            query_facility_ledgers,
        )

        self._patch_reader(monkeypatch, {})
        result = asyncio_run(
            query_facility_ledgers(_ctx(None), ledger="special_equipment")
        )
        assert result["status"] == "not_connected"
        assert result["items"] == []

    def test_invalid_ledger_hint(self) -> None:
        from app.modules.safety.business_agent.tools.facility_tools import (
            query_facility_ledgers,
        )

        result = asyncio_run(query_facility_ledgers(_ctx(None), ledger="锅炉"))
        assert result["success"] is False
        assert "ledger" in result["error"]


class TestQueryFacilityTasks:
    def test_returns_tasks_with_summary(self) -> None:
        from datetime import timedelta

        from app.modules.safety.models import FacilityCheckTask
        from app.modules.safety.business_agent.tools.facility_tools import (
            query_facility_tasks,
        )

        today = _bj_today()
        task = FacilityCheckTask(
            biz_type="fire_equipment", ledger_key="rec01",
            equipment_no="EQ-01", equipment_name="干粉灭火器",
            department="生产部", location="车间一",
            task_kind="检查", due_date=today - timedelta(days=2),
            lead_days=60, status="issued",
            anchor_at_dispatch=today - timedelta(days=62),
            issued_on=today - timedelta(days=62),
        )
        # list_tasks 与 task_summary 各拉一次全量，FakeSession 按序返回
        db = FakeSession([_FakeResult(rows=[task]), _FakeResult(rows=[task])])
        result = asyncio_run(query_facility_tasks(_ctx(db), status="issued"))
        assert result["success"] is True
        assert result["total"] == 1
        item = result["items"][0]
        assert item["equipment_no"] == "EQ-01"
        assert item["overdue"] is True
        assert result["summary"]["open"] == 1
        params = str(db.statements[0].compile().params)
        assert "issued" in params


class TestQueryFacilityInspections:
    def _patch_bitable(
        self, monkeypatch: pytest.MonkeyPatch, raw_records: list[dict],
    ) -> None:
        async def _fake_search(tenant_token, app_token, table_id, http=None):
            return raw_records

        async def _fake_token() -> str:
            return "t-fake"

        monkeypatch.setattr(
            "app.modules.safety.fire_inspection.bitable.search_records", _fake_search,
        )
        monkeypatch.setattr(
            "app.modules.safety.fire_inspection.bitable.load_tenant_token", _fake_token,
        )

    def test_filters_and_pagination(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.facility_tools import (
            query_facility_inspections,
        )

        ms = lambda d: int(d.timestamp() * 1000)  # noqa: E731
        from datetime import datetime, timedelta, timezone

        tz = timezone(timedelta(hours=8))
        day1 = datetime(2026, 10, 20, 9, 0, tzinfo=tz)
        day2 = datetime(2026, 10, 25, 10, 0, tzinfo=tz)
        raw = [
            {"record_id": "r-new", "fields": {
                "设备编号": "MP-01", "点检人": [{"name": "张三"}],
                "点检人.部门": ["生产部"], "点检时间": ms(day2),
                "点检结果": "正常", "整改状态": "无",
            }},
            {"record_id": "r-old", "fields": {
                "设备编号": "MP-02", "点检人": [{"name": "李四"}],
                "点检人.部门": ["环保部"], "点检时间": ms(day1),
                "点检结果": "异常", "整改状态": "整改中",
                "异常描述": "压力表指针不在绿区",
            }},
        ]
        self._patch_bitable(monkeypatch, raw)

        result = asyncio_run(
            query_facility_inspections(
                _ctx(None), equipment_no="MP-01",
                date_from="2026-10-21", date_to="2026-10-28",
            )
        )
        assert result["success"] is True
        assert result["total"] == 1
        item = result["items"][0]
        assert item["equipment_no"] == "MP-01"
        assert item["department"] == "生产部"
        assert item["result"] == "正常"
        assert item["inspect_at"].startswith("2026-10-25")

        # result 过滤 + 时间倒序
        result2 = asyncio_run(
            query_facility_inspections(_ctx(None), result="异常")
        )
        assert [i["record_id"] for i in result2["items"]] == ["r-old"]
        assert result2["items"][0]["abnormal_desc"] == "压力表指针不在绿区"

    def test_error_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.facility_tools import (
            query_facility_inspections,
        )

        async def _boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("feishu down")

        monkeypatch.setattr(
            "app.modules.safety.fire_inspection.bitable.search_records", _boom,
        )

        async def _fake_token() -> str:
            return "t-fake"

        monkeypatch.setattr(
            "app.modules.safety.fire_inspection.bitable.load_tenant_token", _fake_token,
        )
        result = asyncio_run(query_facility_inspections(_ctx(None)))
        assert result["success"] is False


# ═══════════════════════════════════════════════════════════════════
# T3 培训与行为管控域 — query_training_behavior（entity 合一）
# ═══════════════════════════════════════════════════════════════════


def _patch_kind_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows_by_kind: dict[str, list[dict] | None],
) -> None:
    """monkeypatch domain_pages.fetch_kind_rows：按 kind 返回预设（None=未接入）。"""

    async def _fake(url_key: str, kind: str, *, opener: Any = None):
        assert url_key == "training-behavior"
        return rows_by_kind.get(kind)

    monkeypatch.setattr(
        "app.modules.safety.service.domain_pages.fetch_kind_rows", _fake,
    )
    # 工具内延迟 import，需同步 patch 工具模块引用（若实现 import 方式不同，
    # patch 源头模块属性即对延迟 import 生效）


class TestTrainingToolsWiring:
    def test_registry_and_groups(self) -> None:
        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )

        assert registry.TOOL_KIND["query_training_behavior"] is False
        assert registry._FUNC_BY_NAME["query_training_behavior"] is query_training_behavior
        assert "query_training_behavior" not in registry.RESIDENT_TOOLS
        assert tool_selector.TOOL_GROUPS["training"] == ["query_training_behavior"]

    def test_permissions_viewer_can_query(self) -> None:
        assert "query_training_behavior" in allowed_tools(ROLE_VIEWER)

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("谁有违章记录", "query_training_behavior"),
            ("今年的三违情况怎么样", "query_training_behavior"),
            ("培训计划完成情况", "query_training_behavior"),
            ("哪些人快到复训期了", "query_training_behavior"),
        ],
    )
    def test_route_selects_training_tool(self, message: str, expected: str) -> None:
        names = tool_selector.select_tool_names(message)
        assert expected in names, f"{message!r} → {names}"


class TestQueryTrainingViolations:
    def _rows(self) -> list[dict]:
        return [
            {"record_id": "v1", "occurred_at": "2026-10-10T00:00:00+08:00",
             "person_name": "张三", "department": ["生产部"], "category": "违章作业",
             "level": "一般", "description": "未佩戴防护眼镜", "status": "纠正中",
             "handling": None, "corrective_action": None,
             "related_hazard_no": None, "retraining_note": None, "note": None,
             "evidence_files": [], "ai_level_suggestion": None},
            {"record_id": "v2", "occurred_at": "2026-09-01T00:00:00+08:00",
             "person_name": "李四", "department": ["环保部"], "category": "违章指挥",
             "level": "严重", "description": "违章指挥吊装", "status": "已纠正",
             "handling": None, "corrective_action": None,
             "related_hazard_no": None, "retraining_note": None, "note": None,
             "evidence_files": [], "ai_level_suggestion": None},
        ]

    def test_department_and_year_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )

        _patch_kind_rows(monkeypatch, {"violation": self._rows()})
        result = asyncio_run(
            query_training_behavior(
                _ctx(None), entity="violations", department="生产", year="2026",
            )
        )
        assert result["success"] is True
        assert result["total"] == 1
        assert result["items"][0]["person_name"] == "张三"

    def test_keyword_and_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )

        _patch_kind_rows(monkeypatch, {"violation": self._rows()})
        result = asyncio_run(
            query_training_behavior(_ctx(None), entity="violations", keyword="吊装")
        )
        assert result["total"] == 1
        assert result["items"][0]["level"] == "严重"

    def test_not_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )

        _patch_kind_rows(monkeypatch, {"violation": None})
        result = asyncio_run(query_training_behavior(_ctx(None), entity="violations"))
        assert result["status"] == "not_connected"


class TestQueryTrainingPlansAndRetraining:
    def _training_rows(self) -> list[dict]:
        from datetime import timedelta

        today = _bj_today()
        d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
        return [
            {"record_id": "t1", "name": "有限空间作业培训", "category": "安全",
             "planned_at": None, "held_at": None, "form": None,
             "department": ["生产部"], "lecturer": None, "expected_count": "20",
             "actual_count": None, "attendance_file": [], "assessment": None,
             "passed_count": None, "status": "已实施",
             "next_retraining_at": d(-5), "note": None},          # 已逾期
            {"record_id": "t2", "name": "消防器材使用培训", "category": "消防",
             "planned_at": None, "held_at": None, "form": None,
             "department": ["环保部"], "lecturer": None, "expected_count": "15",
             "actual_count": None, "attendance_file": [], "assessment": None,
             "passed_count": None, "status": "计划",
             "next_retraining_at": d(10), "note": None},          # 30 天内
            {"record_id": "t3", "name": "应急疏散演练培训", "category": "应急",
             "planned_at": None, "held_at": None, "form": None,
             "department": ["生产部"], "lecturer": None, "expected_count": "30",
             "actual_count": None, "attendance_file": [], "assessment": None,
             "passed_count": None, "status": "计划",
             "next_retraining_at": d(100), "note": None},         # 窗口外
            {"record_id": "t4", "name": "已取消培训", "category": "其它",
             "planned_at": None, "held_at": None, "form": None,
             "department": ["生产部"], "lecturer": None, "expected_count": "0",
             "actual_count": None, "attendance_file": [], "assessment": None,
             "passed_count": None, "status": "已取消",
             "next_retraining_at": d(3), "note": None},           # 已取消排除
            {"record_id": "t5", "name": "无复训日期培训", "category": "其它",
             "planned_at": None, "held_at": None, "form": None,
             "department": ["生产部"], "lecturer": None, "expected_count": "0",
             "actual_count": None, "attendance_file": [], "assessment": None,
             "passed_count": None, "status": "计划",
             "next_retraining_at": None, "note": None},           # 无日期跳过
        ]

    def test_plans_department_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )

        _patch_kind_rows(monkeypatch, {"training": self._training_rows()})
        result = asyncio_run(
            query_training_behavior(
                _ctx(None), entity="plans", department="生产", status="计划",
            )
        )
        assert result["success"] is True
        assert result["total"] == 2
        # 「已取消」不含「计划」不命中；无复训日期行的 status=计划 命中
        assert {i["name"] for i in result["items"]} == {
            "应急疏散演练培训", "无复训日期培训",
        }

    def test_retraining_due_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )

        _patch_kind_rows(monkeypatch, {"training": self._training_rows()})
        result = asyncio_run(
            query_training_behavior(_ctx(None), entity="retraining_due", days=30)
        )
        assert result["success"] is True
        # 已逾期(-5)在前，30 天内(+10)随后；已取消/窗口外/无日期排除
        assert [i["name"] for i in result["items"]] == [
            "有限空间作业培训", "消防器材使用培训",
        ]
        assert result["items"][0]["overdue"] is True
        assert result["items"][0]["remaining_days"] == -5
        assert result["overdue_count"] == 1


class TestQueryTrainingDemandDrafts:
    def test_drafts_via_db(self) -> None:
        from datetime import datetime

        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )
        from app.modules.safety.models import TrainingDemandDraft

        draft = TrainingDemandDraft(
            year=2026, position="仓管员", topic="危化品仓储安全",
            suggested_hours=4, form="线下", audience="仓储部",
            basis="GB 15603", is_statutory_gap=True, status="draft",
        )
        db = FakeSession([_FakeResult(rows=[draft])])
        result = asyncio_run(
            query_training_behavior(_ctx(db), entity="demand_drafts", year="2026")
        )
        assert result["success"] is True
        assert result["total"] == 1
        assert result["items"][0]["topic"] == "危化品仓储安全"
        params = str(db.statements[0].compile().params)
        assert "2026" in params

    def test_invalid_status_hint(self) -> None:
        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )

        result = asyncio_run(
            query_training_behavior(_ctx(None), entity="demand_drafts", status="boom")
        )
        assert result["success"] is False
        assert "status" in result["error"]

    def test_unknown_entity_hint(self) -> None:
        from app.modules.safety.business_agent.tools.training_tools import (
            query_training_behavior,
        )

        result = asyncio_run(
            query_training_behavior(_ctx(None), entity="whatever")
        )
        assert result["success"] is False
        assert "entity" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# T4 三小域 — query_visitor_insurance / query_overview / query_chemical_trend
# ═══════════════════════════════════════════════════════════════════


def _warning_result() -> Any:
    """构造一个三类命中的 WarningResult（独立于实现口径的手工样例）。"""
    from datetime import date, timedelta

    from app.modules.safety.service.visitor_insurance.warning import (
        ExpiringGroup, MissingGroup, WarningResult,
    )

    today = date(2026, 10, 28)
    return WarningResult(
        today=today,
        expired=[
            ExpiringGroup(
                company="甲建设", names="王五", people=1, work_content="防腐施工",
                work_scope="罐区", entry_end=today + timedelta(days=10),
                insurance_end=today - timedelta(days=3), days_left=-3,
            ),
        ],
        soon=[
            ExpiringGroup(
                company="乙安装", names="赵六、钱七", people=2, work_content="管道安装",
                work_scope="车间二", entry_end=today + timedelta(days=20),
                insurance_end=today + timedelta(days=2), days_left=2,
            ),
        ],
        missing=[
            MissingGroup(
                company="丙劳务", notices=2, people=5,
                latest_entry_end=today + timedelta(days=30),
                work_contents=["保洁", "搬运"],
            ),
        ],
        total_notices=12, active_notices=8,
        next_expiry=today + timedelta(days=2), next_expiry_company="乙安装",
    )


class TestSmallDomainToolsWiring:
    def test_registry_and_groups(self) -> None:
        from app.modules.safety.business_agent.tools.domain_query_tools import (
            query_chemical_trend,
            query_overview,
            query_visitor_insurance,
        )

        for name, func in [
            ("query_visitor_insurance", query_visitor_insurance),
            ("query_overview", query_overview),
            ("query_chemical_trend", query_chemical_trend),
        ]:
            assert registry.TOOL_KIND[name] is False
            assert registry._FUNC_BY_NAME[name] is func
            assert name not in registry.RESIDENT_TOOLS
        assert tool_selector.TOOL_GROUPS["visitor_insurance"] == [
            "query_visitor_insurance",
        ]
        assert tool_selector.TOOL_GROUPS["overview"] == ["query_overview"]
        assert "query_chemical_trend" in tool_selector.TOOL_GROUPS["chemical"]

    def test_permissions_viewer_can_query(self) -> None:
        viewer = allowed_tools(ROLE_VIEWER)
        for name in ("query_visitor_insurance", "query_overview",
                     "query_chemical_trend"):
            assert name in viewer

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("外来人员保险到期的有哪些", "query_visitor_insurance"),
            ("访客的保险过期了没", "query_visitor_insurance"),
            ("今天安全状况怎么样", "query_overview"),
            ("给我一个整体情况汇总", "query_overview"),
            ("危化品库存趋势怎么样", "query_chemical_trend"),
            ("最近化学品有什么异动", "query_chemical_trend"),
        ],
    )
    def test_route_selects_small_domain_tools(self, message: str, expected: str) -> None:
        names = tool_selector.select_tool_names(message)
        assert expected in names, f"{message!r} → {names}"


class TestQueryVisitorInsurance:
    def test_all_groups_and_category_filter(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.domain_query_tools import (
            query_visitor_insurance,
        )

        async def _fake_result(reader=None, *, today=None):
            return _warning_result()

        monkeypatch.setattr(
            "app.modules.safety.service.visitor_insurance.report.build_warning_result",
            _fake_result,
        )
        ctx = _ctx(None)
        result = asyncio_run(query_visitor_insurance(ctx))
        assert result["success"] is True
        assert result["summary"]["total_notices"] == 12
        assert result["summary"]["active_notices"] == 8
        assert len(result["expired"]) == 1
        assert len(result["soon"]) == 1
        assert len(result["missing"]) == 1
        assert result["expired"][0]["company"] == "甲建设"
        assert result["expired"][0]["days_left"] == -3

        only = asyncio_run(query_visitor_insurance(ctx, category="soon"))
        assert only["soon"]
        assert only["expired"] == [] and only["missing"] == []

    def test_invalid_category_hint(self) -> None:
        from app.modules.safety.business_agent.tools.domain_query_tools import (
            query_visitor_insurance,
        )

        result = asyncio_run(query_visitor_insurance(_ctx(None), category="boom"))
        assert result["success"] is False
        assert "category" in result["error"]


class TestQueryOverview:
    def test_overview_trimmed_digest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_overview 被 patch：验证工具不传 collectors（生产全采集）+
        digest 裁剪只留计数/标题 + generated_at 转 isoformat。"""
        from datetime import UTC, datetime
        from types import SimpleNamespace as NS

        from app.modules.safety.business_agent.tools.domain_query_tools import (
            query_overview,
        )

        cell = NS(tag_text="保险预警", title="外来人员保险到期预警")

        async def _fake_build_overview(*, digest_store=None, collectors=None):
            assert collectors is None, "生产链路应走默认全量采集器"
            return {
                "date": "2026-10-28",
                "generated_at": datetime(2026, 10, 28, 8, 0, tzinfo=UTC),
                "hazards": {"today_total": 3, "high": 1},
                "special_ops": {"today_total": 5},
                "alarms": {"fire": 0, "central": 2},
                "certs": {"expiring_30d": 4},
                "chemicals": {"over_limit": 1},
                "key_risk_ops": {"open": 2},
                "ehs": {"month_total": 7},
                "facility_tasks": {"open": 3},
                "digest": {"count": 2, "cells": [cell, cell]},
                "module_health": {},
                "errors": [],
            }

        monkeypatch.setattr(
            "app.modules.safety.service.overview.build_overview",
            _fake_build_overview,
        )
        result = asyncio_run(query_overview(_ctx(None)))
        assert result["success"] is True
        assert result["hazards"]["today_total"] == 3
        # digest 裁剪：只留计数+标题，不带正文
        assert result["digest"] == {
            "count": 2, "titles": ["保险预警·外来人员保险到期预警"] * 2,
        }
        assert result["generated_at"] == "2026-10-28T08:00:00+00:00"
        assert result["errors"] == []

    def test_error_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.domain_query_tools import (
            query_overview,
        )

        async def _boom(**kwargs):
            raise RuntimeError("collector down")

        monkeypatch.setattr(
            "app.modules.safety.service.overview.build_overview", _boom,
        )
        result = asyncio_run(query_overview(_ctx(None)))
        assert result["success"] is False


class TestQueryChemicalTrend:
    def test_views_routed_to_trend_functions(self) -> None:
        from app.modules.safety.business_agent.tools.domain_query_tools import (
            query_chemical_trend,
        )

        called: list[str] = []

        async def _points(db, days=30):
            called.append(f"points:{days}")
            return [{"date": "2026-10-27", "total_t": 12.5, "item_count": 3,
                     "warn_count": 0}]

        async def _changes(db, target_date=None, limit=100):
            called.append(f"changes:{target_date}:{limit}")
            return {"target_date": target_date, "base_date": "2026-10-26",
                    "compare_skipped": False,
                    "summary": {"surge_count": 1, "decline_count": 0,
                                "new_count": 0, "removed_count": 0,
                                "total_materials": 3},
                    "items": []}

        async def _ctrend(db, days=30):
            called.append(f"ctrend:{days}")
            return [{"date": "2026-10-27", "surge_count": 1,
                     "decline_count": 0, "compare_skipped": False}]

        import app.modules.safety.chemical_inventory.trend as trend_mod

        orig = (trend_mod.daily_trend_points, trend_mod.material_changes,
                trend_mod.change_trend)
        trend_mod.daily_trend_points = _points
        trend_mod.material_changes = _changes
        trend_mod.change_trend = _ctrend
        try:
            ctx = _ctx(None)
            r1 = asyncio_run(query_chemical_trend(ctx, view="trend_points", days=7))
            assert r1["success"] is True
            assert r1["points"][0]["total_t"] == 12.5

            r2 = asyncio_run(query_chemical_trend(ctx, view="material_changes",
                                                  target_date="2026-10-27"))
            assert r2["success"] is True
            assert r2["summary"]["surge_count"] == 1

            r3 = asyncio_run(query_chemical_trend(ctx, view="change_trend", days=14))
            assert r3["success"] is True
            assert r3["trend"][0]["surge_count"] == 1

            bad = asyncio_run(query_chemical_trend(ctx, view="boom"))
            assert bad["success"] is False
        finally:
            (trend_mod.daily_trend_points, trend_mod.material_changes,
             trend_mod.change_trend) = orig
        assert called == ["points:7", "changes:2026-10-27:50", "ctrend:14"]


# ═══════════════════════════════════════════════════════════════════
# T5 扩展现有工具 — query_hazards source / query_oh monitors /
#                  ehs_change「变更」裸词路由
# ═══════════════════════════════════════════════════════════════════


def _ext_view(record_id: str, *, closed: bool = False, desc: str = "罐区围堰破损",
              departments: list[str] | None = None,
              checked_at: "date | None" = None) -> Any:
    from datetime import date

    from app.modules.safety.service.hazard_direct.external_audit import (
        ExternalAuditView,
    )

    return ExternalAuditView(
        record_id=record_id, seq=1, description=desc, plan="限期修复",
        departments=departments or ["生产部"], closed=closed,
        in_progress=False, checked_at=checked_at or date(2026, 10, 10),
        target_date=date(2026, 11, 10), responsible=[("张三", "ou_zs")],
    )


class TestQueryHazardsSource:
    def _patch_internal(self, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
        """内部隐患表链路 mock（bitable_repo.query_hazards）。"""
        from datetime import date

        from app.modules.safety.business_agent.tools import read_tools

        class _FakeView:
            def __init__(self, no: str) -> None:
                self.record_id = f"i-{no}"
                self.hazard_no = f"HZ-2026-01{no}"
                self.department = "生产部"
                self.description = f"内部隐患{no}"
                self.status = "open"
                self.rectification_status = "pending"
                self.discovered_at = date(2026, 10, 1)
                self.rectification_responsible_person_name = "李四"

        async def _fake_query(client, **kwargs):
            views = [_FakeView("1"), _FakeView("2")]
            return views, len(views)

        monkeypatch.setattr(
            "app.modules.safety.service.hazard_direct.bitable_repo.query_hazards",
            _fake_query,
        )
        return read_tools

    def test_default_unchanged_internal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """不传 source：走内部隐患登记表原链路（行为零变化）。"""
        from app.modules.safety.business_agent.tools.read_tools import query_hazards

        self._patch_internal(monkeypatch)
        result = asyncio_run(query_hazards(_ctx(None)))
        assert result["items"][0]["hazard_no"] == "HZ-2026-011"
        assert result["total"] == 2
        assert all(i["source"] == "internal" for i in result["items"])

    def test_source_external(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.read_tools import query_hazards

        async def _fake_fetch():
            return [_ext_view("e1"), _ext_view("e2", closed=True, desc="标识缺失")]

        monkeypatch.setattr(
            "app.modules.safety.service.hazard_direct.external_audit.fetch_external_audit",
            _fake_fetch,
        )
        result = asyncio_run(query_hazards(_ctx(None), source="external"))
        assert result["total"] == 2
        assert result["source"] == "external_audit"
        open_items = [i for i in result["items"] if not i["closed"]]
        assert len(open_items) == 1
        item = result["items"][0]
        assert item["display_status"] == "未关闭"
        assert item["departments"] == ["生产部"]
        assert item["checked_at"] == "2026-10-10"
        assert item["responsible_names"] == ["张三"]
        closed_item = result["items"][1]
        assert closed_item["display_status"] == "已关闭"

    def test_source_all_merges(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.read_tools import query_hazards

        self._patch_internal(monkeypatch)

        async def _fake_fetch():
            return [_ext_view("e1")]

        monkeypatch.setattr(
            "app.modules.safety.service.hazard_direct.external_audit.fetch_external_audit",
            _fake_fetch,
        )
        result = asyncio_run(query_hazards(_ctx(None), source="all"))
        assert result["total"] == 3
        sources = {i["source"] for i in result["items"]}
        assert sources == {"internal", "external"}

    def test_source_external_date_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.read_tools import query_hazards

        from datetime import date

        async def _fake_fetch():
            return [
                _ext_view("e1", checked_at=date(2026, 8, 1)),  # 窗口外
                _ext_view("e2", closed=True, desc="标识缺失"),
            ]

        monkeypatch.setattr(
            "app.modules.safety.service.hazard_direct.external_audit.fetch_external_audit",
            _fake_fetch,
        )
        result = asyncio_run(
            query_hazards(_ctx(None), source="external",
                          date_from="2026-10-01", date_to="2026-10-31")
        )
        assert result["total"] == 1
        assert result["items"][0]["description"] == "标识缺失"

    def test_invalid_source_hint(self) -> None:
        from app.modules.safety.business_agent.tools.read_tools import query_hazards

        result = asyncio_run(query_hazards(_ctx(None), source="moon"))
        assert result["success"] is False
        assert "source" in result["error"]


class TestQueryOhMonitors:
    def test_entity_monitors(self) -> None:
        from datetime import UTC, datetime

        from app.modules.safety.business_agent.tools.read_tools import query_oh
        from app.modules.safety.models import OhHazardMonitor

        monitor = OhHazardMonitor(
            monitor_no="JC-2026-001", workplace="车间一", location="包装岗位",
            detection_type="regular", status="completed",
            detection_date=datetime(2026, 9, 15, tzinfo=UTC),
            detection_agency="江苏检测中心", inspector_name="王五",
            detection_results=[{"factor_name": "噪声", "compliance_status": "符合"}],
        )
        # repo 顺序：execute(rows) → scalar(count)；返回形状与其他 entity impl 一致
        db = FakeSession([_FakeResult(rows=[monitor]), _FakeResult(scalar=1)])
        result = asyncio_run(
            query_oh(_ctx(db), entity="monitors", detection_type="regular",
                     keyword="车间")
        )
        assert result["total"] == 1
        item = result["items"][0]
        assert item["monitor_no"] == "JC-2026-001"
        assert item["workplace"] == "车间一"
        assert item["detection_date"].startswith("2026-09-15")
        params = str(db.statements[0].compile().params)
        assert "regular" in params and "车间" in params


class TestEhsChangeBareKeyword:
    def test_bare_change_routes_to_ehs_change(self) -> None:
        decision = tool_selector.route_message("最近有哪些变更")
        assert decision.path == "rule"
        assert "ehs_change" in decision.domains
        assert "query_ehs_changes" in decision.tool_names

    def test_change_question_selects_tool(self) -> None:
        names = tool_selector.select_tool_names("最近有哪些变更")
        assert "query_ehs_changes" in names
