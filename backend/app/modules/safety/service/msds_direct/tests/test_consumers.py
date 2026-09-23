"""msds 消费入口切直读单测（Ticket 03）。

query_msds_documents 双路径：开关关走 ORM（断言不触碰直读工厂）、
开关开走直读（monkeypatch open_reader 替身）；输出键一致；id 双态；
零回写（替身无任何写方法，直读分支无从调用）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.msds_direct.views import MsdsDocumentView

ENV_DIRECT = "SAFETY_MSDS_DIRECT_ENABLED"

# legacy 工具体输出键（read_tools.query_msds_documents 逐字对齐）
OUTPUT_KEYS = {
    "id", "name", "cas_no", "molecular_formula", "un_no",
    "hazard_statement", "appearance", "flash_point", "relative_density",
    "pc_twa", "health_hazard", "first_aid", "review_status", "archive_status",
}


class FakeScalars:
    def all(self) -> list[Any]:
        return []


class FakeDB:
    """legacy ORM 路径替身：scalar/scalars 恒返空（不触碰真库）。

    legacy list_documents 形态：``await db.scalar(count)`` +
    ``(await db.scalars(stmt)).all()``。
    """

    def __init__(self) -> None:
        self.executed = 0

    async def scalar(self, stmt: Any) -> int:
        self.executed += 1
        return 0

    async def scalars(self, stmt: Any) -> FakeScalars:
        self.executed += 1
        return FakeScalars()


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(deps=SimpleNamespace(db=FakeDB(), person=None))


def _direct_view(vid: str, **kw: Any) -> MsdsDocumentView:
    defaults: dict[str, Any] = dict(
        name=f"化学品{vid}", cas_no="67-63-0",
    )
    defaults.update(kw)
    return MsdsDocumentView(id=vid, feishu_record_id=vid, **defaults)


class FakeReader:
    def __init__(self, views: list[MsdsDocumentView]) -> None:
        self._views = views
        self.calls = 0

    async def fetch_all(self, *, strict: bool = False) -> list[MsdsDocumentView]:
        self.calls += 1
        return self._views


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)


def _patch_reader(monkeypatch: pytest.MonkeyPatch, reader: FakeReader) -> None:
    from app.modules.safety.service.msds_direct import reader as md_reader

    monkeypatch.setattr(md_reader, "open_reader", lambda: reader)


class TestDirectPathOn:
    async def test_switch_on_uses_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_msds_documents,
        )

        reader = FakeReader([
            _direct_view("recA", name="异丙醇"),
            _direct_view("recB", name="二甲基亚砜"),
        ])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_msds_documents(_ctx())  # type: ignore[arg-type]

        assert reader.calls == 1
        assert got["total"] == 2
        assert {i["id"] for i in got["items"]} == {"recA", "recB"}

    async def test_output_keys_and_constants(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_msds_documents,
        )

        reader = FakeReader([_direct_view("recA")])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_msds_documents(
            _ctx(), limit=5,  # type: ignore[arg-type]
        )

        for item in got["items"]:
            assert set(item) == OUTPUT_KEYS
        item = got["items"][0]
        assert item["id"] == "recA"  # 直读 id = recXXX（双态之一）
        assert item["name"] == "化学品recA"
        assert item["review_status"] == "pending"
        assert item["archive_status"] == "pending"

    async def test_name_filter_applies(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_msds_documents,
        )

        reader = FakeReader([
            _direct_view("recA", name="异丙醇"),
            _direct_view("recB", name="二甲基亚砜"),
        ])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_msds_documents(
            _ctx(), name="异丙醇",  # type: ignore[arg-type]
        )

        assert [i["id"] for i in got["items"]] == ["recA"]
        assert got["total"] == 1


class TestLegacyPathOff:
    async def test_switch_off_skips_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_msds_documents,
        )

        reader = FakeReader([_direct_view("recA")])
        _patch_reader(monkeypatch, reader)
        ctx = _ctx()

        got = await query_msds_documents(ctx)  # type: ignore[arg-type]

        assert reader.calls == 0  # 直读工厂未被触碰
        assert ctx.deps.db.executed >= 1  # 走了 ORM 查询
        assert got == {"items": [], "total": 0}
