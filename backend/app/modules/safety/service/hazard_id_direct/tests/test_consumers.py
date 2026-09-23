"""hazard_id 消费入口切直读单测（Ticket 05）。

query_hazard_identifications 双路径：开关关走 ORM（断言不触碰直读工厂）、
开关开走直读（monkeypatch open_reader 替身 + identity 部门批量派生注入）；
输出键与外层形态逐字同款；handler/API/scheduler 零改动守恒（模块可导入）；
零回写（替身无任何写方法，直读分支无从调用）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.hazard_id_direct.views import (
    HazardIdentificationView,
)

ENV_DIRECT = "SAFETY_HAZARD_ID_DIRECT_ENABLED"

# legacy 工具体输出键（read_tools.query_hazard_identifications 逐字对齐）
HI_KEYS = {
    "hazard_id_no", "department", "position", "production_step",
    "specific_activity", "hazard_type", "possible_accident",
    "inherent_risk_label", "residual_risk_label", "post_risk_label",
    "control_level", "recommendation_content", "overall_status",
    "submitter_name", "feishu_url",
}


class FakeResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def scalar(self) -> int:
        return 0  # legacy count 查询

    def scalars(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return self._rows


class FakeDB:
    """双路径通用替身：legacy ORM（scalar/execute→scalars().all()）与
    identity 部门批量派生（execute→all() 元组行）。"""

    def __init__(self, dept_rows: list[Any] | None = None) -> None:
        self.dept_rows = dept_rows or []
        self.executed = 0

    async def scalar(self, stmt: Any) -> int:
        self.executed += 1
        return 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.executed += 1
        return FakeResult(self.dept_rows)


def _ctx(dept_rows: list[Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(deps=SimpleNamespace(db=FakeDB(dept_rows), person=None))


def _view(rid: str, **kw: Any) -> HazardIdentificationView:
    defaults: dict[str, Any] = dict(
        hazard_id_no=f"HI-{rid[-12:]}", position="结晶岗位",
        specific_activity="料液准备", hazard_type="火灾爆炸",
        possible_accident="爆炸", inherent_risk_label="一级/重大风险",
        residual_risk_label="三级/一般风险", post_risk_label="四级/低风险",
        control_level="公司级", recommendation_content="加装联锁",
        overall_status="completed", submitter_name="李伟豪",
        created_time_ms=1776300000000,
    )
    defaults.update(kw)
    return HazardIdentificationView(record_id=rid, **defaults)


class FakeReader:
    def __init__(self, views: list[HazardIdentificationView]) -> None:
        self._views = views
        self.calls = 0

    async def fetch_all(
        self, *, strict: bool = False,
    ) -> list[HazardIdentificationView]:
        self.calls += 1
        return self._views


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)


def _patch_reader(monkeypatch: pytest.MonkeyPatch, reader: FakeReader) -> None:
    from app.modules.safety.service.hazard_id_direct import reader as hid_reader

    monkeypatch.setattr(hid_reader, "open_reader", lambda: reader)


class TestDirectOn:
    async def test_switch_on_uses_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_hazard_identifications,
        )

        reader = FakeReader([_view("recA")])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")
        ctx = _ctx(dept_rows=[("李伟豪", "提炼工程五部")])

        got = await query_hazard_identifications(ctx)  # type: ignore[arg-type]

        assert reader.calls == 1
        assert ctx.deps.db.executed == 1  # 仅 identity 部门批量派生一次
        assert got["success"] is True
        assert got["total"] == 1
        item = got["items"][0]
        assert set(item) == HI_KEYS
        assert item["hazard_id_no"] == "HI-" + "recA"[-12:]
        assert item["department"] == "提炼工程五部"
        assert item["feishu_url"] is None  # 死值 quirk 复刻
        assert got["page"] == 1 and got["page_size"] == 20

    async def test_filter_passthrough(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_hazard_identifications,
        )

        reader = FakeReader([
            _view("recA", overall_status="completed"),
            _view("recB", overall_status="draft"),
        ])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_hazard_identifications(
            _ctx(),  # type: ignore[arg-type]
            overall_status="draft",
        )
        assert got["total"] == 1
        assert got["items"][0]["hazard_id_no"] == "HI-" + "recB"[-12:]


class TestLegacyPathOff:
    async def test_switch_off_skips_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_hazard_identifications,
        )

        reader = FakeReader([_view("recA")])
        _patch_reader(monkeypatch, reader)
        ctx = _ctx()

        got = await query_hazard_identifications(ctx)  # type: ignore[arg-type]

        assert reader.calls == 0  # 直读工厂未被触碰
        assert ctx.deps.db.executed >= 1  # 恒走 ORM 查询
        assert got == {
            "success": True, "items": [], "page": 1, "page_size": 20, "total": 0,
        }


class TestZeroChangeConservation:
    """spec D1 守恒：事件 handler / API / scheduler 模块零改动（可导入冒烟）。"""

    def test_handler_api_scheduler_importable(self) -> None:
        import app.modules.safety.api.hazard_identifications  # noqa: F401
        import app.modules.safety.feishu.hazard_identification_bitable_handler  # noqa: F401
        import app.modules.safety.scheduler  # noqa: F401
