"""cert 08:00 预警编排双路径单测（cert-direct Ticket 03）。

覆盖：开关三态（全关=ORM 镜像路径 / DIRECT 开=直读路径 / 直读 strict 失败上抛）、
两条路径三级推送内容逐字一致（替身注入同源数据）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest

import app.core.database as db_mod
import app.modules.safety.feishu as feishu_pkg
import app.modules.safety.feishu.notification as notification_mod
import app.modules.safety.service.cert_warning as cert_warning_mod
from app.modules.safety.scheduler import _run_cert_warning_notification
from app.modules.safety.service.cert_direct import reader as cert_reader_mod
from app.modules.safety.service.cert_warning import CertWarningService


@dataclass
class FakePerson:
    open_id: str


class FakeResolver:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def resolve_by_name(
        self, name: str, department_hint: str | None = None
    ) -> FakePerson:
        return FakePerson(open_id=f"ou-{name}")

    async def resolve_department_leader(self, dept: str) -> FakePerson:
        return FakePerson(open_id=f"ou-leader-{dept}")


class FakeSessionFactory:
    def __call__(self) -> FakeSessionFactory:
        return self

    async def __aenter__(self) -> FakeSessionFactory:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class SentCard:
    def __init__(self, open_id: str, title: str, content: str) -> None:
        self.open_id = open_id
        self.title = title
        self.content = content


def _make_views() -> list[dict[str, Any]]:
    """两条 active（urgent special_op + overdue guardian_a）+ 一条 normal。"""
    today = date.today()
    urgent = dict(
        id="recU", cert_category="special_op", person_name="张三",
        department="生产部", next_review_date=today + timedelta(days=3),
        review_frequency="3年", should_renew_date=None, renewed_date=None,
        issue_date=None, first_review_deadline=None, second_review_deadline=None,
    )
    overdue = dict(
        id="recO", cert_category="guardian_a", person_name="李四",
        department="质检部", next_review_date=None, review_frequency=None,
        should_renew_date=today - timedelta(days=10), renewed_date=None,
        issue_date=None, first_review_deadline=None, second_review_deadline=None,
    )
    normal = dict(
        id="recN", cert_category="special_op", person_name="王五",
        department="生产部", next_review_date=today + timedelta(days=200),
        review_frequency="3年", should_renew_date=None, renewed_date=None,
        issue_date=None, first_review_deadline=None, second_review_deadline=None,
    )
    return [urgent, overdue, normal]


def _views_from_dicts(dicts: list[dict[str, Any]]) -> list[Any]:
    from app.modules.safety.service.cert_direct.reader import CertWarningView

    return [CertWarningView(**d) for d in dicts]


class _FakeRepo:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def get_all_active(self) -> list[Any]:
        return list(self._rows)


class _FakeService:
    def __init__(self, rows: list[Any]) -> None:
        self.repo = _FakeRepo(rows)


def _fake_service_factory(rows: list[Any]) -> Any:
    """替换 CertWarningService 类：repo 返回预置行；保留 _event_key
    （scheduler._build_full_summary_card 会在 patch 生效期间按名导入使用）。"""

    class _PatchedService:
        def __init__(self, session: Any) -> None:
            self.repo = _FakeRepo(rows)

    _PatchedService._event_key = staticmethod(  # type: ignore[attr-defined]
        CertWarningService._event_key
    )
    return _PatchedService


def _no_direct(**_kw: Any) -> Any:
    raise AssertionError("直读不该被调用")


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> list[SentCard]:
    """替身化身份解析 / 推送 / session 工厂，返回推送记录列表。"""
    sent: list[SentCard] = []

    async def _fake_send(*, open_id: str, title: str, content: str) -> None:
        sent.append(SentCard(open_id, title, content))

    monkeypatch.setattr(notification_mod, "send_user_card", _fake_send)
    monkeypatch.setattr(feishu_pkg, "IdentityResolver", FakeResolver)
    monkeypatch.setattr(db_mod, "async_session_factory", FakeSessionFactory())
    return sent


async def test_direct_off_uses_mirror_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全关（默认）：走 ORM 镜像路径（CertWarningService.repo.get_all_active）。"""
    monkeypatch.delenv("SAFETY_CERT_DIRECT_ENABLED", raising=False)
    sent = _patch_common(monkeypatch)
    views = _views_from_dicts(_make_views())

    monkeypatch.setattr(
        cert_warning_mod, "CertWarningService", _fake_service_factory(views),
    )
    # 直读误用时立即暴露：镜像路径不应触碰 open_reader
    monkeypatch.setattr(cert_reader_mod, "open_reader", _no_direct)

    await _run_cert_warning_notification()

    # 本人 2 张（urgent+overdue）+ 部门 2 张 + 安管全量 1 张；normal 不推送
    assert len(sent) == 5
    titles = [c.title for c in sent]
    assert "持证到期提醒" in titles
    assert "生产部 持证到期汇总" in titles
    assert "质检部 持证到期汇总" in titles
    assert "全厂持证到期预警汇总" in titles


async def test_direct_on_push_equivalence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DIRECT 开：直读路径推送内容与 ORM 路径逐字一致（同源数据）。"""
    views_dicts = _make_views()

    sent_mirror: list[SentCard] = []
    monkeypatch.delenv("SAFETY_CERT_DIRECT_ENABLED", raising=False)
    sent_mirror.extend(_patch_common(monkeypatch))
    views = _views_from_dicts(views_dicts)

    monkeypatch.setattr(
        cert_warning_mod, "CertWarningService", _fake_service_factory(views),
    )
    await _run_cert_warning_notification()

    # 切直读重跑
    sent_direct: list[SentCard] = []
    monkeypatch.setenv("SAFETY_CERT_DIRECT_ENABLED", "true")
    sent_direct.extend(_patch_common(monkeypatch))

    class _DirectReader:
        async def get_all_active(self, *, strict: bool = False) -> list[Any]:
            return _views_from_dicts(views_dicts)

    monkeypatch.setattr(
        cert_reader_mod, "open_reader", lambda **kw: _DirectReader(),
    )
    await _run_cert_warning_notification()

    key = lambda c: (c.title, c.open_id, c.content)  # noqa: E731
    assert sorted(map(key, sent_mirror)) == sorted(map(key, sent_direct))


async def test_direct_on_strict_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """直读单表失败（strict）→ 聚合上抛（调度器标 failed 走补发）。"""
    monkeypatch.setenv("SAFETY_CERT_DIRECT_ENABLED", "true")
    _patch_common(monkeypatch)

    class _BoomReader:
        async def get_all_active(self, *, strict: bool = False) -> list[Any]:
            raise RuntimeError("cert 直读单表拉取失败（strict）: guardian_b")

    monkeypatch.setattr(cert_reader_mod, "open_reader", lambda **kw: _BoomReader())

    with pytest.raises(RuntimeError, match="strict"):
        await _run_cert_warning_notification()
