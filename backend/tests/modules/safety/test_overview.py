"""总览驾驶舱聚合（GET /safety/overview）单元/端点测试——二期。

接缝（质询 Q5 拍板）：
- build_overview 的 collectors 整体注入桩（聚合编排/降级/健康度墙）；
- 隐患趋势与时点未闭环用真实 DB（db_session 回滚）种数据验证；
- 报警分桶用 monkeypatch 假记录（fire/central 镜像分支）；
- 端点冒烟走 conftest client（空库 + 直读 gate 默认关 → 镜像零值）。
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import HazardReport
from app.modules.safety.service.overview import (
    _bj_day_start_utc,
    _bj_today,
    build_overview,
    collect_alarms,
    collect_hazards,
)

# ── 采集器桩（返回值形状与真实采集器一致，只覆盖健康度用到的字段）──


def _stub_collectors() -> dict[str, Any]:
    async def hazards() -> dict[str, Any]:
        return {
            "unclosed": 12,
            "delta": -3,
            "overdue": 2,
            "trend": {"dates": ["2026-10-11"], "created": [4], "closed": [7]},
        }

    async def special_ops() -> dict[str, Any]:
        return {"today_total": 8, "high": 2}

    async def alarms() -> dict[str, Any]:
        return {
            "today_total": 15,
            "fire_today": 9,
            "central_today": 6,
            "fire_real_today": 1,
            "analysis": {
                "dates": ["2026-10-11"],
                "fire_daily": [9],
                "central_daily": [6],
                "top_fire_types": [{"name": "手动报警", "count": 5}],
            },
        }

    async def certs() -> dict[str, Any]:
        return {
            "within_30d": 9,
            "urgent_or_overdue": 1,
            "items": [
                {
                    "person_name": "张三",
                    "department": "EHS部",
                    "cert_category": "special_op",
                    "deadline": None,
                    "remaining_days": 5,
                },
            ],
        }

    async def chemicals() -> dict[str, Any]:
        return {
            "over_limit": 3,
            "materials": [
                {
                    "material_name": "甲醇",
                    "department": "一车间",
                    "storage_location": "库1",
                    "total_quantity_t": 12.5,
                    "max_limit": 10.0,
                    "unit": "t",
                },
            ],
        }

    async def key_risk_ops() -> dict[str, Any]:
        return {
            "today_approved": 3,
            "in_progress": 1,
            "items": [
                {
                    "start_time": None,
                    "department": "二车间",
                    "operation_content": "受限空间作业",
                    "apply_status": "已通过",
                },
            ],
        }

    async def ehs() -> dict[str, Any]:
        return {"in_progress": 4}

    async def digest() -> dict[str, Any]:
        return {
            "count": 1,
            "cells": [
                {
                    "key": "special_op",
                    "tag_color": "blue",
                    "tag_text": "特殊作业",
                    "title": "特殊作业日报",
                    "stats": "今日 **8** 项",
                    "zone": "",
                    "detail": "明细",
                    "sent_at": "2026-10-12T08:00:00+00:00",
                },
            ],
        }

    return {
        "hazards": hazards,
        "special_ops": special_ops,
        "alarms": alarms,
        "certs": certs,
        "chemicals": chemicals,
        "key_risk_ops": key_risk_ops,
        "ehs": ehs,
        "digest": digest,
    }


class TestBuildOverview:
    async def test_aggregates_all_domains_and_health_wall(self) -> None:
        data = await build_overview(collectors=_stub_collectors())
        assert data["hazards"]["unclosed"] == 12
        assert data["special_ops"]["high"] == 2
        assert data["alarms"]["fire_real_today"] == 1
        assert data["certs"]["within_30d"] == 9
        assert data["chemicals"]["over_limit"] == 3
        assert data["key_risk_ops"]["today_approved"] == 3
        assert data["ehs"]["in_progress"] == 4
        assert data["digest"]["count"] == 1
        assert data["errors"] == []

        wall = {c["key"]: c for c in data["module_health"]}
        assert len(wall) == 17  # 17 个体系模块全覆盖
        # 黄预警规则（overdue/高险/真报/超储/紧急到期 > 0）
        assert wall["hazard-ledger"]["status"] == "warn"
        assert wall["special-ops"]["status"] == "warn"
        assert wall["alarms"]["status"] == "warn"
        assert wall["cert-warnings"]["status"] == "warn"
        assert wall["chemicals"]["status"] == "warn"
        # 运行中绿卡与灰卡
        assert wall["knowledge-base"]["metric"] == "运行中"
        assert wall["goals"]["status"] == "inactive"
        assert wall["supervision"] == {
            "key": "supervision",
            "status": "upcoming",
            "metric": "未上线",
        }
        assert wall["risk-reporting"]["metric"] == "今日通过 3 / 审批中 1"

    async def test_single_domain_failure_degrades_not_fatal(self) -> None:
        stubs = _stub_collectors()

        async def boom() -> dict[str, Any]:
            raise RuntimeError("bitable down")

        stubs["certs"] = boom
        data = await build_overview(collectors=stubs)
        assert data["certs"] is None
        assert data["errors"] == ["certs: RuntimeError"]
        assert data["hazards"]["unclosed"] == 12  # 其余域不受影响
        # 证书卡降级为无指标，健康度墙仍 17 张
        wall = {c["key"]: c for c in data["module_health"]}
        assert len(wall) == 17
        assert wall["cert-warnings"]["metric"] is None


class TestCollectHazards:
    async def test_trend_buckets_and_delta(self, db_session: AsyncSession) -> None:
        today = _bj_today()
        y0 = _bj_day_start_utc(today)
        db = db_session

        async def add(
            no: str,
            discovered_off: timedelta,
            *,
            closed_off: timedelta | None = None,
        ) -> None:
            db.add(
                HazardReport(
                    hazard_no=f"HZ-TEST-{no}",
                    hazard_type="unsafe_condition",
                    hazard_level="general",
                    description="overview 测试",
                    discovered_at=y0 + discovered_off,
                    rectification_status="closed" if closed_off else "pending",
                    actual_completion_date=(y0 + closed_off if closed_off else None),
                )
            )

        await add("A", timedelta(days=-3))  # 3 天前新增，未闭环
        await add(
            "B", timedelta(days=-2), closed_off=timedelta(hours=-12)
        )  # 昨日午间闭环
        await add("E", timedelta(hours=-15))  # 昨日 09:00 新增，未闭环
        await add("D", timedelta(hours=9))  # 今日 09:00 新增，未闭环
        await db.flush()

        data = await collect_hazards(db)

        # 未闭环 = total - closed = 3；时点未闭环（昨日零点）= A、B = 2 → delta +1
        assert data["unclosed"] == 3
        assert data["delta"] == 1

        dates = data["trend"]["dates"]
        assert len(dates) == 30 and dates[-1] == today.isoformat()
        created = dict(zip(dates, data["trend"]["created"], strict=True))
        closed = dict(zip(dates, data["trend"]["closed"], strict=True))
        assert created[today.isoformat()] == 1
        assert created[(today - timedelta(days=1)).isoformat()] == 1
        assert created[(today - timedelta(days=2)).isoformat()] == 1
        assert created[(today - timedelta(days=3)).isoformat()] == 1
        assert closed[(today - timedelta(days=1)).isoformat()] == 1


class TestCollectAlarms:
    async def test_bucketing_real_alarm_and_top_types(
        self,
        db_session: AsyncSession,
        monkeypatch: Any,
    ) -> None:
        from app.modules.safety.service.central_alarm.service import (
            CentralAlarmService,
        )
        from app.modules.safety.service.fire_alarm.service import FireAlarmService

        today = _bj_today()
        t0 = _bj_day_start_utc(today)

        async def fake_fire_week(self: Any, ws: Any, we: Any) -> list[Any]:
            return [
                SimpleNamespace(
                    alarm_time=t0 + timedelta(hours=1),
                    alarm_type="手动报警",
                    alarm_nature="真实报警",
                ),
                SimpleNamespace(
                    alarm_time=t0 + timedelta(hours=2),
                    alarm_type="探测器报警",
                    alarm_nature="误报",
                ),
                SimpleNamespace(  # 昨日两条
                    alarm_time=t0 - timedelta(hours=10),
                    alarm_type="手动报警",
                    alarm_nature="误报",
                ),
                SimpleNamespace(
                    alarm_time=t0 - timedelta(hours=11),
                    alarm_type="手动报警",
                    alarm_nature="误报",
                ),
                SimpleNamespace(alarm_time=None, alarm_type=None, alarm_nature=None),
            ]

        async def fake_central_week(self: Any, ws: Any, we: Any) -> list[Any]:
            return [
                SimpleNamespace(alarm_date=t0 + timedelta(hours=3)),
                SimpleNamespace(alarm_date=t0 - timedelta(hours=1)),  # 昨日
            ]

        monkeypatch.setattr(FireAlarmService, "get_week_records", fake_fire_week)
        monkeypatch.setattr(CentralAlarmService, "get_week_records", fake_central_week)

        data = await collect_alarms(db_session)
        assert data["fire_today"] == 2
        assert data["central_today"] == 1
        assert data["today_total"] == 3
        assert data["fire_real_today"] == 1

        analysis = data["analysis"]
        assert len(analysis["dates"]) == 7  # 滚动近 7 天
        assert analysis["dates"][-1] == today.isoformat()
        fire_daily = dict(zip(analysis["dates"], analysis["fire_daily"], strict=True))
        assert fire_daily[today.isoformat()] == 2
        assert fire_daily[(today - timedelta(days=1)).isoformat()] == 2
        top = analysis["top_fire_types"]
        assert top[0] == {"name": "手动报警", "count": 3}
        assert top[1] == {"name": "探测器报警", "count": 1}


class TestOverviewEndpoint:
    async def test_endpoint_smoke_structure(self, client: AsyncClient) -> None:
        """端点冒烟：200 + 全结构键 + 健康度墙 17 卡。

        采集器自开 session 连本地库（仓库测试范式即真实库），不断言具体数值；
        单域失败允许降级（errors 标注 / 该域 None），整页必须 200。
        """
        resp = await client.get("/api/v1/safety/overview")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        for key in (
            "date",
            "generated_at",
            "hazards",
            "special_ops",
            "alarms",
            "certs",
            "chemicals",
            "key_risk_ops",
            "ehs",
            "digest",
            "module_health",
            "errors",
        ):
            assert key in data
        assert len(data["module_health"]) == 17
        assert isinstance(data["errors"], list)
        # 健康度墙的 key 与前端菜单约定（抽样校验）
        wall_keys = {c["key"] for c in data["module_health"]}
        assert {"goals", "supervision", "hazard-ledger", "chemicals"} <= wall_keys
