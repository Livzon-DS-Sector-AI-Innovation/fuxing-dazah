"""工具子集选择器（tool_selector）覆盖回归测试。

背景（2026-09-11 线上回复）：
    飞书安全助手对「把最新的隐患督办通报发给我」回复
    「本次会话中『督办通报生成』工具未挂载」。

根因：
    - executor 按关键词把工具收窄成子集（``tool_selector.select_tool_names``）；
    - 但 ``TOOL_GROUPS`` 漏登记了 17 个工具（含 ``generate_supervision_bulletin`` /
      ``send_hazard_supervision_bulletin``），命中「隐患」类关键词时它们被摘掉；
    - 同时 system prompt 的 ``tool_catalog`` 节按角色目录（``allowed_tools``）
      把它们列为「可用工具」 模型知道工具名、却不在实际工具表里  回复「未挂载」。

本测试钉住两条不变量：
    1. registry 注册的每个工具都至少属于一个意图分组（防止新工具再次"不可达"）；
    2. agent.md 写明的触发话术必须真能选到对应工具。
"""

from __future__ import annotations

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    KNOWN_ROLES,
    allowed_tools,
)
from app.modules.safety.business_agent.tools import registry


def _grouped_tool_names() -> set[str]:
    names: set[str] = set()
    for group in tool_selector.TOOL_GROUPS.values():
        names.update(group)
    return names


def test_every_registered_tool_belongs_to_a_group() -> None:
    """registry 里的工具必须至少出现在一个意图分组里。

    否则命中其它意图关键词时，它会从子集里被静默摘掉（本次事故的根因）。
    """
    registered = set(registry._FUNC_BY_NAME)
    grouped = _grouped_tool_names()

    assert grouped <= registered, f"分组里写了不存在的工具: {sorted(grouped - registered)}"
    missing = sorted(registered - grouped)
    assert missing == [], (
        f"这些工具不在任何意图分组里，关键词收窄时永远选不到: {missing}"
    )


def test_tool_groups_align_with_intent_keywords() -> None:
    """TOOL_GROUPS 的每个分组都应有对应的意图关键词，否则该组永远选不到。"""
    silent = sorted(set(tool_selector.TOOL_GROUPS) - set(tool_selector.INTENT_KEYWORDS))
    assert silent == [], f"这些分组没有关键词、永远无法命中: {silent}"


def test_role_catalog_only_lists_registered_tools() -> None:
    """tool_catalog 节按角色目录渲染；目录里的工具必须真实存在（防再次"画饼"）。"""
    registered = set(registry._FUNC_BY_NAME)
    for role in KNOWN_ROLES:
        unknown = sorted(allowed_tools(role) - registered)
        assert unknown == [], f"角色 {role} 的目录里有无此工具的名字: {unknown}"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # 本次线上问题：命中「隐患」但工具被摘掉
        ("把最新的隐患督办通报发给我", "generate_supervision_bulletin"),
        ("隐患督办通报", "generate_supervision_bulletin"),
        ("看一下督办情况", "generate_supervision_bulletin"),
        ("把督办通报发到群里", "send_hazard_supervision_bulletin"),
        ("轮询一下隐患AI分析", "poll_hazard_ai_analysis"),
        ("补一下隐患的整改审核", "poll_hazard_rectification_review"),
        # 同类：office 写工具（无链接/token 时走不到全量回退）
        ("把本月隐患汇总导出成电子表格", "office_create_sheet"),
        # 同类：操规审核 / URS PDF
        ("用法规审核一下这份操作规程", "run_regulation_ai_review"),
        ("导出URS智能审核报告PDF", "generate_urs_report_pdf"),
    ],
)
def test_documented_triggers_select_expected_tool(message: str, expected: str) -> None:
    """agent.md 写明的触发话术必须能选到对应工具。

    选择器没有任何匹配时会返回 None（调用方回退全量工具），也算可用；
    但只要返回了子集，目标工具就必须在子集里。
    """
    names = tool_selector.select_tool_names(message)
    assert names is None or expected in names, f"{message!r}  {names}"


@pytest.mark.parametrize(
    "message",
    ["把最新的隐患督办通报发给我", "隐患督办通报"],
)
def test_hazard_bulletin_phrases_do_not_fall_back_to_all_tools(message: str) -> None:
    """「隐患督办通报」必须命中 hazard 分组（而非返回 None 让全量回退兜底）。

    返回 None 虽可用，但说明关键词没覆盖到；这里显式钉住关键词命中。
    """
    names = tool_selector.select_tool_names(message)
    assert names is not None
    assert {"generate_supervision_bulletin", "query_hazards"} <= set(names)
