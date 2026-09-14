"""AI 配置 store 回退链测试（接缝 2：构造函数注入 row_loader，生产路径零侵入）。

覆盖外部行为：
- 字段级回退链 DB 活行 → env → registry 默认（sources/status 归属）
- disabled 行整行回落 env/default；缺行 = 默认放行
- 缓存 invalidate 后重建；TTL 过期后重建
- DB 读取异常回落 env/default（配置中心故障不中断业务）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.modules.warehouse.ai_config import registry
from app.modules.warehouse.ai_config.scenario_store import AiScenarioStore
from app.modules.warehouse.ai_config.store import AiConfigStore
from app.modules.warehouse.bitable_config.store import BitableConfigStore
from app.modules.warehouse.ops_config.runtime_registry import RUNTIME_REGISTRY
from app.modules.warehouse.ops_config.runtime_store import RuntimeConfigStore
from app.modules.warehouse.ops_config.scheduler_store import SchedulerConfigStore


@dataclass
class StubRuntimeRow:
    """模拟 runtime_configs 活行。"""

    key: str
    value: Any = None
    note: str | None = None
    is_deleted: bool = False


@dataclass
class StubScenarioRow:
    """模拟 ai_scenario_configs 活行。"""

    scenario: str
    enabled: bool = True
    model_profile: str | None = None
    note: str | None = None
    is_deleted: bool = False


@dataclass
class StubProfileRow:
    """模拟 ai_model_profiles 活行（store 只读这几个属性）。"""

    profile: str
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    note: str | None = None
    is_deleted: bool = False


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """把测试值打到缓存的 Settings 实例上（env 兜底层经 get_settings 读取）。

    monkeypatch teardown 自动恢复原值。
    """
    from app.core.config import get_settings

    settings = get_settings()
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value, raising=False)


def make_store(rows: dict[str, StubProfileRow | None]) -> AiConfigStore:
    return AiConfigStore(row_loader=lambda profile: rows.get(profile))


class TestProfileFallbackChain:
    def test_missing_row_falls_back_to_registry_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # settings 实例（.env env_file 层）可能带 WAREHOUSE_AGENT_* 值，
        # 按 env_map 全量置空保证封闭（env 层空值被忽略 → 回落 default）
        _patch_settings(
            monkeypatch,
            **{
                var: ""
                for var in registry.REGISTRY["agent"].env_map.values()
                if var
            },
        )
        store = make_store({})
        view = store.get_profile("agent")
        assert view.config["model"] == registry.REGISTRY["agent"].default_config["model"]
        assert view.config["api_key"] == ""  # 密钥默认空串
        assert view.status == "default"
        assert view.enabled is True
        assert view.sources["model"] == "default"

    def test_db_row_overrides_env_and_default_field_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_MODEL="from-env-model")
        store = make_store(
            {"agent": StubProfileRow(profile="agent", config={"model": "from-db-model"})}
        )
        view = store.get_profile("agent")
        assert view.config["model"] == "from-db-model"
        assert view.sources["model"] == "db"
        assert view.status == "db"
        # DB 未覆盖的字段仍走 env / 默认
        assert view.config["base_url"] == "https://api.deepseek.com"
        assert view.sources["base_url"] == "env"

    def test_env_overrides_default_when_no_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_MODEL="from-env-model")
        store = make_store({})
        view = store.get_profile("agent")
        assert view.config["model"] == "from-env-model"
        assert view.sources["model"] == "env"
        assert view.status == "env"

    def test_empty_env_value_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_MODEL="")
        store = make_store({})
        view = store.get_profile("agent")
        assert view.sources["model"] == "default"

    def test_disabled_row_falls_back_entirely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_MODEL="from-env-model")
        store = make_store(
            {"agent": StubProfileRow(profile="agent", config={"model": "from-db-model"}, enabled=False)}
        )
        view = store.get_profile("agent")
        assert view.config["model"] == "from-env-model"  # 不吃 DB 值
        assert view.status == "disabled"

    def test_db_read_failure_falls_back_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """配置中心 DB 故障：读链回落 env/默认，不抛错。"""
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_MODEL="from-env-model")

        def broken_loader(profile: str) -> StubProfileRow | None:
            raise RuntimeError("db down")

        store = AiConfigStore(row_loader=broken_loader)
        view = store.get_profile("agent")
        assert view.config["model"] == "from-env-model"
        assert view.status == "env"

    def test_unknown_profile_raises_value_error(self) -> None:
        store = make_store({})
        with pytest.raises(ValueError, match="未知 profile"):
            store.get_profile("nope")

    def test_get_profile_config_returns_merged_copy(self) -> None:
        store = make_store(
            {"agent": StubProfileRow(profile="agent", config={"temperature": 0.3})}
        )
        cfg = store.get_profile_config("agent")
        assert cfg["temperature"] == 0.3
        cfg["temperature"] = 9.9  # 副本，改写不影响缓存
        assert store.get_profile_config("agent")["temperature"] == 0.3


class ProfileCacheContract:
    def test_invalidate_rebuilds_from_loader(self) -> None:
        rows: dict[str, StubProfileRow | None] = {}
        store = make_store(rows)
        assert store.get_profile("agent").status == "default"
        rows["agent"] = StubProfileRow(profile="agent", config={"model": "late-row"})
        assert store.get_profile("agent").status == "default"  # 缓存内
        store.invalidate("agent")
        assert store.get_profile("agent").config["model"] == "late-row"  # 重建

    def test_ttl_expiry_rebuilds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def loader(profile: str) -> StubProfileRow | None:
            calls.append(profile)
            return None

        store = AiConfigStore(row_loader=loader)
        store._ttl_seconds = 0.0  # 直接置零模拟过期
        store.get_profile("agent")
        store.get_profile("agent")
        assert len(calls) == 2  # TTL 过期后重建


class TestScenarioStore:
    def test_missing_row_defaults_enabled(self) -> None:
        store = AiScenarioStore(row_loader=lambda s: None)
        view = store.get_scenario_view("agent_chat")
        assert view.enabled is True
        assert view.source == "default"
        assert view.effective_profile == "agent"
        assert view.allowed_profiles == ("agent", "agent_backup")

    def test_unregistered_scenario_passes_through(self) -> None:
        """未注册场景默认放行（熔断层只看 enabled），不抛异常。"""
        store = AiScenarioStore(row_loader=lambda s: None)
        view = store.get_scenario_view("future_scenario")
        assert view.enabled is True
        assert view.scenario == "future_scenario"

    def test_disabled_row_circuits_off(self) -> None:
        store = AiScenarioStore(
            row_loader=lambda s: StubScenarioRow(scenario=s, enabled=False)
        )
        view = store.get_scenario_view("receipt_recognition")
        assert view.enabled is False
        assert view.source == "disabled"
        assert store.is_enabled("receipt_recognition") is False

    def test_binding_agent_backup_takes_effect(self) -> None:
        store = AiScenarioStore(
            row_loader=lambda s: StubScenarioRow(scenario=s, model_profile="agent_backup")
        )
        view = store.get_scenario_view("agent_chat")
        assert view.effective_profile == "agent_backup"
        assert store.get_effective_profile("agent_chat") == "agent_backup"

    def test_invalid_binding_in_db_falls_back_defensively(self) -> None:
        """劣化数据防御：DB 中白名单外绑定回退场景默认。"""
        store = AiScenarioStore(
            row_loader=lambda s: StubScenarioRow(scenario=s, model_profile="text")
        )
        view = store.get_scenario_view("agent_chat")
        assert view.effective_profile == "agent"

    def test_empty_binding_string_treated_as_none(self) -> None:
        store = AiScenarioStore(
            row_loader=lambda s: StubScenarioRow(scenario=s, model_profile="")
        )
        view = store.get_scenario_view("agent_chat")
        assert view.model_profile is None
        assert view.effective_profile == "agent"

    def test_invalidate_rebuilds(self) -> None:
        rows: dict[str, StubScenarioRow | None] = {}
        store = AiScenarioStore(row_loader=lambda s: rows.get(s))
        assert store.is_enabled("agent_chat") is True
        rows["agent_chat"] = StubScenarioRow(scenario="agent_chat", enabled=False)
        assert store.is_enabled("agent_chat") is True  # 缓存内
        store.invalidate("agent_chat")
        assert store.is_enabled("agent_chat") is False

    def test_db_read_failure_defaults_enabled(self) -> None:
        def broken_loader(scenario: str) -> StubScenarioRow | None:
            raise RuntimeError("db down")

        store = AiScenarioStore(row_loader=broken_loader)
        assert store.is_enabled("agent_chat") is True  # 配置中心故障不中断业务


class TestRuntimeStore:
    def test_missing_key_falls_back_to_registry_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(
            monkeypatch,
            **{info.env_var: "" for info in RUNTIME_REGISTRY.values() if info.env_var},
        )
        store = RuntimeConfigStore(row_loader=lambda k: None)
        assert store.get_value("max_turns") == 10
        assert store.get_view("max_turns").source == "default"

    def test_env_fallback_when_no_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_MAX_TURNS="18")
        store = RuntimeConfigStore(row_loader=lambda k: None)
        assert store.get_value("max_turns") == 18
        assert store.get_view("max_turns").source == "env"

    def test_db_value_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_AGENT_MAX_TURNS="18")
        store = RuntimeConfigStore(
            row_loader=lambda k: StubRuntimeRow(key=k, value=25)
        )
        assert store.get_value("max_turns") == 25
        assert store.get_view("max_turns").source == "db"

    def test_soft_deleted_row_treated_as_absent(self) -> None:
        """runtime_configs 停用即软删：软删行视同缺行回落 env/默认。"""
        store = RuntimeConfigStore(
            row_loader=lambda k: StubRuntimeRow(key=k, value=25, is_deleted=True)
        )
        assert store.get_value("max_turns") == 10

    def test_db_read_failure_falls_back(self) -> None:
        def broken(key: str) -> StubRuntimeRow | None:
            raise RuntimeError("db down")

        store = RuntimeConfigStore(row_loader=broken)
        assert store.get_value("confirm_ttl_seconds") == 600  # 默认值，不抛错

    def test_unknown_key_raises(self) -> None:
        store = RuntimeConfigStore(row_loader=lambda k: None)
        with pytest.raises(ValueError, match="未知参数"):
            store.get_value("nope")

    def test_invalidate_rebuilds(self) -> None:
        rows: dict[str, StubRuntimeRow | None] = {}
        store = RuntimeConfigStore(row_loader=lambda k: rows.get(k))
        assert store.get_value("confirm_ttl_seconds") == 600
        rows["confirm_ttl_seconds"] = StubRuntimeRow(key="confirm_ttl_seconds", value=900)
        assert store.get_value("confirm_ttl_seconds") == 600  # 缓存内
        store.invalidate("confirm_ttl_seconds")
        assert store.get_value("confirm_ttl_seconds") == 900

    def test_value_type_coercion(self) -> None:
        store = RuntimeConfigStore(
            row_loader=lambda k: StubRuntimeRow(key=k, value="0.75")
        )
        assert store.get_value("align_fuzzy_min_ratio") == 0.75  # JSONB 字符串按注册表类型收敛


@dataclass
class StubConnectionRow:
    """模拟 bitable_connections 活行。"""

    table_key: str
    base_token: str | None = None
    table_id: str | None = None
    enabled: bool = True
    note: str | None = None
    is_deleted: bool = False


@dataclass
class StubJobRow:
    """模拟 scheduler_task_configs 活行。"""

    job_name: str
    enabled: bool = True
    schedule: Any = None
    target_chat_id: str | None = None
    note: str | None = None
    is_deleted: bool = False


class TestBitableStore:
    def test_missing_row_falls_back_to_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_FEISHU_BITABLE_MATERIAL_APP_TOKEN="")
        store = BitableConfigStore(row_loader=lambda k: None)
        conn = store.resolve("material_receipt")
        assert conn.table_id == "tbliBlofs19qM8sg"  # 代码快照坐标
        # settings 层被显式置空：token 无处可取（default），适配层报 missing_credentials
        assert conn.token_source == "default"
        assert conn.base_token == ""

    def test_env_token_used_when_no_db(self) -> None:
        store = BitableConfigStore(row_loader=lambda k: None)
        conn = store.resolve("material_receipt")
        assert conn.base_token.startswith("LmuBb3")  # env 兜底（live 环境已配置）
        assert conn.token_source == "env"

    def test_db_row_overrides_env_and_snapshot(self) -> None:
        store = BitableConfigStore(
            row_loader=lambda k: StubConnectionRow(
                table_key=k, base_token="db-token", table_id="tblOverride"
            )
        )
        conn = store.resolve("material_receipt")
        assert conn.base_token == "db-token"
        assert conn.table_id == "tblOverride"
        assert conn.token_source == "db"
        assert conn.table_id_source == "db"

    def test_disabled_row_is_explicit_off(self) -> None:
        store = BitableConfigStore(
            row_loader=lambda k: StubConnectionRow(table_key=k, enabled=False)
        )
        conn = store.resolve("material_receipt")
        assert conn.enabled is False  # 显式停用不回退默认

    def test_unknown_table_raises(self) -> None:
        store = BitableConfigStore(row_loader=lambda k: None)
        with pytest.raises(ValueError, match="未知表"):
            store.resolve("nope")

    def test_ten_connections_registered(self) -> None:
        store = BitableConfigStore(row_loader=lambda k: None)
        assert len(store.iter_connection_views()) == 10

    def test_view_masks_token(self) -> None:
        store = BitableConfigStore(
            row_loader=lambda k: StubConnectionRow(table_key=k, base_token="LmuBb3secret123")
        )
        view = store.get_connection_view("material_receipt")
        assert "LmuBb3secret" not in view.base_token
        assert view.base_token.endswith("n123") or view.base_token.startswith("****")


class TestSchedulerStore:
    def test_missing_row_defaults_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WAREHOUSE_ALERT_CHAT_ID", raising=False)
        _patch_settings(monkeypatch, WAREHOUSE_ALERT_CHAT_ID="")
        store = SchedulerConfigStore(row_loader=lambda k: None)
        view = store.get_job_view("draft_expire_stale")
        assert view.enabled is True
        assert view.schedule == {"type": "interval", "seconds": 300}
        assert view.source == "default"
        assert view.target_chat_id is None

    def test_alert_target_db_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_ALERT_CHAT_ID="oc_env")
        store = SchedulerConfigStore(
            row_loader=lambda k: StubJobRow(job_name=k, target_chat_id="oc_db")
        )
        assert store.get_alert_target() == "oc_db"

    def test_alert_target_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, WAREHOUSE_ALERT_CHAT_ID="oc_env")
        store = SchedulerConfigStore(row_loader=lambda k: None)
        assert store.get_alert_target() == "oc_env"

    def test_disabled_job_view(self) -> None:
        store = SchedulerConfigStore(
            row_loader=lambda k: StubJobRow(job_name=k, enabled=False)
        )
        view = store.get_job_view("system_alert")
        assert view.enabled is False

    def test_unknown_job_raises(self) -> None:
        store = SchedulerConfigStore(row_loader=lambda k: None)
        with pytest.raises(ValueError, match="未知任务"):
            store.get_job_view("nope")


class RegistryAssertions:
    def test_profiles_registered(self) -> None:
        assert set(registry.REGISTRY) == {"agent", "agent_backup"}

    def test_api_key_default_empty(self) -> None:
        for info in registry.iter_profiles():
            assert info.default_config.get("api_key", "") == ""

    def test_backup_profile_has_no_temperature(self) -> None:
        info = registry.REGISTRY["agent_backup"]
        assert "temperature" not in info.field_names

    def test_agent_env_map_uses_warehouse_keys(self) -> None:
        env_map = registry.REGISTRY["agent"].env_map
        assert env_map["api_key"] == "WAREHOUSE_AGENT_API_KEY"
        assert env_map["timeout"] == "WAREHOUSE_AGENT_TIMEOUT"
        assert env_map["temperature"] == ""  # 无 env 兜底
