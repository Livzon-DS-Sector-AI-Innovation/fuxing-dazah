"""tool_catalog 与「本轮实际挂载工具」一致性测试。

背景（2026-09-11 线上）：飞书安全助手回「督办通报生成工具未挂载」。
根因是 prompt 的 tool_catalog 节渲染的是角色目录 ``allowed_tools(role)``，
而 Agent 实际只注册关键词子集  prompt "画饼"。
修复后 catalog = 角色允许 与 本轮实际挂载 的交集。

本测试钉住的四条不变量：
    1. 目录只列本轮真的挂载了的工具；
    2. 目录不列角色无权调用的工具；
    3. 目录缺省（无 context）时退化为 registry 全量，绝不超出真实工具表；
    4. 本轮一个工具都没挂载时，明确告知"未挂载"，而不是留白让模型瞎猜。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.safety.business_agent.core.permissions import allowed_tools
from app.modules.safety.business_agent.core.prompt import (
    ALL_SECTIONS,
    ToolCatalogSection,
    assemble,
)
from app.modules.safety.business_agent.tools import registry

_HEAD = "可用工具："


def _deps(role: str | None) -> SimpleNamespace:
    """只用到 role 字段；其余节在 render 里按需取。"""
    return SimpleNamespace(role=role, person=None)


def _parse_catalog(text: str) -> set[str]:
    assert _HEAD in text
    body = text.split(_HEAD, 1)[1].strip()
    if body.startswith("无（"):
        return set()
    return {name.strip() for name in body.split(",") if name.strip()}


def test_catalog_only_lists_registered_subset() -> None:
    mounted = ["query_hazards", "knowledge_search"]
    text = ToolCatalogSection().render(_deps("safety_admin"), {"tool_names": mounted})
    assert _parse_catalog(text) == set(mounted)


def test_catalog_never_advertises_unmounted_tool() -> None:
    """本次事故回归：督办通报工具没挂载时，目录里不能再出现它。"""
    mounted = ["query_hazards", "knowledge_search"]
    text = ToolCatalogSection().render(_deps("safety_admin"), {"tool_names": mounted})
    assert "generate_supervision_bulletin" not in text
    assert "send_hazard_supervision_bulletin" not in text


def test_catalog_excludes_role_forbidden_tool() -> None:
    mounted = ["query_hazards", "send_hazard_supervision_bulletin"]
    text = ToolCatalogSection().render(_deps("viewer"), {"tool_names": mounted})
    assert "query_hazards" in _parse_catalog(text)
    assert "send_hazard_supervision_bulletin" not in text


def test_catalog_is_explicit_when_nothing_mounted() -> None:
    text = ToolCatalogSection().render(
        _deps("viewer"), {"tool_names": ["send_hazard_supervision_bulletin"]}
    )
    assert "本轮未挂载任何工具" in text
    assert _parse_catalog(text) == set()


def test_catalog_fallback_never_exceeds_registry() -> None:
    text = ToolCatalogSection().render(_deps("safety_admin"), {})
    names = _parse_catalog(text)
    assert names == set(allowed_tools("safety_admin"))
    assert names <= set(registry.TOOL_KIND)


def test_catalog_empty_for_role_none() -> None:
    text = ToolCatalogSection().render(_deps(None), {"tool_names": ["query_hazards"]})
    assert text == ""


def test_assemble_uses_passed_tool_names() -> None:
    prefix = assemble(
        ALL_SECTIONS, _deps("safety_admin"), {"tool_names": ["query_hazards"]}
    )
    assert f"{_HEAD}query_hazards" in prefix


def test_bulletin_query_is_both_mounted_and_advertised() -> None:
    """端到端：『隐患督办通报』既真的挂载，也如实写进目录。"""
    from app.modules.safety.business_agent.executor import _registered_tool_names
    from app.modules.safety.business_agent.tool_selector import select_tool_names

    mounted = _registered_tool_names(select_tool_names("把最新的隐患督办通报发给我"))
    assert "generate_supervision_bulletin" in mounted

    text = ToolCatalogSection().render(_deps("safety_admin"), {"tool_names": mounted})
    assert "generate_supervision_bulletin" in text


def test_registered_tool_names_matches_agent_input() -> None:
    from app.modules.safety.business_agent.executor import _registered_tool_names

    assert _registered_tool_names(None) == sorted(registry.TOOL_KIND)
    assert _registered_tool_names([]) == sorted(registry.TOOL_KIND)
    # 未知工具名与 register_tools_subset 一样被丢弃
    assert _registered_tool_names(["query_hazards", "not_a_tool"]) == ["query_hazards"]
