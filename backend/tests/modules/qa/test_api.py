"""QA 外部来源引用接口测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa.api import reference_sources
from app.platform.identity.models import User


@pytest.mark.asyncio
async def test_equipment_reference_selector_uses_qa_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """设备来源选择器只调用带目标模块上下文的公共接口。"""
    equipment_id = uuid4()
    refs = [
        SimpleNamespace(
            id=equipment_id,
            equipment_no="EQ-QA-SELECT",
            name="可引用设备",
            status="完好",
            is_active=True,
            is_deleted=False,
            source="shared",
        )
    ]
    list_refs = AsyncMock(return_value=(refs, 1))
    monkeypatch.setattr(
        "app.modules.equipment.public_api.list_equipment_references", list_refs
    )

    response = await reference_sources(
        "EQUIPMENT",
        cast(User, SimpleNamespace(id=uuid4())),
        cast(AsyncSession, SimpleNamespace()),
        keyword="EQ-QA",
        page=1,
        page_size=20,
    )

    body = response.body
    # JSONResponse.body is bytes; decode only in the assertion helper to avoid
    # coupling the service test to the HTTP client fixture.
    import json

    data: dict[str, Any] = json.loads(body)
    assert data["data"][0]["id"] == str(equipment_id)
    assert data["data"][0]["source_module"] == "equipment"
    assert data["data"][0]["source"] == "shared"
    list_refs.assert_awaited_once()
    call = list_refs.await_args
    assert call is not None
    assert call.args[2] == "qa"


@pytest.mark.asyncio
async def test_unsupported_reference_kind_is_rejected() -> None:
    with pytest.raises(Exception) as error:
        await reference_sources(
            "NOT_A_SOURCE",
            cast(User, SimpleNamespace(id=uuid4())),
            cast(AsyncSession, SimpleNamespace()),
        )
    assert getattr(error.value, "status_code", None) == 422
