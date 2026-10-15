"""直读开关单测（chemical_inventory-direct Ticket 03）。

三开关独立、全默认关；legacy_event_sync_active 组合语义（gates 总开关组合）。
"""

from __future__ import annotations

import pytest

from app.modules.safety.service.chemical_inventory_direct import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED",
        "SAFETY_CHEMICAL_INVENTORY_EVENT_SYNC_ENABLED",
        "SAFETY_CHEMICAL_INVENTORY_WRITEBACK_RISK_ENABLED",
        "SAFETY_CHEMICAL_INVENTORY_SOURCE",
    ):
        monkeypatch.delenv(name, raising=False)


class TestDefaults:
    def test_all_default_off(self) -> None:
        assert config.direct_enabled() is False
        assert config.event_sync_enabled() is False
        assert config.writeback_risk_enabled() is False
        assert config.legacy_event_sync_active() is True  # 全关 = 改造前行为
        assert config.sheet_source_enabled() is False
        assert config.current_source() == "bitable"

    def test_direct_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED", "true")
        assert config.direct_enabled() is True

    def test_writeback_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_WRITEBACK_RISK_ENABLED", "true")
        assert config.writeback_risk_enabled() is True


class TestSheetSource:
    """SAFETY_CHEMICAL_INVENTORY_SOURCE（D1：默认 bitable，回滚=拨回）。"""

    def test_sheet_source_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet")
        assert config.sheet_source_enabled() is True
        assert config.current_source() == "sheet"

    def test_sheet_source_implies_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """sheet 模式隐含 direct 语义：DIRECT 关也能点亮全部直读读路径（D1）。"""
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet")
        assert config.direct_enabled() is True

    def test_unknown_value_falls_back_bitable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """拼错的值宁可回退 bitable（安全默认），不当成 sheet。"""
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "xxx")
        assert config.sheet_source_enabled() is False
        assert config.current_source() == "bitable"

    def test_explicit_bitable_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "bitable")
        assert config.sheet_source_enabled() is False
        assert config.direct_enabled() is False


class TestLegacyEventSyncActive:
    def test_direct_on_event_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """直读开 + 事件关：镜像停（标准直读形态）。"""
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED", "true")
        assert config.legacy_event_sync_active() is False

    def test_direct_on_event_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """直读开 + 事件显式开：双跑（分项回滚用）。"""
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED", "true")
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_EVENT_SYNC_ENABLED", "true")
        assert config.legacy_event_sync_active() is True

    def test_direct_off_event_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_EVENT_SYNC_ENABLED", "true")
        assert config.legacy_event_sync_active() is True
