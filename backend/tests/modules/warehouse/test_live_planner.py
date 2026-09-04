"""S1 ticket 05 验收：任务计划器（Harness 第二批第一票）。

组件直测（spec Testing Decisions）：PlanService（plans 表读写 + 步骤状态机 +
进度卡片首帧/重发），真库 whdev、事务回滚隔离；卡片渲染纯函数断言。
live 主接缝：gateway.handle_im_message 全链路（真 LLM 真库），发送 dry-run
捕获（monkeypatch notification._send_create）：
- 「盘点呆料并按大类分组再汇总」→ 捕获序列出现计划卡片 + ≥2 次进度卡片更新，
  plans 表落库；
- 中断恢复：预置部分完成的计划 → 新消息「继续刚才的盘点任务」→ Agent 从
  plans 表恢复（回复提到 plan_no / 剩余步骤）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_planner.py -v
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.cards import render_progress_card
from app.modules.warehouse.agent.repository import get_or_create_session
from app.modules.warehouse.agent.tools import plan as plan_tools
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseAgentPlan,
    WarehouseAgentSession,
)

PLAN_NO_PREFIX = f"WP{date.today().strftime('%Y%m%d')}-"


# ── fixtures ──


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch):
    """每测试重置 Runner 单例（pytest-asyncio 每测试新建 loop，连接池不可跨用）。"""
    monkeypatch.setattr(runner_module, "_runner", None)
    yield
    runner_module._runner = None


@pytest.fixture
def planner_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    """plan/runner/gateway 的 _db_session → 包装测试 session（不 commit，回滚隔离）。"""

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(plan_tools, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    monkeypatch.setattr(gateway, "_db_session", _patched)
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


async def _make_session(db: AsyncSession, *, open_id: str = "ou_planner") -> WarehouseAgentSession:
    return await get_or_create_session(
        db, chat_id=f"oc_plan_{uuid.uuid4().hex[:10]}", user_open_id=open_id
    )


async def _plan_by_no(db: AsyncSession, plan_no: str) -> WarehouseAgentPlan | None:
    stmt = select(WarehouseAgentPlan).where(WarehouseAgentPlan.plan_no == plan_no)
    return (await db.execute(stmt)).scalar_one_or_none()


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


# ══ 组件：PlanService ══


async def test_create_plan_persists_steps(planner_db: AsyncSession) -> None:
    """create_plan → plans 表记录 + 步骤初始全 pending + 会话/发起人关联。"""
    session = await _make_session(planner_db)
    result = await plan_tools.create_plan(
        title="盘点呆料并按大类分组汇总",
        steps=["查询呆料批次清单", "按物料大类分组统计", "汇总各类数量"],
        session_id=session.id,
        open_id=session.user_open_id,
    )
    assert "error" not in result
    assert result["plan_no"].startswith(PLAN_NO_PREFIX)
    assert [s["status"] for s in result["steps"]] == ["pending"] * 3
    assert [s["no"] for s in result["steps"]] == [1, 2, 3]

    row = await _plan_by_no(planner_db, result["plan_no"])
    assert row is not None
    assert row.title == "盘点呆料并按大类分组汇总"
    assert row.status == "active"
    assert row.session_id == session.id
    assert row.created_by_open_id == session.user_open_id
    assert len(row.steps) == 3
    assert all(step["status"] == "pending" for step in row.steps)


async def test_create_plan_sends_first_card(
    planner_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """plan_task 带 chat_id → 进度卡片首帧（全 pending 图标）。"""
    result = await plan_tools.create_plan(
        title="测试计划",
        steps=["第一步", "第二步", "第三步"],
        chat_id="oc_first_card",
    )
    assert "error" not in result
    cards = _plan_cards(captured_sends)
    assert len(cards) == 1
    content = cards[0]["elements"][0]["content"]
    assert result["plan_no"] in content
    assert content.count("⬜") == 3, f"首帧应 3 个 pending 图标: {content}"


async def test_update_step_valid_transitions(planner_db: AsyncSession) -> None:
    """合法状态迁移：in_progress → done，note 落库，返回进度。"""
    session = await _make_session(planner_db)
    created = await plan_tools.create_plan(
        title="迁移测试", steps=["甲", "乙", "丙"], session_id=session.id
    )
    plan_no = created["plan_no"]

    out1 = await plan_tools.update_step(
        plan_no=plan_no, step_no=1, status="in_progress"
    )
    assert "error" not in out1
    assert out1["status"] == "in_progress"
    assert out1["progress"] == "0/3"

    out2 = await plan_tools.update_step(
        plan_no=plan_no, step_no=1, status="done", note="已核对 12 条"
    )
    assert "error" not in out2
    assert out2["progress"] == "1/3"
    assert out2["plan_status"] == "active"

    row = await _plan_by_no(planner_db, plan_no)
    assert row is not None
    assert row.steps[0]["status"] == "done"
    assert row.steps[0]["note"] == "已核对 12 条"
    assert row.steps[1]["status"] == "pending"
    assert row.status == "active"


async def test_update_step_invalid_status(planner_db: AsyncSession) -> None:
    """非法状态值 → {"error": ...}，计划数据不变（不中断 Runner）。"""
    created = await plan_tools.create_plan(
        title="非法状态测试", steps=["甲", "乙"]
    )
    plan_no = created["plan_no"]
    out = await plan_tools.update_step(
        plan_no=plan_no, step_no=1, status="finished"
    )
    assert "error" in out
    assert "pending/in_progress/done/skipped/failed" in out["error"]

    row = await _plan_by_no(planner_db, plan_no)
    assert row is not None
    assert row.steps[0]["status"] == "pending"


async def test_update_step_unknown_plan_or_step(planner_db: AsyncSession) -> None:
    """plan_no 不存在 / step_no 越界 → error。"""
    out = await plan_tools.update_step(
        plan_no="WP19990101-999", step_no=1, status="done"
    )
    assert "error" in out

    created = await plan_tools.create_plan(title="越界测试", steps=["甲"])
    out2 = await plan_tools.update_step(
        plan_no=created["plan_no"], step_no=5, status="done"
    )
    assert "error" in out2
    assert "步骤" in out2["error"]


async def test_plan_done_when_all_terminal(planner_db: AsyncSession) -> None:
    """全部步骤终态（done/skipped）→ plan.status=done。"""
    created = await plan_tools.create_plan(
        title="完结测试", steps=["甲", "乙", "丙"]
    )
    plan_no = created["plan_no"]
    await plan_tools.update_step(plan_no=plan_no, step_no=1, status="done")
    await plan_tools.update_step(plan_no=plan_no, step_no=2, status="skipped")
    out = await plan_tools.update_step(plan_no=plan_no, step_no=3, status="done")
    assert out["plan_status"] == "done"

    row = await _plan_by_no(planner_db, plan_no)
    assert row is not None
    assert row.status == "done"


async def test_update_step_resends_progress_card(
    planner_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """update_step 带 chat_id → 每次重发新进度卡片（S1 不做 patch）。"""
    created = await plan_tools.create_plan(
        title="重发测试", steps=["甲", "乙"], chat_id="oc_resend"
    )
    await plan_tools.update_step(
        plan_no=created["plan_no"], step_no=1, status="done", note="ok",
        chat_id="oc_resend",
    )
    cards = _plan_cards(captured_sends)
    assert len(cards) == 2, f"首帧 + 1 次更新应 2 张卡片，实际 {len(cards)}"
    second = cards[1]["elements"][0]["content"]
    assert "✅" in second and "1. 甲" in second
    assert "进度 1/2" in second


async def test_plan_no_increments_same_day(planner_db: AsyncSession) -> None:
    """同日多个计划 plan_no 序号递增（WP+日期+NNN；相对断言，dev 库当天
    可能已有其他计划提交，序号基线不写死）。"""
    first = await plan_tools.create_plan(title="序号一", steps=["甲"])
    second = await plan_tools.create_plan(title="序号二", steps=["甲"])
    assert "error" not in first and "error" not in second
    assert first["plan_no"].startswith(PLAN_NO_PREFIX)
    seq = int(first["plan_no"][-3:])
    assert second["plan_no"] == f"{PLAN_NO_PREFIX}{seq + 1:03d}"


async def test_get_plan_detail_resume(planner_db: AsyncSession) -> None:
    """get_plan：缺省取最近 active 计划（中断恢复入口）；plan_no 指定取详情。"""
    session = await _make_session(planner_db, open_id="ou_resume")
    finished = await plan_tools.create_plan(
        title="已完成计划", steps=["甲"], session_id=session.id
    )
    await plan_tools.update_step(
        plan_no=finished["plan_no"], step_no=1, status="done"
    )
    active = await plan_tools.create_plan(
        title="进行中计划",
        steps=["查询呆料批次清单", "按大类分组"],
        session_id=session.id,
    )

    got = await plan_tools.get_plan_detail(session_id=session.id)
    assert got["found"] is True
    assert got["plan"]["plan_no"] == active["plan_no"]
    assert got["plan"]["status"] == "active"
    assert got["plan"]["steps"][0]["status"] == "pending"

    got_by_no = await plan_tools.get_plan_detail(plan_no=finished["plan_no"])
    assert got_by_no["plan"]["status"] == "done"

    none_got = await plan_tools.get_plan_detail(
        session_id=uuid.uuid4(), open_id="ou_nobody"
    )
    assert none_got["found"] is False


# ══ 组件：进度卡片渲染 ══


def test_render_progress_card_all_statuses() -> None:
    """各状态图标 / 标题 / note / 进度行断言。"""
    card = render_progress_card(
        {
            "plan_no": "WP20260904-001",
            "title": "盘点呆料并按大类分组汇总",
            "status": "active",
            "steps": [
                {"no": 1, "desc": "查询呆料批次清单", "status": "done"},
                {"no": 2, "desc": "按物料大类分组统计", "status": "in_progress",
                 "note": "已分组 3 类"},
                {"no": 3, "desc": "汇总各类数量", "status": "pending"},
                {"no": 4, "desc": "废弃步骤", "status": "skipped"},
                {"no": 5, "desc": "失败步骤", "status": "failed"},
            ],
        }
    )
    assert card["header"]["title"]["content"] == "📋 任务计划"
    content = card["elements"][0]["content"]
    assert "WP20260904-001" in content and "盘点呆料" in content
    assert "✅ 1. 查询呆料批次清单" in content
    assert "⏳ 2. 按物料大类分组统计" in content
    assert "已分组 3 类" in content
    assert "⬜ 3. 汇总各类数量" in content
    assert "⏭ 4. 废弃步骤" in content
    assert "❌ 5. 失败步骤" in content
    assert "进度 3/5" in content  # done+skipped+failed 计入已完成


def test_render_progress_card_done_template() -> None:
    """计划全部完成 → 卡片标题不变、配色转绿。"""
    card = render_progress_card(
        {
            "plan_no": "WP20260904-002",
            "title": "小任务",
            "status": "done",
            "steps": [{"no": 1, "desc": "唯一一步", "status": "done"}],
        }
    )
    assert card["header"]["template"] == "green"
    assert "进度 1/1" in card["elements"][0]["content"]


# ══ live 主接缝：多步任务规划执行 ══


async def test_live_planned_task_flow(
    planner_db: AsyncSession,
    captured_sends: list[dict[str, str]],
) -> None:
    """「盘点呆料并按大类分组再汇总」→ plan_task 首帧 + ≥2 次 update_plan 进度卡；plans 落库。"""
    chat_id = f"oc_live_plan_{uuid.uuid4().hex[:10]}"
    event = {
        "sender": {
            "sender_id": {"open_id": "ou_live_planner", "union_id": "un", "user_id": "u"},
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": f"om_plan_{uuid.uuid4().hex}",
            "root_id": "",
            "parent_id": "",
            "create_time": "1700000000000",
            "chat_id": chat_id,
            "chat_type": "p2p",
            "message_type": "text",
            "content": json.dumps(
                {"text": "帮我盘点呆料并按大类分组，再汇总数量。"
                         "这是个多步任务，请先用 plan_task 制定计划，"
                         "然后逐步执行，每完成一步就用 update_plan 更新进度。"},
                ensure_ascii=False,
            ),
            "mentions": [],
        },
    }
    await gateway.handle_im_message(event)
    print(f"[捕获] {len(captured_sends)} 次发送")

    cards = _plan_cards(captured_sends)
    for i, card in enumerate(cards):
        print(f"[计划卡{i}] {card['elements'][0]['content'][:200]}")
    assert len(cards) >= 3, (
        f"计划首帧 + ≥2 次进度更新应 ≥3 张计划卡，实际 {len(cards)}"
    )
    first_content = cards[0]["elements"][0]["content"]
    assert "⬜" in first_content, "首帧应含 pending 步骤"
    assert any(
        ("✅" in c["elements"][0]["content"] or "⏳" in c["elements"][0]["content"])
        for c in cards[1:]
    ), "进度卡片应出现 done/in_progress 状态"

    rows = (
        await planner_db.execute(
            select(WarehouseAgentPlan).where(
                WarehouseAgentPlan.created_by_open_id == "ou_live_planner"
            )
        )
    ).scalars().all()
    assert rows, "plans 表应落库"
    target = rows[0]
    print(f"[落库] {target.plan_no} {target.title} status={target.status}")
    assert target.plan_no.startswith("WP")
    assert any(step["status"] != "pending" for step in target.steps), (
        f"至少一步被更新过，实际 {target.steps}"
    )


# ══ live 中断恢复 ══


async def test_live_interrupted_resume(
    planner_db: AsyncSession,
    captured_sends: list[dict[str, str]],
) -> None:
    """预置半完成计划 → 新会话「继续刚才的盘点任务」→ Agent 从 plans 表恢复。"""
    session = await _make_session(planner_db, open_id="ou_resume_live")
    created = await plan_tools.create_plan(
        title="呆料盘点并按大类分组汇总",
        steps=["查询呆料批次清单", "按物料大类分组统计", "汇总各类数量"],
        session_id=session.id,
        open_id=session.user_open_id,
    )
    plan_no = created["plan_no"]
    await plan_tools.update_step(
        plan_no=plan_no, step_no=1, status="done", note="已取得呆料批次清单"
    )

    event = {
        "sender": {
            "sender_id": {"open_id": session.user_open_id, "union_id": "un", "user_id": "u"},
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": f"om_resume_{uuid.uuid4().hex}",
            "root_id": "",
            "parent_id": "",
            "create_time": "1700000001000",
            "chat_id": session.chat_id,
            "chat_type": "p2p",
            "message_type": "text",
            "content": json.dumps(
                {"text": f"继续刚才的盘点任务（{plan_no}），把剩下的步骤做完。"},
                ensure_ascii=False,
            ),
            "mentions": [],
        },
    }
    await gateway.handle_im_message(event)

    row = await _plan_by_no(planner_db, plan_no)
    assert row is not None
    print(f"[恢复后] {row.plan_no} status={row.status} steps={row.steps}")
    resumed = (
        row.status == "done"
        or sum(1 for s in row.steps if s["status"] != "pending") >= 2
    )
    assert resumed, f"中断恢复应推进剩余步骤，实际 {row.steps}"
