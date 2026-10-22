"""未更新进展催办 · 收件人解析链的单元测试。

背景（2026-10-22 修复）：identity 通讯录同步被 40004 挡死，users/departments
表近乎空表，旧链 ``IdentityResolver`` 单走导致 4 项催办全部「收件人解析失败」。
修复后为三层链：Bitable 人员字段直取 → ``bitable_id_mapper`` 静态映射 →
identity 回退；分管安全员改 ``DEPARTMENT_CONFIG`` 直查（不再依赖空部门表）。

纯内存桩验证，不依赖 DB / 飞书网络 / Redis。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.feishu import bitable_id_mapper, daily_digest, mention
from app.modules.safety.feishu import notification, progress_card
from app.modules.safety.feishu.identity_resolver import ResolvedPerson
from app.modules.safety.service.hazard_direct import progress_dunning
from app.modules.safety.service.hazard_direct.bitable_repo import (
    F_INSPECTOR,
    F_RESPONSIBLE,
    HazardView,
)


class _FakeSessionCM:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: Any) -> None:
        return None


class _StubResolver:
    """identity 链桩：按表驱动返回，默认全部解析不到（模拟空表）。"""

    def __init__(
        self,
        by_name: dict[str, ResolvedPerson | None] | None = None,
        by_officer: dict[str, ResolvedPerson | None] | None = None,
    ) -> None:
        self.by_name = by_name or {}
        self.by_officer = by_officer or {}
        self.name_calls: list[str] = []

    async def resolve_by_name(
        self, name: str, department_hint: str | None = None
    ) -> ResolvedPerson | None:
        self.name_calls.append(name)
        return self.by_name.get(name)

    async def resolve_safety_officer(self, dept: str) -> ResolvedPerson | None:
        return self.by_officer.get(dept)


def _view(
    no: str,
    dept: str,
    *,
    responsible: list[dict] | None = None,
    inspector: list[dict] | None = None,
    responsible_name: str | None = None,
) -> HazardView:
    raw: dict[str, Any] = {}
    if responsible is not None:
        raw[F_RESPONSIBLE] = responsible
    if inspector is not None:
        raw[F_INSPECTOR] = inspector
    return HazardView(
        record_id=f"rec_{no}", hazard_no=no,
        description="未按期更新整改进展", department=dept,
        rectification_responsible_person_name=responsible_name,
        raw=raw,
    )


def _person(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, user_id=f"u_{name}", open_id=f"ou_{name}")


@pytest.fixture
def stub_resolver() -> _StubResolver:
    return _StubResolver()


def _install(
    monkeypatch: pytest.MonkeyPatch, stub: _StubResolver,
) -> None:
    """把 identity 会话与解析器整体替换为桩（DB 不触达）。"""
    import app.core.database as db_mod
    import app.modules.safety.feishu.identity_resolver as ir_mod

    monkeypatch.setattr(db_mod, "async_session_factory", _FakeSessionCM)
    monkeypatch.setattr(ir_mod, "IdentityResolver", lambda session: stub)


def _no_mapper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bitable_id_mapper, "get_bitable_open_id",
        lambda **kw: None,  # 静态映射缺人时不告警、只返回 None
    )


async def test_responsible_from_bitable_field_identity_dead(
    monkeypatch: pytest.MonkeyPatch, stub_resolver: _StubResolver,
) -> None:
    """责任人直取人员字段 open_id——identity 空表时仍可解析（本事故回归锚）。"""
    _install(monkeypatch, stub_resolver)
    _no_mapper(monkeypatch)

    v = _view(
        "HZ-034", "菌种中心",
        responsible=[{"name": "林礼枫", "id": "ou_live_lin"}],
        responsible_name="林礼枫",
    )
    plan = await progress_dunning.resolve_dunning_recipients([v])

    assert [(r, p.name, p.open_id, p.user_id, p.id_scope) for _, r, p in plan] == [
        ("责任人", "林礼枫", "ou_live_lin", "", "safety"),
    ]
    # 表内责任人直取命中，identity 链只被表外安全员（翁日生）求助
    assert stub_resolver.name_calls == ["翁日生"]


async def test_officer_from_dept_config_via_mapper(
    monkeypatch: pytest.MonkeyPatch, stub_resolver: _StubResolver,
) -> None:
    """分管安全员：DEPT_CONFIG 直查部门字段值，人名走静态映射——
    identity.departments 空表不再把安全员挡死（本事故回归锚）。"""
    _install(monkeypatch, stub_resolver)
    mapper_hits = {"翁日生": "ou_map_weng", "陈宇辉": "ou_map_chen"}
    monkeypatch.setattr(
        bitable_id_mapper, "get_bitable_open_id",
        lambda *, name=None, **kw: mapper_hits.get(name or ""),
    )

    views = [
        _view("HZ-034", "菌种中心", responsible=[{"name": "林礼枫", "id": "ou_lin"}]),
        _view("HZ-036", "精制工程一部", responsible=[{"name": "汪功剑", "id": "ou_wang"}]),
    ]
    plan = await progress_dunning.resolve_dunning_recipients(views)

    by_no: dict[str, dict[str, ResolvedPerson]] = {}
    for v, role, p in plan:
        by_no.setdefault(v.hazard_no, {})[role] = p
    assert by_no["HZ-034"]["分管安全员"].name == "翁日生"
    assert by_no["HZ-034"]["分管安全员"].open_id == "ou_map_weng"
    assert by_no["HZ-036"]["分管安全员"].name == "陈宇辉"
    assert by_no["HZ-036"]["分管安全员"].id_scope == "safety"


async def test_officer_harvested_from_inspector_field(
    monkeypatch: pytest.MonkeyPatch, stub_resolver: _StubResolver,
) -> None:
    """安全员姓名出现在任一记录「检查人员」字段时优先直取（免静态映射）。"""
    _install(monkeypatch, stub_resolver)
    _no_mapper(monkeypatch)

    v1 = _view(
        "HZ-034", "菌种中心",
        responsible=[{"name": "林礼枫", "id": "ou_lin"}],
        responsible_name="林礼枫",
        inspector=[{"name": "翁日生", "id": "ou_live_weng"}],
    )
    plan = await progress_dunning.resolve_dunning_recipients([v1])

    officers = [p for _, r, p in plan if r == "分管安全员"]
    assert [(p.name, p.open_id) for p in officers] == [("翁日生", "ou_live_weng")]


async def test_qc_override_responsible_via_mapper(
    monkeypatch: pytest.MonkeyPatch, stub_resolver: _StubResolver,
) -> None:
    """质量控制部（QC部）覆盖责任人陈雅芬（表外人名）走静态映射解析。"""
    _install(monkeypatch, stub_resolver)
    mapper_hits = {"陈雅芬": "ou_map_chen", "翁日生": "ou_map_weng"}
    monkeypatch.setattr(
        bitable_id_mapper, "get_bitable_open_id",
        lambda *, name=None, **kw: mapper_hits.get(name or ""),
    )

    v = _view(
        "HZ-035", "质量控制部（QC部）",
        responsible=[{"name": "其他某人", "id": "ou_other"}],
        responsible_name="其他某人",
    )
    plan = await progress_dunning.resolve_dunning_recipients([v])

    assert [(r, p.name) for _, r, p in plan] == [
        ("责任人", "陈雅芬"),      # 部门映射覆盖，不吃记录里的个人责任人
        ("分管安全员", "翁日生"),
    ]


async def test_identity_fallback_when_direct_sources_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """直取与静态映射都缺人时回退 identity 链（通讯录同步恢复后自动生效）。"""
    identity_person = ResolvedPerson(
        open_id="ou_plat", user_id="u_plat", name="何远树", id_scope="platform",
    )
    stub = _StubResolver(by_name={"何远树": identity_person})
    _install(monkeypatch, stub)
    _no_mapper(monkeypatch)

    # 人员字段 id 为空（直取失败）、映射缺人 → 走 identity 拿到平台作用域身份
    v = _view("HZ-004", "动力部",
              responsible=[{"name": "何远树", "id": ""}],
              responsible_name="何远树")
    plan = await progress_dunning.resolve_dunning_recipients([v])

    assert "何远树" in stub.name_calls
    resp = [p for _, r, p in plan if r == "责任人"]
    assert resp and resp[0].id_scope == "platform"


async def test_same_person_deduped_within_hazard(
    monkeypatch: pytest.MonkeyPatch, stub_resolver: _StubResolver,
) -> None:
    """同一隐患同一人兼任责任人与安全员 → 只保留一次。"""
    _install(monkeypatch, stub_resolver)
    _no_mapper(monkeypatch)

    # 提炼工程一部 leader=林礼枫 安全员=郑雅杰；构造责任人=郑雅杰 与安全员同人
    v = _view(
        "HZ-036", "提炼工程一部",
        responsible=[{"name": "郑雅杰", "id": "ou_zheng"}],
        responsible_name="郑雅杰",
    )
    plan = await progress_dunning.resolve_dunning_recipients([v])

    assert [(r, p.name) for _, r, p in plan] == [("责任人", "郑雅杰")]


async def test_multi_dept_split_resolves_both_officers(
    monkeypatch: pytest.MonkeyPatch, stub_resolver: _StubResolver,
) -> None:
    """部门一格多值（如「菌种中心, 精制工程一部」）拆分后两个安全员都收进来。"""
    _install(monkeypatch, stub_resolver)
    mapper_hits = {"翁日生": "ou_weng", "陈宇辉": "ou_chen", "杨剑": "ou_yang"}
    monkeypatch.setattr(
        bitable_id_mapper, "get_bitable_open_id",
        lambda *, name=None, **kw: mapper_hits.get(name or ""),
    )

    v = _view("HZ-001", "菌种中心, 精制工程一部",
              responsible=[{"name": "杨剑", "id": "ou_yang"}],
              responsible_name="杨剑")
    plan = await progress_dunning.resolve_dunning_recipients([v])

    officers = [p.name for _, r, p in plan if r == "分管安全员"]
    assert officers == ["翁日生", "陈宇辉"]


async def test_mention_split_by_id_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """@提及：直取来源（safety 作用域）open_id 直接用；identity 来源才走
    mention 链换算（identity 依赖被隔离到最小集）。"""
    v = _view("HZ-001", "菌种中心")
    safety_person = ResolvedPerson(
        open_id="ou_safety_direct", user_id="", name="林礼枫", id_scope="safety",
    )
    platform_person = ResolvedPerson(
        open_id="ou_plat_x", user_id="u_plat", name="翁日生", id_scope="platform",
    )
    plan = [(v, "责任人", safety_person), (v, "分管安全员", platform_person)]

    async def fake_overview() -> tuple[list[HazardView], int]:
        return [v], 1

    async def fake_resolve(views: list[HazardView]) -> list[Any]:
        return plan

    mention_calls: list[list[str]] = []

    async def fake_mention(names: Any) -> dict[str, str]:
        mention_calls.append(sorted(names))
        return {n: f"ou_safety_{n}" for n in names}

    card_mentions: list[str] = []

    def fake_card(view: Any, mention_id: str) -> tuple[str, list[dict[str, Any]]]:
        card_mentions.append(mention_id)
        return "content", []

    async def fake_send(**kw: Any) -> bool:
        return True

    async def fake_upsert(*a: Any, **kw: Any) -> bool:
        return True

    monkeypatch.setattr(progress_dunning, "find_dunning_overview", fake_overview)
    monkeypatch.setattr(progress_dunning, "resolve_dunning_recipients", fake_resolve)
    monkeypatch.setattr(mention, "resolve_open_ids", fake_mention)
    monkeypatch.setattr(progress_card, "build_progress_card", fake_card)
    monkeypatch.setattr(notification, "send_user_card", fake_send)
    monkeypatch.setattr(daily_digest, "upsert_daily_digest", fake_upsert)

    stats = await progress_dunning.send_progress_dunning_dynamic()

    assert stats["sent"] == 2
    # identity 来源（翁日生）才进 mention 换算；直取来源不进
    assert mention_calls == [["翁日生"]]
    # 两张卡的 @：直取 open_id 原样 / 换算结果
    assert "ou_safety_direct" in card_mentions
    assert "ou_safety_翁日生" in card_mentions
