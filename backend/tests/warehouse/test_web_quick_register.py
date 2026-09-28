"""快速登记后端测试（分期B Ticket 07）：上传、识别建稿（Web 来源）、确认流转。

2026-09-28 识别完善 B 项补充：成品入库识别分支（classify 路由）与
PATCH /agent/drafts/{id}/fields 表单直改端点。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse import web_quick_register
from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.agent.confirm import ConfirmOutcome
from app.modules.warehouse.agent.pipeline import (
    FinishedAlignedReceipt,
    RecognizedField,
    RecognizedFinishedReceipt,
    RecognizedReceipt,
)
from app.modules.warehouse.models import WarehouseAgentDraft

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _make_recognized() -> RecognizedReceipt:
    return RecognizedReceipt.model_validate(
        {
            "material_name": {"value": "某物料", "confidence": 0.7},
            "vendor_batch_no": {"value": "VB-1", "confidence": 0.8},
            "quantity": {"value": "10", "confidence": 0.85},
            "unit": {"value": "kg", "confidence": 0.9},
            "supplier": {"value": "某供应商", "confidence": 0.9},
            "manufacturer": {"value": None, "confidence": 0},
            "plate_no": {"value": None, "confidence": 0},
            "contract_no": {"value": None, "confidence": 0},
            "raw": {},
        }
    )


def _patch_pipeline(monkeypatch) -> None:
    recognized = _make_recognized()
    aligned_mock = MagicMock()
    aligned_mock.model_dump.return_value = {"match_confidence": 0.7}

    async def _fake_mark_aligned(db, draft, aligned):
        draft.aligned = aligned.model_dump() if hasattr(aligned, "model_dump") else aligned
        draft.status = "aligned"

    monkeypatch.setattr(
        web_quick_register, "recognize_receipt", AsyncMock(return_value=recognized)
    )
    monkeypatch.setattr(
        web_quick_register, "align_receipt", AsyncMock(return_value=aligned_mock)
    )
    monkeypatch.setattr(web_quick_register, "mark_aligned", _fake_mark_aligned)


async def _upload(auth_client: AsyncClient) -> str:
    resp = await auth_client.post(
        "/api/v1/warehouse/agent/uploads",
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["upload_id"]


async def test_upload_rejects_non_image(auth_client: AsyncClient) -> None:
    resp = await auth_client.post(
        "/api/v1/warehouse/agent/uploads",
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert resp.status_code == 422


async def test_upload_and_fetch_image(auth_client: AsyncClient) -> None:
    upload_id = await _upload(auth_client)
    resp = await auth_client.get(f"/api/v1/warehouse/agent/uploads/{upload_id}")
    assert resp.status_code == 200
    assert resp.content.startswith(b"\x89PNG")


async def test_recognition_creates_web_draft(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    _patch_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)

    resp = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["draft_no"].startswith("WR")

    draft = (
        await db_session.execute(
            select(WarehouseAgentDraft).where(WarehouseAgentDraft.draft_no == data["draft_no"])
        )
    ).scalar_one()
    assert draft.source == "web"
    assert draft.status == "aligned"

    detail = await auth_client.get(f"/api/v1/warehouse/agent/drafts/{draft.id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["source_image"] == f"web:{upload_id}"


async def test_confirm_web_draft_routes_through_handle_action(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    _patch_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)
    created = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    draft_id = created.json()["data"]["draft_id"]

    called: dict = {}

    async def _fake_handle_action(db, *, value, operator_open_id, execute=True):
        called["value"] = value
        called["operator"] = operator_open_id
        # BLOCK 修复验证：handle_action 被调用时草稿必须已是 pending_confirm
        draft = await agent_repository.get_agent_draft(
            db, uuid.UUID(value["draft_id"])
        )
        called["draft_status_at_handle"] = draft.status if draft else None
        return ConfirmOutcome(ok=True, status="ok", message="已确认")

    monkeypatch.setattr(web_quick_register, "handle_action", _fake_handle_action)

    confirmed = await auth_client.post(
        f"/api/v1/warehouse/agent/drafts/{draft_id}/confirm",
        json={"action": "confirm"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["ok"] is True
    assert called["value"]["draft_id"] == draft_id
    assert called["value"]["scene"] == "receipt"
    assert called["operator"].startswith("web:")
    # BLOCK 修复断言：进入 handle_action 前已迁移到 pending_confirm
    assert called["draft_status_at_handle"] == "pending_confirm"


async def test_confirm_other_users_draft_not_found(
    auth_client: AsyncClient, monkeypatch
) -> None:
    """web 来源草稿仅本人可见/可操作（另一假用户 404）。"""
    _patch_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)
    created = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    draft_id = created.json()["data"]["draft_id"]

    # 换一个用户身份（改写 fake user 的 id）
    from app.platform.permission import deps as permission_deps

    async def _fake_user() -> object:
        return object.__new__(
            type("FakeUser", (), {"id": __import__("uuid").uuid4(), "name": "别人"}),
        )

    from app.main import app
    from app.platform.permission.deps import require_user

    async def _limited_perms(user_id: str, db: AsyncSession) -> set[str]:
        return {"warehouse:movement:create"}

    app.dependency_overrides[require_user] = _fake_user
    monkeypatch.setattr(permission_deps, "get_user_permissions", _limited_perms)
    try:
        resp = await auth_client.get(f"/api/v1/warehouse/agent/drafts/{draft_id}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(require_user, None)


# ═══════════════════════════════════════════════════════════════
# 2026-09-28 B 项：成品识别分支 + PATCH 表单直改
# ═══════════════════════════════════════════════════════════════


def _make_finished_recognized() -> RecognizedFinishedReceipt:
    return RecognizedFinishedReceipt(
        product_name=RecognizedField(value="达托霉", confidence=0.6),
        product_batch_no=RecognizedField(value="DA2609001", confidence=0.9),
        quantity=RecognizedField(value="100", confidence=0.85),
        unit=RecognizedField(value="pl", confidence=0.4),
        rows=[
            {
                "product_name": "达托霉",
                "product_batch_no": "DA2609001",
                "quantity": "100",
                "unit": "pl",
            }
        ],
    )


def _patch_finished_pipeline(monkeypatch) -> None:
    """成品分支桩：分类=成品 → 识别假件 → 名录对齐假件（近似匹配+警示）。"""
    recognized = _make_finished_recognized()

    async def fake_classify(image_b64: str, content_type: str = "image/jpeg") -> str:
        return "finished_receipt"

    async def fake_recognize_finished(
        image_b64: str,
        content_type: str = "image/jpeg",
        user_text: str | None = None,
    ) -> RecognizedFinishedReceipt:
        return recognized

    async def fake_align(recognized: RecognizedFinishedReceipt) -> FinishedAlignedReceipt:
        return FinishedAlignedReceipt(
            aligned={
                "product_name": "达托霉素",
                "rows": [dict(row, product_name="达托霉素") for row in recognized.rows],
            },
            match_confidence="fuzzy",
            match_detail={"key": "达托霉", "matched_by": "fuzzy"},
            warnings={"product_name": "产品名称按近似匹配「达托霉」→「达托霉素」，请核对"},
        )

    async def fake_mark_finished(db, draft, aligned) -> None:
        draft.aligned = {
            **aligned.aligned,
            "match_confidence": aligned.match_confidence,
            "match_detail": aligned.match_detail,
            "warnings": aligned.warnings,
        }
        draft.status = "aligned"

    monkeypatch.setattr(web_quick_register, "classify_document", fake_classify)
    monkeypatch.setattr(
        web_quick_register, "recognize_finished_receipt", fake_recognize_finished
    )
    monkeypatch.setattr(web_quick_register, "align_finished_receipt", fake_align)
    monkeypatch.setattr(web_quick_register, "mark_finished_aligned", fake_mark_finished)


async def test_finished_recognition_creates_finished_draft(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_finished_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)

    resp = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["scene"] == "finished_receipt"
    assert data["aligned"]["product_name"] == "达托霉素"
    assert data["aligned"]["warnings"]

    draft = (
        await db_session.execute(
            select(WarehouseAgentDraft).where(WarehouseAgentDraft.draft_no == data["draft_no"])
        )
    ).scalar_one()
    assert draft.scene == "finished_receipt"
    assert draft.status == "aligned"


async def test_patch_fields_updates_aligned(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)
    created = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    draft_id = created.json()["data"]["draft_id"]

    resp = await auth_client.patch(
        f"/api/v1/warehouse/agent/drafts/{draft_id}/fields",
        json={"fields": {"quantity": "55"}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["aligned"]["quantity"] == 55

    draft = await agent_repository.get_agent_draft(db_session, uuid.UUID(draft_id))
    assert draft is not None and draft.aligned["quantity"] == 55  # aligned working set


async def test_patch_rows_replaces_and_syncs_quantity(
    auth_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_finished_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)
    created = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    draft_id = created.json()["data"]["draft_id"]

    resp = await auth_client.patch(
        f"/api/v1/warehouse/agent/drafts/{draft_id}/fields",
        json={
            "rows": [
                {
                    "product_name": "达托霉素",
                    "product_batch_no": "DA2609001",
                    "quantity": "60",
                    "unit": "kg",
                },
                {
                    "product_name": "达托霉素",
                    "product_batch_no": "DA2609001",
                    "quantity": "40",
                    "unit": "kg",
                },
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    aligned = resp.json()["data"]["aligned"]
    assert len(aligned["rows"]) == 2
    assert aligned["quantity"] == 100  # 首组合计同步 scalar quantity
    # 行编辑不碰的警示元数据保留
    assert aligned["warnings"]


async def test_patch_rejects_unknown_field(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)
    created = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    draft_id = created.json()["data"]["draft_id"]

    resp = await auth_client.patch(
        f"/api/v1/warehouse/agent/drafts/{draft_id}/fields",
        json={"fields": {"不存在字段XYZ": "1"}},
    )
    assert resp.status_code == 422
    assert "不支持的字段" in resp.json()["message"]


async def test_patch_rejects_invalid_row(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_finished_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)
    created = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    draft_id = created.json()["data"]["draft_id"]

    resp = await auth_client.patch(
        f"/api/v1/warehouse/agent/drafts/{draft_id}/fields",
        json={
            "rows": [
                {
                    "product_name": "达托霉素",
                    "product_batch_no": "DA2609001",
                    "quantity": "60",
                    # 缺 unit
                }
            ]
        },
    )
    assert resp.status_code == 422
    assert "行缺少必填字段" in resp.json()["message"]


async def test_patch_empty_payload_rejected(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)
    created = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    draft_id = created.json()["data"]["draft_id"]

    resp = await auth_client.patch(
        f"/api/v1/warehouse/agent/drafts/{draft_id}/fields",
        json={},
    )
    assert resp.status_code == 422


async def test_patch_other_users_draft_not_found(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pipeline(monkeypatch)
    upload_id = await _upload(auth_client)
    created = await auth_client.post(
        "/api/v1/warehouse/agent/recognition",
        json={"upload_id": upload_id},
    )
    draft_id = created.json()["data"]["draft_id"]

    from app.main import app
    from app.platform.permission import deps as permission_deps
    from app.platform.permission.deps import require_user

    async def _fake_user() -> object:
        return object.__new__(
            type("FakeUser", (), {"id": uuid.uuid4(), "name": "别人"}),
        )

    async def _limited_perms(user_id: str, db: AsyncSession) -> set[str]:
        return {"warehouse:movement:create"}

    app.dependency_overrides[require_user] = _fake_user
    monkeypatch.setattr(permission_deps, "get_user_permissions", _limited_perms)
    try:
        resp = await auth_client.patch(
            f"/api/v1/warehouse/agent/drafts/{draft_id}/fields",
            json={"fields": {"quantity": "55"}},
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(require_user, None)
