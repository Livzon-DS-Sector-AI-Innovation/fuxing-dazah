"""emergency_drill 消费入口直读分支单测（Ticket 03/04）。

覆盖：service.list_records/get_stats 直读分支与 legacy 分支（全关=改造前行为）、
resolve_record / resolve_pg_record 双态、采集表查询不受 DIRECT 影响、
API schema 对视图校验、Agent 工具映射兼容 recXXX、write tool 双态。
"""

from __future__ import annotations

import uuid as uuid_mod
from typing import Any

import pytest

from app.modules.safety.schemas.emergency_drills import DrillRecordResponse
from app.modules.safety.service.emergency_drill import EmergencyDrillService
from app.modules.safety.service.emergency_drill_direct import reader as reader_mod
from app.modules.safety.service.emergency_drill_direct.views import (
    EmergencyDrillRecordView,
    view_from_record_id,
)

ENV_DIRECT = "SAFETY_EMERGENCY_DRILL_DIRECT_ENABLED"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)


def _view(vid: str, **bitable_fields: Any) -> EmergencyDrillRecordView:
    """合成 Bitable 字段构造视图（kwargs 用中文列名，与探针形态一致）。"""
    base: dict[str, Any] = {
        "演练类型": "应急疏散演练",
        "演练部门": "设备动力部",
        "演练内容": [{"text": "第一季度火灾疏散演练", "type": "text"}],
    }
    base.update(bitable_fields)
    return view_from_record_id(vid, base)


class FakeReader:
    def __init__(self, views: list[EmergencyDrillRecordView]):
        self._views = views

    async def fetch_all(self, *, strict: bool = False) -> list[EmergencyDrillRecordView]:
        return self._views


def _make_service(
    monkeypatch: pytest.MonkeyPatch, views: list[EmergencyDrillRecordView]
) -> EmergencyDrillService:
    monkeypatch.setattr(reader_mod, "open_reader", lambda: FakeReader(views))
    return EmergencyDrillService(None)  # type: ignore[arg-type]


class FakeScalarResult:
    def __init__(self, value: Any):
        self._value = value

    def scalar(self, *_a: Any, **_k: Any) -> Any:
        return self._value


class FakeExecResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def scalars(self) -> FakeExecResult:
        return self

    def all(self) -> list[Any]:
        return self._rows


class FakeSession:
    """list_records/list_collection_records legacy 路径最小会话替身。"""

    def __init__(self, rows: list[Any], total: int):
        self.rows = rows
        self.total = total
        self.scalar_calls = 0

    async def scalar(self, *_a: Any, **_k: Any) -> int:
        self.scalar_calls += 1
        return self.total

    async def execute(self, *_a: Any, **_k: Any) -> FakeExecResult:
        return FakeExecResult(self.rows)


class TestListRecordsBranches:
    async def test_direct_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(
            monkeypatch, [_view("rec1"), _view("rec2", drill_type="现场岗位处置")]
        )
        items, total = await service.list_records(0, 20)
        assert total == 2
        assert [i.id for i in items] == ["rec1", "rec2"]

    async def test_direct_filters_and_pagination(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(
            monkeypatch,
            [
                _view("rec1"),
                _view("rec2", 演练内容=[{"text": "宿舍楼疏散演练", "type": "text"}]),
                _view("rec3", 演练类型="消防器材培训"),
            ],
        )
        items, total = await service.list_records(0, 20, keyword="宿舍")
        assert total == 1 and items[0].id == "rec2"
        items, total = await service.list_records(
            1, 1, drill_type="应急疏散演练"
        )
        assert total == 2 and [i.id for i in items] == ["rec2"]

    async def test_legacy_untouched_when_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """契约：开关全关 = 改造前镜像查询行为；直读 reader 不得被触碰。"""
        def _boom() -> None:
            raise AssertionError("DIRECT 关时不得构建直读 reader")

        monkeypatch.setattr(reader_mod, "open_reader", _boom)
        session = FakeSession(["row1", "row2"], total=2)
        service = EmergencyDrillService(session)  # type: ignore[arg-type]
        items, total = await service.list_records(0, 10, department="设备动力部")
        assert (total, len(items)) == (2, 2)
        assert session.scalar_calls == 1


class TestGetStatsBranches:
    async def test_direct_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [
            view_from_record_id("rec1", {
                "状态": "已完成", "实施时间": 1768924800000,
            }),
            view_from_record_id("rec2", {}),
        ])
        stats = await service.get_stats()
        assert stats.total == 2
        assert stats.executed == 1
        assert stats.completed == 1
        assert stats.pending == 1

    async def test_legacy_stats_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> None:
            raise AssertionError("DIRECT 关时不得构建直读 reader")

        monkeypatch.setattr(reader_mod, "open_reader", _boom)
        session = FakeSession([], total=7)
        service = EmergencyDrillService(session)  # type: ignore[arg-type]
        stats = await service.get_stats()
        assert stats.total == 7


class TestResolveRecord:
    async def test_direct_rec_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("recABC")])
        item = await service.resolve_record("recABC")
        assert item is not None and item.id == "recABC"

    async def test_uuid_goes_mirror_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _make_service(monkeypatch, [_view("recABC")])
        uid = uuid_mod.uuid4()
        row: Any = FakeRow({"id": uid})

        async def fake_get(rid: uuid_mod.UUID) -> Any:
            assert rid == uid
            return row

        monkeypatch.setattr(service, "get_record", fake_get)
        assert await service.resolve_record(str(uid)) is row

    async def test_legacy_rec_id_via_mirror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _make_service(monkeypatch, [_view("recABC")])
        row: Any = FakeRow({"feishu_record_id": "recABC"})

        async def fake_by_feishu(fid: str) -> Any:
            assert fid == "recABC"
            return row

        monkeypatch.setattr(service, "get_record_by_feishu_id", fake_by_feishu)
        assert await service.resolve_record("recABC") is row

    async def test_unknown_rec_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("recABC")])
        assert await service.resolve_record("recZZZ") is None


class TestResolvePgRecord:
    async def test_uuid_by_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = _make_service(monkeypatch, [])
        uid = uuid_mod.uuid4()
        row: Any = FakeRow({"id": uid})

        async def fake_get(rid: uuid_mod.UUID) -> Any:
            assert rid == uid
            return row

        monkeypatch.setattr(service, "get_record", fake_get)
        assert await service.resolve_pg_record(str(uid)) is row

    async def test_rec_by_feishu_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _make_service(monkeypatch, [])
        row: Any = FakeRow({"feishu_record_id": "recX"})

        async def fake_by_feishu(fid: str) -> Any:
            assert fid == "recX"
            return row

        monkeypatch.setattr(service, "get_record_by_feishu_id", fake_by_feishu)
        assert await service.resolve_pg_record("recX") is row

    async def test_missing_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = _make_service(monkeypatch, [])

        async def fake_none(fid: str) -> None:
            return None

        monkeypatch.setattr(service, "get_record_by_feishu_id", fake_none)
        assert await service.resolve_pg_record("recMISS") is None


class TestCollectionUnaffected:
    async def test_collection_stays_pg_under_direct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D2 契约：DIRECT 开时采集表三查询仍走 PG（解析态只在平台库）。"""
        def _boom() -> None:
            raise AssertionError("采集表查询不得走直读 reader")

        monkeypatch.setenv(ENV_DIRECT, "true")
        monkeypatch.setattr(reader_mod, "open_reader", _boom)
        session = FakeSession([FakeRow({"id": "c1"})], total=1)
        service = EmergencyDrillService(session)  # type: ignore[arg-type]
        items, total = await service.list_collection_records(0, 20)
        assert total == 1 and items[0].id == "c1"


class TestSchemaCompat:
    def test_response_validates_view(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.modules.safety.service.emergency_drill_direct.views.minio_enabled",
            lambda: True,
        )
        view = view_from_record_id("rec1", {
            "演练类型": "应急疏散演练",
            "演练部门": "设备动力部",
            "演练内容": [{"text": "内容", "type": "text"}],
            "实施时间": 1768924800000,
            "签到表": [{"file_token": "tok", "name": "a.pdf"}],
        })
        response = DrillRecordResponse.model_validate(view)
        assert response.id == "rec1"
        assert response.drill_type == "应急疏散演练"
        assert response.execution_time is not None
        from app.modules.safety import attachment_store

        assert response.signin_file == [
            "drill/"
            + attachment_store.safe_filename("drill_rec1_tok_a.pdf")
        ]
        assert response.is_deleted is False
        assert response.created_at is None

    def test_agent_item_mapping_compatible(self) -> None:
        """read_tools.items 映射口径（str(id) + 属性取值）对视图成立。"""
        import datetime as dt_mod

        view = _view("rec1")
        view.plan_time_ref = dt_mod.date(2026, 1, 5)
        mapped = {
            "id": str(view.id),
            "drill_content": view.drill_content,
            "drill_type": view.drill_type,
            "department": view.department,
            "organizer": view.organizer,
            "participants": view.participants,
            "plan_time": view.plan_time,
            "plan_time_ref": (
                str(view.plan_time_ref) if view.plan_time_ref else None
            ),
            "duration": view.duration,
            "notes": view.notes,
        }
        assert mapped["id"] == "rec1"
        assert mapped["plan_time_ref"] == "2026-01-05"


class TestAgentWriteTool:
    """write_tools.generate_drill_plan 双态（Ticket 04）：recXXX/UUID 均可解析。"""

    def _ctx(self) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(deps=SimpleNamespace(db=None))

    def _patch_service(self, monkeypatch: pytest.MonkeyPatch, row_id: Any) -> list[str]:
        calls: list[str] = []

        class FakeDoc:
            id = "doc-1"
            title = "演练方案"
            doc_type = "drill_plan"
            version = 1
            feishu_doc_url = "https://example.doc"
            feishu_doc_status = "created"

        class FakeService:
            def __init__(self, db: Any) -> None:
                pass

            async def resolve_pg_record(self, rid: str) -> Any:
                calls.append(f"resolve:{rid}")
                if rid in ("recX", str(row_id)):
                    return FakeRow({"id": row_id})
                return None

            async def generate_drill_plan(self, rid: Any) -> Any:
                calls.append(f"generate:{rid}")
                return FakeDoc()

        monkeypatch.setattr(
            "app.modules.safety.service.emergency_drill.EmergencyDrillService",
            FakeService,
        )
        return calls

    async def test_rec_id_resolves_to_pg_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.safety.business_agent.tools import write_tools

        row_id = uuid_mod.uuid4()
        calls = self._patch_service(monkeypatch, row_id)
        result = await write_tools.generate_drill_plan(self._ctx(), "recX")
        assert result["document_id"] == "doc-1"
        assert calls == ["resolve:recX", f"generate:{row_id}"]

    async def test_uuid_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools import write_tools

        row_id = uuid_mod.uuid4()
        calls = self._patch_service(monkeypatch, row_id)
        result = await write_tools.generate_drill_plan(self._ctx(), str(row_id))
        assert result["action"] == "drill_plan_generated"
        assert calls == [f"resolve:{row_id}", f"generate:{row_id}"]

    async def test_unknown_returns_error_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.safety.business_agent.tools import write_tools

        self._patch_service(monkeypatch, uuid_mod.uuid4())
        result = await write_tools.generate_drill_plan(self._ctx(), "recNOPE")
        assert "error" in result
        assert "演练计划不存在" in result["error"]


class FakeRow:
    def __init__(self, values: dict[str, Any]):
        self.__dict__.update(values)
