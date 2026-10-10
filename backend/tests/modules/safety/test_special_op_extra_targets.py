"""特殊作业日报附加投递群 compose_report_targets — 单测（2026-09-30 需求）。

覆盖：主目标 + 附加群（默认特殊作业报备及日报表群）组装与去重、
env off 停用、主目标未配置维持「无目标不推送」契约。
"""

from __future__ import annotations

import pytest

from app.modules.safety.service import special_operation_daily_report as sor

EXTRA = "oc_4ab4a89f7bbb2450f5e0e341bf0f5f10"  # 特殊作业报备及日报表群


class TestComposeReportTargets:
    def test_primary_plus_extra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sor, "EXTRA_REPORT_CHAT_ID", EXTRA)
        assert sor.compose_report_targets("oc_main") == ["oc_main", EXTRA]

    def test_no_primary_no_push(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """主目标未配置 = 不推送（既有契约），附加群不得单独触发。"""
        monkeypatch.setattr(sor, "EXTRA_REPORT_CHAT_ID", EXTRA)
        assert sor.compose_report_targets(None) == []
        assert sor.compose_report_targets("") == []

    def test_extra_disabled_by_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sor, "EXTRA_REPORT_CHAT_ID", "off")
        assert sor.compose_report_targets("oc_main") == ["oc_main"]
        monkeypatch.setattr(sor, "EXTRA_REPORT_CHAT_ID", "")
        assert sor.compose_report_targets("oc_main") == ["oc_main"]

    def test_extra_equal_primary_dedup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DB 覆写把主目标指到附加群本身时不重复投递。"""
        monkeypatch.setattr(sor, "EXTRA_REPORT_CHAT_ID", EXTRA)
        assert sor.compose_report_targets(EXTRA) == [EXTRA]

    def test_default_extra_is_report_group(self) -> None:
        """代码默认：附加群 = 特殊作业报备及日报表群（真机群清单核对 2026-09-30）。"""
        assert sor.EXTRA_REPORT_CHAT_ID == EXTRA
