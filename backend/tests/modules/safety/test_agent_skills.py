"""2-B SOP 技能化基建：skills registry + load_skill 工具 + 目录注入。

组件直测（无 LLM/网络/DB），对齐仓储 test_live_skills.py 六件套骨架，
接缝：
- ``SkillRegistry``（目录扫描/mtime 热更新/catalog/load）
- ``load_skill`` 工具（经 execute_tool 管道可执行）
- ``SkillCatalogSection``（prompt 组装的「可用技能」节）

依据：.scratch/safety-agent-optimization-p2/spec.md 2-B 节。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

_SKILL_MD = """---
name: daily-report-output
description: 日报输出规则。当用户要生成特殊作业日报时加载。
---

## 步骤

1. 调用 generate_daily_report
2. 原样输出工具返回的 markdown

## 输出格式

按工具返回原文输出，禁止增删段落。
"""


def _make_registry(tmp_path: Path):
    from app.modules.safety.business_agent.skills.registry import SkillRegistry

    return SkillRegistry(tmp_path)


def _write_skill(tmp_path: Path, filename: str = "daily-report-output.md",
                 content: str = _SKILL_MD) -> Path:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return path


# ── 目录格式与扫描 ────────────────────────────────────────────────


def test_catalog_markdown_format(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    reg = _make_registry(tmp_path)
    catalog = reg.catalog_markdown()
    assert catalog == "- daily-report-output：日报输出规则。当用户要生成特殊作业日报时加载。"


def test_list_skills_requires_frontmatter_name(tmp_path: Path) -> None:
    (tmp_path / "no-frontmatter.md").write_text("## 步骤\n没有 frontmatter", encoding="utf-8")
    reg = _make_registry(tmp_path)
    assert reg.list_skills() == []
    assert reg.catalog_markdown() == ""


# ── load_skill：全文/未知名 ──────────────────────────────────────


def test_load_skill_returns_full_sop(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    reg = _make_registry(tmp_path)
    body = reg.load_skill("daily-report-output")
    assert "## 步骤" in body
    assert "## 输出格式" in body
    assert "generate_daily_report" in body
    assert "daily-report-output" not in body  # frontmatter 之后才是正文


def test_load_skill_unknown_name(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    reg = _make_registry(tmp_path)
    out = reg.load_skill("nope")
    assert "nope" in out
    assert "daily-report-output" in out  # 可用技能列表


# ── mtime 热更新 ─────────────────────────────────────────────────


def test_skill_registry_mtime_hot_reload(tmp_path: Path) -> None:
    path = _write_skill(tmp_path)
    reg = _make_registry(tmp_path)
    assert reg.load_skill("daily-report-output") == _SKILL_MD.split("---", 2)[2].strip()

    path.write_text(
        _SKILL_MD.replace("原样输出工具返回的 markdown", "改过的规则 v2"),
        encoding="utf-8",
    )
    os.utime(path, (os.stat(path).st_atime, os.stat(path).st_mtime + 10))
    assert "改过的规则 v2" in reg.load_skill("daily-report-output")

    path.unlink()
    assert reg.list_skills() == []


# ── 目录注入 prompt（空目录省略 / 有技能注入 + 引导文案）─────────


def _deps(role: str = "safety_admin") -> SimpleNamespace:
    return SimpleNamespace(
        role=role, session_id=None, channel="test", person=None, db=None,
    )


def test_catalog_injection_into_prompt(tmp_path: Path) -> None:
    from app.modules.safety.business_agent.core.prompt import (
        SkillCatalogSection,
        assemble,
    )
    from app.modules.safety.business_agent.skills.registry import SkillRegistry

    _write_skill(tmp_path)
    reg = SkillRegistry(tmp_path)
    ctx = {"tool_names": ["query_hazards"], "memories": []}

    with_skill = assemble(
        [SkillCatalogSection(_registry=reg)], _deps(), ctx,
    )
    assert "## 可用技能" in with_skill
    assert "daily-report-output" in with_skill
    assert "load_skill" in with_skill
    assert "禁止编造" in with_skill

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    empty = assemble(
        [SkillCatalogSection(_registry=SkillRegistry(empty_dir))],
        _deps(), ctx,
    )
    assert empty == ""


def test_skill_catalog_section_in_default_sections() -> None:
    from app.modules.safety.business_agent.core.prompt import (
        ALL_SECTIONS,
        SkillCatalogSection,
    )

    assert any(isinstance(s, SkillCatalogSection) for s in ALL_SECTIONS)


# ── 2-B 迁移验收：默认技能在册 + agent.md <8KB ──────────────────


def test_default_registry_has_migrated_sops() -> None:
    from app.modules.safety.business_agent.skills.registry import default_registry

    names = {s.name for s in default_registry.list_skills()}
    assert {
        "daily-report-output",
        "supervision-bulletin-output",
        "guardian-subsidy",
    } <= names


def test_agent_md_under_8kb() -> None:
    import app.modules.safety.business_agent.agent as agent_mod

    agent_md = Path(agent_mod.__file__).parent / "agent.md"
    assert agent_md.stat().st_size < 8192


def test_default_registry_has_drill_sop() -> None:
    from app.modules.safety.business_agent.skills.registry import default_registry

    names = {s.name for s in default_registry.list_skills()}
    assert "drill-plan-format" in names


# ── 演练 8 节格式唯源+热读（生成服务消费侧）───────────────────────


def test_drill_sections_hot_read_from_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """技能 .md 改动 → 下次生成读到新格式（唯源+热读）。"""
    from app.modules.safety.business_agent.skills import registry as skills_registry
    from app.modules.safety.service import emergency_drill

    modified = (
        "---\nname: drill-plan-format\ndescription: x\n---\n\n"
        "## 步骤\n\n1. x\n\n## 输出格式\n\n- x\n\n"
        "## 八节格式（生成服务唯源）\n\n"
        "方案必须包含以下9个部分（测试改写 v2）：\n\n一、新格式第一节……\n"
    )
    (tmp_path / "drill-plan-format.md").write_text(modified, encoding="utf-8")
    monkeypatch.setattr(
        skills_registry, "default_registry", skills_registry.SkillRegistry(tmp_path),
    )

    spec = emergency_drill._drill_sections_spec()
    assert "9个部分" in spec
    assert "新格式第一节" in spec
    # prompt 组装完整：头部规则 + 8/9 节格式 + JSON schema
    prompt = emergency_drill._build_drill_plan_prompt()
    assert "应急管理专家" in prompt
    assert "新格式第一节" in prompt
    assert "请以 JSON 格式返回" in prompt
    assert "cited_regulations" in prompt


def test_drill_sections_fallback_to_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """技能缺失 / 无「八节格式」节 → 回退内置默认，生成链路不断。"""
    from app.modules.safety.business_agent.skills import registry as skills_registry
    from app.modules.safety.service import emergency_drill

    # ① 目录里没有 drill-plan-format
    monkeypatch.setattr(
        skills_registry, "default_registry", skills_registry.SkillRegistry(tmp_path),
    )
    spec = emergency_drill._drill_sections_spec()
    assert "八、演练要求" in spec

    # ② 技能存在但没有唯源节
    (tmp_path / "drill-plan-format.md").write_text(
        "---\nname: drill-plan-format\ndescription: x\n---\n\n## 步骤\n\n1. x\n",
        encoding="utf-8",
    )
    skills_registry.default_registry._cache.clear()
    spec2 = emergency_drill._drill_sections_spec()
    assert spec2 == emergency_drill._DEFAULT_DRILL_SECTIONS


# ── load_skill 工具注册（名册/只读/常驻/权限/路由一致性）─────────


def test_load_skill_tool_registered() -> None:
    from app.modules.safety.business_agent.core.permissions import allowed_tools
    from app.modules.safety.business_agent.tools.registry import (
        _FUNC_BY_NAME,
        RESIDENT_TOOLS,
        TOOL_KIND,
    )

    assert "load_skill" in _FUNC_BY_NAME
    assert TOOL_KIND["load_skill"] is False
    assert "load_skill" in RESIDENT_TOOLS
    # 只读工具：四角色全部可用（通用能力）
    from app.modules.safety.business_agent.core.permissions import KNOWN_ROLES

    for role in KNOWN_ROLES:
        assert "load_skill" in allowed_tools(role)


def test_load_skill_tool_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety.business_agent import skills as skills_pkg
    from app.modules.safety.business_agent.skills import registry as skills_registry

    _write_skill(tmp_path)
    monkeypatch.setattr(
        skills_registry, "default_registry", skills_registry.SkillRegistry(tmp_path),
    )
    from app.modules.safety.business_agent.core.pipeline import execute_tool
    from app.modules.safety.business_agent.tools.registry import _FUNC_BY_NAME

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            role="viewer", session_id=None, channel="test", person=None,
        ),
    )
    out = asyncio.run(
        execute_tool(ctx, "load_skill", {"name": "daily-report-output"},
                     _FUNC_BY_NAME["load_skill"]),
    )
    assert out["name"] == "daily-report-output"
    assert "## 步骤" in out["content"]

    unknown = asyncio.run(
        execute_tool(ctx, "load_skill", {"name": "nope"},
                     _FUNC_BY_NAME["load_skill"]),
    )
    assert "error" in unknown
    assert skills_pkg is not None
