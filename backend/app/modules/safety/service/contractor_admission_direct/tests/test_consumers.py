"""contractor_admission 消费入口直读分支单测（Ticket 04/05/07）。

覆盖：service.get_list/get_stats 直读分支（触发器挂载）、resolve_detail id 双态、
run_admission_audit_dual 直读解析、_writeback_review WRITEBACK_AI 两态、
API schema 对视图校验、Agent items 映射兼容 recXXX、handler 两处闸门。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.modules.safety.schemas import (
    ContractorAdmissionListItem,
    ContractorAdmissionResponse,
)
from app.modules.safety.service.contractor_admission import ContractorAdmissionService
from app.modules.safety.service.contractor_admission_direct import (
    config as direct_config,
)
from app.modules.safety.service.contractor_admission_direct import reader as reader_mod
from app.modules.safety.service.contractor_admission_direct.views import (
    ContractorAdmissionView,
    view_from_record_id,
)

ENV_DIRECT = "SAFETY_CONTRACTOR_ADMISSION_DIRECT_ENABLED"
ENV_WRITEBACK = "SAFETY_CONTRACTOR_ADMISSION_WRITEBACK_AI_ENABLED"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ENV_DIRECT, ENV_WRITEBACK,
                 "SAFETY_CONTRACTOR_ADMISSION_EVENT_SYNC_ENABLED"):
        monkeypatch.delenv(name, raising=False)


def _view(vid: str = "rec1", *, completed: bool = False) -> ContractorAdmissionView:
    view = view_from_record_id(vid, {
        "作业单位名称": [{"text": "某某公司", "type": "text"}],
        "相关方类型": "承包商",
        "提交状态": "已完成",
        "入厂日期": 1765382400000,
        "承包商安全管理协议": [{"file_token": "tok_a", "name": "协议.pdf"}],
        "AI审核结论": ("审核通过" if completed else None),
    })
    view.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return view


class FakeReader:
    def __init__(self, views: list[ContractorAdmissionView]):
        self._views = views
        self.strict_used: bool | None = None

    async def fetch_all(self, *, strict: bool = False) -> list[ContractorAdmissionView]:
        self.strict_used = strict
        return self._views


def _make_service(monkeypatch: pytest.MonkeyPatch,
                  views: list[ContractorAdmissionView]) -> ContractorAdmissionService:
    monkeypatch.setattr(reader_mod, "open_reader", lambda: FakeReader(views))
    return ContractorAdmissionService(None)  # type: ignore[arg-type]


class TestServiceDirectBranches:
    async def test_get_list_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("rec1"), _view("rec2")])
        triggered: list[list[str]] = []

        async def fake_trigger(views: list[ContractorAdmissionView]) -> None:
            triggered.append([v.id for v in views])

        monkeypatch.setattr(service, "_maybe_trigger_direct_reviews", fake_trigger)
        items, total = await service.get_list(
            {"related_party_type": "承包商"}, page=1, page_size=20
        )
        assert total == 2
        assert [i.id for i in items] == ["rec1", "rec2"]
        assert triggered == [["rec1", "rec2"]]

    async def test_get_list_legacy_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """开关全关走 repo 镜像路径（契约：全关=改造前行为）。"""
        service = ContractorAdmissionService(None)  # type: ignore[arg-type]
        called: dict[str, Any] = {}

        async def fake_repo_get(**kwargs: Any) -> tuple[list[Any], int]:
            called.update(kwargs)
            return ["row"], 1

        monkeypatch.setattr(service.repo,
                            "get_contractor_admission_list", fake_repo_get)
        items, total = await service.get_list({"submit_status": "已完成"}, page=2,
                                              page_size=5)
        assert (items, total) == (["row"], 1)
        assert called["skip"] == 5 and called["limit"] == 5
        assert called["submit_status"] == "已完成"

    async def test_get_stats_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("rec1", completed=True),
                                              _view("rec2")])

        async def fake_trigger(views: list[ContractorAdmissionView]) -> None:
            return None

        monkeypatch.setattr(service, "_maybe_trigger_direct_reviews", fake_trigger)
        stats = await service.get_stats()
        assert stats["total"] == 2
        assert stats["by_ai_review_status"] == {"completed": 1, "none": 1}


class TestResolveDetail:
    async def test_direct_rec_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("recABC")])
        item = await service.resolve_detail("recABC")
        assert item is not None and item.id == "recABC"

    async def test_direct_uuid_via_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import uuid as uuid_mod

        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("recABC")])
        uid = uuid_mod.uuid4()

        class FakeRepo:
            async def get_contractor_admission_by_id(self, rid: Any) -> Any:
                assert rid == uid
                return FakeRow({"feishu_record_id": "recABC"})

        service.repo = FakeRepo()  # type: ignore[assignment]
        item = await service.resolve_detail(str(uid))
        assert item is not None and item.id == "recABC"

    async def test_direct_unknown_rec_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("recABC")])
        assert await service.resolve_detail("recZZZ") is None

    async def test_legacy_invalid_id_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """直读关：非法串 None→404（原 422，受控偏差落档）。"""
        service = ContractorAdmissionService(None)  # type: ignore[arg-type]
        assert await service.resolve_detail("not-a-uuid") is None


class TestRunAdmissionAuditDual:
    async def test_direct_rec_upserts_then_reviews(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("recABC")])
        calls: list[str] = []
        row = FakeRow({"id": "uuid-1"})

        async def fake_upsert(mapped: dict[str, Any], record_id: str,
                              table_kind: str) -> Any:
            calls.append(f"upsert:{record_id}:{table_kind}")
            assert mapped["company_name"] == "某某公司"
            return row

        async def fake_review(admission_id: Any, channel: str) -> Any:
            calls.append(f"review:{channel}")
            assert admission_id == "uuid-1"
            return row

        monkeypatch.setattr(service, "upsert_from_bitable", fake_upsert)
        monkeypatch.setattr(service, "run_admission_review", fake_review)
        result = await service.run_admission_audit_dual("recABC", channel="web")
        assert result is row
        assert calls == ["upsert:recABC:admission", "review:web"]

    async def test_direct_unknown_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_DIRECT, "true")
        service = _make_service(monkeypatch, [_view("recABC")])
        assert await service.run_admission_audit_dual("recZZZ") is None

    async def test_legacy_uuid_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import uuid as uuid_mod

        service = ContractorAdmissionService(None)  # type: ignore[arg-type]
        uid = uuid_mod.uuid4()
        row = FakeRow({"id": uid})
        calls: list[str] = []

        async def fake_review(admission_id: Any, channel: str) -> Any:
            calls.append(f"review:{admission_id}:{channel}")
            return row

        monkeypatch.setattr(service, "run_admission_review", fake_review)
        result = await service.run_admission_audit_dual(str(uid), channel="web")
        assert result is row
        assert calls == [f"review:{uid}:web"]


class TestWritebackGate:
    async def test_direct_writeback_off_skips_bitable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """直读+WRITEBACK_AI 关：跳过 Bitable 写（不构造客户端、不置防回环）。"""
        monkeypatch.setenv(ENV_DIRECT, "true")
        from app.modules.safety.feishu import bitable_client as client_mod
        from app.modules.safety.feishu import bitable_handler as bh

        def _boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("WRITEBACK_AI 关闭时不得触碰 Bitable")

        monkeypatch.setattr(client_mod, "SafetyBitableClient", _boom)
        monkeypatch.setattr(bh, "_set_sync_ignore", _boom)
        service = ContractorAdmissionService(None)  # type: ignore[arg-type]
        ok = await service._writeback_review(
            FakeRow({"feishu_record_id": "rec1"}),  # type: ignore[arg-type]
            _output(),
        )
        assert ok is True

    async def test_legacy_writeback_unconditional(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DIRECT 关（legacy）：WRITEBACK_AI 全关也不影响回写（全关=改造前行为）。"""
        from app.modules.safety.feishu import bitable_client as client_mod
        from app.modules.safety.feishu import bitable_handler as bh

        written: dict[str, Any] = {}

        class FakeClient:
            def __init__(self, app_token: str, table_id: str | None) -> None:
                pass

            async def update_record(self, record_id: str, fields: dict[str, Any]) -> bool:
                written.update(fields)
                return True

        async def fake_set_sync_ignore(record_id: str, ttl: int = 30) -> None:
            written["__ignore__"] = record_id

        monkeypatch.setattr(client_mod, "SafetyBitableClient", FakeClient)
        monkeypatch.setattr(bh, "_set_sync_ignore", fake_set_sync_ignore)
        monkeypatch.setattr(
            "app.modules.safety.feishu.contractor_admission_bitable.admission_app_token",
            lambda: "appX",
        )
        monkeypatch.setattr(
            "app.modules.safety.feishu.contractor_admission_bitable.admission_tables",
            lambda: {"admission": "tblX"},
        )
        service = ContractorAdmissionService(None)  # type: ignore[arg-type]
        ok = await service._writeback_review(
            FakeRow({"feishu_record_id": "rec1"}),  # type: ignore[arg-type]
            _output(),
        )
        assert ok is True
        # 写请求只含目标 3 列 + 防回环标记
        assert set(written) == {
            "__ignore__", "AI审核结论", "AI审核报告", "AI不符合项",
        }
        assert written["AI审核结论"] == "审核通过"
        assert written["AI不符合项"] == ["安全管理协议-A基础信息类"]


def _output() -> Any:
    from app.modules.safety.ai_contractor_review.schemas import (
        AdmissionDimensionResult,
        AdmissionReviewOutput,
    )

    return AdmissionReviewOutput(
        agreement=AdmissionDimensionResult(
            conclusion="审核通过", report="报告", defects=[],
        ),
        license=None,
        insurance=None,
        overall_conclusion="审核通过",
        overall_report="综合报告",
        defect_categories=["安全管理协议-A基础信息类"],
    )


class FakeRow:
    def __init__(self, values: dict[str, Any]):
        self.__dict__.update(values)


class TestSchemaCompat:
    def test_list_item_validates_view(self) -> None:
        item = ContractorAdmissionListItem.model_validate(_view("rec1", completed=True))
        assert item.id == "rec1"
        assert item.company_name == "某某公司"
        assert item.ai_overall_conclusion == "审核通过"
        assert item.created_at == datetime(2026, 1, 1, tzinfo=UTC)
        assert item.entry_date == date(2025, 12, 10)

    def test_response_validates_view(self) -> None:
        response = ContractorAdmissionResponse.model_validate(_view("rec1", completed=True))
        assert response.id == "rec1"
        assert response.feishu_table_id == "admission"
        assert response.source == "bitable"
        assert response.updated_at is None
        assert response.ai_review_result is not None
        assert response.ai_review_result.overall_conclusion == "审核通过"
        assert response.ai_review_result.agreement is None

    def test_agent_item_mapping_compatible(self) -> None:
        """read_tools.items 映射口径（str(id) + dict 取 key）对视图成立。"""
        view = _view("rec1", completed=True)
        mapped = {
            "id": str(view.id),
            "company_name": view.company_name,
            "related_party_type": view.related_party_type,
            "contact_person": view.contact_person,
            "liaison_user_name": view.liaison_user_name,
            "entry_date": view.entry_date.isoformat() if view.entry_date else None,
            "submit_status": view.submit_status,
            "ai_review_status": view.ai_review_status,
            "ai_overall_conclusion": (view.ai_review_result or {}).get(
                "overall_conclusion"
            ),
        }
        assert mapped["id"] == "rec1"
        assert mapped["ai_overall_conclusion"] == "审核通过"


class TestHandlerGates:
    def test_direct_gate_short_circuits_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from app.modules.safety.feishu import contractor_admission_bitable_handler as h

        monkeypatch.setattr(direct_config, "legacy_event_sync_active", lambda: False)
        called: list[str] = []
        monkeypatch.setattr(
            h, "_match_table", lambda ft, tid: called.append("match")
        )
        asyncio.run(h._on_drive_record_changed({}))
        assert called == []  # 闸门短路，未触表匹配

    def test_legacy_gate_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from app.modules.safety.feishu import contractor_admission_bitable_handler as h

        monkeypatch.setattr(direct_config, "legacy_event_sync_active", lambda: True)
        called: list[str] = []
        monkeypatch.setattr(
            h, "_match_table", lambda ft, tid: called.append("match") or None
        )
        asyncio.run(h._on_drive_record_changed({}))
        assert called == ["match"]  # 全关=改造前行为：照常进入表匹配

    async def test_subscribe_gate_skips_when_direct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.safety.feishu import contractor_admission_bitable_handler as h

        monkeypatch.setattr(direct_config, "legacy_event_sync_active", lambda: False)
        assert await h.ensure_contractor_admission_bitable_subscribed() is False
