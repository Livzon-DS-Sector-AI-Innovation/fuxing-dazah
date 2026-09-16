"""预警规则 CRUD 测试（分期B Ticket 01）。"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def test_list_rules_returns_defaults(auth_client: AsyncClient) -> None:
    resp = await auth_client.get("/api/v1/warehouse/intelligence/rules")
    assert resp.status_code == 200
    rules = {item["rule_key"]: item for item in resp.json()["data"]}
    assert set(rules) >= {"low_stock", "zero_stock", "idle", "expiry", "cover_days"}
    assert rules["idle"]["threshold"] == {"days": 90}
    assert rules["expiry"]["threshold"] == {"days": 30}
    assert rules["cover_days"]["threshold"] == {"days": 14}


async def test_update_rule_threshold_writes_audit(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await auth_client.put(
        "/api/v1/warehouse/intelligence/rules/idle",
        json={"threshold": {"days": 60}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["threshold"] == {"days": 60}

    # 审计走 API（client 会话未提交，跨会话查库不可见）
    audits = await auth_client.get("/api/v1/warehouse/intelligence/rules/idle/audits")
    assert audits.status_code == 200
    items = audits.json()["data"]
    assert any(a["action"] == "update" for a in items)

    # 恢复默认，避免影响其他用例
    await auth_client.put(
        "/api/v1/warehouse/intelligence/rules/idle",
        json={"threshold": {"days": 90}},
    )


async def test_update_rule_enable_toggles_audit(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await auth_client.put(
        "/api/v1/warehouse/intelligence/rules/expiry",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False

    audits = await auth_client.get("/api/v1/warehouse/intelligence/rules/expiry/audits")
    assert audits.status_code == 200
    assert any(a["action"] == "disable" for a in audits.json()["data"])

    # 恢复
    await auth_client.put(
        "/api/v1/warehouse/intelligence/rules/expiry",
        json={"enabled": True},
    )


async def test_update_unknown_rule_rejected(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(
        "/api/v1/warehouse/intelligence/rules/not_exist",
        json={"threshold": {"days": 1}},
    )
    assert resp.status_code in (404, 422)


async def test_rules_require_permission(
    auth_client: AsyncClient, monkeypatch
) -> None:
    from app.platform.permission import deps as permission_deps

    async def _limited(user_id: str, db: AsyncSession) -> set[str]:
        return {"warehouse:stock:read"}

    monkeypatch.setattr(permission_deps, "get_user_permissions", _limited)
    resp = await auth_client.get("/api/v1/warehouse/intelligence/rules")
    assert resp.status_code == 403
