"""职称评审 API 测试（v2）：活动/评审组 CRUD、状态流转、权限隔离。"""

import uuid
from unittest.mock import patch

from httpx import AsyncClient


def _rand(prefix: str = "") -> str:
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}{suffix}"


def _activity_payload(**overrides) -> dict:
    payload = {"name": f"测试活动{_rand()}"}
    payload.update(overrides)
    return payload


class TestActivityApi:
    async def test_create_and_get(self, client: AsyncClient):
        resp = await client.post("/api/v1/hr/title/activities", json=_activity_payload())
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "draft"
        activity_id = data["id"]

        detail = await client.get(f"/api/v1/hr/title/activities/{activity_id}")
        assert detail.status_code == 200
        body = detail.json()["data"]
        assert len(body["levels"]) == 10  # 制度 10 档（技术5+技能5，技术助理已取消）
        assert len(body["dimensions"]) == 7

    async def test_list(self, client: AsyncClient):
        await client.post("/api/v1/hr/title/activities", json=_activity_payload())
        resp = await client.get("/api/v1/hr/title/activities")
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] >= 1

    async def test_open_requires_tables(self, client: AsyncClient):
        resp = await client.post("/api/v1/hr/title/activities", json=_activity_payload())
        activity_id = resp.json()["data"]["id"]
        r = await client.post(f"/api/v1/hr/title/activities/{activity_id}/open")
        assert r.status_code == 400

    async def test_open_review_close_flow(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/hr/title/activities",
            json=_activity_payload(
                feishu_app_token="app1", apply_table_id="tbl1", vote_table_id="tbl2"
            ),
        )
        activity_id = resp.json()["data"]["id"]
        r = await client.post(f"/api/v1/hr/title/activities/{activity_id}/open")
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "open"
        r = await client.post(f"/api/v1/hr/title/activities/{activity_id}/review")
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "reviewing"
        r = await client.post(f"/api/v1/hr/title/activities/{activity_id}/close")
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "closed"

    async def test_delete_draft(self, client: AsyncClient):
        resp = await client.post("/api/v1/hr/title/activities", json=_activity_payload())
        activity_id = resp.json()["data"]["id"]
        assert (await client.delete(f"/api/v1/hr/title/activities/{activity_id}")).status_code == 200
        assert (await client.get(f"/api/v1/hr/title/activities/{activity_id}")).status_code == 404


class TestCommitteeApi:
    async def test_upsert_and_list(self, client: AsyncClient):
        payload = {
            "department": f"部门{_rand()}",
            "manager_name": "负责人A",
            "leader_name": "领导B",
            "committee_members": [],
        }
        r = await client.post("/api/v1/hr/title/committees", json=payload)
        assert r.status_code == 200
        r = await client.get("/api/v1/hr/title/committees")
        assert r.status_code == 200
        departments = [c["department"] for c in r.json()["data"]]
        assert payload["department"] in departments


class TestPermission:
    async def test_permission_denied(self, client: AsyncClient):
        async def _limited_perms(user_id: str, db: object) -> set[str]:
            return {"hr:profile:read"}  # 无 hr:title 权限

        with patch(
            "app.platform.permission.deps.get_user_permissions",
            new=_limited_perms,
        ):
            resp = await client.get("/api/v1/hr/title/activities")
            assert resp.status_code == 403
            resp = await client.post("/api/v1/hr/title/activities", json=_activity_payload())
            assert resp.status_code == 403

    async def test_results_require_scores_read(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/hr/title/activities",
            json=_activity_payload(
                feishu_app_token="app1", apply_table_id="tbl1", vote_table_id="tbl2"
            ),
        )
        activity_id = resp.json()["data"]["id"]

        async def _no_scores_perm(user_id: str, db: object) -> set[str]:
            return {"hr:title:read", "hr:title:manage"}  # 无 scores:read

        with patch(
            "app.platform.permission.deps.get_user_permissions",
            new=_no_scores_perm,
        ):
            resp = await client.get(f"/api/v1/hr/title/activities/{activity_id}/results")
            assert resp.status_code == 403
