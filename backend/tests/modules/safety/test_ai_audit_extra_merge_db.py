"""B0 · 审计 `extra` JSONB 合并在真 PG 上的行为验证（T01）。

为什么必须真 PG（历史教训）：旧的 `test_mark_parse_outcome_writes_extra_via_independent_session`
只断言 UPDATE 语句参数里的 patch dict，看不到 `coalesce` 兜底绑定值是 Python str
`"{}"`（经 JSONB bind processor 变成 JSON 字符串），也执行不到 SQL。而 SQLAlchemy
JSONB 默认 `none_as_null=False`：`_write_audit` 对无 extra 的 scope 落的是
**JSON null（`'null'::jsonb`）而不是 SQL NULL**，`coalesce` 永不取兜底，
`'null'::jsonb || patch` 直接得到 `[null, {...}]` 数组 → `AICallAuditDetail.extra`
校验失败 → `GET /api/v1/safety/ai-audits/{id}` 500。

本文件覆盖 4 种起始值（SQL NULL / JSON null / object / array）在真实
`_mark_parse_outcome` 执行后的结果，以及 schema 校验与详情接口 200。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, text

from app.modules.safety.ai_audit import audited_client
from app.modules.safety.ai_audit import schemas as audit_schemas
from app.modules.safety.ai_audit.models import AICallAudit
from app.modules.safety.ai_audit.schemas import AICallAuditDetail


class _SharedSessionCtx:
    """把「独立 session」的上下文管理器替换为测试事务里的同一 session。

    `_mark_parse_outcome` 内部 `async_session_factory()` 开独立 session 并 commit；
    测试用 `sealed_client` 的 savepoint session 顶替，commit 只释放 savepoint，
    外层事务 teardown 回滚，绝不真写开发库。
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    async def __aenter__(self) -> Any:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


async def _insert_audit(session: Any, *, extra: Any = None) -> AICallAudit:
    row = AICallAudit(
        scenario="pytest_extra_merge",
        model="test-model",
        status="success",
        extra=extra,
    )
    session.add(row)
    await session.flush()
    return row


async def _raw_set_extra_sql(session: Any, row_id: uuid.UUID, sql_literal: str) -> None:
    """用原生字面量构造 SQL NULL / 数组等 ORM 不便表达的起始值。"""
    await session.execute(
        text(
            f"UPDATE safety.ai_call_audits SET extra = {sql_literal} "  # noqa: S608 — 测试内固定字面量
            "WHERE id = :row_id"
        ),
        {"row_id": row_id},
    )


async def _extra_state(session: Any, row_id: uuid.UUID) -> tuple[str | None, Any]:
    stmt = select(func.jsonb_typeof(AICallAudit.extra), AICallAudit.extra).where(
        AICallAudit.id == row_id
    )
    row = (await session.execute(stmt)).one()
    return row[0], row[1]


async def _run_mark(
    monkeypatch: pytest.MonkeyPatch,
    session: Any,
    row_id: uuid.UUID,
    **kwargs: Any,
) -> None:
    import app.core.database as database

    monkeypatch.setattr(
        database, "async_session_factory", lambda: _SharedSessionCtx(session)
    )
    audited_client._last_audit_row_id.set(row_id)
    params: dict[str, Any] = {
        "json_valid": True,
        "json_repaired": False,
        "stages": (),
        "parse_attempts": 1,
    }
    params.update(kwargs)
    await audited_client._mark_parse_outcome(**params)


async def test_mark_heals_json_null_extra(sealed_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """线上主路径：extra=None 经 ORM 落 JSON null → mark 后必须是对象（不是数组）。"""
    _client, session = sealed_client
    row = await _insert_audit(session, extra=None)

    before_type, _ = await _extra_state(session, row.id)
    assert before_type == "null", "前提：SQLAlchemy JSONB 默认把 None 落成 JSON null"

    await _run_mark(monkeypatch, session, row.id)

    after_type, extra = await _extra_state(session, row.id)
    assert after_type == "object", f"extra 必须是对象，实际 {after_type!r}: {extra!r}"
    assert isinstance(extra, dict)
    assert extra["json_valid"] is True
    assert extra["parse_attempts"] == 1
    assert "json_valid" in extra


async def test_mark_heals_sql_null_extra(sealed_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """SQL NULL 起始值（空库/外部写入）同样必须得到对象。"""
    _client, session = sealed_client
    row = await _insert_audit(session, extra=None)
    await _raw_set_extra_sql(session, row.id, "NULL")

    before_type, _ = await _extra_state(session, row.id)
    assert before_type is None

    await _run_mark(monkeypatch, session, row.id)

    after_type, extra = await _extra_state(session, row.id)
    assert after_type == "object"
    assert isinstance(extra, dict) and extra["json_valid"] is True


async def test_mark_merges_into_object_extra(
    sealed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """对象起始值：保留已有键，patch 覆盖同名键。"""
    _client, session = sealed_client
    row = await _insert_audit(
        session, extra={"bitable_record_id": "rec-1", "json_valid": False}
    )

    await _run_mark(monkeypatch, session, row.id, json_valid=True, json_repaired=True)

    after_type, extra = await _extra_state(session, row.id)
    assert after_type == "object"
    assert isinstance(extra, dict)
    assert extra["bitable_record_id"] == "rec-1"
    assert extra["json_valid"] is True
    assert extra["json_repaired"] is True


async def test_mark_heals_corrupted_array_extra(
    sealed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """历史数组脏行：运行期守卫自愈为对象（内容不保留，跨环境由修复脚本负责）。"""
    _client, session = sealed_client
    row = await _insert_audit(session, extra=None)
    await _raw_set_extra_sql(
        session, row.id, """'[null, {"json_valid": false, "parse_attempts": 1}]'::jsonb"""
    )

    before_type, _ = await _extra_state(session, row.id)
    assert before_type == "array"

    await _run_mark(monkeypatch, session, row.id)

    after_type, extra = await _extra_state(session, row.id)
    assert after_type == "object", f"数组必须被自愈为对象，实际 {after_type!r}"
    assert isinstance(extra, dict) and extra["json_valid"] is True


async def test_write_audit_none_extra_is_json_null_then_mark_heals(
    sealed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全链路：真 `_write_audit`（ctx=None → extra=None）落 JSON null → mark 后对象。"""
    import app.core.database as database

    _client, session = sealed_client
    monkeypatch.setattr(
        database, "async_session_factory", lambda: _SharedSessionCtx(session)
    )
    audited_client._last_audit_row_id.set(None)
    await audited_client._write_audit(
        ctx=None,
        model="test-model",
        messages=[{"role": "user", "content": "x"}],
        output="{}",
        usage=None,
        latency_ms=1,
        status="success",
    )
    row_id = audited_client._last_audit_row_id.get()
    assert row_id is not None

    before_type, _ = await _extra_state(session, row_id)
    assert before_type == "null"

    await _run_mark(monkeypatch, session, row_id)

    after_type, extra = await _extra_state(session, row_id)
    assert after_type == "object"
    assert isinstance(extra, dict) and extra["json_valid"] is True


async def test_audit_detail_schema_and_get_api_200(
    sealed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收：AICallAuditDetail 校验通过 + GET /ai-audits/{id} 200 且 extra 为 dict。"""
    client, session = sealed_client
    row = await _insert_audit(session, extra=None)
    row_id = row.id
    await _run_mark(monkeypatch, session, row_id)

    session.expire_all()
    refreshed = await session.get(AICallAudit, row_id, populate_existing=True)
    assert refreshed is not None
    detail = AICallAuditDetail.model_validate(refreshed)
    assert isinstance(detail.extra, dict)
    assert detail.extra["json_valid"] is True

    resp = await client.get(f"/api/v1/safety/ai-audits/{row_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body["data"]
    assert data["id"] == str(row_id)
    assert isinstance(data["extra"], dict)
    assert data["extra"]["json_valid"] is True
    assert data["extra"]["parse_attempts"] == 1


def test_audit_detail_schema_rejects_array_extra() -> None:
    """契约回归：数组 extra 本身必须校验失败（证明旧 bug 会 500 的机制）。"""
    from pydantic import ValidationError

    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "created_at": "2026-11-05T00:00:00Z",
        "scenario": "pytest",
        "model": "m",
        "status": "success",
    }
    with pytest.raises(ValidationError):
        audit_schemas.AICallAuditDetail.model_validate({**base, "extra": [None, {"a": 1}]})
