"""S6 审计 extra 引用质量维度（``mark_audit_extra``）测试。

背景：A1 的 ``_mark_parse_outcome`` 已用「独立 session + JSONB CASE 合并」把
JSON 质量维度回写到最近一次审计行 extra；C2 需要复用同一合并语义写引用质量
维度。本文件把该合并抽成通用 ``mark_audit_extra(fields)`` 后的契约锁死：

- 无审计行（``_last_audit_row_id`` 未设置）→ 完全 no-op，不打开 DB session；
- 有审计行 → 恰好一次 UPDATE ``safety.ai_call_audits.extra``（JSONB 合并）+ commit；
- 任何 DB 异常只日志、绝不向上抛（不影响识别业务）；
- ``_mark_parse_outcome`` 委托 ``mark_audit_extra``，原有 4 个 JSON 质量维度不丢。

全部 fake（不连 DB）。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.safety.ai_audit import audited_client


class _FakeFactory:
    """记录 session 使用情况的假 async_session_factory。"""

    def __init__(self, *, explode: bool = False) -> None:
        self.explode = explode
        self.opened = 0
        self.statements: list[Any] = []
        self.commits = 0

    def __call__(self) -> _FakeFactory:
        self.opened += 1
        if self.explode:
            raise RuntimeError("DB 不可用")
        return self

    async def __aenter__(self) -> _FakeFactory:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture(autouse=True)
def _reset_row_id() -> Any:
    token = audited_client._last_audit_row_id.set(None)
    yield
    audited_client._last_audit_row_id.reset(token)


class TestMarkAuditExtra:
    async def test_no_row_id_is_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.core.database as core_db

        factory = _FakeFactory(explode=True)
        monkeypatch.setattr(core_db, "async_session_factory", factory)
        await audited_client.mark_audit_extra({"citation_total": 2})
        assert factory.opened == 0

    async def test_empty_fields_is_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.core.database as core_db

        factory = _FakeFactory(explode=True)
        monkeypatch.setattr(core_db, "async_session_factory", factory)
        audited_client._last_audit_row_id.set(uuid.uuid4())
        await audited_client.mark_audit_extra({})
        assert factory.opened == 0

    async def test_merges_fields_into_last_audit_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.core.database as core_db

        factory = _FakeFactory()
        monkeypatch.setattr(core_db, "async_session_factory", factory)
        audited_client._last_audit_row_id.set(uuid.uuid4())

        await audited_client.mark_audit_extra(
            {"citation_total": 3, "citation_verified": 2}
        )

        assert factory.opened == 1
        assert factory.commits == 1
        assert len(factory.statements) == 1
        statement = factory.statements[0]
        assert getattr(statement, "table").name == "ai_call_audits"
        sql = str(statement)
        assert "extra" in sql
        # JSONB 合并（CASE 回落空对象，防 'null'::jsonb || patch 变数组）
        assert "CASE" in sql.upper() or "jsonb" in sql.lower()

    async def test_db_error_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.core.database as core_db

        factory = _FakeFactory(explode=True)
        monkeypatch.setattr(core_db, "async_session_factory", factory)
        audited_client._last_audit_row_id.set(uuid.uuid4())

        # 不抛异常（识别链路不因审计回写失败而失败）
        await audited_client.mark_audit_extra({"citation_total": 1})


class TestMarkParseOutcomeDelegation:
    async def test_delegates_with_json_quality_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, Any]] = []

        async def _capture(fields: dict[str, Any]) -> None:
            captured.append(dict(fields))

        monkeypatch.setattr(audited_client, "mark_audit_extra", _capture)
        audited_client._last_audit_row_id.set(uuid.uuid4())

        await audited_client._mark_parse_outcome(
            json_valid=True,
            json_repaired=True,
            stages=("trailing_comma",),
            parse_attempts=2,
        )

        assert captured == [
            {
                "json_valid": True,
                "json_repaired": True,
                "repair_stages": ["trailing_comma"],
                "parse_attempts": 2,
            }
        ]

    async def test_no_row_id_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, Any]] = []

        async def _capture(fields: dict[str, Any]) -> None:
            captured.append(dict(fields))

        monkeypatch.setattr(audited_client, "mark_audit_extra", _capture)
        # _last_audit_row_id=None（fixture 已重置）
        await audited_client._mark_parse_outcome(
            json_valid=False,
            json_repaired=False,
            stages=(),
            parse_attempts=1,
        )
        assert captured == []
