"""系统配置管理 API 测试（票 03 验收，api_context 接缝）。

契约：总览回显脱敏（明文密钥绝不出现在任何响应/审计 JSON）；
PUT 语义 404/422；写路径审计落库且缓存失效即时生效。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    AiConfigAudit,
    AiScenarioConfigAudit,
    BitableConfigAudit,
    RuntimeConfigAudit,
    SchedulerConfigAudit,
)

AI_MODELS = "/api/v1/warehouse/system-config/ai-models"
AI_SCENARIOS = "/api/v1/warehouse/system-config/ai-scenarios"
RUNTIME = "/api/v1/warehouse/system-config/runtime"
BITABLE = "/api/v1/warehouse/system-config/bitable/connections"
SCHEDULER = "/api/v1/warehouse/system-config/scheduler-tasks"


async def test_list_ai_models_masked(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.get(AI_MODELS)
    assert resp.status_code == 200
    profiles = resp.json()["data"]["profiles"]
    assert {p["profile"] for p in profiles} == {"agent", "agent_backup"}
    body = resp.text
    assert "api_key" in body  # 脱敏字段存在
    assert "sk-" not in body  # 明文密钥绝不回显


async def test_put_model_updates_and_audits(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, db = api_context
    resp = await client.put(f"{AI_MODELS}/agent", json={"temperature": 0.2})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["config"]["temperature"] == 0.2
    assert data["status"] == "db"
    # 审计行（同一会话可见）
    audits = (
        await db.execute(
            select(AiConfigAudit).where(AiConfigAudit.profile == "agent")
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].action == "update"
    assert audits[0].operator_name is not None


async def test_put_model_invalid_value_422(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.put(f"{AI_MODELS}/agent", json={"temperature": 9.9})
    assert resp.status_code == 422
    resp = await client.put(f"{AI_MODELS}/agent", json={"nope": 1})
    assert resp.status_code == 422


async def test_put_model_unknown_profile_404(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.put(f"{AI_MODELS}/nope", json={"temperature": 0.2})
    assert resp.status_code == 404


async def test_put_model_api_key_masked_everywhere(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, db = api_context
    key = "sk-test-secret-1234567890abcdef"
    resp = await client.put(f"{AI_MODELS}/agent_backup", json={"api_key": key})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert key not in resp.text  # 明文不回显
    assert data["api_key_masked"].endswith("cdef")
    audit = (
        await db.execute(select(AiConfigAudit).where(AiConfigAudit.profile == "agent_backup"))
    ).scalars().one()
    serialized = f"{audit.before_json}{audit.after_json}"
    assert key not in serialized  # 审计不落明文
    assert "****cdef" in serialized


async def test_list_ai_scenarios(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.get(AI_SCENARIOS)
    assert resp.status_code == 200
    scenarios = resp.json()["data"]["scenarios"]
    assert {s["scenario"] for s in scenarios} == {"agent_chat", "receipt_recognition"}
    assert all(s["enabled"] is True for s in scenarios)


async def test_put_scenario_disable_and_audits(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, db = api_context
    resp = await client.put(f"{AI_SCENARIOS}/agent_chat", json={"enabled": False})
    assert resp.status_code == 200
    data: dict[str, Any] = resp.json()["data"]
    assert data["enabled"] is False
    assert data["status"] == "disabled"
    audit = (
        await db.execute(
            select(AiScenarioConfigAudit).where(AiScenarioConfigAudit.scenario == "agent_chat")
        )
    ).scalars().one()
    assert audit.action == "disable"


async def test_put_scenario_invalid_binding_422(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.put(
        f"{AI_SCENARIOS}/agent_chat", json={"model_profile": "text"}
    )
    assert resp.status_code == 422
    resp = await client.put(f"{AI_SCENARIOS}/nope", json={"enabled": False})
    assert resp.status_code == 404


async def test_audits_endpoints(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    for path in (f"{AI_MODELS}/audits", f"{AI_SCENARIOS}/audits"):
        resp = await client.get(path)
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"]["audits"], list)


async def test_requires_permission(
    api_context: tuple[AsyncClient, AsyncSession],
    monkeypatch: Any,
) -> None:
    """无 system-config:read 权限 → 403。"""
    from unittest.mock import patch

    import app.platform.permission.deps as perm_deps

    client, _ = api_context

    async def _no_perms(user_id: str, db: object) -> set[str]:
        return set()

    with patch.object(perm_deps, "get_user_permissions", new=_no_perms):
        resp = await client.get(AI_MODELS)
        assert resp.status_code == 403


async def test_runtime_list_and_update(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, db = api_context
    resp = await client.get(RUNTIME)
    assert resp.status_code == 200
    configs = resp.json()["data"]["configs"]
    assert len(configs) == 12  # 既有 11 键 + bitable_env_mode（V3D 环境模式）
    assert {c["source"] for c in configs} <= {"db", "env", "default"}
    # 回写开关/环境模式：共享库 live 值随验收期翻转（C 期交互式验收会把
    # qc_writeback_enabled 临时置 1），API 测试只断言键存在且取值合法；
    # **fail-safe 默认值（0/0/test）的封闭断言在 test_system_config_stores
    # 的 test_fail_safe_switch_defaults**（不依赖 live 值）
    writeback = [c for c in configs if c["key"] == "bitable_writeback_enabled"][0]
    assert writeback["value"] in (0, 1)
    qc_writeback = [c for c in configs if c["key"] == "qc_writeback_enabled"][0]
    assert qc_writeback["value"] in (0, 1)
    qa_target = [c for c in configs if c["key"] == "qa_confirm_target"][0]
    assert isinstance(qa_target["value"], str)
    env_mode = [c for c in configs if c["key"] == "bitable_env_mode"][0]
    assert env_mode["value"] in ("test", "prod")

    resp = await client.put(f"{RUNTIME}/max_turns", json={"value": 15})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["value"] == 15
    assert data["source"] == "db"
    # 审计落库
    audit_count = len(
        (
            await db.execute(
                select(RuntimeConfigAudit).where(RuntimeConfigAudit.key == "max_turns")
            )
        ).scalars().all()
    )
    assert audit_count == 1


async def test_runtime_update_validation(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.put(f"{RUNTIME}/max_turns", json={"value": 999})  # 超 30 上限
    assert resp.status_code == 422
    resp = await client.put(f"{RUNTIME}/max_turns", json={"value": "abc"})
    assert resp.status_code == 422
    resp = await client.put(f"{RUNTIME}/nope", json={"value": 1})
    assert resp.status_code == 404
    resp = await client.put(f"{RUNTIME}/max_turns", json={})
    assert resp.status_code == 422


async def test_runtime_audits_endpoint(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.get(f"{RUNTIME}/audits")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"]["audits"], list)


async def test_bitable_connections_list_and_update(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, db = api_context
    resp = await client.get(BITABLE)
    assert resp.status_code == 200
    connections = resp.json()["data"]["connections"]
    assert len(connections) == 15  # 11 既有 + 分期D 成品侧四表（daily_sales_summary 等）
    assert all(c["base_token"] != "" for c in connections)  # 脱敏后非空（**** 或 未配置）

    resp = await client.put(
        f"{BITABLE}/material_receipt", json={"table_id": "tblOverride01"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["table_id"] == "tblOverride01"
    assert data["table_id_source"] == "db"
    audit = (
        await db.execute(
            select(BitableConfigAudit).where(BitableConfigAudit.table_key == "material_receipt")
        )
    ).scalars().one()
    assert audit.action == "update"


async def test_bitable_unknown_table_404(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.put(f"{BITABLE}/nope", json={"table_id": "tblX"})
    assert resp.status_code == 404


async def test_bitable_audits_endpoint(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.get("/api/v1/warehouse/system-config/bitable/audits")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"]["audits"], list)


async def test_scheduler_tasks_list_and_update(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, db = api_context
    resp = await client.get(SCHEDULER)
    assert resp.status_code == 200
    tasks = resp.json()["data"]["tasks"]
    assert {t["job_name"] for t in tasks} == {
        "system_alert", "draft_expire_stale", "reminder_recover",
    }

    resp = await client.put(f"{SCHEDULER}/draft_expire_stale", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False
    audit = (
        await db.execute(
            select(SchedulerConfigAudit).where(
                SchedulerConfigAudit.job_name == "draft_expire_stale"
            )
        )
    ).scalars().one()
    assert audit.action == "disable"


async def test_scheduler_schedule_validation(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.put(
        f"{SCHEDULER}/draft_expire_stale",
        json={"schedule": {"type": "interval", "seconds": 600}},
    )
    assert resp.status_code == 200
    resp = await client.put(
        f"{SCHEDULER}/draft_expire_stale",
        json={"schedule": {"type": "interval", "seconds": 5}},  # 低于 30 下限
    )
    assert resp.status_code == 422
    resp = await client.put(
        f"{SCHEDULER}/draft_expire_stale",
        json={"schedule": {"type": "bogus"}},
    )
    assert resp.status_code == 422
    resp = await client.put(f"{SCHEDULER}/nope", json={"enabled": False})
    assert resp.status_code == 404


async def test_scheduler_audits_endpoint(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.get(f"{SCHEDULER}/audits")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"]["audits"], list)


async def test_ai_call_audits_list_detail_stats(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    """审计查询三端点：写入一行（同会话回滚）→ 列表命中 → 详情回读 → 统计聚合。"""
    from app.modules.warehouse.ai_audit.models import AiCallAudit

    client, db = api_context
    trace = str(uuid4())
    db.add(AiCallAudit(
        trace_id=trace, scenario="agent_chat", resource="chat",
        model="deepseek-flash", prompt_version="a" * 12,
        input_json={"messages": []}, output_json={"content": "ok"},
        tool_names=[], status="success", input_tokens=10, output_tokens=5,
        latency_ms=123, chat_id="oc_t", user_open_id="ou_t", channel="feishu",
    ))
    await db.flush()

    resp = await client.get(
        "/api/v1/warehouse/ai-audits",
        params={"scenario": "agent_chat", "status": "success", "trace_id": trace},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    row = body["data"][0]
    assert row["trace_id"] == trace
    assert row["input_tokens"] == 10

    audit_id = row["id"]
    resp = await client.get(f"/api/v1/warehouse/ai-audits/{audit_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["output_json"]["content"] == "ok"

    resp = await client.get("/api/v1/warehouse/ai-audits/stats")
    assert resp.status_code == 200
    assert "by_scenario_status" in resp.json()["data"]

    resp = await client.get(f"/api/v1/warehouse/ai-audits/{uuid4()}")
    assert resp.status_code == 404
