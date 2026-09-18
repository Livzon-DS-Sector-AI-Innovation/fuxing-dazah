"""通用业务确认门测试（V3.0 分期A Ticket 05）。

接缝：服务函数级——状态机/回写/重发/清扫直接调 confirm_request 服务
（monkeypatch adapter.update_record 断言回写契约）；API 走 api_context
薄契约；网关分发 monkeypatch gateway._db_session 复用 db_session。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import confirm_request as cr
from app.modules.warehouse.agent import gateway
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseConfirmAudit,
    WarehouseConfirmRequest,
)

CONFIRM_API = "/api/v1/warehouse/system-config/confirm-requests"


async def _make_request(
    db: AsyncSession,
    *,
    status: str = "pending",
    expires_at: datetime | None = None,
    ref_record_ids: list[str] | None = None,
    writeback: dict[str, Any] | None = None,
) -> WarehouseConfirmRequest:
    request = await cr.create_request(
        db,
        business_type="unqualified_disposition",
        title="不合格物料处理确认",
        summary="以下 2 条不合格物料确认已跟进处理",
        ref_table="unqualified_stock",
        ref_record_ids=ref_record_ids or ["rec1", "rec2"],
        target="oc_test_group",
        payload={"total": 2},
        writeback=writeback if writeback is not None else {"处理日期": "2026-09-17"},
        ttl_seconds=3600,
    )
    if status != "pending":
        request.status = status
        await db.flush()
    if expires_at is not None:
        request.expires_at = expires_at
        await db.flush()
    return request


def _value(request: WarehouseConfirmRequest, action: str) -> dict[str, Any]:
    return {"scene": cr.CONFIRM_GATE_SCENE, "request_id": str(request.id), "action": action}


@pytest.fixture(autouse=True)
def _writeback_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认开启回写（生产默认关；确认动作依赖回写）。

    关闭路径由 test_confirm_rejected_when_writeback_disabled 显式覆盖。
    """
    from app.modules.warehouse import base_mirror

    monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: True)


async def _audits_of(db: AsyncSession, request_no: str) -> list[str]:
    rows = (
        await db.execute(
            select(WarehouseConfirmAudit.action).where(
                WarehouseConfirmAudit.request_no == request_no
            )
        )
    ).scalars().all()
    return list(rows)


# ═══════════════════════════════════════════════════════════════
# 创建与卡片
# ═══════════════════════════════════════════════════════════════


class TestCreateAndCard:
    async def test_create_request_pending_with_audit(self, db_session: AsyncSession) -> None:
        request = await _make_request(db_session)
        assert request.status == "pending"
        assert request.request_no.startswith("CR-")
        assert request.expires_at > datetime.now(UTC)
        assert "create" in await _audits_of(db_session, request.request_no)

    async def test_card_structure_and_button_value(self, db_session: AsyncSession) -> None:
        request = await _make_request(db_session)
        card = cr.build_request_card(request)
        assert card["schema"] == "2.0"
        assert card["header"]["title"]["content"] == request.title
        buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
        assert len(buttons) == 2
        values = [b["value"] for b in buttons]
        assert all(v["scene"] == cr.CONFIRM_GATE_SCENE for v in values)
        assert all(v["request_id"] == str(request.id) for v in values)
        assert {v["action"] for v in values} == {"confirm", "cancel"}

    async def test_send_request_card_records_message_id(
        self, db_session: AsyncSession
    ) -> None:
        request = await _make_request(db_session)
        assert await cr.send_request_card(request, dry_run=True) is True
        assert request.card_message_id == notification.DRY_RUN_MESSAGE_ID


# ═══════════════════════════════════════════════════════════════
# 状态机
# ═══════════════════════════════════════════════════════════════


class TestStateMachine:
    async def test_invalid_request_id(self, db_session: AsyncSession) -> None:
        outcome = await cr.handle_action(
            db_session,
            value={"scene": cr.CONFIRM_GATE_SCENE, "request_id": "not-a-uuid", "action": "confirm"},
            operator_open_id="ou_op",
        )
        assert outcome.ok is False and outcome.status == "invalid"

    async def test_missing_request_rejected(self, db_session: AsyncSession) -> None:
        outcome = await cr.handle_action(
            db_session,
            value=_value(type("R", (), {"id": uuid.uuid4()})(), "confirm"),
            operator_open_id="ou_op",
        )
        assert outcome.ok is False and outcome.status == "invalid"

    async def test_confirmed_rejects_repeat_click(self, db_session: AsyncSession) -> None:
        request = await _make_request(db_session, status="confirmed")
        outcome = await cr.handle_action(
            db_session, value=_value(request, "confirm"), operator_open_id="ou_op"
        )
        assert outcome.ok is False and outcome.status == "invalid"
        assert "已被处理" in outcome.message

    async def test_expired_moves_to_expired(self, db_session: AsyncSession) -> None:
        request = await _make_request(
            db_session, expires_at=datetime.now(UTC) - timedelta(seconds=10)
        )
        outcome = await cr.handle_action(
            db_session, value=_value(request, "confirm"), operator_open_id="ou_op"
        )
        assert outcome.ok is False and outcome.status == "expired"
        assert request.status == "expired"
        assert "expire" in await _audits_of(db_session, request.request_no)

    async def test_cancel_records_without_writeback(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update_mock = AsyncMock()
        monkeypatch.setattr(WarehouseBitableAdapter, "update_record", update_mock)
        request = await _make_request(db_session)
        outcome = await cr.handle_action(
            db_session, value=_value(request, "cancel"), operator_open_id="ou_op"
        )
        assert outcome.ok is True and outcome.status == "cancelled"
        assert request.status == "cancelled"
        update_mock.assert_not_awaited()
        assert "cancel" in await _audits_of(db_session, request.request_no)

    async def test_confirm_execute_false_only_sets_status(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update_mock = AsyncMock()
        monkeypatch.setattr(WarehouseBitableAdapter, "update_record", update_mock)
        request = await _make_request(db_session)
        outcome = await cr.handle_action(
            db_session, value=_value(request, "confirm"), operator_open_id="ou_op", execute=False
        )
        assert outcome.ok is True and outcome.status == "confirmed"
        assert request.status == "confirmed"
        assert request.confirmed_by == "ou_op"
        assert request.confirmed_at is not None
        update_mock.assert_not_awaited()  # 回写留给后台任务

    async def test_unknown_action_rejected(self, db_session: AsyncSession) -> None:
        request = await _make_request(db_session)
        outcome = await cr.handle_action(
            db_session, value=_value(request, "hack"), operator_open_id="ou_op"
        )
        assert outcome.ok is False and outcome.status == "invalid"

    async def test_confirm_rejected_when_writeback_disabled(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回写开关关闭（生产默认）：确认拒绝、保持 pending；取消不受影响。"""
        from app.modules.warehouse import base_mirror

        monkeypatch.setattr(base_mirror, "bitable_writeback_enabled", lambda: False)
        request = await _make_request(db_session)

        outcome = await cr.handle_action(
            db_session, value=_value(request, "confirm"), operator_open_id="ou_op"
        )
        assert outcome.ok is False and outcome.status == "error"
        assert "停用" in outcome.message
        assert request.status == "pending"  # 未确认，可待开启后重试
        assert request.confirmed_by is None

        # 取消路径不受开关影响
        outcome = await cr.handle_action(
            db_session, value=_value(request, "cancel"), operator_open_id="ou_op"
        )
        assert outcome.ok is True and outcome.status == "cancelled"


# ═══════════════════════════════════════════════════════════════
# 回写
# ═══════════════════════════════════════════════════════════════


class TestWriteback:
    async def test_writeback_updates_each_record(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update_mock = AsyncMock(return_value={"record_id": "r", "fields": {}})
        monkeypatch.setattr(WarehouseBitableAdapter, "update_record", update_mock)
        # 真实流程：handle_action 置 confirmed 后才执行回写
        request = await _make_request(db_session)
        outcome = await cr.handle_action(
            db_session, value=_value(request, "confirm"), operator_open_id="ou_op"
        )
        assert outcome.ok is True
        assert update_mock.await_count == 2
        calls = [c.args for c in update_mock.await_args_list]
        assert all(c[0] == "unqualified_stock" for c in calls)
        assert {c[1] for c in calls} == {"rec1", "rec2"}
        assert all(c[2] == {"处理日期": "2026-09-17"} for c in calls)
        assert request.status == "confirmed"  # 全部成功保持 confirmed
        assert "writeback_ok" in await _audits_of(db_session, request.request_no)

    async def test_writeback_partial_failure_marks_failed(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _flaky(self: Any, table_key: str, record_id: str, fields: dict) -> dict[str, Any]:
            if record_id == "rec1":
                raise RuntimeError("Base 写入被拒")
            return {"record_id": record_id, "fields": {}}

        monkeypatch.setattr(WarehouseBitableAdapter, "update_record", _flaky)
        request = await _make_request(db_session)
        result = await cr.execute_writeback(db_session, request)
        assert result["ok"] == 1
        assert [f["record_id"] for f in result["failed"]] == ["rec1"]
        assert request.status == "failed"
        assert "writeback_failed" in await _audits_of(db_session, request.request_no)


# ═══════════════════════════════════════════════════════════════
# 重发与过期清扫
# ═══════════════════════════════════════════════════════════════


class TestResendAndExpire:
    async def test_resend_only_pending(self, db_session: AsyncSession) -> None:
        request = await _make_request(db_session)
        assert await cr.resend_request(db_session, request, dry_run=True) is True
        assert request.resend_count == 1
        assert request.expires_at > datetime.now(UTC)
        assert "resend" in await _audits_of(db_session, request.request_no)

        request.status = "cancelled"
        await db_session.flush()
        with pytest.raises(ValueError, match="仅待确认"):
            await cr.resend_request(db_session, request, dry_run=True)

    async def test_expire_stale_batch(self, db_session: AsyncSession) -> None:
        stale = await _make_request(
            db_session, expires_at=datetime.now(UTC) - timedelta(hours=2)
        )
        fresh = await _make_request(db_session)
        count = await cr.expire_stale_requests(db_session)
        assert count == 1
        assert stale.status == "expired"
        assert fresh.status == "pending"


# ═══════════════════════════════════════════════════════════════
# 网关分发（薄集成：scene=biz_confirm 正确路由）
# ═══════════════════════════════════════════════════════════════


class TestGatewayDispatch:
    async def _with_gateway_session(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        @asynccontextmanager
        async def _fake_session() -> Any:
            yield db_session

        monkeypatch.setattr(gateway, "_db_session", _fake_session)

    async def test_confirm_dispatches_background(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._with_gateway_session(db_session, monkeypatch)
        request = await _make_request(db_session)
        spawned: list[Any] = []

        async def _fake_background(rid: uuid.UUID) -> None:
            spawned.append(rid)

        monkeypatch.setattr(gateway, "_run_biz_confirm_writeback", _fake_background)
        patch_mock = AsyncMock()
        monkeypatch.setattr(gateway, "_patch_confirm_request_card", patch_mock)

        event = {
            "action": {"value": _value(request, "confirm")},
            "operator": {"open_id": "ou_clicker"},
            "context": {"open_message_id": "om_card"},
        }
        result = await gateway.handle_card_action_trigger(event)
        assert result == {"code": 200}
        assert request.status == "confirmed"
        assert request.confirmed_by == "ou_clicker"
        # 等待后台回写任务收尾（gateway._background_tasks 强引用集合）
        if gateway._background_tasks:
            await asyncio.wait(gateway._background_tasks)
        assert spawned == [request.id]  # 回写移交后台

    async def test_cancel_dispatches_sync(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._with_gateway_session(db_session, monkeypatch)
        request = await _make_request(db_session)
        patch_mock = AsyncMock()
        monkeypatch.setattr(gateway, "_patch_confirm_request_card", patch_mock)

        event = {
            "action": {"value": _value(request, "cancel")},
            "operator": {"open_id": "ou_clicker"},
            "context": {"open_message_id": "om_card"},
        }
        result = await gateway.handle_card_action_trigger(event)
        assert result is None  # _ack_with_patch 有 message_id → 纯 ACK
        assert request.status == "cancelled"

    async def test_other_scene_ignored(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._with_gateway_session(db_session, monkeypatch)
        event = {"action": {"value": {"scene": "unknown", "action": "confirm"}}}
        assert await gateway.handle_card_action_trigger(event) is None


# ═══════════════════════════════════════════════════════════════
# API 薄契约
# ═══════════════════════════════════════════════════════════════


class TestConfirmRequestApi:
    async def test_list_and_stats(
        self, api_context: tuple[AsyncClient, AsyncSession]
    ) -> None:
        client, db = api_context
        await _make_request(db)
        resp = await client.get(CONFIRM_API)
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] >= 1
        entry = [e for e in body["data"] if e["business_type"] == "unqualified_disposition"][0]
        assert entry["status"] == "pending"

        resp = await client.get(f"{CONFIRM_API}/stats")
        assert resp.status_code == 200
        assert any(
            s["business_type"] == "unqualified_disposition"
            for s in resp.json()["data"]["by_status_business"]
        )

    async def test_resend_endpoint(
        self, api_context: tuple[AsyncClient, AsyncSession]
    ) -> None:
        client, db = api_context
        request = await _make_request(db)
        resp = await client.post(f"{CONFIRM_API}/{request.id}/resend")
        assert resp.status_code == 200
        assert resp.json()["data"]["resend_count"] == 1

        # 非 pending 重发 → 422
        request.status = "cancelled"
        await db.flush()
        resp = await client.post(f"{CONFIRM_API}/{request.id}/resend")
        assert resp.status_code == 422

    async def test_resend_unknown_404(
        self, api_context: tuple[AsyncClient, AsyncSession]
    ) -> None:
        client, _ = api_context
        resp = await client.post(f"{CONFIRM_API}/{uuid.uuid4()}/resend")
        assert resp.status_code == 404
