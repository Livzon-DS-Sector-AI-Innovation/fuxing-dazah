"""提案审批通过后自动建立文件关联的行为测试。

`approve_proposal` 的其余守卫（stale、权限、编码冲突）在真实链路上
覆盖；这里聚焦自动关联这一附属动作：调用参数正确、失败不阻塞审批。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa import ai_analysis, service
from app.platform.identity.models import User


class _Result:
    def __init__(self, rows: Iterable[Any] = (), scalar: Any = None) -> None:
        self.rows = list(rows)
        self.scalar = scalar

    def scalars(self) -> Iterator[Any]:
        return iter(self.rows)

    def scalar_one_or_none(self) -> Any:
        return self.scalar


class _FakeDb:
    """按调用顺序吐出预置结果，模拟审批路径上的三次查询。"""

    def __init__(self, results: Iterable[_Result] = ()) -> None:
        self.results = list(results)

    def add(self, _row: Any) -> None:  # pragma: no cover - 审批路径不新增 ORM 行
        raise AssertionError("审批路径不应直接 db.add")

    async def execute(self, _statement: Any) -> _Result:
        return self.results.pop(0) if self.results else _Result()

    async def flush(self) -> None:
        return None


def _run(*, version_id: uuid.UUID) -> Any:
    extraction_run_id = uuid.uuid4()
    chunk_run_id = uuid.uuid4()
    return type(
        "Run",
        (),
        {
            "id": uuid.uuid4(),
            "version_id": version_id,
            "extraction_run_id": extraction_run_id,
            "chunk_run_id": chunk_run_id,
            "status": "ready",
            "source_policy": "authoritative",
            "input_fingerprint": "fp",
            "catalog_fingerprint": "catalog",
            "model": "test-model",
            "provider": "test-provider",
            "prompt_version": "v1",
            "schema_version": "v1",
        },
    )()


def _proposal(*, analysis_run_id: uuid.UUID) -> Any:
    return type(
        "Proposal",
        (),
        {
            "id": uuid.uuid4(),
            "analysis_run_id": analysis_run_id,
            "proposal_type": "create",
            "target_master_object_id": None,
            "object_type": "SUPPLIER",
            "proposed_payload": {
                "object_type": "SUPPLIER",
                "code": "SUP-001",
                "name": "供应商甲",
            },
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
        },
    )()


@pytest.fixture
def approve_context(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """搭好审批前置条件，返回可断言的自动关联调用记录。"""
    version_id = uuid.uuid4()
    run = _run(version_id=version_id)
    proposal = _proposal(analysis_run_id=run.id)
    master_id = uuid.uuid4()
    link_calls: list[dict[str, Any]] = []

    async def _fake_get_ai_run(_db: Any, run_id: uuid.UUID) -> Any:
        return run if run_id == run.id else None

    async def _fake_lock_file(_db: Any, current_run: Any) -> Any:
        return type(
            "File",
            (),
            {
                "current_extraction_run_id": current_run.extraction_run_id,
                "current_chunk_run_id": current_run.chunk_run_id,
            },
        )()

    async def _fake_lock_proposal(_db: Any, proposal_id: uuid.UUID) -> Any:
        return proposal if proposal_id == proposal.id else None

    async def _fake_stale_reason(_db: Any, _current_run: Any) -> None:
        return None

    async def _fake_version_lock(_db: Any, _version_id: uuid.UUID) -> Any:
        return type("Version", (), {"status": "registered"})()

    async def _fake_catalog(_db: Any) -> tuple[list[Any], dict[Any, list[str]], str]:
        # 审批只会在写入主数据后重算一次目录指纹，这里给固定值即可。
        return [], {}, "catalog-after-approve"

    async def _fake_create_master(_db: Any, _payload: Any, _user: User | None) -> Any:
        return type("Master", (), {"id": master_id})()

    async def _fake_link(
        _db: AsyncSession,
        _version_id: uuid.UUID,
        master_object_ids: list[uuid.UUID],
        _user: User | None,
        *,
        audit: bool = True,
    ) -> list[Any]:
        link_calls.append(
            {"version_id": _version_id, "ids": list(master_object_ids), "audit": audit}
        )
        return []

    monkeypatch.setattr(ai_analysis, "get_ai_run", _fake_get_ai_run)
    monkeypatch.setattr(ai_analysis, "_lock_analysis_file", _fake_lock_file)
    monkeypatch.setattr(ai_analysis, "_lock_master_proposal", _fake_lock_proposal)
    monkeypatch.setattr(ai_analysis, "_analysis_stale_reason", _fake_stale_reason)
    monkeypatch.setattr(ai_analysis, "_catalog", _fake_catalog)
    monkeypatch.setattr(ai_analysis, "_actor_id", lambda _user: uuid.uuid4())
    monkeypatch.setattr(ai_analysis, "_audit", _noop_audit)
    monkeypatch.setattr(service, "_get_version_with_document_lock", _fake_version_lock)
    monkeypatch.setattr(service, "create_master", _fake_create_master)
    monkeypatch.setattr(service, "set_relations_append", _fake_link)
    return {
        "version_id": version_id,
        "run": run,
        "proposal": proposal,
        "master_id": master_id,
        "link_calls": link_calls,
        "catalog_after": "catalog-after-approve",
    }


async def _noop_audit(_db: Any, **_kwargs: Any) -> None:
    return None


def _db_for(proposal: Any, run: Any) -> _FakeDb:
    # execute 顺序：提案初查 → 分析运行加锁重读 → create 编码冲突预检。
    return _FakeDb(
        [
            _Result(scalar=proposal),
            _Result(scalar=run),
            _Result(scalar=None),
        ]
    )


@pytest.mark.asyncio
async def test_approve_proposal_auto_links_document(
    approve_context: dict[str, Any],
) -> None:
    """审批通过即在来源版本上追加文件关联，且不写独立审计。"""
    db = _db_for(approve_context["proposal"], approve_context["run"])
    approved, skipped = await ai_analysis.approve_proposal(
        db, approve_context["proposal"].id, None, None
    )
    assert approved.status == "approved"
    assert approved.target_master_object_id == approve_context["master_id"]
    assert skipped is None
    assert approve_context["link_calls"] == [
        {
            "version_id": approve_context["version_id"],
            "ids": [approve_context["master_id"]],
            "audit": False,
        }
    ]


@pytest.mark.asyncio
async def test_approve_proposal_auto_link_failure_does_not_block(
    approve_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """版本锁定等追加失败只降级为提示原因，审批本身照常完成。"""

    async def _failing_link(
        _db: AsyncSession,
        _version_id: uuid.UUID,
        _master_object_ids: list[uuid.UUID],
        _user: User | None,
        *,
        audit: bool = True,
    ) -> list[Any]:
        raise AppException(status_code=409, message="文件版本锁定后不能修改关联")

    monkeypatch.setattr(service, "set_relations_append", _failing_link)
    db = _db_for(approve_context["proposal"], approve_context["run"])
    approved, skipped = await ai_analysis.approve_proposal(
        db, approve_context["proposal"].id, None, None
    )
    assert approved.status == "approved"
    assert approved.target_master_object_id == approve_context["master_id"]
    assert skipped == "文件版本锁定后不能修改关联"


@pytest.mark.asyncio
async def test_approve_proposal_advances_run_catalog_fingerprint(
    approve_context: dict[str, Any],
) -> None:
    """审批写入主数据后必须推进运行快照。

    审批自身会新建/改动主数据，而目录指纹包含 code/name/aliases。不推进时，
    同一次分析里剩下的提案会在下一次审批时被判为「主数据目录已变化」，
    整批提案连同待确认关联一起被标记过期且无法恢复。
    """

    run = approve_context["run"]
    assert run.catalog_fingerprint == "catalog"
    db = _db_for(approve_context["proposal"], run)
    await ai_analysis.approve_proposal(db, approve_context["proposal"].id, None, None)
    assert run.catalog_fingerprint == approve_context["catalog_after"]
