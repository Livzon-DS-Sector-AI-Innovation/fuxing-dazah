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

from app.modules.safety.models import HazardReport, WorkTicketReview
from app.modules.safety.service.overview import (
    _bj_day_start_utc,
    _bj_today,
    build_overview,
    collect_alarms,
    collect_hazards,
    collect_supervision,
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

    async def knowledge_base_s2() -> dict[str, str]:
        return {"status": "ok", "metric": "采集正常 · 近7日+3"}

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

    async def supervision() -> dict[str, Any]:
        return {"latest": {"date": "2026-10-12", "violation_count": 2}}

    async def facility_tasks() -> dict[str, Any]:
        return {"open": 3, "overdue": 1}

    async def facility_tasks_clear() -> dict[str, Any]:
        return {"open": 0, "overdue": 0}

    return {
        "hazards": hazards,
        "special_ops": special_ops,
        "alarms": alarms,
        "certs": certs,
        "chemicals": chemicals,
        "key_risk_ops": key_risk_ops,
        "ehs": ehs,
        "knowledge_base_s2": knowledge_base_s2,
        "digest": digest,
        "supervision": supervision,
        "facility_tasks": facility_tasks,
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
        assert data["facility_tasks"] == {"open": 3, "overdue": 1}  # 2026-10-21 出参
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
        assert wall["knowledge-base"]["metric"] == "采集正常 · 近7日+3"
        # 四新域卡（四期 1-B）：未接入是常态（registry 连接位空）→ inactive·未接入
        assert wall["goals"] == {"key": "goals", "status": "inactive", "metric": "未接入"}
        assert wall["training-behavior"]["metric"] == "未接入"
        # facilities：域卡虽「未接入」（蓝本旧 kind 连接位空），但有在办任务
        # （open=3>0）→ 任务口径覆盖（2026-10-21 修复：不再被 inactive 卡死）
        assert wall["facilities"] == {
            "key": "facilities",
            "status": "warn",
            "metric": "校验待闭环 3 · 逾期 1",
        }
        assert wall["incidents"]["metric"] == "未接入"
        # 监督卡（三期起步）：最近一次审核真实指标，违规>0 → 黄
        assert wall["supervision"] == {
            "key": "supervision",
            "status": "warn",
            "metric": "最近审核 2026-10-12 · 违规 2",
        }
        assert wall["risk-reporting"]["metric"] == "今日通过 3 / 审批中 1"

    async def test_supervision_card_pending_and_degraded_states(self) -> None:
        # 无审核记录 → 灰「待首跑」
        stubs = _stub_collectors()

        async def empty() -> dict[str, Any]:
            return {"latest": None}

        stubs["supervision"] = empty
        data = await build_overview(collectors=stubs)
        wall = {c["key"]: c for c in data["module_health"]}
        assert wall["supervision"] == {
            "key": "supervision",
            "status": "upcoming",
            "metric": "待首跑",
        }

        # 采集异常（单域降级）→ 灰卡无指标
        stubs = _stub_collectors()

        async def boom() -> dict[str, Any]:
            raise RuntimeError("wt down")

        stubs["supervision"] = boom
        data = await build_overview(collectors=stubs)
        wall = {c["key"]: c for c in data["module_health"]}
        assert wall["supervision"] == {
            "key": "supervision",
            "status": "upcoming",
            "metric": None,
        }
        assert data["errors"] == ["supervision: RuntimeError"]

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

    async def test_domain_page_cards_three_states(self) -> None:
        """四新域卡三态（蓝本 §6）：live=ok|warn / 未接入=inactive·未接入 / 降级=inactive·None。"""
        stubs = _stub_collectors()

        async def live_warn() -> dict[str, Any]:
            return {
                "connected": True,
                "health_status": "warn",
                "health_metric": "目标达成 2/4 · 责任书签订率 67% · 年投入 75.0万",
            }

        async def boom() -> dict[str, Any]:
            raise RuntimeError("bitable down")

        stubs["goals"] = live_warn
        stubs["facilities"] = boom
        # 降级灰卡断言须配空任务桩：有在办任务时任务口径会覆盖降级卡
        # （2026-10-21 起 inactive/降级都不再阻塞覆盖）

        async def tasks_clear() -> dict[str, Any]:
            return {"open": 0, "overdue": 0}

        stubs["facility_tasks"] = tasks_clear
        data = await build_overview(collectors=stubs)
        wall = {c["key"]: c for c in data["module_health"]}
        assert len(wall) == 17
        assert wall["goals"] == {
            "key": "goals",
            "status": "warn",
            "metric": "目标达成 2/4 · 责任书签订率 67% · 年投入 75.0万",
        }
        # 采集异常（连接有效但读取失败）→ 降级灰卡无指标 + errors 标注
        assert wall["facilities"] == {"key": "facilities", "status": "inactive", "metric": None}
        # 空任务（open=0）不把未接入卡覆盖成假 ok（facilities-p1 口径）
        async def facility_tasks_clear() -> dict[str, Any]:
            return {"open": 0, "overdue": 0}

        stubs_clear = _stub_collectors()
        stubs_clear["facility_tasks"] = facility_tasks_clear
        data_clear = await build_overview(collectors=stubs_clear)
        wall_clear = {c["key"]: c for c in data_clear["module_health"]}
        assert wall_clear["facilities"]["status"] == "inactive"
        assert "facilities: RuntimeError" in data["errors"]
        # 未 stub 的两域走真采集器 → 未接入（registry 连接位空）
        assert wall["training-behavior"]["metric"] == "未接入"
        assert wall["incidents"]["status"] == "inactive"

    async def test_facility_card_task_override_over_inactive(self) -> None:
        """2026-10-21 修复回归：域卡「未接入」（蓝本旧 kind 连接位空）+
        有在办任务 → 任务口径覆盖为 warn——三台账新 kind 已接入时
        域健康看不见新连接，曾把卡死锁在「未接入」。"""
        stubs = _stub_collectors()  # facilities 未 stub → 真采集 → 未接入
        data = await build_overview(collectors=stubs)
        wall = {c["key"]: c for c in data["module_health"]}
        assert wall["facilities"]["status"] == "warn"
        assert wall["facilities"]["metric"] == "校验待闭环 3 · 逾期 1"

        # 逾期 0 → ok 口径
        async def facility_tasks_soon() -> dict[str, Any]:
            return {"open": 2, "overdue": 0}

        stubs_ok = _stub_collectors()
        stubs_ok["facility_tasks"] = facility_tasks_soon
        wall_ok = {
            c["key"]: c for c in (await build_overview(collectors=stubs_ok))["module_health"]
        }
        assert wall_ok["facilities"]["status"] == "ok"
        assert wall_ok["facilities"]["metric"] == "校验待闭环 2 · 逾期 0"


class TestCollectSupervision:
    async def test_latest_review_by_date(self, db_session: AsyncSession) -> None:
        # 种两条未来日期审核（超出本地库任何真实数据，使「最近」判定确定）→ 取更近日期
        db_session.add(
            WorkTicketReview(date=_bj_today() + timedelta(days=100), violation_count=1)
        )
        db_session.add(
            WorkTicketReview(date=_bj_today() + timedelta(days=101), violation_count=3)
        )
        await db_session.flush()
        latest = await collect_supervision(db_session)
        assert latest == {
            "latest": {
                "date": (_bj_today() + timedelta(days=101)).isoformat(),
                "violation_count": 3,
            }
        }


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
        assert {"training-behavior", "facilities", "incidents"} <= wall_keys
        # 四新域未接入（连接位空是常态），降级而非报错
        wall = {c["key"]: c for c in data["module_health"]}
        assert wall["goals"]["metric"] in ("未接入", None)


class TestDomainPageEndpoints:
    async def test_four_endpoints_not_connected_envelope(self, client: AsyncClient) -> None:
        """四端点冒烟：未接入常态下 200 + 三态信封（真 store 路径）。"""
        for path in ("goals", "training-behavior", "facilities", "incidents"):
            resp = await client.get(f"/api/v1/safety/{path}")
            assert resp.status_code == 200, f"{path}: {resp.text}"
            body = resp.json()
            assert body["code"] == 200
            data = body["data"]
            assert data["status"] in ("not_connected", "degraded")
            if data["status"] == "not_connected":
                assert data["stats"] is None
                assert data["ledger"]["data"] == []
                assert data["ledger"]["meta"] == {"total": 0, "page": 1, "page_size": 20}

    async def test_goals_endpoint_pagination_params(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/safety/goals", params={"page": 2, "page_size": 5})
        assert resp.status_code == 200
        meta = resp.json()["data"]["ledger"]["meta"]
        assert meta == {"total": 0, "page": 2, "page_size": 5}

    async def test_goals_endpoint_rejects_bad_pagination(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/safety/goals", params={"page": 0})
        assert resp.status_code == 422
