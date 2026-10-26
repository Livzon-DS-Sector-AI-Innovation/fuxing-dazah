"""QA 偏差管理 API 测试：鉴权、偏差全生命周期、CAPA 守卫、附件。

沿用 test_api_authz 的模式：手工覆盖 get_db / get_current_user 并 patch
权限集合，整条用例共用一个最终回滚的会话。附件存储打到内存，避免落盘。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import time as app_time
from app.core.database import get_db
from app.main import app as fastapi_app
from app.modules.qa import file_service
from app.modules.qa.service import deviation as deviation_service
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory

READ = {"qa:deviation:read", "qa:capa:read"}
WRITE = READ | {
    "qa:deviation:create",
    "qa:deviation:update",
    "qa:capa:create",
    "qa:capa:update",
}

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def _ensure_test_user(session: AsyncSession) -> User:
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="qa偏差测试用户", employee_no="QA-DEV-TEST-001")
    session.add(user)
    await session.flush()
    return user


@asynccontextmanager
async def _client(
    perms: set[str] | None,
) -> AsyncGenerator[tuple[AsyncClient, AsyncSession], None]:
    """perms=None 表示匿名；否则以测试用户登录并授予给定权限码。"""
    async with _test_session_factory() as session:
        user = await _ensure_test_user(session)

        async def _override_get_db() -> Any:
            yield session

        async def _override_user() -> Any:
            return user

        async def _perms(user_id: str, db: object) -> set[str]:
            return set(perms or ())

        fastapi_app.dependency_overrides[get_db] = _override_get_db
        if perms is not None:
            fastapi_app.dependency_overrides[get_current_user] = _override_user
        try:
            with patch("app.platform.permission.deps.get_user_permissions", new=_perms):
                transport = ASGITransport(app=fastapi_app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    yield ac, session
        finally:
            fastapi_app.dependency_overrides.clear()
            await session.rollback()


def _payload(**overrides: Any) -> dict[str, Any]:
    today = app_time.today()
    base: dict[str, Any] = {
        "discovery_date": today.isoformat(),
        "occurrence_date": (today - timedelta(days=1)).isoformat(),
        "department_name": "质量控制部",
        "group_name": "理化组",
        "reporter_name": "李蝶",
        "description": "检验员使用紫外分光光度计前未做波长准确性确认",
        "emergency_measures": "涉及批次批记录备注偏差，暂停放行",
        "items": [
            {
                "category": "finished",
                "name": "盐酸万古霉素（沉淀粉）",
                "batch_no": "HAP2606013EB",
            },
            {
                "category": "in_process",
                "name": "硫酸黏菌素浓缩液",
                "batch_no": "STI2606017",
            },
        ],
    }
    base.update(overrides)
    return base


async def _create(ac: AsyncClient, **overrides: Any) -> dict[str, Any]:
    resp = await ac.post("/api/v1/qa/deviations", json=_payload(**overrides))
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _investigate(ac: AsyncClient, deviation_id: str) -> None:
    resp = await ac.put(
        f"/api/v1/qa/deviations/{deviation_id}",
        json={
            "m1e_personnel": "已培训合格，新增项目首次独立操作",
            "m1e_machine": "校准在有效期内，自检正常",
            "direct_cause": "检验员疏忽忘记波长准确性确认",
            "root_cause": "新增项缺乏提醒机制，记录分散，复核未覆盖",
            "root_cause_category": "method",
            "why_chain": [
                {"question": "为何未执行？", "answer": "首次独立操作疏忽"},
                {"question": "为何会忘？", "answer": "记录分散无视觉提醒"},
            ],
            "extended_investigation": True,
            "extended_result": "红外系统适用性试验记录同样独立，暂未遗漏",
        },
    )
    assert resp.status_code == 200, resp.text


# ───────────────────────── 鉴权 ─────────────────────────


class TestDeviationAuthz:
    async def test_anonymous_rejected(self) -> None:
        """匿名访问偏差台账被拒：偏差含批次与质量事件细节，必须先登录。"""
        async with _client(None) as (ac, _):
            resp = await ac.get("/api/v1/qa/deviations")
        assert resp.status_code == 401

    async def test_no_permission_forbidden(self) -> None:
        """已登录但未授权时偏差与 CAPA 台账都 403，读权限完全显式。"""
        async with _client(set()) as (ac, _):
            assert (await ac.get("/api/v1/qa/deviations")).status_code == 403
            assert (await ac.get("/api/v1/qa/capas")).status_code == 403

    async def test_module_wildcard_read_grants_read_only(self) -> None:
        """模块通配读码 qa:*:read 放行偏差/CAPA 读取，但不放行登记。"""
        async with _client({"qa:*:read"}) as (ac, _):
            assert (await ac.get("/api/v1/qa/deviations")).status_code == 200
            assert (await ac.get("/api/v1/qa/capas")).status_code == 200
            created = await ac.post("/api/v1/qa/deviations", json=_payload())
        assert created.status_code == 403

    async def test_deviation_read_does_not_grant_update(self) -> None:
        """只持读码的用户不能推进偏差状态：读与写是两份独立授权。"""
        async with _client(WRITE) as (ac, _):
            dev = await _create(ac)
        async with _client(READ) as (ac, _):
            # 上面的会话已回滚，这里只验证写端点被拒而非记录存在。
            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev['id']}/transition",
                json={"action": "start_investigation"},
            )
        assert resp.status_code == 403


# ───────────────────────── 偏差生命周期 ─────────────────────────


class TestDeviationLifecycle:
    async def test_create_assigns_number_and_defaults(self) -> None:
        """登记偏差即自动编号（DE+年月+三位流水顺延）并给出合规默认值。

        编号是偏差的唯一追溯标识，期限默认发现日起 30 天，登记人为
        首条日志作者；这些默认值是 SOP 规定的口径，不允许手工绕开。
        """
        async with _client(WRITE) as (ac, _):
            first = await _create(ac)
            second = await _create(ac)
        prefix = f"DE{app_time.today():%y%m}"
        assert first["deviation_no"].startswith(prefix)
        assert len(first["deviation_no"]) == len(prefix) + 3
        assert int(second["deviation_no"][-3:]) == int(first["deviation_no"][-3:]) + 1
        assert first["status"] == "draft"
        assert first["due_date"] == (app_time.today() + timedelta(days=30)).isoformat()
        assert first["days_remaining"] == 30
        assert first["is_overdue"] is False
        assert first["reported_late"] is False
        assert [i["batch_no"] for i in first["items"]] == ["HAP2606013EB", "STI2606017"]
        assert first["logs"][0]["action"] == "create"
        assert first["missing_for_next"] == []

    async def test_late_report_flag(self) -> None:
        """超次日上报的偏差自动打迟报标记，并从剩余天数里扣除迟报天数。"""
        async with _client(WRITE) as (ac, _):
            late = await _create(
                ac,
                discovery_date=(app_time.today() - timedelta(days=5)).isoformat(),
                occurrence_date=None,
            )
        assert late["reported_late"] is True
        assert late["days_remaining"] == 25

    async def test_occurrence_after_discovery_rejected(self) -> None:
        """发生日期晚于发现日期的登记被拒：时间线自相矛盾无法追溯。"""
        async with _client(WRITE) as (ac, _):
            resp = await ac.post(
                "/api/v1/qa/deviations",
                json=_payload(
                    occurrence_date=(app_time.today() + timedelta(days=1)).isoformat()
                ),
            )
        assert resp.status_code == 422

    async def test_full_flow_to_closure(self) -> None:
        """偏差全生命周期：登记→调查→评估→CAPA→关闭→锁定。

        每个阶段推进前校验该阶段必填项（调查结论、分类、CAPA 意向），
        勾选发起 CAPA 但没有 CAPA 记录时禁止关闭；关闭后任何修改与
        延期都被拒绝，保证关闭即定稿。
        """
        async with _client(WRITE) as (ac, _):
            dev = await _create(ac)
            dev_id = dev["id"]

            # 登记 → 调查
            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition",
                json={"action": "start_investigation", "comment": "QA 受理"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["status"] == "investigating"
            assert resp.json()["data"]["investigating_at"] is not None

            # 调查未填写完不能进评估
            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition",
                json={"action": "submit_assessment"},
            )
            assert resp.status_code == 422
            detail = resp.json()
            assert "根本原因" in str(detail)

            await _investigate(ac, dev_id)
            detail_resp = await ac.get(f"/api/v1/qa/deviations/{dev_id}")
            assert detail_resp.json()["data"]["missing_for_next"] == []

            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition",
                json={"action": "submit_assessment"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["status"] == "assessing"

            # 评估未填不能关闭
            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition", json={"action": "close"}
            )
            assert resp.status_code == 422
            assert "偏差分类" in resp.text

            resp = await ac.put(
                f"/api/v1/qa/deviations/{dev_id}",
                json={
                    "quality_impact": "not_affected",
                    "quality_impact_reason": "原样复测偏差≤0.002，仪器未漂移",
                    "classification": "minor",
                    "capa_initiated": True,
                    "items": [
                        {
                            "category": "finished",
                            "name": "盐酸万古霉素（沉淀粉）",
                            "batch_no": "HAP2606013EB",
                            "handling": "原样复测后放行",
                        }
                    ],
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["items"][0]["handling"] == "原样复测后放行"

            # 勾选发起 CAPA 但未建 CAPA 记录 → 拦截
            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition", json={"action": "close"}
            )
            assert resp.status_code == 422
            assert "CAPA" in resp.text

            capa_resp = await ac.post(
                "/api/v1/qa/capas",
                json={
                    "deviation_id": dev_id,
                    "severity": "minor",
                    "summary": "理化组再培训 + 制订紫外仪专用使用记录",
                    "responsible_department_name": "质量控制部",
                    "effect_method": "tracking_month",
                    "actions": [
                        {
                            "content": "全员专项再培训 SOP.03.2284.007",
                            "action_type": "corrective",
                        },
                        {
                            "content": "制订紫外仪使用及清洁保养记录并增加波长确认勾选栏",
                            "action_type": "preventive",
                        },
                    ],
                },
            )
            assert capa_resp.status_code == 201, capa_resp.text
            capa = capa_resp.json()["data"]
            assert capa["capa_no"] == f"CAPA-{dev['deviation_no']}"
            assert capa["status"] == "planned"
            assert len(capa["actions"]) == 2

            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition",
                json={"action": "close", "comment": "质量负责人批准关闭"},
            )
            assert resp.status_code == 200, resp.text
            closed = resp.json()["data"]
            assert closed["status"] == "closed"
            assert closed["closed_at"] is not None
            assert closed["days_remaining"] is None
            assert [c["capa_no"] for c in closed["capas"]] == [capa["capa_no"]]
            assert [log["action"] for log in closed["logs"]] == [
                "create",
                "start_investigation",
                "submit_assessment",
                "close",
            ]

            # 关闭后锁定
            assert (
                await ac.put(f"/api/v1/qa/deviations/{dev_id}", json={"remark": "x"})
            ).status_code == 409
            assert (
                await ac.post(
                    f"/api/v1/qa/deviations/{dev_id}/extend",
                    json={
                        "new_due_date": (
                            app_time.today() + timedelta(days=60)
                        ).isoformat(),
                        "reason": "试试",
                    },
                )
            ).status_code == 409

    async def test_invalid_transition_rejected(self) -> None:
        """不允许跳过调查直接关闭：状态机只接受相邻推进。"""
        async with _client(WRITE) as (ac, _):
            dev = await _create(ac)
            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev['id']}/transition",
                json={"action": "close"},
            )
        assert resp.status_code == 409

    async def test_extend_due_date(self) -> None:
        """延长关闭期限必须给出新日期和理由，且新期限要真正后移。

        延期是受控动作：次数被记录（extension_count）、理由进操作
        日志，原期限不变或提前的请求属于无效延期。
        """
        async with _client(WRITE) as (ac, _):
            dev = await _create(ac)
            too_early = await ac.post(
                f"/api/v1/qa/deviations/{dev['id']}/extend",
                json={"new_due_date": dev["due_date"], "reason": "没变"},
            )
            assert too_early.status_code == 422
            new_due = app_time.today() + timedelta(days=45)
            resp = await ac.post(
                f"/api/v1/qa/deviations/{dev['id']}/extend",
                json={"new_due_date": new_due.isoformat(), "reason": "复测周期长"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
        assert data["due_date"] == new_due.isoformat()
        assert data["extension_count"] == 1
        extend_log = [log for log in data["logs"] if log["action"] == "extend"][0]
        assert "复测周期长" in extend_log["comment"]

    async def test_delete_only_draft(self) -> None:
        """只有登记中的偏差可删除；一经进入调查即不可删，删除后不可见。

        进入流程的偏差已有监管追溯意义，只能推进或关闭，不能抹掉。
        """
        async with _client(WRITE) as (ac, _):
            dev = await _create(ac)
            started = await _create(ac)
            await ac.post(
                f"/api/v1/qa/deviations/{started['id']}/transition",
                json={"action": "start_investigation"},
            )
            assert (
                await ac.delete(f"/api/v1/qa/deviations/{started['id']}")
            ).status_code == 409
            assert (
                await ac.delete(f"/api/v1/qa/deviations/{dev['id']}")
            ).status_code == 200
            assert (
                await ac.get(f"/api/v1/qa/deviations/{dev['id']}")
            ).status_code == 404

    async def test_list_filters_and_summary(self) -> None:
        """台账按关键词（含涉及批号）与状态过滤，并给出状态分布统计。

        按批号检索支撑「这个批次出过哪些偏差」的追溯问法；统计口径
        供管理回顾使用。
        """
        async with _client(WRITE) as (ac, _):
            dev = await _create(ac, reporter_name="唯一关键词甲")
            await ac.post(
                f"/api/v1/qa/deviations/{dev['id']}/transition",
                json={"action": "start_investigation"},
            )
            listed = await ac.get(
                "/api/v1/qa/deviations",
                params={"keyword": "唯一关键词甲", "status": "investigating"},
            )
            assert listed.status_code == 200
            body = listed.json()
            assert body["meta"]["total"] == 1
            assert body["data"][0]["id"] == dev["id"]
            by_batch = await ac.get(
                "/api/v1/qa/deviations", params={"keyword": "HAP2606013EB"}
            )
            assert any(row["id"] == dev["id"] for row in by_batch.json()["data"])
            summary = await ac.get("/api/v1/qa/deviations/summary")
            assert summary.status_code == 200
            assert summary.json()["data"]["investigating"] >= 1

    async def test_repeat_candidates_same_group_and_root_cause(self) -> None:
        """重复偏差候选按「同组+同根因分类」圈定，勾选重复后必须关联编号。

        候选是系统提示，关联哪些历史偏差由人确认；勾选了重复却没给
        出关联编号时禁止关闭——重复偏差统计是管理评审的硬指标。
        """
        async with _client(WRITE) as (ac, _):
            first = await _create(ac)
            second = await _create(
                ac,
                discovery_date=(app_time.today() - timedelta(days=40)).isoformat(),
                occurrence_date=None,
            )
            other_group = await _create(ac, group_name="微生物组")
            for dev in (first, second, other_group):
                await ac.post(
                    f"/api/v1/qa/deviations/{dev['id']}/transition",
                    json={"action": "start_investigation"},
                )
                await _investigate(ac, dev["id"])
            detail = (await ac.get(f"/api/v1/qa/deviations/{first['id']}")).json()[
                "data"
            ]
            candidate_ids = {c["id"] for c in detail["repeat_candidates"]}
            assert second["id"] in candidate_ids
            assert other_group["id"] not in candidate_ids

            # 勾选重复但没关联编号 → 关闭前守卫
            await ac.post(
                f"/api/v1/qa/deviations/{first['id']}/transition",
                json={"action": "submit_assessment"},
            )
            resp = await ac.put(
                f"/api/v1/qa/deviations/{first['id']}",
                json={
                    "quality_impact": "not_affected",
                    "classification": "minor",
                    "capa_initiated": False,
                    "capa_not_initiated_reason": "偶发，已口头提醒",
                    "is_repeat": True,
                },
            )
            assert resp.status_code == 200, resp.text
            blocked = await ac.post(
                f"/api/v1/qa/deviations/{first['id']}/transition",
                json={"action": "close"},
            )
            assert blocked.status_code == 422
            assert "重复偏差" in blocked.text
            resp = await ac.put(
                f"/api/v1/qa/deviations/{first['id']}",
                json={"repeat_deviation_ids": [second["id"]]},
            )
            assert resp.status_code == 200, resp.text
            closed = await ac.post(
                f"/api/v1/qa/deviations/{first['id']}/transition",
                json={"action": "close"},
            )
            assert closed.status_code == 200, closed.text
            assert closed.json()["data"]["repeat_deviation_ids"] == [second["id"]]


# ───────────────────────── 台账过滤 ─────────────────────────


class TestLedgerFilters:
    async def test_deviation_ledger_filters(self) -> None:
        """偏差台账支持分类/根因/部门/超期/发现日期多维过滤，各条件独立成立。

        台账是管理回顾的取数口径：过滤条件错一个就会把统计口径带偏，
        这里让两条特征互补的偏差（如期关闭的 method 根因 minor vs
        已超期调查中的微生物组）互相印证每个过滤维度。
        """
        marker = f"台账过滤{uuid4().hex[:4].upper()}"
        today = app_time.today()
        async with _client(WRITE) as (ac, _):
            closed_dev = await _create(ac, reporter_name=marker, group_name="理化组")
            dev_id = closed_dev["id"]
            await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition",
                json={"action": "start_investigation"},
            )
            await _investigate(ac, dev_id)
            await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition",
                json={"action": "submit_assessment"},
            )
            assessed = await ac.put(
                f"/api/v1/qa/deviations/{dev_id}",
                json={
                    "quality_impact": "not_affected",
                    "quality_impact_reason": "原样复测合格",
                    "classification": "minor",
                    "capa_initiated": False,
                    "capa_not_initiated_reason": "偶发，已口头提醒",
                },
            )
            assert assessed.status_code == 200, assessed.text
            closed = await ac.post(
                f"/api/v1/qa/deviations/{dev_id}/transition",
                json={"action": "close", "comment": "如期关闭"},
            )
            assert closed.status_code == 200, closed.text

            overdue_dev = await _create(
                ac,
                reporter_name=marker,
                department_name="微生物保障部",
                group_name="微生物组",
                discovery_date=(today - timedelta(days=40)).isoformat(),
                occurrence_date=None,
            )
            started = await ac.post(
                f"/api/v1/qa/deviations/{overdue_dev['id']}/transition",
                json={"action": "start_investigation"},
            )
            assert started.status_code == 200, started.text

            async def _ids(**params: Any) -> set[str]:
                params["keyword"] = marker
                listed = await ac.get("/api/v1/qa/deviations", params=params)
                assert listed.status_code == 200
                return {row["id"] for row in listed.json()["data"]}

            assert await _ids(classification="minor") == {dev_id}
            assert await _ids(classification="major") == set()
            assert await _ids(root_cause_category="method") == {dev_id}
            assert await _ids(department_name="微生物保障部") == {overdue_dev["id"]}
            assert await _ids(overdue_only=True) == {overdue_dev["id"]}
            assert await _ids(discovery_to=(today - timedelta(days=1)).isoformat()) == {
                overdue_dev["id"]
            }
            assert await _ids(discovery_from=today.isoformat()) == {dev_id}

    async def test_capa_ledger_filters(self) -> None:
        """CAPA 台账按严重度和关键词过滤，保证管理回顾取数可收敛。"""
        marker = f"CAPA过滤{uuid4().hex[:4].upper()}"
        async with _client(WRITE) as (ac, _):
            dev = await _create(ac, reporter_name=marker)
            dev_id = dev["id"]
            minor = await ac.post(
                "/api/v1/qa/capas",
                json={
                    "deviation_id": dev_id,
                    "severity": "minor",
                    "summary": f"再培训{marker}",
                    "actions": [{"content": "再培训", "action_type": "corrective"}],
                },
            )
            assert minor.status_code == 201, minor.text
            major = await ac.post(
                "/api/v1/qa/capas",
                json={
                    "deviation_id": dev_id,
                    "severity": "major",
                    "summary": f"改造防错{marker}",
                    "actions": [{"content": "加装防错装置", "action_type": "corrective"}],
                },
            )
            assert major.status_code == 201, major.text

            by_keyword = await ac.get("/api/v1/qa/capas", params={"keyword": marker})
            assert by_keyword.status_code == 200
            assert {row["severity"] for row in by_keyword.json()["data"]} == {
                "minor",
                "major",
            }
            major_only = await ac.get(
                "/api/v1/qa/capas",
                params={"keyword": marker, "severity": "major"},
            )
            assert major_only.status_code == 200
            assert [row["severity"] for row in major_only.json()["data"]] == ["major"]


# ───────────────────────── CAPA ─────────────────────────


class TestCapaLifecycle:
    async def _deviation_with_capa(
        self, ac: AsyncClient
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        dev = await _create(ac)
        resp = await ac.post(
            "/api/v1/qa/capas",
            json={
                "deviation_id": dev["id"],
                "severity": "minor",
                "summary": "再培训并修订记录表",
                "effect_method": "tracking_week",
                "actions": [
                    {"content": "再培训", "action_type": "corrective"},
                    {"content": "修订记录表", "action_type": "preventive"},
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        return dev, resp.json()["data"]

    async def test_create_marks_deviation_capa_initiated(self) -> None:
        """对偏差发起 CAPA 后偏差侧自动带上「已发起」标记并互相关联。

        偏差与 CAPA 是双向追溯关系：从偏差能看到全部 CAPA，从 CAPA
        能回到来源偏差。
        """
        async with _client(WRITE) as (ac, _):
            dev, capa = await self._deviation_with_capa(ac)
            detail = (await ac.get(f"/api/v1/qa/deviations/{dev['id']}")).json()["data"]
            assert detail["capa_initiated"] is True
            assert detail["capas"][0]["id"] == capa["id"]
            assert capa["deviation"]["deviation_no"] == dev["deviation_no"]

    async def test_guards_and_closure(self) -> None:
        """CAPA 推进守卫链与关闭定稿：每一步只放行满足条件的动作。

        没有措施不能开始；措施未全部完成不能标记完成；有效性结论为
        无效时禁止关闭并要求追加 CAPA（编号顺延 -2/-3）；结论有效
        关闭后 CAPA 锁定不可再改。完成时按跟踪方式自动推算评估到期日。
        """
        async with _client(WRITE) as (ac, _):
            dev, capa = await self._deviation_with_capa(ac)
            capa_id = capa["id"]

            # 没有措施不能开始
            empty = await ac.post(
                "/api/v1/qa/capas",
                json={
                    "deviation_id": dev["id"],
                    "severity": "major",
                    "summary": "空措施",
                },
            )
            assert empty.status_code == 201
            assert empty.json()["data"]["capa_no"] == f"CAPA-{dev['deviation_no']}-2"
            blocked = await ac.post(
                f"/api/v1/qa/capas/{empty.json()['data']['id']}/transition",
                json={"action": "start"},
            )
            assert blocked.status_code == 422

            resp = await ac.post(
                f"/api/v1/qa/capas/{capa_id}/transition", json={"action": "start"}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["status"] == "in_progress"

            # 措施未全部完成不能标记完成
            resp = await ac.post(
                f"/api/v1/qa/capas/{capa_id}/transition", json={"action": "complete"}
            )
            assert resp.status_code == 422
            assert "未完成" in resp.text

            for action in capa["actions"]:
                patched = await ac.patch(
                    f"/api/v1/qa/capas/{capa_id}/actions/{action['id']}",
                    json={"status": "done", "note": "已完成"},
                )
                assert patched.status_code == 200, patched.text
            detail = (await ac.get(f"/api/v1/qa/capas/{capa_id}")).json()["data"]
            assert all(a["status"] == "done" for a in detail["actions"])
            assert all(
                a["actual_date"] == app_time.today().isoformat()
                for a in detail["actions"]
            )

            resp = await ac.post(
                f"/api/v1/qa/capas/{capa_id}/transition", json={"action": "complete"}
            )
            assert resp.status_code == 200, resp.text
            completed = resp.json()["data"]
            assert completed["status"] == "completed"
            # tracking_week 自动推算有效性评估到期日 = 最晚完成日 + 7 天
            assert (
                completed["effect_due_date"]
                == (app_time.today() + timedelta(days=7)).isoformat()
            )

            resp = await ac.post(
                f"/api/v1/qa/capas/{capa_id}/transition",
                json={"action": "start_evaluation"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["status"] == "effect_evaluating"

            # 未填结论不能关闭
            resp = await ac.post(
                f"/api/v1/qa/capas/{capa_id}/transition", json={"action": "close"}
            )
            assert resp.status_code == 422

            # 结论无效 → 禁止关闭并提示追加 CAPA
            resp = await ac.put(
                f"/api/v1/qa/capas/{capa_id}",
                json={
                    "effect_result": "跟踪期内再次漏做确认",
                    "effect_conclusion": "ineffective",
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["evaluated_at"] is not None
            resp = await ac.post(
                f"/api/v1/qa/capas/{capa_id}/transition", json={"action": "close"}
            )
            assert resp.status_code == 422
            assert "追加" in resp.text

            follow_up = await ac.post(
                "/api/v1/qa/capas",
                json={
                    "deviation_id": dev["id"],
                    "parent_capa_id": capa_id,
                    "severity": "major",
                    "summary": "追加：记录表增加强制勾选项并由复核人签字",
                    "actions": [{"content": "修订复核清单"}],
                },
            )
            assert follow_up.status_code == 201, follow_up.text
            assert (
                follow_up.json()["data"]["capa_no"] == f"CAPA-{dev['deviation_no']}-3"
            )
            assert follow_up.json()["data"]["parent_capa_no"] == capa["capa_no"]

            resp = await ac.put(
                f"/api/v1/qa/capas/{capa_id}",
                json={
                    "effect_result": "复评 1 个月无再发",
                    "effect_conclusion": "effective",
                },
            )
            assert resp.status_code == 200
            resp = await ac.post(
                f"/api/v1/qa/capas/{capa_id}/transition", json={"action": "close"}
            )
            assert resp.status_code == 200, resp.text
            closed = resp.json()["data"]
            assert closed["status"] == "closed"
            assert closed["closed_at"] is not None
            assert [c["capa_no"] for c in closed["follow_up_capas"]] == [
                f"CAPA-{dev['deviation_no']}-3"
            ]
            assert (
                await ac.put(f"/api/v1/qa/capas/{capa_id}", json={"remark": "x"})
            ).status_code == 409

    async def test_parent_must_share_deviation(self) -> None:
        """追加 CAPA 的父级必须是同一偏差下的 CAPA，跨偏差挂接被拒。"""
        async with _client(WRITE) as (ac, _):
            _, capa = await self._deviation_with_capa(ac)
            other = await _create(ac)
            resp = await ac.post(
                "/api/v1/qa/capas",
                json={
                    "deviation_id": other["id"],
                    "parent_capa_id": capa["id"],
                    "severity": "minor",
                    "summary": "错配",
                },
            )
        assert resp.status_code == 422

    async def test_capa_list_includes_deviation_no(self) -> None:
        """CAPA 台账行直接带出偏差编号，并可按偏差过滤与状态统计。"""
        async with _client(WRITE) as (ac, _):
            dev, capa = await self._deviation_with_capa(ac)
            listed = await ac.get(
                "/api/v1/qa/capas", params={"deviation_id": dev["id"]}
            )
            assert listed.status_code == 200
            rows = listed.json()["data"]
            assert rows[0]["capa_no"] == capa["capa_no"]
            assert rows[0]["deviation_no"] == dev["deviation_no"]
            summary = await ac.get("/api/v1/qa/capas/summary")
            assert summary.json()["data"]["planned"] >= 1


# ───────────────────────── 附件 ─────────────────────────


class TestDeviationAttachments:
    @pytest.fixture
    def memory_storage(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
        store: dict[str, bytes] = {}

        def _store(key: str, data: bytes, content_type: str = "") -> str:
            store[key] = data
            return key

        def _read(key: str) -> tuple[bytes, str] | None:
            return (store[key], "application/octet-stream") if key in store else None

        def _delete(key: str) -> None:
            store.pop(key, None)

        monkeypatch.setattr(file_service, "store_object", _store)
        monkeypatch.setattr(file_service, "read_object", _read)
        monkeypatch.setattr(file_service, "delete_file", _delete)
        monkeypatch.setattr(file_service, "cleanup_stored_file", _delete)
        return store

    async def test_upload_download_delete(
        self, memory_storage: dict[str, bytes]
    ) -> None:
        """偏差附件上传→预览→删除闭环，伪装文件被内容校验拦截。

        批记录复印件、COA 等证据必须可上传可回看；扩展名与真实内容
        不符、或 HTML 之类可执行内容不允许入库。
        """
        async with _client(WRITE) as (ac, _):
            dev = await _create(ac)
            upload = await ac.post(
                f"/api/v1/qa/deviations/{dev['id']}/attachments",
                files={"file": ("校验标签.png", PNG_BYTES, "image/png")},
            )
            assert upload.status_code == 201, upload.text
            attachment = upload.json()["data"]
            assert attachment["file_name"] == "校验标签.png"
            assert attachment["mime_type"] == "image/png"
            assert len(memory_storage) == 1

            content = await ac.get(
                f"/api/v1/qa/deviations/{dev['id']}/attachments/{attachment['id']}/content"
            )
            assert content.status_code == 200
            assert content.content == PNG_BYTES
            assert content.headers["content-type"].startswith("image/png")
            assert "inline" in content.headers["content-disposition"]

            bad = await ac.post(
                f"/api/v1/qa/deviations/{dev['id']}/attachments",
                files={"file": ("evil.html", b"<script>", "text/html")},
            )
            assert bad.status_code == 422
            mismatched = await ac.post(
                f"/api/v1/qa/deviations/{dev['id']}/attachments",
                files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
            )
            assert mismatched.status_code == 422

            deleted = await ac.delete(
                f"/api/v1/qa/deviations/{dev['id']}/attachments/{attachment['id']}"
            )
            assert deleted.status_code == 200
            assert memory_storage == {}
            detail = (await ac.get(f"/api/v1/qa/deviations/{dev['id']}")).json()["data"]
            assert detail["attachments"] == []


# ───────────────────────── 纯函数 ─────────────────────────


class TestServiceHelpers:
    def test_validate_attachment_accepts_office_magic(self) -> None:
        """附件校验按魔数识别旧版 Office 二进制（.doc），并清洗路径穿越文件名。"""
        name, ext, mime = deviation_service.validate_attachment(
            "批记录.pdf", "application/pdf", b"%PDF-1.7 ..."
        )
        assert (name, ext, mime) == ("批记录.pdf", "pdf", "application/pdf")
        name, ext, mime = deviation_service.validate_attachment(
            "../x/旧版.doc", None, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8
        )
        assert name == "旧版.doc" and ext == "doc"

    def test_missing_before_lists_sop_required_fields(self) -> None:
        """关闭前的必填项清单按 SOP 口径给出，逐项补齐后清零。

        关闭守卫同时复核调查结论，防止提交评估后又把调查字段清空。
        """
        from app.modules.qa.models import Deviation, DeviationStatus

        deviation = Deviation(
            deviation_no="DE2610001",
            status="assessing",
            discovery_date=date(2026, 10, 1),
            due_date=date(2026, 10, 31),
            description="x",
            why_chain=[],
            repeat_deviation_ids=[],
            is_repeat=False,
        )
        missing = deviation_service._missing_before(deviation, DeviationStatus.CLOSED)
        # 关闭时调查结论也要复核，防止提交评估后再被清空。
        assert missing == [
            "直接原因",
            "根本原因",
            "根本原因分类",
            "5Why 分析",
            "对质量的影响结论",
            "偏差分类",
            "是否发起 CAPA",
        ]
        deviation.direct_cause = "直接原因"
        deviation.root_cause = "根本原因"
        deviation.root_cause_category = "method"
        deviation.why_chain = [{"question": "为什么？", "answer": "因为"}]
        deviation.capa_initiated = False
        deviation.quality_impact = "not_affected"
        deviation.classification = "minor"
        assert deviation_service._missing_before(deviation, DeviationStatus.CLOSED) == [
            "不发起 CAPA 的原因"
        ]
