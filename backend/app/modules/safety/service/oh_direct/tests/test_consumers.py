"""oh 消费入口切直读单测（Ticket 03）。

query_oh_positions / query_oh_hazard_factors 双路径：开关关走 ORM（断言不触碰
直读工厂）、开关开走直读（monkeypatch open_reader 替身）；输出键一致；id 双态；
零回写（替身无任何写方法，直读分支无从调用）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.oh_direct.views import (
    OhHazardFactorView,
    OhPositionView,
)

ENV_DIRECT = "SAFETY_OH_DIRECT_ENABLED"

# legacy 工具体输出键（read_tools.query_oh_hazard_factors 逐字对齐；
# positions 维持镜像无直读输出契约，不在此断言）
FACTOR_KEYS = {"id", "factor_name", "ppe_respiratory"}


class FakeResult:
    def scalars(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return []


class FakeDB:
    """legacy ORM 路径替身：scalar/execute 恒返空（不触碰真库）。

    legacy get_positions / get_factors 形态：``await db.scalar(count)`` +
    ``await db.execute(stmt)`` → ``result.scalars().all()``。
    """

    def __init__(self) -> None:
        self.executed = 0

    async def scalar(self, stmt: Any) -> int:
        self.executed += 1
        return 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.executed += 1
        return FakeResult()


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(deps=SimpleNamespace(db=FakeDB(), person=None))


def _position_view(vid: str, **kw: Any) -> OhPositionView:
    defaults: dict[str, Any] = dict(
        department="生产部", position="操作工",
        hazard_factors=["噪声"], hazard_factors_status="filled",
    )
    defaults.update(kw)
    return OhPositionView(id=vid, feishu_record_id=vid, **defaults)


def _factor_view(vid: str, **kw: Any) -> OhHazardFactorView:
    defaults: dict[str, Any] = dict(factor_name="噪声", ppe_respiratory="耳塞")
    defaults.update(kw)
    return OhHazardFactorView(id=vid, feishu_record_id=vid, **defaults)


class FakeReader:
    def __init__(
        self,
        positions: list[OhPositionView] | None = None,
        factors: list[OhHazardFactorView] | None = None,
    ) -> None:
        self._positions = positions or []
        self._factors = factors or []
        self.position_calls = 0
        self.factor_calls = 0

    async def fetch_positions(
        self, *, strict: bool = False,
    ) -> list[OhPositionView]:
        self.position_calls += 1
        return self._positions

    async def fetch_factors(
        self, *, strict: bool = False,
    ) -> list[OhHazardFactorView]:
        self.factor_calls += 1
        return self._factors


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)


def _patch_reader(monkeypatch: pytest.MonkeyPatch, reader: FakeReader) -> None:
    from app.modules.safety.service.oh_direct import reader as od_reader

    monkeypatch.setattr(od_reader, "open_reader", lambda: reader)


class TestPositionsMaintainsMirror:
    """query_oh_positions 维持镜像（spec §0.1 终版切面）：镜像表双源承重
    （470 平台手动行只在 PG），工具分支不接直读——开关开也走 ORM（防呆断言）。"""

    async def test_switch_on_still_uses_orm(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_oh_positions,
        )

        reader = FakeReader(positions=[_position_view("recA")])
        _patch_reader(monkeypatch, reader)
        ctx = _ctx()

        got = await query_oh_positions(ctx)  # type: ignore[arg-type]

        assert reader.position_calls == 0  # 直读工厂未被触碰（分支不接）
        assert ctx.deps.db.executed >= 1  # 恒走 ORM 查询
        assert got == {"items": [], "total": 0}


class TestFactorsDirectOn:
    async def test_switch_on_uses_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_oh_hazard_factors,
        )

        reader = FakeReader(factors=[_factor_view("recF")])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_oh_hazard_factors(_ctx())  # type: ignore[arg-type]

        assert reader.factor_calls == 1
        assert got["total"] == 1
        assert got["items"][0]["id"] == "recF"

    async def test_output_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_oh_hazard_factors,
        )

        reader = FakeReader(factors=[_factor_view("recF")])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_oh_hazard_factors(
            _ctx(),  # type: ignore[arg-type]
            keyword="噪", limit=5,
        )

        assert set(got["items"][0]) == FACTOR_KEYS
        assert got["items"][0]["factor_name"] == "噪声"


class TestLegacyPathOff:
    async def test_factors_switch_off_skips_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_oh_hazard_factors,
        )

        reader = FakeReader(factors=[_factor_view("recF")])
        _patch_reader(monkeypatch, reader)
        ctx = _ctx()

        got = await query_oh_hazard_factors(ctx)  # type: ignore[arg-type]

        assert reader.factor_calls == 0
        assert ctx.deps.db.executed >= 1
        assert got == {"items": [], "total": 0}
