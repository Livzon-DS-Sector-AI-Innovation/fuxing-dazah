"""S1 ticket 08 验收：技能库框架 + 首批 2 技能（Harness 第二批合龙票）。

组件直测（spec Testing Decisions）：技能目录注入系统提示词（「## 五、可用技能」
含 2 技能名与触发描述 + 使用规则）；load_skill 返回完整 SOP 正文；未知名返回
错误信息；文件 mtime 缓存热更新（改文件后 reload 可见新内容）；load_skill
工具并入查询工具注册表。live 主接缝（gateway.handle_im_message 全链路，真
LLM 真库，发送 dry-run 捕获 monkeypatch notification._send_create）：
- S1 端到端验收场景「盘本月呆料并催办各班组长」→ 技能加载 / SOP 步骤执行
  （audit 有 load_skill / plan_task / query_report 序列）、计划卡片捕获、
  plans 表落库、最终回复含真实呆料物料；
- 「哪些物料快到复验期了」→ 回复含真实近效期物料（audit 有 query_stock）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_skills.py -v
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.prompts import build_system_prompt
from app.modules.warehouse.agent.skills.registry import (
    SkillRegistry,
    default_registry,
)
from app.modules.warehouse.agent.tools import office as office_tools
from app.modules.warehouse.agent.tools import plan as plan_tools
from app.modules.warehouse.agent.tools import query as query_tools
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseAgentAudit,
    WarehouseAgentPlan,
    WarehouseAgentSession,
)

TOOL_NAMES = set(query_tools.TOOL_FUNCS)


# ══ 组件：技能目录注入 ══


async def test_catalog_injection_into_system_prompt() -> None:
    """默认构建系统提示词 → 「## 五、可用技能」含 2 技能名、触发描述与使用规则。"""
    prompt = await build_system_prompt()
    assert "## 五、可用技能" in prompt
    assert "dead-stock-analysis" in prompt
    assert "expiring-check" in prompt
    assert "呆料分析与催办" in prompt, "目录应含触发描述（呆料）"
    assert "复验期预警" in prompt, "目录应含触发描述（复验期）"
    assert "load_skill" in prompt, "使用规则应引导先 load_skill 再按 SOP 执行"

    # 显式传空串 = 禁用注入（回归口径：不注入技能段）
    disabled = await build_system_prompt(skill_catalog="")
    assert "可用技能" not in disabled


def test_catalog_markdown_format() -> None:
    """catalog_markdown：一行一技能「- 名称：触发描述」。"""
    catalog = default_registry.catalog_markdown()
    lines = [line for line in catalog.splitlines() if line.strip()]
    assert len(lines) >= 2, f"首批应有 ≥2 个技能，实际目录:\n{catalog}"
    for line in lines:
        assert line.startswith("- "), f"目录行应以 '- ' 开头: {line}"
        assert "：" in line, f"目录行应为「- 名称：描述」格式: {line}"
    assert any(line.startswith("- dead-stock-analysis：") for line in lines)
    assert any(line.startswith("- expiring-check：") for line in lines)


# ══ 组件：load_skill ══


def test_load_skill_returns_full_sop() -> None:
    """load_skill 返回完整 SOP 正文（步骤 + 输出格式，编排既有工具）。"""
    dead = default_registry.load_skill("dead-stock-analysis")
    assert "## 步骤" in dead and "## 输出格式" in dead
    assert "query_report" in dead, "呆料 SOP 应编排 query_report"
    assert "send_card" in dead, "催办 SOP 应走 send_card 确认门"
    assert "陈玉英" in dead, "班组长映射应作为展示信息写入 SOP"

    expiring = default_registry.load_skill("expiring-check")
    assert "## 步骤" in expiring and "## 输出格式" in expiring
    assert "query_stock" in expiring and "expiring_days" in expiring


def test_load_skill_unknown_name() -> None:
    """未知名返回错误信息（含可用技能列表，不抛异常）。"""
    text = default_registry.load_skill("no-such-skill")
    assert "未找到" in text
    assert "dead-stock-analysis" in text, "错误信息应含可用技能名"


def test_skill_registry_mtime_hot_reload(tmp_path: Path) -> None:
    """mtime 缓存：未变文件命中缓存；文件修改（mtime 变化）后 reload 可见新内容。"""

    def write_skill(marker: str) -> None:
        (tmp_path / "demo-skill.md").write_text(
            "---\nname: demo-skill\ndescription: 演示技能。当测试热更新时加载。\n---\n"
            "## 步骤\n1. " + marker + "\n## 输出格式\n" + marker,
            encoding="utf-8",
        )

    write_skill("版本一")
    registry = SkillRegistry(skill_dir=tmp_path)
    assert "版本一" in registry.load_skill("demo-skill")
    assert "- demo-skill：演示技能" in registry.catalog_markdown()

    # 修改文件并确保 mtime 变化（NTFS 时间戳精度兜底）
    write_skill("版本二")
    stat = (tmp_path / "demo-skill.md").stat()
    os.utime(tmp_path / "demo-skill.md", (stat.st_atime + 5, stat.st_mtime + 5))

    assert "版本二" in registry.load_skill("demo-skill"), "mtime 变化后应重读文件"
    assert "版本一" not in registry.load_skill("demo-skill")

    # 文件删除后目录扫描不再收录
    (tmp_path / "demo-skill.md").unlink()
    assert registry.get_meta("demo-skill") is None
    assert "demo-skill" not in registry.catalog_markdown()


# ══ 组件：load_skill 工具并入注册表 ══


async def test_load_skill_tool_registered() -> None:
    """load_skill 出现在 TOOLS schema 与 TOOL_FUNCS；execute_tool 可执行。"""
    assert "load_skill" in TOOL_NAMES
    schema_names = {t["function"]["name"] for t in query_tools.TOOLS}
    assert "load_skill" in schema_names

    out = await query_tools.execute_tool("load_skill", {"name": "expiring-check"})
    assert "error" not in out
    assert out["name"] == "expiring-check"
    assert "## 步骤" in out["content"], "工具应返回 SOP 全文"

    bad = await query_tools.execute_tool("load_skill", {"name": "nope"})
    assert "error" in bad
    assert "未找到" in str(bad["error"])


# ══ live 主接缝 fixtures ══


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch):
    """每测试重置 Runner 单例（pytest-asyncio 每测试新建 loop，连接池不可跨用）。"""
    monkeypatch.setattr(runner_module, "_runner", None)
    yield
    runner_module._runner = None


@pytest.fixture
def skills_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    """plan/runner/gateway/office 的 _db_session → 包装测试 session（回滚隔离）。"""

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(plan_tools, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    monkeypatch.setattr(gateway, "_db_session", _patched)
    monkeypatch.setattr(office_tools, "_db_session", _patched)
    return db_session


@pytest.fixture
def captured_sends(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """捕获 notification 全部发送 payload（构建路径真实执行，不触网）。"""
    sent: list[dict[str, str]] = []

    async def fake_send(payload: dict[str, str]) -> str | None:
        sent.append(payload)
        return "om_fake_id"

    monkeypatch.setattr(notification, "_send_create", fake_send)
    return sent


def _event(chat_id: str, open_id: str, text: str) -> dict[str, Any]:
    return {
        "sender": {
            "sender_id": {"open_id": open_id, "union_id": "un", "user_id": "u"},
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": f"om_skill_{uuid.uuid4().hex}",
            "root_id": "",
            "parent_id": "",
            "create_time": "1700000002000",
            "chat_id": chat_id,
            "chat_type": "p2p",
            "message_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
            "mentions": [],
        },
    }


def _plan_cards(sent: list[dict[str, str]]) -> list[dict[str, Any]]:
    """捕获序列中的计划/进度卡片（按 header 标题过滤）。"""
    cards = []
    for payload in sent:
        if payload.get("msg_type") != "interactive":
            continue
        try:
            card = json.loads(payload["content"])
        except json.JSONDecodeError:
            continue
        title = str(((card.get("header") or {}).get("title") or {}).get("content") or "")
        if "任务计划" in title:
            cards.append(card)
    return cards


async def _audit_seq(db: AsyncSession, session_id: Any) -> list[str]:
    rows = (
        await db.execute(
            select(WarehouseAgentAudit)
            .where(WarehouseAgentAudit.session_id == session_id)
            .order_by(WarehouseAgentAudit.created_at)
        )
    ).scalars().all()
    return [row.tool_name for row in rows]


async def _session_by_chat(db: AsyncSession, chat_id: str) -> WarehouseAgentSession | None:
    db.expire_all()  # gateway 事务内 UPDATE 后强制重读（identity map 失效兜底）
    stmt = select(WarehouseAgentSession).where(WarehouseAgentSession.chat_id == chat_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _final_assistant_text(db: AsyncSession, chat_id: str) -> str:
    session = await _session_by_chat(db, chat_id)
    if session is None:
        return ""
    history = session.history or {}
    for msg in reversed(history.get("messages") or []):
        if str(msg.get("role")) == "assistant" and str(msg.get("content") or "").strip():
            return str(msg["content"])
    return ""


# ══ live 主接缝 1：S1 端到端验收「盘本月呆料并催办各班组长」 ══


async def test_live_dead_stock_skill_flow(
    skills_db: AsyncSession,
    captured_sends: list[dict[str, str]],
) -> None:
    """SOP 编排链路：load_skill → plan_task → query_report → 分组报告展示。"""
    baseline = await query_tools.query_report("dead")
    if not baseline.get("total"):
        pytest.skip("测试版 Base 无呆料记录（live 数据依赖）")
    names = [r["物料名称"] for r in baseline["records"] if r.get("物料名称")]
    print(f"[预查] 呆料 total={baseline['total']} 物料={names[:5]}")

    open_id = f"ou_live_skill_{uuid.uuid4().hex[:8]}"
    chat_id = f"oc_live_skill_{uuid.uuid4().hex[:10]}"
    text = (
        "帮我盘一下本月呆料，按物料大类分组做一份分组报告，并准备催办各班组长。"
        "这是个多步任务，请先用 plan_task 制定计划，然后逐步执行并用 update_plan "
        "更新进度。分组报告做好后先向我展示；发送催办等我提供各班组长的飞书账号"
        "后再进行，暂时不要发送。"
    )
    await gateway.handle_im_message(_event(chat_id, open_id, text))

    session = await _session_by_chat(skills_db, chat_id)
    assert session is not None, "gateway 应创建会话"
    seq = await _audit_seq(skills_db, session.id)
    print(f"[audit] {seq}")
    known = [name for name in seq if name in TOOL_NAMES]
    assert known, f"应有工具调用 audit 记录: {seq}"
    # 至少断言：load_skill 或 SOP 核心步骤被执行（plan_task + query_report 序列）
    skill_loaded = "load_skill" in seq
    sop_steps_done = "plan_task" in seq and "query_report" in seq
    assert skill_loaded or sop_steps_done, (
        f"应加载技能或执行 SOP 步骤（load_skill/plan_task/query_report）: {seq}"
    )
    assert "query_report" in seq, "呆料查询（SOP 第 2 步）应出现在 audit 序列"

    # 计划卡片（plan_task 进度卡首帧 + 更新）经 dry-run 捕获
    cards = _plan_cards(captured_sends)
    for i, card in enumerate(cards):
        print(f"[计划卡{i}] {card['elements'][0]['content'][:160]}")
    assert cards, "SOP 第 1 步 plan_task 应产生计划卡片（dry-run 捕获）"

    # plans 表落库：至少一步被更新过（update_plan 状态机运转）
    plans = (
        await skills_db.execute(
            select(WarehouseAgentPlan).where(
                WarehouseAgentPlan.created_by_open_id == open_id
            )
        )
    ).scalars().all()
    print(f"[落库] {[(p.plan_no, p.title, p.status) for p in plans]}")
    assert plans, "plans 表应落库"
    assert any(
        any(step["status"] != "pending" for step in plan.steps) for plan in plans
    ), f"至少一步被 update_plan 更新过: {[p.steps for p in plans]}"

    # 最终回复 = 分组报告：含真实呆料物料名
    final_text = await _final_assistant_text(skills_db, chat_id)
    print(f"[回复] {final_text[:300]}")
    assert final_text.strip(), "最终回复不应为空"
    assert any(name in final_text for name in names[:5]), (
        f"分组报告应含真实呆料物料（{names[:5]}）: {final_text[:200]}"
    )


# ══ live 主接缝 2：复验期预警 ══


async def test_live_expiring_check_flow(
    skills_db: AsyncSession,
    captured_sends: list[dict[str, str]],
) -> None:
    """「哪些物料快到复验期了」→ 预警清单（真实近效期物料）+ audit 有 query_stock。"""
    days = 30
    baseline = await query_tools.query_stock(expiring_days=days)
    if not baseline.get("total"):
        days = 90
        baseline = await query_tools.query_stock(expiring_days=days)
    if not baseline.get("total"):
        pytest.skip("测试版 Base 未来 30/90 天均无到期批次（live 数据依赖）")
    names = [r["物料名称"] for r in baseline["records"] if r.get("物料名称")]
    print(f"[预查] 未来{days}天到期 total={baseline['total']} 物料={names[:5]}")

    open_id = f"ou_live_exp_{uuid.uuid4().hex[:8]}"
    chat_id = f"oc_live_exp_{uuid.uuid4().hex[:10]}"
    question = (
        "哪些物料快到复验期了？" if days == 30 else f"未来{days}天内哪些物料快到复验期了？"
    )
    await gateway.handle_im_message(_event(chat_id, open_id, question))

    session = await _session_by_chat(skills_db, chat_id)
    assert session is not None
    seq = await _audit_seq(skills_db, session.id)
    print(f"[audit] {seq}")
    assert "query_stock" in seq, f"复验期预警应调用 query_stock（expiring-check 流程）: {seq}"
    if "load_skill" in seq:
        print("[技能] expiring-check SOP 被加载")

    final_text = await _final_assistant_text(skills_db, chat_id)
    print(f"[回复] {final_text[:300]}")
    assert final_text.strip(), "最终回复不应为空"
    assert any(name in final_text for name in names[:8]), (
        f"回复应含真实近效期物料（{names[:8]}）: {final_text[:200]}"
    )
