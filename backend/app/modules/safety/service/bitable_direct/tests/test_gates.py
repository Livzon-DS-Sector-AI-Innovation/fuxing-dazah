"""bitable_direct 开关闸门单测。

不依赖真实环境变量（全部用 monkeypatch 隔离）、不依赖 DB / 网络 / AI。
语义必须与 hazard_direct.config、special_op_direct.config 逐条一致。
"""

from __future__ import annotations

import pytest

from app.modules.safety.service.bitable_direct import gates

#  布尔字面量

TRUTHY = ["1", "true", "TRUE", "True", "yes", "YES", "on", "On", " on ", "1 "]
FALSY = ["0", "false", "FALSE", "no", "off", "abc", "null", "2", "-1", "enabled"]


class TestFlag:
    def test_unset_returns_default_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_UNIT_FLAG", raising=False)
        assert gates.flag("SAFETY_UNIT_FLAG") is False

    def test_unset_returns_default_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_UNIT_FLAG", raising=False)
        assert gates.flag("SAFETY_UNIT_FLAG", default=True) is True

    def test_empty_string_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_UNIT_FLAG", "")
        assert gates.flag("SAFETY_UNIT_FLAG") is False
        assert gates.flag("SAFETY_UNIT_FLAG", default=True) is True

    @pytest.mark.parametrize("raw", TRUTHY)
    def test_truthy_literals(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv("SAFETY_UNIT_FLAG", raw)
        assert gates.flag("SAFETY_UNIT_FLAG") is True

    @pytest.mark.parametrize("raw", FALSY)
    def test_falsy_and_invalid_literals(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv("SAFETY_UNIT_FLAG", raw)
        assert gates.flag("SAFETY_UNIT_FLAG") is False

    def test_invalid_value_is_false_even_when_default_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非空但无法识别的值 -> False（与两个旧包既有实现逐字一致）。

        既有实现的 ``default`` 只在未设置 / 空值时生效；把拼错的值当成
        true 会产生"以为关掉了其实开着"的隐患，因此保持 False 语义。
        这条断言是兼容性契约，收敛旧包时不许改。
        """
        monkeypatch.setenv("SAFETY_UNIT_FLAG", "definitely")
        assert gates.flag("SAFETY_UNIT_FLAG", default=True) is False


class TestIntEnv:
    def test_unset_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_UNIT_INT", raising=False)
        assert gates.int_env("SAFETY_UNIT_INT", 7) == 7

    def test_parses_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_UNIT_INT", "42")
        assert gates.int_env("SAFETY_UNIT_INT", 7) == 42

    def test_invalid_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_UNIT_INT", "abc")
        assert gates.int_env("SAFETY_UNIT_INT", 7) == 7

    def test_minimum_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_UNIT_INT", "0")
        assert gates.int_env("SAFETY_UNIT_INT", 7, minimum=1) == 1

    def test_minimum_zero_allows_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_UNIT_INT", "0")
        assert gates.int_env("SAFETY_UNIT_INT", 7, minimum=0) == 0

    def test_negative_value_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_UNIT_INT", "-5")
        assert gates.int_env("SAFETY_UNIT_INT", 7, minimum=0) == 0

class TestDomainEnv:
    def test_builds_prefixed_name(self) -> None:
        assert gates.domain_env("FIRE_ALARM", "DIRECT_ENABLED") == "SAFETY_FIRE_ALARM_DIRECT_ENABLED"

    def test_matches_existing_hazard_variable(self) -> None:
        assert gates.domain_env("HAZARD", "EVENT_SYNC_ENABLED") == "SAFETY_HAZARD_EVENT_SYNC_ENABLED"

    def test_matches_existing_special_op_variable(self) -> None:
        assert gates.domain_env("SPECIAL_OP", "SYNC_JOB_ENABLED") == "SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED"


class TestDomainSwitches:
    def test_direct_enabled_reads_domain_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_SPECIAL_OP_DIRECT_ENABLED", raising=False)
        assert gates.direct_enabled("SPECIAL_OP") is False
        monkeypatch.setenv("SAFETY_SPECIAL_OP_DIRECT_ENABLED", "true")
        assert gates.direct_enabled("SPECIAL_OP") is True

    def test_event_sync_enabled_reads_domain_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED", raising=False)
        assert gates.event_sync_enabled("SPECIAL_OP") is False
        monkeypatch.setenv("SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED", "1")
        assert gates.event_sync_enabled("SPECIAL_OP") is True

    def test_sync_job_enabled_reads_domain_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED", raising=False)
        assert gates.sync_job_enabled("SPECIAL_OP") is False
        monkeypatch.setenv("SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED", "yes")
        assert gates.sync_job_enabled("SPECIAL_OP") is True

    def test_writeback_enabled_uses_custom_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_FIRE_ALARM_WRITEBACK_AI_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_FIRE_ALARM_WRITEBACK_RISK_ENABLED", raising=False)
        assert gates.writeback_enabled("FIRE_ALARM", "AI") is False
        monkeypatch.setenv("SAFETY_FIRE_ALARM_WRITEBACK_AI_ENABLED", "true")
        assert gates.writeback_enabled("FIRE_ALARM", "AI") is True
        assert gates.writeback_enabled("FIRE_ALARM", "RISK") is False

    def test_domains_do_not_leak_into_each_other(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_HAZARD_DIRECT_ENABLED", raising=False)
        monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
        assert gates.direct_enabled("FIRE_ALARM") is True
        assert gates.direct_enabled("HAZARD") is False


class TestLegacyActiveComposition:
    """legacy_*_active 语义（与 special_op_direct.config 逐条对齐）。

    总开关关闭 -> 旧链路恒生效（默认部署 = 与改造前一致）；
    总开关打开 -> 由单项开关决定（显式打开 = 回滚 / 双跑）。
    """

    @pytest.mark.parametrize(
        ("direct", "switch", "expected"),
        [
            (None, None, True),      # 默认：全关 -> 旧链路生效
            ("true", None, False),   # 直读开、单项关 -> 旧链路停止
            ("true", "true", True),  # 直读开、单项开 -> 双跑
            (None, "true", True),    # 直读关、单项开 -> 旧链路生效
        ],
    )
    def test_legacy_event_sync_active(
        self, monkeypatch: pytest.MonkeyPatch, direct: str | None, switch: str | None, expected: bool
    ) -> None:
        self._set(monkeypatch, "SAFETY_SPECIAL_OP_DIRECT_ENABLED", direct)
        self._set(monkeypatch, "SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED", switch)
        assert gates.legacy_event_sync_active("SPECIAL_OP") is expected

    @pytest.mark.parametrize(
        ("direct", "switch", "expected"),
        [
            (None, None, True),
            ("true", None, False),
            ("true", "true", True),
            (None, "true", True),
        ],
    )
    def test_legacy_sync_job_active(
        self, monkeypatch: pytest.MonkeyPatch, direct: str | None, switch: str | None, expected: bool
    ) -> None:
        self._set(monkeypatch, "SAFETY_SPECIAL_OP_DIRECT_ENABLED", direct)
        self._set(monkeypatch, "SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED", switch)
        assert gates.legacy_sync_job_active("SPECIAL_OP") is expected

    @staticmethod
    def _set(monkeypatch: pytest.MonkeyPatch, name: str, value: str | None) -> None:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


class TestHazardStylePerSwitchIsPreserved:
    """隐患侧语义：单项开关独立读取，不受任何总开关影响（原样保留）。"""

    def test_event_sync_is_independent_of_direct_poll(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SAFETY_HAZARD_EVENT_SYNC_ENABLED", raising=False)
        monkeypatch.setenv("SAFETY_HAZARD_DIRECT_POLL_ENABLED", "true")
        assert gates.event_sync_enabled("HAZARD") is False
        monkeypatch.setenv("SAFETY_HAZARD_EVENT_SYNC_ENABLED", "true")
        assert gates.event_sync_enabled("HAZARD") is True

    def test_arbitrary_switch_name_is_supported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_HAZARD_CATCHUP_ENABLED", "false")
        assert gates.flag(gates.domain_env("HAZARD", "CATCHUP_ENABLED")) is False


class TestDomainConstants:
    def test_constants_are_plain_strings(self) -> None:
        for name in ("DOMAIN_HAZARD", "DOMAIN_SPECIAL_OP", "DOMAIN_FIRE_ALARM"):
            value = getattr(gates, name)
            assert isinstance(value, str)
            assert value == value.upper()

    def test_constants_map_to_existing_variables(self) -> None:
        assert gates.domain_env(gates.DOMAIN_HAZARD, "EVENT_SYNC_ENABLED") == (
            "SAFETY_HAZARD_EVENT_SYNC_ENABLED"
        )
        assert gates.domain_env(gates.DOMAIN_SPECIAL_OP, "DIRECT_ENABLED") == (
            "SAFETY_SPECIAL_OP_DIRECT_ENABLED"
        )
        assert gates.domain_env(gates.DOMAIN_FIRE_ALARM, "DIRECT_ENABLED") == (
            "SAFETY_FIRE_ALARM_DIRECT_ENABLED"
        )

    def test_fire_alarm_prefix_matches_existing_dm_switch(self) -> None:
        # 既有 SAFETY_FIRE_ALARM_DAILY_DM_ENABLED 已在使用同一前缀
        assert gates.domain_env(gates.DOMAIN_FIRE_ALARM, "DAILY_DM_ENABLED") == (
            "SAFETY_FIRE_ALARM_DAILY_DM_ENABLED"
        )


class TestAllStandardSwitchesDefaultClosed:
    def test_default_closed_for_every_domain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_HAZARD_DIRECT_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_HAZARD_EVENT_SYNC_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_HAZARD_SYNC_JOB_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_SPECIAL_OP_DIRECT_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_FIRE_ALARM_EVENT_SYNC_ENABLED", raising=False)
        monkeypatch.delenv("SAFETY_FIRE_ALARM_SYNC_JOB_ENABLED", raising=False)

        for domain in (
            gates.DOMAIN_HAZARD,
            gates.DOMAIN_SPECIAL_OP,
            gates.DOMAIN_FIRE_ALARM,
        ):
            assert gates.direct_enabled(domain) is False
            assert gates.event_sync_enabled(domain) is False
            assert gates.sync_job_enabled(domain) is False
