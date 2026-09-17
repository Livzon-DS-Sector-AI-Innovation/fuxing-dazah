"""推送任务管理 API 测试（V3.0 分期A Ticket 02，api_context 接缝）。

契约：总览合并视图；PUT 语义 404/422 + 审计落库；手动触发绕过到期判断、
dry_run 演练不真发；推送日志分页可查。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.ai_audit import failure_notifier
from app.modules.warehouse.models import (
    WarehousePushLog,
    WarehousePushTaskAudit,
)
from app.modules.warehouse.push_center import engine
from app.modules.warehouse.push_center.store import PushConfigStore, push_store

PUSH_TASKS = "/api/v1/warehouse/system-config/push-tasks"
PUSH_LOGS = "/api/v1/warehouse/system-config/push-logs"


@dataclass
class StubPushRow:
    task_name: str
    enabled: bool = True
    schedule: dict[str, Any] | None = None
    targets: str | None = None
    note: str | None = None
    is_deleted: bool = False


@pytest.fixture(autouse=True)
def _fresh_push_store_cache() -> None:
    """隔离单例缓存（PUT 会失效缓存，测试间不串状态）。"""
    push_store.invalidate()
    yield
    push_store.invalidate()


async def test_list_push_tasks(api_context: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = api_context
    resp = await client.get(PUSH_TASKS)
    assert resp.status_code == 200
    tasks = resp.json()["data"]["tasks"]
    assert len(tasks) == 5
    by_name = {t["task_name"]: t for t in tasks}
    assert by_name["morning_report"]["trigger"] == "scheduled"
    assert by_name["morning_report"]["schedule"] == {"type": "daily", "time": "08:00"}
    assert by_name["express_notify"]["trigger"] == "event"
    assert by_name["express_notify"]["schedule"] is None


async def test_put_push_task_updates_and_audits(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, db = api_context
    resp = await client.put(
        f"{PUSH_TASKS}/morning_report", json={"targets": "oc_x", "note": "验收配置"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert list(data["targets"]) == ["oc_x"]
    assert data["enabled"] is True

    audits = (
        await db.execute(
            select(WarehousePushTaskAudit).where(
                WarehousePushTaskAudit.task_name == "morning_report"
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].action == "update"
    assert audits[0].operator_name is not None
    assert audits[0].after_json is not None and audits[0].after_json["targets"] == "oc_x"


async def test_put_push_task_unknown_404(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.put(f"{PUSH_TASKS}/nope", json={"targets": "oc_x"})
    assert resp.status_code == 404


async def test_put_push_task_bad_schedule_422(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.put(
        f"{PUSH_TASKS}/morning_report", json={"schedule": {"type": "cron", "expr": "* * * * *"}}
    )
    assert resp.status_code == 422
    resp = await client.put(f"{PUSH_TASKS}/morning_report", json={"nope": 1})
    assert resp.status_code == 422


async def test_trigger_push_task_executes(
    api_context: tuple[AsyncClient, AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = api_context
    rows = {
        "morning_report": StubPushRow(task_name="morning_report", targets="oc_test"),
    }
    monkeypatch.setattr(
        engine, "push_store", PushConfigStore(row_loader=lambda name: rows.get(name))
    )
    monkeypatch.setattr(failure_notifier, "fire_notify_failure", lambda **kw: None)

    resp = await client.post(f"{PUSH_TASKS}/morning_report/trigger", json={"dry_run": True})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "executed"
    assert data["task_name"] == "morning_report"

    logs = (
        await db.execute(
            select(WarehousePushLog).where(WarehousePushLog.task_name == "morning_report")
        )
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].trigger == "manual"
    assert logs[0].message_id == "dry_run"

    # 推送日志端点可见（分页 + 过滤）
    resp = await client.get(PUSH_LOGS, params={"task_name": "morning_report"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 1
    entries = [e for e in body["data"] if e["task_name"] == "morning_report"]
    assert entries and entries[0]["trigger"] == "manual"


async def test_trigger_push_task_unknown_404(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.post(f"{PUSH_TASKS}/nope/trigger", json={"dry_run": True})
    assert resp.status_code == 404


async def test_trigger_event_task_not_scheduled(
    api_context: tuple[AsyncClient, AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """事件型任务（快递通知）不支持定时手动触发，返回可读状态而非报错。"""
    client, _ = api_context
    rows = {"express_notify": StubPushRow(task_name="express_notify", targets="oc_test")}
    monkeypatch.setattr(
        engine, "push_store", PushConfigStore(row_loader=lambda name: rows.get(name))
    )
    resp = await client.post(f"{PUSH_TASKS}/express_notify/trigger", json={"dry_run": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "skipped_not_scheduled"


async def test_push_task_audits_endpoint(
    api_context: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = api_context
    resp = await client.get(f"{PUSH_TASKS}/audits")
    assert resp.status_code == 200
    assert "audits" in resp.json()["data"]
