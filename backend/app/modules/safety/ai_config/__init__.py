"""AI 配置中心 — 5 组模型配置的 registry/store/resolver/probe + 场景配置。

本包零副作用导入（不 import service/、knowledge/、feishu/ 等包），
migration 可安全引用 ``registry``。

命名注意：包级 ``get_profile`` 仍是 registry 语义（返回 ProfileInfo 元数据）；
ProfileView 合并视图请从 ``resolver``/``store`` 子模块导入
（``ai_config.resolver.get_profile`` 或 ``store.get_profile``）。
"""

from app.modules.safety.ai_config.exceptions import ScenarioDisabledError
from app.modules.safety.ai_config.probe import probe_profile
from app.modules.safety.ai_config.registry import (
    PROFILE_KEYS,
    REGISTRY,
    ProfileInfo,
    get_profile,
    iter_profiles,
)
from app.modules.safety.ai_config.resolver import get_profile_config
from app.modules.safety.ai_config.scenario_registry import (
    SCENARIO_REGISTRY,
    SCENARIO_UNKNOWN,
    ScenarioInfo,
    allowed_profiles_for,
    default_profile_for,
    get_scenario,
    get_scenario_info,
    iter_scenarios,
)
from app.modules.safety.ai_config.scenario_store import (
    AiScenarioStore,
    ScenarioView,
    scenario_store,
)
from app.modules.safety.ai_config.store import AiConfigStore, ProfileView, store

__all__ = [
    "PROFILE_KEYS",
    "REGISTRY",
    "ProfileInfo",
    "get_profile",
    "iter_profiles",
    "get_profile_config",
    "AiConfigStore",
    "ProfileView",
    "store",
    "probe_profile",
    # 场景配置（三期）
    "SCENARIO_REGISTRY",
    "SCENARIO_UNKNOWN",
    "ScenarioInfo",
    "get_scenario",
    "get_scenario_info",
    "iter_scenarios",
    "allowed_profiles_for",
    "default_profile_for",
    "AiScenarioStore",
    "ScenarioView",
    "scenario_store",
    "ScenarioDisabledError",
]
