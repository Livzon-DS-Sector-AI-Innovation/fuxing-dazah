"""运行参数消费端接线测试（票 04 验收：改值即时生效，无需重启）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import confirm
from app.modules.warehouse.ops_config.runtime_store import runtime_store
from tests.modules.warehouse.conftest import rand_code


@pytest.fixture
def patch_runtime_value(monkeypatch: pytest.MonkeyPatch):
    """向 runtime_store 单例注入预设行（接缝 2 复用）。"""

    def _patch(key: str, value) -> None:
        row = type("Row", (), {"key": key, "value": value, "note": None, "is_deleted": False})()
        monkeypatch.setattr(runtime_store, "_row_loader", lambda k: row if k == key else None)
        runtime_store.invalidate()

    yield _patch
    monkeypatch.setattr(runtime_store, "_row_loader", None)
    runtime_store.invalidate()


async def test_confirm_ttl_reads_runtime_config(
    db_session: AsyncSession, patch_runtime_value
) -> None:
    """confirm_ttl_seconds 改 60 后，request_confirm 生成的过期时间随之变化。"""
    patch_runtime_value("confirm_ttl_seconds", 60)
    before = datetime.now(UTC)
    draft = await confirm.request_confirm(
        db_session, requester_open_id=rand_code("OU"), summary="TTL 接线测试"
    )
    delta = (draft.expires_at - before).total_seconds()
    assert 55 <= delta <= 65  # ≈ 60s（时钟误差容忍）
