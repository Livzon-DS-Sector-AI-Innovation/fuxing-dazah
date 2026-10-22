"""标准核查页聚合服务测试（S1 体系标准符合性核查引擎）。

接缝（用户确认）：build_standard_check_page 为唯一后端接缝——
Bitable 源 opener 注入替身（test_domain_pages 手法）、DB 源 db_session fixture、
判定引擎纯函数已独立钉死。信封三态 + 去重取数 + 分组/汇总 + 年份口径在此验证。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.models.contractors import EmergencyDrillRecord
from app.modules.safety.service.bitable_direct.errors import BitableQueryError
from app.modules.safety.service.standard_check import page as sc_page
from app.modules.safety.service.standard_check.engine import (
    ST_IN_PROGRESS,
    ST_MISSED,
    ST_NO_DATA,
    ST_OK,
)


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


class FakePageClient:
    def __init__(self, items: list[dict[str, Any]], *, boom: bool = False) -> None:
        self._items = items
        self._boom = boom

    async def search_records(self, **kwargs: Any) -> dict[str, Any]:
        if self._boom:
            raise BitableQueryError("Bitable 查询失败: code=1254043")
        return {"items": self._items, "has_more": False, "page_token": None}


def _rec(record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"record_id": record_id, "fields": fields}


def _std(
    record_id: str,
    no: str,
    *,
    element: str = "应急管理",
    metric_key: str | None = "drill.count.comprehensive_or_special",
    period: str = "半年",
    operator: str = "≥",
    target: str = "1",
    unit: str = "次",
    department: list[str] | None = None,
    manual: str | None = None,
    year: str | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "标准编号": no,
        "年度": year or str(_bj_today().year),
        "标准条款": f"{no} 条款文本",
        "依据": "测试依据",
        "要素归属": element,
        "指标键": metric_key,
        "比较符": operator,
        "目标值": target,
        "单位": unit,
        "周期": period,
        "责任部门": department if department is not None else ["安环部"],
        "责任人": None,
        "上次完成日期": None,
        "人工核查结果": manual,
        "备注": None,
    }
    return _rec(record_id, fields)


def _drill_row(drill_type: str, on: date) -> EmergencyDrillRecord:
    return EmergencyDrillRecord(
        drill_type=drill_type, execution_time=on, status="已完成",
        drill_content=f"{drill_type}演练",
    )


class TestNotConnected:
    async def test_default_state(self) -> None:
        """未接入（播种前曾是默认态；2026-10-21 播种后用显式未配置 opener 钉死该分支）。"""
        from app.modules.safety.service.bitable_direct.errors import (
            BitableConfigError as _CfgErr,
        )

        def _unconfigured(domain: str, kind: str):
            raise _CfgErr(f"Bitable 连接未配置或已停用: {domain}/{kind}")

        data = await sc_page.build_standard_check_page(opener=_unconfigured)
        assert data["status"] == "not_connected"
        assert data["summary"] is None
        assert data["groups"] == []
        assert data["errors"] == []


class TestLive:
    async def test_groups_summary_and_verdicts(self, db_session) -> None:
        today = _bj_today()
        db_session.add_all([
            _drill_row("综合应急演练", today - timedelta(days=30)),
            _drill_row("专项应急演练", today - timedelta(days=10)),
        ])
        await db_session.flush()
        items = [
            _std("r1", "D6-01"),  # 演练计数 → 2 ≥1 → ok
            _std("r2", "D6-02", metric_key="drill.count.site_handling"),  # 0 场 → in_progress
            _std("r3", "D1-03", element="目标职责", metric_key=None, manual="已完成"),
            _std("r4", "D1-04", element="目标职责", metric_key=None, manual="未完成"),
            _std("r5", "D2-06", element="制度化管理", metric_key=None, manual=None),  # 待核查
            _std("r6", "D3-05", element="教育培训", metric_key="training.completion_rate"),  # 未注册 → no_data
            _std("r7", "D0-99", element="其他要素", metric_key=None, manual="不适用"),
            _std("r8", "D0-98", year=str(today.year - 1), metric_key=None, manual="已完成"),  # 去年不计
        ]
        data = await sc_page.build_standard_check_page(
            db=db_session, opener=lambda d, k: FakePageClient(items)
        )
        assert data["status"] == "live"
        assert data["errors"] == []

        by_no = {r["no"]: r for g in data["groups"] for r in g["rows"]}
        assert by_no["D6-01"]["status"] == ST_OK
        assert by_no["D6-01"]["actual_display"] == "2次"
        assert by_no["D6-01"]["auto"] is True
        assert by_no["D6-02"]["status"] == ST_IN_PROGRESS
        assert by_no["D6-02"]["residual_days"] > 0
        assert by_no["D1-03"]["status"] == ST_OK
        assert by_no["D1-03"]["auto"] is False
        assert by_no["D1-04"]["status"] == ST_MISSED
        assert by_no["D2-06"]["status"] == ST_IN_PROGRESS
        assert by_no["D3-05"]["status"] == ST_NO_DATA
        assert "r8" not in by_no

        # 分组按八要素固定顺序，未知要素归「其他」兜底组末尾
        elements = [g["element"] for g in data["groups"]]
        assert elements.index("目标职责") < elements.index("制度化管理") < elements.index("应急管理")
        assert elements[-1] == "其他"

        summary = data["summary"]
        assert summary["total"] == 7  # 去年行不计
        assert summary["ok"] == 2
        assert summary["in_progress"] == 2
        assert summary["missed"] == 1
        assert summary["no_data"] == 2  # 未注册 + 不适用
        assert summary["compliance_rate"] == 67  # 2/(2+1)

    async def test_metric_dedup_same_key_period(self, db_session, monkeypatch) -> None:
        """同 metric_key 同周期只取一次数（两张演练标准行共享一次查询）。"""
        from dataclasses import replace

        calls: list[str] = []
        original = sc_page.get_metric

        def spy(key: str):
            metric = original(key)

            async def counting_compute(window, ctx):
                calls.append(f"compute:{key}")
                return await metric.compute(window, ctx)

            return replace(metric, compute=counting_compute)

        monkeypatch.setattr(sc_page, "get_metric", spy)
        items = [
            _std("r1", "D6-01"),
            _std("r2", "D6-01b"),  # 同指标同周期第二行
            _std("r3", "D6-02", metric_key="drill.count.site_handling"),
        ]
        data = await sc_page.build_standard_check_page(
            db=db_session, opener=lambda d, k: FakePageClient(items)
        )
        assert data["status"] == "live"
        assert calls.count("compute:drill.count.comprehensive_or_special") == 1
        assert calls.count("compute:drill.count.site_handling") == 1

    async def test_compliance_rate_none_when_no_judged(self, db_session) -> None:
        items = [_std("r1", "D3-05", metric_key="training.completion_rate")]
        data = await sc_page.build_standard_check_page(
            db=db_session, opener=lambda d, k: FakePageClient(items)
        )
        assert data["summary"]["compliance_rate"] is None


class TestDegraded:
    async def test_query_error(self, db_session) -> None:
        data = await sc_page.build_standard_check_page(
            db=db_session, opener=lambda d, k: FakePageClient([], boom=True)
        )
        assert data["status"] == "degraded"
        assert data["summary"] is None
        assert data["errors"]


class TestGoalsHealth:
    async def test_not_connected(self) -> None:
        from app.modules.safety.service.bitable_direct.errors import (
            BitableConfigError as _CfgErr,
        )

        def _unconfigured(domain: str, kind: str):
            raise _CfgErr(f"Bitable 连接未配置或已停用: {domain}/{kind}")

        part = await sc_page.collect_goals_health(opener=_unconfigured)
        assert part == {"connected": False}

    async def test_live_ok_and_warn(self, db_session) -> None:
        items = [_std("r1", "D6-01")]
        part = await sc_page.collect_goals_health(
            db=db_session, opener=lambda d, k: FakePageClient(items)
        )
        assert part["connected"] is True
        assert part["health_status"] == "ok"  # 演练 0 场=进行中，无未达标
        assert "达标 0/0" in part["health_metric"]

        items_missed = [
            _std("r1", "D1-04", metric_key=None, manual="未完成"),
        ]
        part2 = await sc_page.collect_goals_health(
            db=db_session, opener=lambda d, k: FakePageClient(items_missed)
        )
        assert part2["health_status"] == "warn"
        assert "未达标 1" in part2["health_metric"]


class TestEvidence:
    async def test_evidence_for_auto_row(self, db_session) -> None:
        from datetime import UTC as _UTC
        from app.modules.safety.models.contractors import EmergencyDrillRecord as EDR
        today = _bj_today()
        db_session.add(EDR(drill_type="综合应急演练", execution_time=today - timedelta(days=30),
                           status="已完成", drill_content="罐区综合演练"))
        await db_session.flush()
        items = [_std("r1", "D6-01")]
        data = await sc_page.build_standard_evidence(
            "r1", db=db_session, opener=lambda d, k: FakePageClient(items)
        )
        assert data["status"] == "live"
        assert data["no"] == "D6-01"
        assert data["evidence"][0]["title"] == "罐区综合演练"
        assert data["verdict_status"] == ST_OK

    async def test_evidence_no_data_reason(self, db_session) -> None:
        items = [_std("r9", "D3-05", metric_key="training.completion_rate")]
        data = await sc_page.build_standard_evidence(
            "r9", db=db_session, opener=lambda d, k: FakePageClient(items)
        )
        assert data["status"] == "live"
        assert data["verdict_status"] == ST_NO_DATA
        assert "未注册" in (data["no_data_reason"] or "")
        assert data["evidence"] == []

    async def test_evidence_record_not_found(self, db_session) -> None:
        items = [_std("r1", "D6-01")]
        data = await sc_page.build_standard_evidence(
            "nope", db=db_session, opener=lambda d, k: FakePageClient(items)
        )
        assert data["status"] == "not_found"


class TestFiltersAndDeptSummary:
    async def test_filter_by_element_status_department(self, db_session) -> None:
        items = [
            _std("r1", "D6-01", department=["安环部"]),
            _std("r2", "D6-02", metric_key="drill.count.site_handling", department=["安环部", "生产一部"]),
            _std("r3", "D1-04", element="目标职责", metric_key=None, manual="未完成",
                 department=["生产一部"]),
        ]
        base = dict(db=db_session, opener=lambda d, k: FakePageClient(items))

        by_element = await sc_page.build_standard_check_page(element="目标职责", **base)
        assert [r["no"] for g in by_element["groups"] for r in g["rows"]] == ["D1-04"]

        by_status = await sc_page.build_standard_check_page(status="missed", **base)
        assert [r["no"] for g in by_status["groups"] for r in g["rows"]] == ["D1-04"]

        by_dept = await sc_page.build_standard_check_page(department="生产一部", **base)
        assert {r["no"] for g in by_dept["groups"] for r in g["rows"]} == {"D6-02", "D1-04"}

    async def test_department_summary(self, db_session) -> None:
        """部门汇总：一行多部门计入每个部门（联合责任口径），无部门行归「未指派」。"""
        items = [
            _std("r1", "D6-01", department=["安环部"]),
            _std("r2", "D6-02", metric_key="drill.count.site_handling",
                 department=["安环部", "生产一部"]),
            _std("r3", "D1-04", element="目标职责", metric_key=None, manual="未完成",
                 department=["生产一部"]),
            _std("r4", "D2-06", element="制度化管理", metric_key=None, manual="不适用",
                 department=[]),
        ]
        data = await sc_page.build_standard_check_page(
            db=db_session, opener=lambda d, k: FakePageClient(items)
        )
        dept = {d["name"]: d for d in data["departments"]}
        # 本用例未造演练数据：两条演练标准均「进行中」
        assert dept["安环部"] == {"name": "安环部", "total": 2, "ok": 0,
                                  "in_progress": 2, "missed": 0, "no_data": 0}
        assert dept["生产一部"] == {"name": "生产一部", "total": 2, "ok": 0,
                                    "in_progress": 1, "missed": 1, "no_data": 0}
        assert dept["未指派"] == {"name": "未指派", "total": 1, "ok": 0,
                                  "in_progress": 0, "missed": 0, "no_data": 1}
