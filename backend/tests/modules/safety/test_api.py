"""Safety module — 事故/安全检查/每日风险报备/职业危害因素监测 API 端点测试。

复用顶层 tests/conftest.py 的 client/db_session（真实库 + 回滚）。
契约：统一响应包 {code,message,data,meta}；分页 meta {page,page_size,total}。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient


def _accident_payload(**overrides) -> dict:
    payload = {
        "accident_no": f"ACC-TEST-{uuid.uuid4().hex[:8]}",
        "accident_type": "injury",
        "accident_level": "general",
        "happened_at": datetime.now().isoformat(),
        "location": "车间二",
        "department": "生产部",
        "description": "测试事故描述",
        "reported_at": datetime.now().isoformat(),
    }
    payload.update(overrides)
    return payload


def _check_payload(**overrides) -> dict:
    payload = {
        "check_no": f"CHK-TEST-{uuid.uuid4().hex[:8]}",
        "check_type": "daily",
        "check_date": datetime.now().isoformat(),
        "department": "生产部",
        "location": "车间三",
    }
    payload.update(overrides)
    return payload


def _report_payload(**overrides) -> dict:
    payload = {
        "report_no": f"DRR-TEST-{uuid.uuid4().hex[:8]}",
        "report_date": datetime.now().isoformat(),
        "report_type": "regular",
        "department": "生产部",
        "operation_description": "罐区动火作业",
    }
    payload.update(overrides)
    return payload


def _monitor_payload(**overrides) -> dict:
    payload = {
        "monitor_no": f"OHM-TEST-{uuid.uuid4().hex[:8]}",
        "workplace": "车间一",
        "detection_type": "regular",
    }
    payload.update(overrides)
    return payload


class TestAccidentApi:
    async def test_crud_lifecycle(self, client: AsyncClient) -> None:
        """创建 → 查询列表 → 详情 → 更新 → 删除。"""
        payload = _accident_payload()
        resp = await client.post("/api/v1/safety/accidents", json=payload)
        assert resp.status_code == 200, resp.text
        created = resp.json()["data"]
        assert created["accident_no"] == payload["accident_no"]
        assert created["status"] == "reported"
        accident_id = created["id"]

        resp = await client.get(
            "/api/v1/safety/accidents", params={"keyword": payload["accident_no"]}
        )
        assert resp.status_code == 200
        meta = resp.json()["meta"]
        assert meta["total"] >= 1

        resp = await client.get(f"/api/v1/safety/accidents/{accident_id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == accident_id

        resp = await client.put(
            f"/api/v1/safety/accidents/{accident_id}",
            json={"description": "更新后的描述"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["description"] == "更新后的描述"

        resp = await client.delete(f"/api/v1/safety/accidents/{accident_id}")
        assert resp.status_code == 200
        resp = await client.get(f"/api/v1/safety/accidents/{accident_id}")
        assert resp.json()["code"] == 404

    async def test_state_machine_reported_to_closed(
        self, client: AsyncClient
    ) -> None:
        """reported → investigating → investigated → capa_in_progress → closed。"""
        resp = await client.post("/api/v1/safety/accidents", json=_accident_payload())
        accident_id = resp.json()["data"]["id"]

        resp = await client.post(
            f"/api/v1/safety/accidents/{accident_id}/investigate"
        )
        assert resp.json()["data"]["status"] == "investigating"

        resp = await client.post(
            f"/api/v1/safety/accidents/{accident_id}/resolve",
            params={
                "direct_cause": "违规操作",
                "root_cause": "培训不足",
                "handling_measures": "现场整改",
            },
        )
        assert resp.json()["data"]["status"] == "investigated"

        deadline = (datetime.now() + timedelta(days=7)).isoformat()
        resp = await client.post(
            f"/api/v1/safety/accidents/{accident_id}/start-capa",
            params={
                "corrective_action_deadline": deadline,
                "corrective_action_responsible": "张三",
            },
        )
        data = resp.json()["data"]
        assert data["status"] == "capa_in_progress"
        assert data["corrective_action_status"] == "in_progress"

        resp = await client.post(f"/api/v1/safety/accidents/{accident_id}/verify-capa")
        data = resp.json()["data"]
        assert data["status"] == "closed"
        assert data["corrective_action_status"] == "verified"

    async def test_invalid_transition_rejected(self, client: AsyncClient) -> None:
        """reported 状态不能直接关闭（无CAPA路径要求 investigated）。"""
        resp = await client.post("/api/v1/safety/accidents", json=_accident_payload())
        accident_id = resp.json()["data"]["id"]
        resp = await client.post(f"/api/v1/safety/accidents/{accident_id}/close")
        assert resp.json()["code"] == 400

    async def test_get_missing_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/safety/accidents/{uuid.uuid4()}")
        assert resp.json()["code"] == 404


class TestSafetyCheckApi:
    async def test_crud_and_workflow(self, client: AsyncClient) -> None:
        """创建 → 提交 → 审核 → 删除。"""
        payload = _check_payload()
        resp = await client.post("/api/v1/safety/checks", json=payload)
        assert resp.status_code == 200, resp.text
        created = resp.json()["data"]
        assert created["status"] == "draft"
        assert created["inspector_confirmed"] is False
        check_id = created["id"]

        resp = await client.get(
            "/api/v1/safety/checks", params={"check_type": "daily"}
        )
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] >= 1

        resp = await client.post(f"/api/v1/safety/checks/{check_id}/submit")
        assert resp.json()["data"]["status"] == "submitted"

        resp = await client.post(
            f"/api/v1/safety/checks/{check_id}/review",
            params={"result": "qualified"},
        )
        assert resp.json()["data"]["status"] == "reviewed"

        resp = await client.delete(f"/api/v1/safety/checks/{check_id}")
        assert resp.status_code == 200

    async def test_confirm_endpoints(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/safety/checks", json=_check_payload())
        check_id = resp.json()["data"]["id"]

        resp = await client.post(
            f"/api/v1/safety/checks/{check_id}/confirm",
            json={"role": "inspector"},
        )
        assert resp.json()["data"]["inspector_confirmed"] is True

        resp = await client.post(
            f"/api/v1/safety/checks/{check_id}/confirm",
            json={"role": "safety_officer"},
        )
        assert resp.json()["data"]["safety_officer_confirmed"] is True


class TestDailyRiskReportApi:
    async def test_crud_and_workflow(self, client: AsyncClient) -> None:
        """创建 → 提交 → 审批；驳回分支；删除。"""
        payload = _report_payload()
        resp = await client.post("/api/v1/safety/daily-risk-reports", json=payload)
        assert resp.status_code == 200, resp.text
        created = resp.json()["data"]
        assert created["status"] == "draft"
        assert created["report_type"] == "regular"
        report_id = created["id"]

        resp = await client.get(
            "/api/v1/safety/daily-risk-reports",
            params={"department": "生产部"},
        )
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] >= 1

        resp = await client.post(f"/api/v1/safety/daily-risk-reports/{report_id}/submit")
        assert resp.json()["data"]["status"] == "submitted"

        resp = await client.post(f"/api/v1/safety/daily-risk-reports/{report_id}/approve")
        data = resp.json()["data"]
        assert data["status"] == "approved"
        assert data["approved_at"] is not None

        resp = await client.delete(f"/api/v1/safety/daily-risk-reports/{report_id}")
        assert resp.status_code == 200

    async def test_reject_flow(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/safety/daily-risk-reports", json=_report_payload())
        report_id = resp.json()["data"]["id"]
        await client.post(f"/api/v1/safety/daily-risk-reports/{report_id}/submit")
        resp = await client.post(
            f"/api/v1/safety/daily-risk-reports/{report_id}/reject",
            params={"reason": "措施不足"},
        )
        data = resp.json()["data"]
        assert data["status"] == "rejected"
        assert data["rejection_reason"] == "措施不足"


class TestOhHazardMonitorApi:
    async def test_crud_and_oel_workflow(self, client: AsyncClient) -> None:
        """创建 → 开始 → 完成（自动计算合规）→ 验证 → 删除。"""
        payload = _monitor_payload(
            detection_results=[
                {
                    "factor_name": "噪声",
                    "detection_value": 90,
                    "unit": "dB(A)",
                    "oel_limit": 85,
                    "standard_ref": "GBZ 2.2",
                }
            ]
        )
        resp = await client.post("/api/v1/safety/oh-hazard-monitors", json=payload)
        assert resp.status_code == 200, resp.text
        created = resp.json()["data"]
        assert created["status"] == "draft"
        monitor_id = created["id"]

        resp = await client.get(
            "/api/v1/safety/oh-hazard-monitors", params={"workplace": "车间一"}
        )
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] >= 1

        resp = await client.post(f"/api/v1/safety/oh-hazard-monitors/{monitor_id}/start")
        assert resp.json()["data"]["status"] == "in_progress"

        resp = await client.post(f"/api/v1/safety/oh-hazard-monitors/{monitor_id}/complete")
        data = resp.json()["data"]
        assert data["status"] == "completed"
        # 90/85 > 1.0 → exceeding + 自动生成异常记录
        assert data["detection_results"][0]["compliance_status"] == "exceeding"
        assert len(data["abnormality_records"]) == 1

        resp = await client.post(
            f"/api/v1/safety/oh-hazard-monitors/{monitor_id}/verify",
            json={"verified_by": "李四", "comments": "已确认"},
        )
        assert resp.json()["data"]["status"] == "verified"

        resp = await client.delete(f"/api/v1/safety/oh-hazard-monitors/{monitor_id}")
        assert resp.status_code == 200

    async def test_sub_record_operations(self, client: AsyncClient) -> None:
        """检测结果/异常处置 JSON 子记录增删改。"""
        resp = await client.post("/api/v1/safety/oh-hazard-monitors", json=_monitor_payload())
        monitor_id = resp.json()["data"]["id"]

        resp = await client.post(
            f"/api/v1/safety/oh-hazard-monitors/{monitor_id}/detection-results",
            json={"factor_name": "粉尘", "detection_value": 2, "oel_limit": 8},
        )
        assert resp.status_code == 200

        resp = await client.put(
            f"/api/v1/safety/oh-hazard-monitors/{monitor_id}/detection-results/0",
            json={"detection_value": 3},
        )
        assert resp.json()["data"]["detection_results"][0]["detection_value"] == 3

        resp = await client.post(
            f"/api/v1/safety/oh-hazard-monitors/{monitor_id}/abnormality-records",
            json={"abnormality_desc": "浓度异常", "status": "open"},
        )
        assert resp.status_code == 200

        resp = await client.put(
            f"/api/v1/safety/oh-hazard-monitors/{monitor_id}/abnormality-records/0",
            params={"status": "closed"},
        )
        assert resp.json()["data"]["abnormality_records"][0]["status"] == "closed"

        resp = await client.delete(
            f"/api/v1/safety/oh-hazard-monitors/{monitor_id}/detection-results/0"
        )
        assert resp.json()["data"]["detection_results"] == []
