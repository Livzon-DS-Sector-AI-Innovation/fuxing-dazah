"""cert API/Agent 直读切换单测（cert-direct Ticket 05）。

覆盖：API 列表/summary 双路径（直读 meta.mode；legacy meta 不变）、
renew 直读短路 400、Agent query 双路径、Agent renew 直读 error。
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

import app.modules.safety.service.cert_warning as cert_warning_mod
from app.modules.safety.api import cert_warnings as api_mod
from app.modules.safety.business_agent.tools import read_tools, write_tools
from app.modules.safety.schemas.cert_warnings import (
    CertWarningDetail,
    RenewRequest,
)
from app.modules.safety.service.cert_direct import reader as cert_reader_mod
from app.modules.safety.service.cert_direct.reader import CertWarningView

_DIRECT_MESSAGE = "直读模式下回填不可用"


def _view(vid: str, category: str, dept: str) -> CertWarningView:
    return CertWarningView(
        id=vid,
        cert_category=category,
        person_name=f"人-{vid}",
        department=dept,
        next_review_date=date.today() + timedelta(days=3),
        review_frequency="3年",
    )


def _sample_views() -> list[CertWarningView]:
    return [
        _view("recU", "special_op", "生产部"),
        _view("recG", "guardian_a", "质检部"),
    ]


class FakeReader:
    def __init__(self, views: list[CertWarningView]) -> None:
        self._views = views

    async def get_all_active(self, *, strict: bool = True) -> list[CertWarningView]:
        return list(self._views)


def _patch_direct_reader(
    monkeypatch: pytest.MonkeyPatch, views: list[CertWarningView]
) -> None:
    monkeypatch.setenv("SAFETY_CERT_DIRECT_ENABLED", "true")
    monkeypatch.setattr(
        cert_reader_mod, "open_reader", lambda **kw: FakeReader(views)
    )


def _ctx(db: Any) -> Any:
    # deps.person 为 write_tools._current_user_id 所需（None → user_id=None）
    return SimpleNamespace(
        deps=SimpleNamespace(db=db, person=None),
    )


class _DetailService:
    """返回单条派生 Detail 的 CertWarningService 替身（镜像路径用）。"""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def get_warnings(self, **_kw: Any) -> tuple[list[CertWarningDetail], int]:
        return [CertWarningDetail.model_validate(_sample_views()[0])], 1

    async def get_summary(self, **_kw: Any) -> Any:
        from app.modules.safety.schemas.cert_warnings import CertWarningSummary

        return CertWarningSummary(total=1, urgent_count=1)

    async def renew(self, cert_id: uuid.UUID, data: RenewRequest, *,
                    user_id: Any = None) -> CertWarningDetail:
        return CertWarningDetail.model_validate(_sample_views()[0])


class TestApiEndpoints:
    async def test_list_direct_mode_meta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_direct_reader(monkeypatch, _sample_views())
        resp = await api_mod.get_cert_warnings(
            page=1, page_size=20, status_level=None, department=None,
            cert_category=None, days_within=None, db=cast(Any, None), current_user=None,
        )
        assert resp.meta is not None
        assert resp.meta["mode"] == "direct"
        assert resp.meta["total"] == 2
        assert [d.id for d in resp.data] == ["recU", "recG"]

    async def test_list_mirror_meta_unchanged(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """开关全关：列表 meta 与改造前逐项一致（无 mode 键）。"""
        monkeypatch.delenv("SAFETY_CERT_DIRECT_ENABLED", raising=False)
        monkeypatch.setattr(api_mod, "CertWarningService", _DetailService)
        resp = await api_mod.get_cert_warnings(
            page=1, page_size=20, status_level=None, department=None,
            cert_category=None, days_within=None, db=cast(Any, None), current_user=None,
        )
        assert resp.meta is not None
        assert "mode" not in resp.meta
        assert resp.meta["total"] == 1

    async def test_summary_direct_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_direct_reader(monkeypatch, _sample_views())
        resp = await api_mod.get_cert_warnings_summary(
            department=None, cert_category=None, db=cast(Any, None), current_user=None,
        )
        assert resp.meta is not None
        assert resp.meta["mode"] == "direct"
        assert resp.data.total == 2

    async def test_renew_direct_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_CERT_DIRECT_ENABLED", "true")
        resp = await api_mod.renew_cert_warning(
            uuid.uuid4(), RenewRequest(next_review_date="2027-01-01"),
            db=cast(Any, None), current_user=None,
        )
        assert resp.code == 400
        assert _DIRECT_MESSAGE in resp.message

    async def test_renew_legacy_unchanged(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("SAFETY_CERT_DIRECT_ENABLED", raising=False)
        monkeypatch.setattr(api_mod, "CertWarningService", _DetailService)
        resp = await api_mod.renew_cert_warning(
            uuid.uuid4(), RenewRequest(next_review_date="2027-01-01"),
            db=cast(Any, None), current_user=None,
        )
        assert resp.code == 200
        assert resp.data.id == "recU"


class TestAgentTools:
    async def test_query_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_direct_reader(monkeypatch, _sample_views())
        out = await read_tools.query_cert_warnings(_ctx(None))
        assert out["total"] == 2
        assert out["items"][0]["id"] == "recU"
        assert out["items"][0]["status_level"] == "urgent"

    async def test_query_mirror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_CERT_DIRECT_ENABLED", raising=False)
        monkeypatch.setattr(cert_warning_mod, "CertWarningService", _DetailService)
        out = await read_tools.query_cert_warnings(_ctx(None))
        assert out["total"] == 1

    async def test_renew_direct_disabled(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SAFETY_CERT_DIRECT_ENABLED", "true")
        out = await write_tools.renew_person_certificate(
            _ctx(None), str(uuid.uuid4()), next_review_date="2027-01-01",
        )
        assert _DIRECT_MESSAGE in out["error"]

    async def test_renew_legacy_unchanged(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("SAFETY_CERT_DIRECT_ENABLED", raising=False)
        monkeypatch.setattr(cert_warning_mod, "CertWarningService", _DetailService)
        out = await write_tools.renew_person_certificate(
            _ctx(None), str(uuid.uuid4()), next_review_date="2027-01-01",
        )
        assert "error" not in out
        assert out["message"] == "已回填，预警状态已刷新"
