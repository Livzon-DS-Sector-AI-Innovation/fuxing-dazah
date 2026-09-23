"""knowledge 消费入口切直读单测（Ticket 04）。

query_latest_regulations 双路径：开关关走 ORM（断言不触碰直读工厂）、
开关开走直读（monkeypatch open_reader 替身）；输出键一致；id 双态。
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.knowledge_direct.views import KnowledgeArticleView

ENV_DIRECT = "SAFETY_KNOWLEDGE_DIRECT_ENABLED"

OUTPUT_KEYS = {
    "id", "article_no", "title", "category", "impact_level",
    "publish_date", "status", "source",
}


class FakeScalars:
    def all(self) -> list[Any]:
        return []


class FakeResult:
    def scalars(self) -> FakeScalars:
        return FakeScalars()


class FakeDB:
    """legacy ORM 路径替身：execute 恒返空结果（不触碰真库）。"""

    def __init__(self) -> None:
        self.executed = 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.executed += 1
        return FakeResult()


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(deps=SimpleNamespace(db=FakeDB(), person=None))


def _direct_view(vid: str, **kw: Any) -> KnowledgeArticleView:
    defaults: dict[str, Any] = dict(
        title=f"标题{vid}", category="laws_regulations", status="published",
        source="应急管理部", article_no="LAW-X", input_date=date.today(),
    )
    defaults.update(kw)
    return KnowledgeArticleView(id=vid, feishu_record_id=vid, **defaults)


class FakeReader:
    def __init__(self, views: list[KnowledgeArticleView]) -> None:
        self._views = views
        self.calls = 0

    async def fetch_all(self, *, strict: bool = False) -> list[KnowledgeArticleView]:
        self.calls += 1
        return self._views


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)


def _patch_reader(monkeypatch: pytest.MonkeyPatch, reader: FakeReader) -> None:
    from app.modules.safety.service.knowledge_direct import reader as kd_reader

    monkeypatch.setattr(kd_reader, "open_reader", lambda: reader)


class TestDirectPathOn:
    async def test_switch_on_uses_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_latest_regulations,
        )

        reader = FakeReader([
            _direct_view("recA", notes="影响等级: 高"),
            _direct_view("recB"),
        ])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_latest_regulations(_ctx())  # type: ignore[arg-type]

        assert reader.calls == 1
        assert got["total"] == 2
        assert {i["id"] for i in got["items"]} == {"recA", "recB"}

    async def test_output_keys_and_params_passthrough(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_latest_regulations,
        )

        reader = FakeReader([_direct_view("recA")])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_latest_regulations(
            _ctx(), limit=5, days=7,  # type: ignore[arg-type]
        )

        for item in got["items"]:
            assert set(item) == OUTPUT_KEYS
        item = got["items"][0]
        assert item["id"] == "recA"  # 直读 id = recXXX（双态之一）
        assert item["article_no"] == "LAW-X"
        assert item["impact_level"] is None

    async def test_direct_filters_still_apply(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_latest_regulations,
        )

        reader = FakeReader([
            _direct_view("recHot", notes="影响等级: 高"),
            _direct_view("recMid", notes="影响等级: 中"),
        ])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_latest_regulations(
            _ctx(), impact_level="高",  # type: ignore[arg-type]
        )

        assert [i["id"] for i in got["items"]] == ["recHot"]


class TestLegacyPathOff:
    async def test_switch_off_skips_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_latest_regulations,
        )

        reader = FakeReader([_direct_view("recA")])
        _patch_reader(monkeypatch, reader)
        ctx = _ctx()

        got = await query_latest_regulations(ctx)  # type: ignore[arg-type]

        assert reader.calls == 0  # 直读工厂未被触碰
        assert ctx.deps.db.executed >= 1  # 走了 ORM 查询
        assert got == {"items": [], "total": 0}

    async def test_switch_off_legacy_items_mapping(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """legacy 路径行映射不被本批改动（换真 ORM 行形态走不到，仅断言空库行为）。"""
        from app.modules.safety.business_agent.tools.read_tools import (
            query_latest_regulations,
        )

        _patch_reader(monkeypatch, FakeReader([]))
        ctx = _ctx()

        got = await query_latest_regulations(
            ctx, limit=3, days=1,  # type: ignore[arg-type]
        )

        assert set(got) == {"items", "total"}


class TestCutoffBehaviorParity:
    async def test_direct_respects_days_window(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_latest_regulations,
        )

        old = date.today() - timedelta(days=40)
        recent = date.today() - timedelta(days=1)
        reader = FakeReader([
            _direct_view("recOld", input_date=old),
            _direct_view("recNew", input_date=recent),
        ])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_latest_regulations(_ctx(), days=30)  # type: ignore[arg-type]

        assert [i["id"] for i in got["items"]] == ["recNew"]
