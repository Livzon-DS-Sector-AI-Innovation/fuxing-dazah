"""QA 主数据、版本、关联和搜索规则的业务服务测试。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, ForbiddenException
from app.modules.qa import service
from app.modules.qa.file_service import StoredFile
from app.modules.qa.models import (
    Document,
    DocumentMasterLink,
    DocumentVersion,
    MasterObject,
    MasterObjectAlias,
    MasterObjectSource,
    VersionStatus,
)
from app.modules.qa.schemas import MasterObjectCreate, RelationIn, SourceLinkIn
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
    def __init__(self, results: Iterable[_Result] = ()) -> None:
        self.results = list(results)
        self.added: list[Any] = []
        self.flush_count = 0

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def execute(self, _statement: Any) -> _Result:
        return self.results.pop(0) if self.results else _Result()

    async def flush(self) -> None:
        self.flush_count += 1
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()


def _document(*, status: str = "active") -> Document:
    row = Document(
        document_no="SOP-001",
        title="清洁 SOP",
        document_type_id=uuid.uuid4(),
        status=status,
    )
    row.id = uuid.uuid4()
    return row


def _version(*, status: str = VersionStatus.REGISTERED.value) -> DocumentVersion:
    row = DocumentVersion(
        document_id=uuid.uuid4(),
        version_label="V1.0",
        version_sequence=1,
        approved_declared=True,
        status=status,
    )
    row.id = uuid.uuid4()
    return row


def test_normalization_and_snippet_have_stable_search_rules() -> None:
    """编码规范化、紧凑匹配和正文片段长度遵循固定搜索规则。"""
    assert service.normalize_code(" r-101  ") == "R-101"
    assert service.normalize_text("设备   编号") == "设备 编号"
    assert service._rank("master_object", "code", "R101", "R-101") == 100

    snippet = service._snippet("前" * 200 + "needle" + "后" * 200, "needle")
    assert len(snippet) <= 240
    assert "needle" in snippet


@pytest.mark.asyncio
async def test_create_master_normalizes_identity_and_snapshots_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """创建主数据时规范化编码，并保存别名和外部来源快照。"""
    db = _FakeDb()
    monkeypatch.setattr(service, "_ensure_master_code_available", _async_noop)
    monkeypatch.setattr(service, "_ensure_alias_available", _async_noop)
    monkeypatch.setattr(service, "_validate_region_parent", _async_noop)
    monkeypatch.setattr(service, "_validate_department", _department_ok)
    monkeypatch.setattr(service, "_get_external_source", _source_ok)
    monkeypatch.setattr(service, "_audit", _async_noop)

    source_id = uuid.uuid4()
    payload = MasterObjectCreate(
        object_type="EQUIPMENT",
        code=" eq-01 ",
        name="反应釜",
        aliases=[" r-101 "],
        sources=[
            SourceLinkIn(
                source_module="equipment",
                source_entity="equipment",
                source_id=source_id,
            )
        ],
    )

    row = await service.create_master(cast(AsyncSession, db), payload)

    assert row.code == "EQ-01"
    assert row.normalized_code == "EQ-01"
    assert row.name == "反应釜"
    aliases = [item for item in db.added if isinstance(item, MasterObjectAlias)]
    sources = [item for item in db.added if isinstance(item, MasterObjectSource)]
    assert aliases[0].normalized_alias == "R-101"
    assert sources[0].source_code_snapshot == "EQ-01-SOURCE"
    assert sources[0].source_name_snapshot == "来源设备"


@pytest.mark.asyncio
async def test_create_master_rejects_duplicate_source_in_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一主数据请求重复关联来源对象时抛出冲突异常。"""
    db = _FakeDb()
    monkeypatch.setattr(service, "_ensure_master_code_available", _async_noop)
    monkeypatch.setattr(service, "_validate_region_parent", _async_noop)
    monkeypatch.setattr(service, "_validate_department", _department_ok)
    monkeypatch.setattr(service, "_get_external_source", _source_ok)
    monkeypatch.setattr(service, "_audit", _async_noop)
    source_id = uuid.uuid4()
    payload = MasterObjectCreate(
        object_type="EQUIPMENT",
        code="EQ-02",
        name="设备",
        sources=[
            SourceLinkIn(
                source_module="equipment",
                source_entity="equipment",
                source_id=source_id,
            ),
            SourceLinkIn(
                source_module="equipment",
                source_entity="equipments",
                source_id=source_id,
            ),
        ],
    )

    with pytest.raises(DuplicateException):
        await service.create_master(cast(AsyncSession, db), payload)


@pytest.mark.asyncio
async def test_equipment_source_uses_qa_reference_validation_for_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QA 设备来源必须带用户上下文校验，并支持首次自有设备自动授权。"""
    source_id = uuid.uuid4()
    calls: list[tuple[Any, Any, Any, Any, Any]] = []
    brief = SimpleNamespace(
        id=source_id,
        equipment_no="EQ-QA-01",
        name="QA设备",
        is_active=True,
    )

    async def _validate(
        db: Any, user: Any, module: str, ids: Any, *, auto_publish_owned: bool
    ) -> list[Any]:
        calls.append((db, user, module, ids, auto_publish_owned))
        return [brief]

    monkeypatch.setattr(
        "app.modules.equipment.public_api.validate_equipment_references", _validate
    )
    db = _FakeDb()
    user = cast(User, SimpleNamespace(id=uuid.uuid4()))
    code, name = await service._get_external_source(
        cast(AsyncSession, db),
        "EQUIPMENT",
        "equipment",
        "equipment",
        source_id,
        user,
    )

    assert (code, name) == ("EQ-QA-01", "QA设备")
    assert calls == [(db, user, "qa", [source_id], True)]


@pytest.mark.asyncio
async def test_equipment_source_internal_task_keeps_trusted_brief_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """可信内部任务没有用户上下文时仍可读取无授权摘要。"""
    source_id = uuid.uuid4()
    brief = SimpleNamespace(
        id=source_id,
        equipment_no="EQ-INTERNAL",
        name="内部任务设备",
        is_active=True,
    )
    called: list[uuid.UUID] = []

    async def _brief(_db: Any, equipment_id: uuid.UUID) -> Any:
        called.append(equipment_id)
        return brief

    monkeypatch.setattr("app.modules.equipment.public_api.get_equipment_brief", _brief)
    code, name = await service._get_external_source(
        cast(AsyncSession, _FakeDb()),
        "EQUIPMENT",
        "equipment",
        "equipment",
        source_id,
        None,
    )

    assert (code, name) == ("EQ-INTERNAL", "内部任务设备")
    assert called == [source_id]


@pytest.mark.asyncio
async def test_equipment_source_rejects_hidden_or_revoked_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QA 新建/替换来源遇到隐藏或撤销设备时保留统一无权结果。"""
    source_id = uuid.uuid4()

    async def _reject(*args: Any, **kwargs: Any) -> list[Any]:
        raise ForbiddenException("设备不可用或无权关联")

    monkeypatch.setattr(
        "app.modules.equipment.public_api.validate_equipment_references", _reject
    )
    with pytest.raises(ForbiddenException, match="无权关联"):
        await service._get_external_source(
            cast(AsyncSession, _FakeDb()),
            "EQUIPMENT",
            "equipment",
            "equipment",
            source_id,
            cast(User, SimpleNamespace(id=uuid.uuid4())),
        )


@pytest.mark.asyncio
async def test_qa_external_availability_does_not_reexpose_revoked_equipment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """撤销后的设备在来源可用性查询中只能得到不可用，不会重新暴露摘要。"""
    source_id = uuid.uuid4()
    source = MasterObjectSource(
        master_object_id=uuid.uuid4(),
        source_module="equipment",
        source_entity="equipment",
        source_id=source_id,
        source_code_snapshot="EQ-REVOKED",
        source_name_snapshot="已撤销设备",
    )
    source.id = uuid.uuid4()
    user = cast(User, SimpleNamespace(id=uuid.uuid4()))
    calls: list[tuple[Any, Any, Any, Any]] = []

    async def _refs(db: Any, actor: Any, module: str, ids: Any) -> list[Any]:
        calls.append((db, actor, module, ids))
        return []

    monkeypatch.setattr(
        "app.modules.equipment.public_api.get_equipment_references_by_ids", _refs
    )
    result = await service._availability_map(
        cast(AsyncSession, _FakeDb()), [source], user
    )

    assert result == {source.id: False}
    assert calls and calls[0][1:] == (user, "qa", [source_id])


@pytest.mark.asyncio
async def test_region_parent_rejects_self_and_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """区域不能自引用，也不能通过父级链形成循环。"""
    object_id = uuid.uuid4()
    with pytest.raises(AppException) as self_error:
        await service._validate_region_parent(
            cast(AsyncSession, _FakeDb()), object_id, object_id
        )
    assert self_error.value.status_code == 422

    parent = MasterObject(
        object_type="REGION",
        code="PARENT",
        normalized_code="PARENT",
        name="父区域",
        status="active",
    )
    parent.id = uuid.uuid4()
    parent.region_parent_id = object_id
    monkeypatch.setattr(service, "get_master", _returning(parent))

    with pytest.raises(AppException) as cycle_error:
        await service._validate_region_parent(
            cast(AsyncSession, _FakeDb()), object_id, parent.id
        )
    assert cycle_error.value.status_code == 422


@pytest.mark.asyncio
async def test_create_version_requires_external_approval_and_cleans_failed_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """版本必须声明外部批准，数据库写入失败时清理已上传的孤儿文件。"""
    document = _document()
    db = _FakeDb([_Result(scalar=document), _Result()])
    store_calls: list[bool] = []

    def _store_and_record(*_args: Any) -> StoredFile:
        store_calls.append(True)
        return _stored_file()

    monkeypatch.setattr(service, "_next_version_sequence", _sequence_one)
    monkeypatch.setattr(service, "_audit", _async_noop)
    monkeypatch.setattr(service.file_service, "store_file", _store_and_record)

    with pytest.raises(AppException) as error:
        await service.create_version(
            cast(AsyncSession, db),
            document.id,
            version_label="V1.0",
            approved_declared=False,
            filename="approved.pdf",
            content_type="application/pdf",
            data=b"content",
        )
    assert error.value.status_code == 422
    assert store_calls == []

    cleanup: list[Any] = []
    db = _FakeDb([_Result(scalar=document), _Result()])
    monkeypatch.setattr(
        service.file_service, "cleanup_stored_file", lambda value: cleanup.append(value)
    )
    original_flush = db.flush

    async def fail_second_flush() -> None:
        if db.flush_count >= 1:
            raise RuntimeError("database write failed")
        await original_flush()

    db.flush = fail_second_flush  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await service.create_version(
            cast(AsyncSession, db),
            document.id,
            version_label="V1.0",
            approved_declared=True,
            filename="approved.pdf",
            content_type="application/pdf",
            data=b"content",
        )
    assert cleanup and cleanup[0].key == "documents/test.pdf"


@pytest.mark.asyncio
async def test_relations_reject_inactive_master_and_soft_delete_old_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """版本关联只接受启用主数据，并以软删除方式替换旧关系。"""
    version = _version()
    old_link = DocumentMasterLink(
        version_id=version.id,
        master_object_id=uuid.uuid4(),
        relation_type="APPLIES_TO",
        code_snapshot="OLD",
        name_snapshot="旧设备",
    )
    old_link.id = uuid.uuid4()
    active = MasterObject(
        object_type="EQUIPMENT",
        code="EQ-NEW",
        normalized_code="EQ-NEW",
        name="新设备",
        status="active",
    )
    active.id = uuid.uuid4()
    inactive = MasterObject(
        object_type="EQUIPMENT",
        code="EQ-OFF",
        normalized_code="EQ-OFF",
        name="停用设备",
        status="inactive",
    )
    inactive.id = uuid.uuid4()
    monkeypatch.setattr(service, "get_version", _returning(version))
    monkeypatch.setattr(service, "_get_version_with_document_lock", _returning(version))
    monkeypatch.setattr(service, "_audit", _async_noop)
    monkeypatch.setattr(service, "get_master", _returning(active))
    db = _FakeDb([_Result(rows=[old_link])])

    rows = await service.set_relations(
        cast(AsyncSession, db), version.id, [RelationIn(master_object_id=active.id)]
    )

    assert old_link.is_deleted is True
    assert rows[0].code_snapshot == "EQ-NEW"
    assert rows[0].name_snapshot == "新设备"

    monkeypatch.setattr(service, "get_master", _returning(inactive))
    with pytest.raises(AppException) as error:
        await service.set_relations(
            cast(AsyncSession, db),
            version.id,
            [RelationIn(master_object_id=inactive.id)],
        )
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_relations_allow_current_version_but_freeze_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """现行版本仍可维护关联；历史/停用版本作为过审快照冻结。"""
    active = MasterObject(
        object_type="EQUIPMENT",
        code="EQ-CUR",
        normalized_code="EQ-CUR",
        name="现行关联设备",
        status="active",
    )
    active.id = uuid.uuid4()
    monkeypatch.setattr(service, "_audit", _async_noop)
    monkeypatch.setattr(service, "get_master", _returning(active))

    current = _version(status=VersionStatus.CURRENT.value)
    current.locked_at = current.first_locked_at = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(service, "_get_version_with_document_lock", _returning(current))
    rows = await service.set_relations(
        cast(AsyncSession, _FakeDb([_Result(rows=[])])),
        current.id,
        [RelationIn(master_object_id=active.id)],
    )
    assert [row.master_object_id for row in rows] == [active.id]

    history = _version(status=VersionStatus.HISTORY.value)
    monkeypatch.setattr(service, "_get_version_with_document_lock", _returning(history))
    with pytest.raises(AppException) as error:
        await service.set_relations(
            cast(AsyncSession, _FakeDb()),
            history.id,
            [RelationIn(master_object_id=active.id)],
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_relations_append_keeps_existing_links_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """追加语义默认不清理既有关系：提案审批的自动关联只传新增对象。"""
    version = _version()
    kept_link = DocumentMasterLink(
        version_id=version.id,
        master_object_id=uuid.uuid4(),
        relation_type="APPLIES_TO",
        code_snapshot="EQ-OLD",
        name_snapshot="既有设备",
    )
    kept_link.id = uuid.uuid4()
    approved = MasterObject(
        object_type="EQUIPMENT",
        code="EQ-AI",
        normalized_code="EQ-AI",
        name="提案新建设备",
        status="active",
    )
    approved.id = uuid.uuid4()
    monkeypatch.setattr(service, "_audit", _async_noop)
    monkeypatch.setattr(service, "_get_version_with_document_lock", _returning(version))
    db = _FakeDb([_Result(rows=[kept_link]), _Result(rows=[approved])])

    rows = await service.set_relations_append(
        cast(AsyncSession, db), version.id, [approved.id]
    )

    assert not kept_link.is_deleted
    assert {row.master_object_id for row in rows} == {
        kept_link.master_object_id,
        approved.id,
    }
    assert [row.code_snapshot for row in db.added] == ["EQ-AI"]


@pytest.mark.asyncio
async def test_relations_append_prunes_missing_only_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式 prune_missing 才软删除未出现在最终集合里的既有关系。"""
    version = _version()
    removed_link = DocumentMasterLink(
        version_id=version.id,
        master_object_id=uuid.uuid4(),
        relation_type="APPLIES_TO",
        code_snapshot="EQ-RM",
        name_snapshot="被移除设备",
    )
    removed_link.id = uuid.uuid4()
    kept = MasterObject(
        object_type="EQUIPMENT",
        code="EQ-KEEP",
        normalized_code="EQ-KEEP",
        name="保留设备",
        status="active",
    )
    kept.id = uuid.uuid4()
    monkeypatch.setattr(service, "_audit", _async_noop)
    monkeypatch.setattr(service, "_get_version_with_document_lock", _returning(version))
    db = _FakeDb([_Result(rows=[removed_link]), _Result(rows=[kept])])

    rows = await service.set_relations_append(
        cast(AsyncSession, db), version.id, [kept.id], prune_missing=True
    )

    assert removed_link.is_deleted is True
    assert [row.master_object_id for row in rows] == [kept.id]


@pytest.mark.asyncio
async def test_make_current_moves_previous_to_history_and_locks_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """设置当前版本时锁定目标版本，并将旧当前版本转为历史版本。"""
    document = _document()
    previous = _version(status=VersionStatus.CURRENT.value)
    previous.document_id = document.id
    target = _version()
    target.document_id = document.id
    document.current_version_id = previous.id
    file_row = SimpleNamespace(sha256="abc123")
    # 第三次是 UPDATE 后的 re-fetch（回填 updated_at），返回被设为当前的 target
    monkeypatch.setattr(
        service, "get_version", _returning_sequence([target, previous, target])
    )
    monkeypatch.setattr(service, "get_file_for_version", _returning(file_row))
    monkeypatch.setattr(service, "_audit", _async_noop)
    db = _FakeDb([_Result(scalar=document)])

    result = await service.make_current(cast(AsyncSession, db), document.id, target.id)

    assert result is target
    assert document.current_version_id == target.id
    assert target.status == VersionStatus.CURRENT.value
    assert target.locked_at is not None
    assert target.first_locked_at is not None
    assert previous.status == VersionStatus.HISTORY.value
    assert previous.locked_at is not None


@pytest.mark.asyncio
async def test_disable_current_version_is_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当前版本不能直接停用，必须先切换当前指针。"""
    current = _version(status=VersionStatus.CURRENT.value)
    monkeypatch.setattr(service, "get_version", _returning(current))
    monkeypatch.setattr(service, "_get_version_with_document_lock", _returning(current))

    with pytest.raises(AppException) as error:
        await service.disable_version(cast(AsyncSession, _FakeDb()), current.id)
    assert error.value.status_code == 409


async def _async_noop(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _department_ok(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
    return "dept-qa", "质量部"


async def _source_ok(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
    return "EQ-01-SOURCE", "来源设备"


async def _sequence_one(*_args: Any, **_kwargs: Any) -> int:
    return 1


def _stored_file() -> StoredFile:
    return StoredFile(
        key="documents/test.pdf",
        original_filename="approved.pdf",
        extension="pdf",
        mime_type="application/pdf",
        size_bytes=7,
        sha256="a" * 64,
    )


def _returning(value: Any) -> Callable[..., Awaitable[Any]]:
    async def _func(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _func


def _returning_sequence(values: list[Any]) -> Callable[..., Awaitable[Any]]:
    remaining = list(values)

    async def _func(*_args: Any, **_kwargs: Any) -> Any:
        return remaining.pop(0)

    return _func
