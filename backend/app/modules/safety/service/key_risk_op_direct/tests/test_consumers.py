"""消费端双路径单测（Ticket 03）：service/API/Agent 直读与 legacy 回归。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.key_risk_op_direct import config
from app.modules.safety.service.key_risk_operation_report import (
    KeyRiskOperationReportService,
)


class FakeReader:
    def __init__(self, views: list[Any]) -> None:
        self._views = views
        self.calls = 0

    async def fetch_all(self, *, strict: bool = False) -> list[Any]:
        self.calls += 1
        return list(self._views)


def _view(vid: str, *, dept: str = "提炼六部", status: str = "已通过",
          start: datetime | None = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)) -> Any:
    from app.modules.safety.service.key_risk_op_direct.views import KeyRiskOpView

    return KeyRiskOpView(
        id=vid, feishu_record_id=vid, report_no=f"NO-{vid}",
        department=dept, area="一号车间", operation_content=f"作业-{vid}",
        apply_status=status, start_time=start, duration_hours=2.0,
    )


def _seed_direct(monkeypatch: pytest.MonkeyPatch, views: list[Any]) -> FakeReader:
    from app.modules.safety.service.key_risk_op_direct import reader as rm

    reader = FakeReader(views)
    monkeypatch.setattr(config, "direct_enabled", lambda: True)
    monkeypatch.setattr(rm, "open_reader", lambda **kw: reader)
    return reader


def _seed_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety.service.key_risk_op_direct import reader as rm

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise AssertionError("legacy 不该触直读")

    monkeypatch.setattr(config, "direct_enabled", lambda: False)
    monkeypatch.setattr(rm, "open_reader", _boom)


def _svc() -> KeyRiskOperationReportService:
    return KeyRiskOperationReportService(None)  # type: ignore[arg-type]


class TestServiceDualPath:
    async def test_get_reports_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        views = [_view("r1"), _view("r2", dept="QC")]
        _seed_direct(monkeypatch, views)
        items, total = await _svc().get_reports(0, 10, "提炼六部")
        assert [v.id for v in items] == ["r1"]
        assert total == 1

    async def test_get_reports_legacy_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_legacy(monkeypatch)
        svc = _svc()
        sent: list[tuple[Any, ...]] = []

        async def _fake_repo(*args: Any, **_kw: Any) -> tuple[list[Any], int]:
            sent.append(args)
            return [], 0

        svc.repo = SimpleNamespace(get_key_risk_operation_reports=_fake_repo)  # type: ignore[assignment]
        await svc.get_reports(5, 10, "提炼六部")
        assert sent[0][:2] == (5, 10)

    async def test_get_report_direct_record_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_direct(monkeypatch, [_view("recXYZ")])
        item = await _svc().get_report("recXYZ")
        assert item is not None and item.id == "recXYZ"
        assert await _svc().get_report("recMiss") is None

    async def test_get_report_legacy_uuid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_legacy(monkeypatch)
        svc = _svc()
        rid = uuid.uuid4()
        captured: list[Any] = []

        async def _fake_by_id(value: Any) -> None:
            captured.append(value)
            return None

        svc.repo = SimpleNamespace(get_key_risk_operation_report_by_id=_fake_by_id)  # type: ignore[assignment]
        # UUID 直传
        await svc.get_report(rid)
        assert captured == [rid]
        # 字符串 UUID 解析；非法串 → None（API 层 404 口径）
        await svc.get_report(str(rid))
        assert captured[-1] == rid
        assert await svc.get_report("not-a-uuid") is None

    async def test_get_stats_direct_and_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        views = [_view("r1"), _view("r2", status="审批中")]
        _seed_direct(monkeypatch, views)
        stats = await _svc().get_stats()
        assert set(stats) == {"today_approved", "in_progress", "month_approved", "total"}
        assert stats["in_progress"] == 1 and stats["total"] == 2

        _seed_legacy(monkeypatch)
        svc = _svc()

        async def _fake_stats(*_a: Any) -> dict[str, int]:
            return {"today_approved": 9, "in_progress": 0,
                    "month_approved": 0, "total": 9}

        svc.repo = SimpleNamespace(get_key_risk_operation_stats=_fake_stats)  # type: ignore[assignment]
        assert (await svc.get_stats())["today_approved"] == 9

    async def test_sync_short_circuit_direct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """直读模式（DIRECT 开 + EVENT 关）：手动全量同步短路。"""
        from app.modules.safety.service.key_risk_op_direct import reader as rm

        monkeypatch.setattr(config, "legacy_event_sync_active", lambda: False)
        monkeypatch.setattr(
            rm, "open_reader",
            lambda **kw: (_ for _ in ()).throw(AssertionError("同步短路不该读直读")),
        )
        result = await _svc().sync_from_bitable()
        assert result == {"skipped": True, "reason": "direct_mode"}


class TestApiEndpoints:
    async def test_list_direct_meta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.api import key_risk_operation_reports as api_mod

        monkeypatch.setattr(config, "direct_enabled", lambda: True)

        class _FakeSvc:
            def __init__(self, _db: Any) -> None:
                pass

            async def get_reports(self, *args: Any, **_kw: Any) -> tuple[list[Any], int]:
                return [_view("rec1")], 1

        monkeypatch.setattr(api_mod, "KeyRiskOperationReportService", _FakeSvc)
        resp = await api_mod.get_key_risk_operation_reports(
            page=1, page_size=20, department=None, area=None,
            operation_content=None, apply_status=None, date_from=None,
            date_to=None, keyword=None, db=None, current_user=None)  # type: ignore[arg-type]
        assert resp.meta["mode"] == "direct"
        assert "elapsed_ms" in resp.meta
        assert resp.data[0].id == "rec1"  # schema id 放宽生效（响应为模型对象）

    async def test_stats_direct_meta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.api import key_risk_operation_reports as api_mod

        monkeypatch.setattr(config, "direct_enabled", lambda: True)

        class _FakeSvc:
            def __init__(self, _db: Any) -> None:
                pass

            async def get_stats(self) -> dict[str, int]:
                return {"today_approved": 0, "in_progress": 0,
                        "month_approved": 0, "total": 0}

        monkeypatch.setattr(api_mod, "KeyRiskOperationReportService", _FakeSvc)
        resp = await api_mod.get_key_risk_operation_stats(db=None, current_user=None)  # type: ignore[arg-type]
        assert resp.meta is not None and resp.meta["mode"] == "direct"

    async def test_detail_direct_rec_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.api import key_risk_operation_reports as api_mod

        monkeypatch.setattr(config, "direct_enabled", lambda: True)

        class _FakeSvc:
            def __init__(self, _db: Any) -> None:
                pass

            async def get_report(self, rid: Any) -> Any:
                return _view("recDetail") if rid == "recDetail" else None

        monkeypatch.setattr(api_mod, "KeyRiskOperationReportService", _FakeSvc)
        resp = await api_mod.get_key_risk_operation_report(
            report_id="recDetail", db=None, current_user=None)  # type: ignore[arg-type]
        assert resp.data.id == "recDetail"

    async def test_detail_legacy_malformed_404(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.safety.api import key_risk_operation_reports as api_mod

        monkeypatch.setattr(config, "direct_enabled", lambda: False)

        class _FakeSvc:
            def __init__(self, _db: Any) -> None:
                pass

            async def get_report(self, rid: Any) -> Any:
                # 真 service 语义：非法 UUID 串 → None（404）
                return None

        monkeypatch.setattr(api_mod, "KeyRiskOperationReportService", _FakeSvc)
        resp = await api_mod.get_key_risk_operation_report(
            report_id="not-a-uuid", db=None, current_user=None)  # type: ignore[arg-type]
        assert resp.code == 404


class TestAgentTool:
    async def test_query_tool_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_key_risk_ops,
        )

        views = [
            _view("recA", start=datetime(2026, 9, 10, 2, 0, tzinfo=UTC)),
            _view("recB", dept="QC", start=None),
        ]
        _seed_direct(monkeypatch, views)
        ctx = SimpleNamespace(deps=SimpleNamespace(db=object()))
        res = await query_key_risk_ops(ctx,  # type: ignore[arg-type]
                                       department="提炼六", date_from=None,
                                       date_to=None, apply_status=None,
                                       keyword=None, page=1, page_size=20)
        assert res["success"] is True
        assert res["total"] == 1
        item = res["items"][0]
        assert item["report_no"] == "NO-recA"
        assert item["department"] == "提炼六部"
        assert item["guardian"] is None  # 返回结构与 legacy 逐字段一致

    async def test_query_tool_direct_keyword_two_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_key_risk_ops,
        )

        _seed_direct(monkeypatch, [_view("recC")])
        ctx = SimpleNamespace(deps=SimpleNamespace(db=object()))
        res = await query_key_risk_ops(ctx,  # type: ignore[arg-type]
                                       department=None, date_from=None,
                                       date_to=None, apply_status=None,
                                       keyword="NO-recC", page=1, page_size=20)
        assert res["total"] == 0  # Agent 口径 keyword 不含编号
