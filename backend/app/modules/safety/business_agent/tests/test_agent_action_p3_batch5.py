"""Agent 执行面三期（agent-action-p3）第 5 组三件测试。

覆盖 spec（.scratch/agent-action-p3/spec.md）T6：
freeze_standard_check（季度定格，无参=今天/date 补跑）/
scan_chemical_inventory（危化品全量风险扫描）/
reseed_daily_digest（按日期重投速递格子）。仅 safety_admin。

测试接缝：工具函数边界直接调用；freeze_due/send_standard_compliance_digest、
ChemicalInventoryService.run_full_scan、生成链（fire/special_op）、
digest_enabled/special_digest_chat_id 全部打桩。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    ROLE_DEPT_LEADER,
    ROLE_INSPECTOR,
    ROLE_SAFETY_ADMIN,
    ROLE_VIEWER,
    check,
)
from app.modules.safety.business_agent.tools import registry
from app.modules.safety.business_agent.tools.ops_action_tools import (
    freeze_standard_check,
    reseed_daily_digest,
    scan_chemical_inventory,
)


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _ctx(db: Any = None, role: str = "safety_admin") -> SimpleNamespace:
    if db is None:
        db = _FakeDb()
    return SimpleNamespace(
        deps=SimpleNamespace(
            db=db, person=None, role=role,
            session_id="s1", channel="test",
        )
    )


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _patch(monkeypatch: pytest.MonkeyPatch, mod: str, name: str, value: Any) -> None:
    import importlib

    monkeypatch.setattr(importlib.import_module(mod), name, value)


# ═══ 接线 ═══


class TestBatch5Wiring:
    def test_tool_kind_write(self) -> None:
        assert registry.TOOL_KIND["freeze_standard_check"] is True
        assert registry.TOOL_KIND["scan_chemical_inventory"] is True
        assert registry.TOOL_KIND["reseed_daily_digest"] is True

    def test_group_mounted(self) -> None:
        assert "freeze_standard_check" in tool_selector.TOOL_GROUPS["standard_check"]
        assert "scan_chemical_inventory" in tool_selector.TOOL_GROUPS["chemical"]
        ops = tool_selector.TOOL_GROUPS["ops"]
        assert "reseed_daily_digest" in ops

    @pytest.mark.parametrize(
        "message,tool",
        [
            ("把季度定格跑一下", "freeze_standard_check"),
            ("危化品全量扫描一下", "scan_chemical_inventory"),
            ("昨天的速递格子重投一下", "reseed_daily_digest"),
        ],
    )
    def test_route_hits(self, message: str, tool: str) -> None:
        decision = tool_selector.route_message(message)
        assert tool in decision.tool_names, f"{message} 未挂载 {tool}: {decision}"

    def test_permissions_admin_only(self) -> None:
        for tool in ("freeze_standard_check", "scan_chemical_inventory", "reseed_daily_digest"):
            assert check(ROLE_SAFETY_ADMIN, tool)
            assert not check(ROLE_DEPT_LEADER, tool)
            assert not check(ROLE_INSPECTOR, tool)
            assert not check(ROLE_VIEWER, tool)


# ═══ freeze_standard_check ═══


class TestFreezeStandardCheck:
    _FREEZE_MOD = "app.modules.safety.service.standard_check.freeze"

    def _stub_freeze(self, monkeypatch: pytest.MonkeyPatch, ret: SimpleNamespace) -> dict:
        calls: dict = {}

        async def fake_freeze(*, db, opener=None, today=None):
            calls["today"] = today
            return ret

        async def fake_digest(result, *, chat_id=None):
            calls["digest_called"] = True
            return {"pushed": True}

        _patch(monkeypatch, self._FREEZE_MOD, "freeze_due", fake_freeze)
        _patch(monkeypatch, self._FREEZE_MOD, "send_standard_compliance_digest", fake_digest)
        return calls

    def test_freeze_success_on_quarter_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ret = SimpleNamespace(
            ran=True, no_source=False, frozen=6, quarter_key="2026Q3",
            targets=["t1", "t2"], cell_rows=[],
        )
        calls = self._stub_freeze(monkeypatch, ret)
        out = _run(freeze_standard_check(_ctx(), date="2026-10-01"))
        assert out["success"] is True
        assert out["frozen"] == 6
        assert out["quarter_key"] == "2026Q3"
        assert calls["today"] == date(2026, 10, 1)
        assert calls.get("digest_called") is True  # 投格链随定格触发

    def test_freeze_not_quarter_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ret = SimpleNamespace(
            ran=False, no_source=False, frozen=0, quarter_key=None,
            targets=[], cell_rows=[],
        )
        calls = self._stub_freeze(monkeypatch, ret)
        out = _run(freeze_standard_check(_ctx(), date="2026-10-28"))
        assert out["success"] is False
        assert "非季度定格日" in out["message"]
        assert "2027-01-01" in out["message"]  # 提示下一定格日
        assert "digest_called" not in calls

    def test_freeze_no_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ret = SimpleNamespace(
            ran=False, no_source=True, frozen=0, quarter_key=None,
            targets=[], cell_rows=[],
        )
        self._stub_freeze(monkeypatch, ret)
        out = _run(freeze_standard_check(_ctx()))
        assert out["success"] is False
        assert "核查表" in out["message"] or "未配置" in out["message"]

    def test_freeze_invalid_date(self) -> None:
        out = _run(freeze_standard_check(_ctx(), date="10月1日"))
        assert out["success"] is False
        assert "日期" in out["message"]

    def test_freeze_default_today_passes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ret = SimpleNamespace(
            ran=False, no_source=False, frozen=0, quarter_key=None,
            targets=[], cell_rows=[],
        )
        calls = self._stub_freeze(monkeypatch, ret)
        _run(freeze_standard_check(_ctx()))  # 无参 → service 缺省北京今天
        assert calls["today"] is None


# ═══ scan_chemical_inventory ═══


class TestScanChemicalInventory:
    def test_scan_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.modules.safety.service.chemical_inventory as ci_mod

        calls: list = []

        async def fake_scan(self):
            calls.append(1)
            return {"changed": 4, "warn_count": 12, "normal_count": 501}

        monkeypatch.setattr(ci_mod.ChemicalInventoryService, "run_full_scan", fake_scan)
        out = _run(scan_chemical_inventory(_ctx()))
        assert out["success"] is True
        assert out["stats"] == {"changed": 4, "warn_count": 12, "normal_count": 501}
        assert len(calls) == 1

    def test_scan_error_not_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.modules.safety.service.chemical_inventory as ci_mod

        async def fake_scan(self):
            raise RuntimeError("sheet 拉取超时")

        monkeypatch.setattr(ci_mod.ChemicalInventoryService, "run_full_scan", fake_scan)
        out = _run(scan_chemical_inventory(_ctx()))
        assert out["success"] is False
        assert "sheet 拉取超时" in out["message"]


# ═══ reseed_daily_digest ═══


class TestReseedDailyDigest:
    def _enable_digest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(
            monkeypatch,
            "app.modules.safety.feishu.daily_digest", "digest_enabled", lambda: True,
        )
        _patch(
            monkeypatch,
            "app.modules.safety.feishu.daily_digest",
            "special_digest_chat_id", lambda: "oc_special_board",
        )

    def test_date_required_and_valid(self) -> None:
        out = _run(reseed_daily_digest(_ctx(), date=""))
        assert out["success"] is False
        assert "日期" in out["message"]
        out2 = _run(reseed_daily_digest(_ctx(), date="昨天"))
        assert out2["success"] is False
        assert "YYYY-MM-DD" in out2["message"]

    def test_digest_disabled_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(
            monkeypatch,
            "app.modules.safety.feishu.daily_digest", "digest_enabled", lambda: False,
        )
        out = _run(reseed_daily_digest(_ctx(), date="2026-10-27"))
        assert out["success"] is False
        assert "速递" in out["message"]

    def test_default_all_kinds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._enable_digest(monkeypatch)
        import app.modules.safety.service.fire_alarm.service as fire_mod
        import app.modules.safety.service.special_op_direct.daily as so_daily

        fired: list[dict] = []

        async def fake_report(self, target_date=None, **kwargs):
            fired.append({"target_date": target_date, **kwargs})
            return SimpleNamespace(markdown_report="r", total=3)

        monkeypatch.setattr(fire_mod.FireAlarmService, "generate_daily_report", fake_report)

        so_calls: list[dict] = []

        async def fake_run(target_date, mode="today", **kwargs):
            so_calls.append({"target_date": target_date, "mode": mode, **kwargs})
            return SimpleNamespace(report_date=target_date, mode=mode)

        _patch(monkeypatch, "app.modules.safety.service.special_op_direct.daily", "run", fake_run)

        out = _run(reseed_daily_digest(_ctx(), date="2026-10-27"))
        assert out["success"] is True
        assert fired[0]["target_date"] == date(2026, 10, 27)
        assert fired[0]["push"] is True  # 投格内建于 push=True 分支
        modes = sorted(c["mode"] for c in so_calls)
        assert modes == ["afternoon", "today"]  # 晨报格+晚报格
        # special_op 走板群目标 → 独立卡被滤除（只投格）
        assert all(c["target_chats"] == ["oc_special_board"] for c in so_calls)
        keys = {r["key"] for r in out["results"] if r["ok"]}
        assert keys == {"fire_alarm", "special_op", "special_op_pm"}

    def test_subset_kinds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._enable_digest(monkeypatch)
        import app.modules.safety.service.fire_alarm.service as fire_mod

        async def fake_report(self, target_date=None, **kwargs):
            return SimpleNamespace(markdown_report="r", total=0)

        monkeypatch.setattr(fire_mod.FireAlarmService, "generate_daily_report", fake_report)
        out = _run(reseed_daily_digest(_ctx(), date="2026-10-27", kinds="fire_alarm"))
        assert out["success"] is True
        assert [r["key"] for r in out["results"]] == ["fire_alarm"]

    def test_invalid_kind_lists_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._enable_digest(monkeypatch)
        out = _run(reseed_daily_digest(_ctx(), date="2026-10-27", kinds="workticket"))
        assert out["success"] is False
        assert "fire_alarm" in out["message"] and "special_op_pm" in out["message"]

    def test_stale_date_guard_notice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """早于昨天的日期：内置护栏只写存储不发群——返回如实转述。"""
        self._enable_digest(monkeypatch)
        import app.modules.safety.service.fire_alarm.service as fire_mod

        async def fake_report(self, target_date=None, **kwargs):
            return SimpleNamespace(markdown_report="r", total=0)

        monkeypatch.setattr(fire_mod.FireAlarmService, "generate_daily_report", fake_report)
        out = _run(reseed_daily_digest(_ctx(), date="2026-10-01", kinds="fire_alarm"))
        assert out["success"] is True
        assert "只写存储" in out["message"] or "不向群" in out["message"]

    def test_special_op_board_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._enable_digest(monkeypatch)
        _patch(
            monkeypatch,
            "app.modules.safety.feishu.daily_digest", "special_digest_chat_id", lambda: "",
        )
        out = _run(reseed_daily_digest(_ctx(), date="2026-10-27", kinds="special_op"))
        assert out["success"] is True  # 整体不失败
        results = {r["key"]: r for r in out["results"]}
        assert results["special_op"]["ok"] is False
        assert "板" in results["special_op"]["message"]

    def test_kind_error_isolated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._enable_digest(monkeypatch)
        import app.modules.safety.service.fire_alarm.service as fire_mod

        async def fake_report(self, target_date=None, **kwargs):
            raise RuntimeError("AI 全失败")

        monkeypatch.setattr(fire_mod.FireAlarmService, "generate_daily_report", fake_report)
        out = _run(reseed_daily_digest(_ctx(), date="2026-10-27", kinds="fire_alarm"))
        assert out["success"] is True  # 单格失败不拖垮整体
        assert out["results"][0]["ok"] is False
        assert "AI 全失败" in out["results"][0]["message"]
