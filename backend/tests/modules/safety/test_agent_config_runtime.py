"""2-A 配置运行时化：per-turn resolve 行为钉子。

接缝（公共接口，不测内部实现）：
- ``resolve_runtime_config()``：当前生效配置快照（profile/model/temperature/max_tokens/指纹）
- ``get_agent_for_tools(names)``：同配置复用实例、配置变更重建实例

配置源经 monkeypatch AiConfigStore/AiScenarioStore 单例注入（同步内存读，不打 DB）。
依据：.scratch/safety-agent-optimization-p2/spec.md 2-A 节。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_agent_cache():
    from app.modules.safety.business_agent import agent as agent_mod

    agent_mod._AGENT_CACHE.clear()
    yield
    agent_mod._AGENT_CACHE.clear()


def _patch_config(
    monkeypatch,
    *,
    profile: str = "text",
    model: str = "deepseek-flash",
    api_key: str = "sk-test-abcd1234",
    temperature: float | None = 0.1,
    max_tokens: int | None = 8192,
) -> dict:
    """注入指定生效配置（profile 绑定 + profile config），返回注入的 config dict。"""
    # 注意：包 __init__ 把单例重导出为 store/scenario_store（遮蔽子模块名），
    # 这里 from-import 拿到的就是单例对象本身，直接在单例上打补丁。
    from app.modules.safety.ai_config import scenario_store, store

    cfg: dict = {"model": model, "api_key": api_key}
    if temperature is not None:
        cfg["temperature"] = temperature
    if max_tokens is not None:
        cfg["max_tokens"] = max_tokens

    monkeypatch.setattr(store, "get_profile_config", lambda p: dict(cfg))
    monkeypatch.setattr(scenario_store, "get_effective_profile", lambda scenario: profile)
    return cfg


# ── resolve_runtime_config：配置快照 ───────────────────────────────


def test_resolve_snapshot_reflects_profile(monkeypatch) -> None:
    _patch_config(monkeypatch, model="deepseek-chat", temperature=0.2, max_tokens=4096)
    from app.modules.safety.business_agent.agent import resolve_runtime_config

    cfg = resolve_runtime_config()
    assert cfg.profile == "text"
    assert cfg.model == "deepseek-chat"
    assert cfg.temperature == 0.2
    assert cfg.max_tokens == 4096
    assert cfg.fingerprint


def test_scenario_binding_switches_profile(monkeypatch) -> None:
    """绑定切到 text_backup → 读 backup profile 的配置（换模型零重启）。"""
    calls: list[str] = []

    from app.modules.safety.ai_config import scenario_store, store

    def fake_config(profile: str) -> dict:
        calls.append(profile)
        return {"model": "backup-model-x", "api_key": "sk-b-99"}

    monkeypatch.setattr(store, "get_profile_config", fake_config)
    monkeypatch.setattr(scenario_store, "get_effective_profile", lambda scenario: "text_backup")

    from app.modules.safety.business_agent.agent import resolve_runtime_config

    cfg = resolve_runtime_config()
    assert cfg.profile == "text_backup"
    assert cfg.model == "backup-model-x"
    assert calls == ["text_backup"]


def test_defaults_when_fields_missing(monkeypatch) -> None:
    """text_backup 无 temperature/max_tokens 字段 → 回退代码默认（0.1 / 8192）。"""
    _patch_config(
        monkeypatch, profile="text_backup", model="m", api_key="k",
        temperature=None, max_tokens=None,
    )
    from app.modules.safety.business_agent.agent import resolve_runtime_config

    cfg = resolve_runtime_config()
    assert cfg.temperature == 0.1
    assert cfg.max_tokens == 8192


def test_fingerprint_tracks_api_key_tail_only(monkeypatch) -> None:
    """指纹只含 api_key 尾 4 位：同尾不同头 → 同指纹；换尾 → 新指纹。"""
    from app.modules.safety.business_agent.agent import resolve_runtime_config

    _patch_config(monkeypatch, api_key="sk-aaaa1111")
    fp1 = resolve_runtime_config().fingerprint
    _patch_config(monkeypatch, api_key="sk-bbbb1111")
    fp2 = resolve_runtime_config().fingerprint
    _patch_config(monkeypatch, api_key="sk-aaaa2222")
    fp3 = resolve_runtime_config().fingerprint

    assert fp1 == fp2
    assert fp1 != fp3


# ── get_agent_for_tools：实例复用 / 重建 / 参数 ────────────────────


def test_same_config_reuses_instance(monkeypatch) -> None:
    _patch_config(monkeypatch)
    from app.modules.safety.business_agent.agent import get_agent_for_tools

    a1 = get_agent_for_tools(["query_hazards", "hazard_stats"])
    a2 = get_agent_for_tools(["hazard_stats", "query_hazards"])
    assert a1 is a2


def test_config_change_rebuilds_instance(monkeypatch) -> None:
    _patch_config(monkeypatch, model="model-a")
    from app.modules.safety.business_agent.agent import get_agent_for_tools

    a1 = get_agent_for_tools(["query_hazards"])
    _patch_config(monkeypatch, model="model-b")
    a2 = get_agent_for_tools(["query_hazards"])
    assert a1 is not a2


def test_param_change_only_rebuilds_on_fingerprint_change(monkeypatch) -> None:
    """temperature 调整也触发重建（参数进指纹）。"""
    from app.modules.safety.business_agent.agent import get_agent_for_tools

    _patch_config(monkeypatch, temperature=0.1)
    a1 = get_agent_for_tools(["query_hazards"])
    _patch_config(monkeypatch, temperature=0.3)
    a2 = get_agent_for_tools(["query_hazards"])
    assert a1 is not a2
    assert a2.model_settings == {"temperature": 0.3, "max_tokens": 8192}


def test_model_settings_follow_profile(monkeypatch) -> None:
    _patch_config(monkeypatch, temperature=0.05, max_tokens=2048)
    from app.modules.safety.business_agent.agent import get_agent_for_tools

    agent = get_agent_for_tools(["query_hazards"])
    assert agent.model_settings == {"temperature": 0.05, "max_tokens": 2048}


def test_empty_names_returns_resident_instance(monkeypatch) -> None:
    """None/空 → 常驻集实例（同一 resolve 通路，非 import 期冻结实例）。"""
    _patch_config(monkeypatch)
    from app.modules.safety.business_agent.agent import get_agent_for_tools

    a1 = get_agent_for_tools(None)
    a2 = get_agent_for_tools([])
    assert a1 is a2
    # 常驻实例也随配置变化重建
    _patch_config(monkeypatch, model="another-model")
    a3 = get_agent_for_tools(None)
    assert a3 is not a1


def test_cache_cap_clears_old_entries(monkeypatch) -> None:
    """缓存超上限整体清空懒重建（防配置版本 × 工具子集组合无限增长）。"""
    from app.modules.safety.business_agent import agent as agent_mod
    from app.modules.safety.business_agent.agent import get_agent_for_tools
    from app.modules.safety.business_agent.tools.registry import TOOL_KIND

    monkeypatch.setattr(agent_mod, "_AGENT_CACHE_MAX", 3)
    _patch_config(monkeypatch)

    names = sorted(TOOL_KIND.keys())[:5]
    first = get_agent_for_tools([names[0]])
    for name in names[1:]:
        get_agent_for_tools([name])

    assert len(agent_mod._AGENT_CACHE) <= 3
    # 首个实例已被清出缓存 → 再取会重建
    assert get_agent_for_tools([names[0]]) is not first


def test_executor_model_name_resolves_runtime(monkeypatch) -> None:
    """审计用模型名跟随 resolve（不再引用 import 期实例）。"""
    _patch_config(monkeypatch, model="audit-model")
    from app.modules.safety.business_agent.executor import _model_name

    assert _model_name() == "audit-model"


def test_import_does_not_instantiate_provider() -> None:
    """模块导入期不读配置不建 Provider：空 API key 环境（无 .env 兜底）可正常 import。"""
    backend_root = Path(__file__).resolve().parents[2].parent
    env = {
        **os.environ,
        "APP_ENV": "__p2_import_check__",
        "SAFETY_AI_TEXT_API_KEY": "",
        "PYTHONPATH": ".",
    }
    proc = subprocess.run(
        [sys.executable, "-c", "import app.modules.safety.business_agent.agent"],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
