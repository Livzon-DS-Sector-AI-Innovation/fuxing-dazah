"""ehs_change 消费入口切直读单测（Ticket 04）。

query_ehs_changes 双路径：开关关走 ORM（断言不触碰直读工厂）、开关开走
直读（monkeypatch open_reader 替身）；输出键与外层形态逐字同款；
handler/API/scheduler 零改动守恒（模块可导入）；零回写（替身无任何写
方法，直读分支无从调用）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.ehs_change_direct.views import EhsChangeView

ENV_DIRECT = "SAFETY_EHS_CHANGE_DIRECT_ENABLED"

# legacy 工具体输出键（read_tools.query_ehs_changes 逐字对齐）
EHS_KEYS = {
    "change_no", "title", "change_type", "change_grade", "department",
    "location_unit", "status", "expected_start", "expected_completion",
    "actual_start", "actual_completion", "applicant_name", "ai_review_status",
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
    """legacy ORM 路径替身（scalar/execute→scalars().all()）。"""

    def __init__(self) -> None:
        self.executed = 0

    async def scalar(self, stmt: Any) -> int:
        self.executed += 1
        return 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.executed += 1
        return FakeResult([])


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(deps=SimpleNamespace(db=FakeDB(), person=None))


def _view(rid: str, **kw: Any) -> EhsChangeView:
    defaults: dict[str, Any] = dict(
        kind="approval", created_time_ms=1776300000000,
        change_no=f"BT-{rid}", title=f"变更{rid}",
        change_type="equipment_facility", change_grade="major",
        department="精制工程一部", status="approved",
        applicant_name="赵军元", ai_review_status="completed",
    )
    defaults.update(kw)
    return EhsChangeView(record_id=rid, **defaults)


class FakeReader:
    def __init__(self, views: list[EhsChangeView]) -> None:
        self._views = views
        self.calls = 0

    async def fetch_all(
        self, *, strict: bool = False,
    ) -> list[EhsChangeView]:
        self.calls += 1
        return self._views


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)


def _patch_reader(monkeypatch: pytest.MonkeyPatch, reader: FakeReader) -> None:
    from app.modules.safety.service.ehs_change_direct import reader as ehs_reader

    monkeypatch.setattr(ehs_reader, "open_reader", lambda: reader)


class TestDirectOn:
    async def test_switch_on_uses_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_ehs_changes,
        )

        reader = FakeReader([_view("recA")])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")
        ctx = _ctx()

        got = await query_ehs_changes(ctx)  # type: ignore[arg-type]

        assert reader.calls == 1
        assert ctx.deps.db.executed == 0  # 直读路径不触碰 ORM
        assert got["success"] is True
        assert got["total"] == 1
        item = got["items"][0]
        assert set(item) == EHS_KEYS
        assert item["change_no"] == "BT-recA"
        assert item["actual_start"] is None  # 状态机零使用复刻
        assert got["page"] == 1 and got["page_size"] == 20

    async def test_filter_passthrough(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_ehs_changes,
        )

        reader = FakeReader([
            _view("recA", change_grade="major"),
            _view("recB", change_grade="general"),
        ])
        _patch_reader(monkeypatch, reader)
        monkeypatch.setenv(ENV_DIRECT, "true")

        got = await query_ehs_changes(
            _ctx(),  # type: ignore[arg-type]
            change_grade="重大",
        )
        assert got["total"] == 1
        assert got["items"][0]["change_no"] == "BT-recA"


class TestLegacyPathOff:
    async def test_switch_off_skips_direct_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_ehs_changes,
        )

        reader = FakeReader([_view("recA")])
        _patch_reader(monkeypatch, reader)
        ctx = _ctx()

        got = await query_ehs_changes(ctx)  # type: ignore[arg-type]

        assert reader.calls == 0  # 直读工厂未被触碰
        assert ctx.deps.db.executed >= 1  # 恒走 ORM 查询
        assert got == {
            "success": True, "items": [], "page": 1, "page_size": 20, "total": 0,
        }


class TestZeroChangeConservation:
    """spec D1 守恒：事件 handler / API / scheduler 模块零改动（可导入冒烟）。"""

    def test_handler_api_scheduler_importable(self) -> None:
        import app.modules.safety.api.ehs_changes  # noqa: F401
        import app.modules.safety.feishu.ehs_change_bitable_handler  # noqa: F401
        import app.modules.safety.scheduler  # noqa: F401
