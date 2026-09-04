"""S1 ticket 06 验收：长期记忆（MemoryService + save_memory/recall_memory 工具）。

组件直测（spec Testing Decisions）：MemoryService（memories 表 save/recall +
注入排序 + hit_count 累加 + 超长截断），真库 whdev、事务回滚隔离。
live 主接缝（真 LLM 真库，发送 dry-run 捕获，monkeypatch notification._send_create）：
- 「记住我以后只要看危化品的东西」→ save_memory 被调用（audit 有记录）+
  memories 表落库 + 回复确认已记住；
- 新会话预置偏好后「硫酸还有多少」→ build_system_prompt 注入偏好片段
  （monkeypatch 捕获返回内容断言；LLM 回复自然即可不断言内容）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_memory.py -v
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import gateway
from app.modules.warehouse.agent import prompts as prompts_module
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.repository import (
    get_or_create_session,
    insert_memory,
)
from app.modules.warehouse.agent.tools import memory as memory_tools
from app.modules.warehouse.agent.tools.query import TOOL_FUNCS, TOOLS
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseAgentAudit,
    WarehouseAgentMemory,
)

# ── fixtures ──


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch):
    """每测试重置 Runner 单例（pytest-asyncio 每测试新建 loop，连接池不可跨用）。"""
    monkeypatch.setattr(runner_module, "_runner", None)
    yield
    runner_module._runner = None


@pytest.fixture
def memory_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    """memory/runner/gateway 的 _db_session → 包装测试 session（不 commit，回滚隔离）。"""

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(memory_tools, "_db_session", _patched)
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


async def _first_memory(
    db: AsyncSession, *, owner_open_id: str
) -> WarehouseAgentMemory | None:
    stmt = (
        select(WarehouseAgentMemory)
        .where(
            WarehouseAgentMemory.owner_open_id == owner_open_id,
            WarehouseAgentMemory.is_deleted == False,  # noqa: E712
        )
        .order_by(WarehouseAgentMemory.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


def _event(
    *, chat_id: str, open_id: str, text: str, message_id: str | None = None
) -> dict[str, Any]:
    return {
        "sender": {
            "sender_id": {"open_id": open_id, "union_id": "un", "user_id": "u"},
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": message_id or f"om_mem_{uuid.uuid4().hex}",
            "root_id": "",
            "parent_id": "",
            "create_time": "1700000000000",
            "chat_id": chat_id,
            "chat_type": "p2p",
            "message_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
            "mentions": [],
        },
    }


def _captured_text(sent: list[dict[str, str]]) -> str:
    """全部捕获卡片的内容拼接（确认词断言用）。"""
    parts: list[str] = []
    for payload in sent:
        if payload.get("msg_type") != "interactive":
            continue
        try:
            card = json.loads(payload["content"])
        except json.JSONDecodeError:
            continue
        for element in card.get("elements") or []:
            if element.get("tag") == "markdown":
                parts.append(str(element.get("content") or ""))
    return "\n".join(parts)


# ══ 组件：save / recall ══


async def test_save_and_recall_user_memory(memory_db: AsyncSession) -> None:
    """save(user preference) → recall 命中（内容/scope/类型一致）。"""
    out = await memory_tools.save(
        scope="user",
        owner_open_id="ou_mem_a",
        memory_type="preference",
        content="以后只看危化品的东西",
    )
    assert "error" not in out
    assert out["scope"] == "user" and out["memory_type"] == "preference"

    found = await memory_tools.recall(owner_open_id="ou_mem_a")
    assert found["total"] == 1
    row = found["memories"][0]
    assert row["content"] == "以后只看危化品的东西"
    assert row["scope"] == "user"
    assert row["memory_type"] == "preference"
    assert row["owner_open_id"] == "ou_mem_a"


async def test_scope_isolation(memory_db: AsyncSession) -> None:
    """user 记忆别的用户 recall 不到；global 记忆所有用户都能 recall。"""
    await memory_tools.save(
        scope="user",
        owner_open_id="ou_iso_a",
        memory_type="preference",
        content="用户A的私人偏好",
    )
    await memory_tools.save(
        scope="global",
        owner_open_id=None,
        memory_type="convention",
        content="报表默认不带包材",
    )

    found_a = await memory_tools.recall(owner_open_id="ou_iso_a")
    assert any(m["content"] == "用户A的私人偏好" for m in found_a["memories"])
    found_b = await memory_tools.recall(owner_open_id="ou_iso_b")
    assert all(m["content"] != "用户A的私人偏好" for m in found_b["memories"]), (
        f"user 记忆不应跨用户可见: {found_b}"
    )
    assert any(m["content"] == "报表默认不带包材" for m in found_a["memories"])
    assert any(m["content"] == "报表默认不带包材" for m in found_b["memories"])


async def test_recall_keyword_filter(memory_db: AsyncSession) -> None:
    """keyword 对 content 做 LIKE 模糊过滤，只返回命中条目。"""
    owner = "ou_kw"
    await memory_tools.save(
        scope="user", owner_open_id=owner,
        memory_type="preference", content="以后只看危化品的东西",
    )
    await memory_tools.save(
        scope="user", owner_open_id=owner,
        memory_type="preference", content="报表别带包材",
    )

    all_rows = await memory_tools.recall(owner_open_id=owner)
    assert all_rows["total"] == 2
    hit = await memory_tools.recall(owner_open_id=owner, keyword="危化品")
    assert hit["total"] == 1
    assert "危化品" in hit["memories"][0]["content"]
    miss = await memory_tools.recall(owner_open_id=owner, keyword="不存在的关键词")
    assert miss["total"] == 0


async def test_hit_count_increments(memory_db: AsyncSession) -> None:
    """recall / inject_context 每命中一次，hit_count 递增 1。"""
    owner = "ou_hit"
    await memory_tools.save(
        scope="user", owner_open_id=owner,
        memory_type="preference", content="偏好甲",
    )
    row0 = await _first_memory(memory_db, owner_open_id=owner)
    assert row0 is not None and row0.hit_count == 0

    await memory_tools.recall(owner_open_id=owner)
    row1 = await _first_memory(memory_db, owner_open_id=owner)
    assert row1 is not None and row1.hit_count == 1

    await memory_tools.inject_context(owner_open_id=owner)
    row2 = await _first_memory(memory_db, owner_open_id=owner)
    assert row2 is not None and row2.hit_count == 2


async def test_save_validation(memory_db: AsyncSession) -> None:  # noqa: ARG001
    """非法 memory_type / scope / 空 content / user 缺 owner → {"error"}，不落库。"""
    bad_type = await memory_tools.save(
        scope="user", owner_open_id="ou_v", memory_type="habit", content="x"
    )
    assert "error" in bad_type and "preference/convention/alias" in bad_type["error"]
    bad_scope = await memory_tools.save(
        scope="team", owner_open_id="ou_v", memory_type="preference", content="x"
    )
    assert "error" in bad_scope and "user/global" in bad_scope["error"]
    empty = await memory_tools.save(
        scope="user", owner_open_id="ou_v", memory_type="preference", content="  "
    )
    assert "error" in empty and "content" in empty["error"]
    no_owner = await memory_tools.save(
        scope="user", owner_open_id=None, memory_type="preference", content="x"
    )
    assert "error" in no_owner and "open_id" in no_owner["error"]


async def test_content_truncation(memory_db: AsyncSession) -> None:
    """content > 200 字符 → 截断到 200 并提示（落库内容同步截断）。"""
    out = await memory_tools.save(
        scope="user",
        owner_open_id="ou_trunc",
        memory_type="preference",
        content="危" * 250,
    )
    assert "error" not in out
    assert out["truncated"] is True
    assert len(out["content"]) == memory_tools.CONTENT_MAX_CHARS
    assert "截断" in out["message"]

    found = await memory_tools.recall(owner_open_id="ou_trunc")
    assert found["total"] == 1
    assert len(found["memories"][0]["content"]) == memory_tools.CONTENT_MAX_CHARS


# ══ 组件：inject_context ══


async def test_inject_context_empty(memory_db: AsyncSession) -> None:
    """无记忆时注入片段为空串（提示词不含记忆段）。"""
    assert await memory_tools.inject_context(owner_open_id="ou_none_xyz") == ""


async def test_inject_context_order_and_limits(memory_db: AsyncSession) -> None:
    """用户偏好 top3 + 全局惯例 top5，按 updated_at 倒序；用户段在全局段之前。"""
    owner = "ou_inject"
    now = datetime.now(UTC)
    for i in range(5):  # 偏好 0~4，编号越大越新
        row = await insert_memory(
            memory_db, scope="user", owner_open_id=owner,
            memory_type="preference", content=f"偏好{i}号",
        )
        row.updated_at = now - timedelta(minutes=10 - i)
    for i in range(7):  # 全局惯例 0~6，编号越大越新
        row = await insert_memory(
            memory_db, scope="global", owner_open_id=None,
            memory_type="convention", content=f"惯例{i}号",
        )
        row.updated_at = now - timedelta(minutes=40 - i)
    await memory_db.flush()

    fragment = await memory_tools.inject_context(owner_open_id=owner)
    print(f"[注入片段]\n{fragment}")
    assert fragment, "有记忆时注入片段不应为空"
    # 偏好 top3 = 最新 3 条（4/3/2），1/0 不出现
    assert "偏好4号" in fragment and "偏好3号" in fragment and "偏好2号" in fragment
    assert "偏好1号" not in fragment and "偏好0号" not in fragment
    # 全局 top5 = 最新 5 条（6~2），1/0 不出现
    assert "惯例6号" in fragment and "惯例2号" in fragment
    assert "惯例1号" not in fragment and "惯例0号" not in fragment
    # 段内倒序（最新在前），用户段在全局段之前
    idx = fragment.index
    assert idx("偏好4号") < idx("偏好3号") < idx("偏好2号")
    assert idx("惯例6号") < idx("惯例5号")
    assert idx("偏好4号") < idx("惯例6号")


# ══ 组件：工具注册表与 _ctx 注入 ══


def test_registry_merged() -> None:
    """save_memory / recall_memory 并入 query 注册表（TOOLS schema + TOOL_FUNCS）。"""
    assert TOOL_FUNCS["save_memory"] is memory_tools.save_memory
    assert TOOL_FUNCS["recall_memory"] is memory_tools.recall_memory
    names = {t["function"]["name"] for t in TOOLS}
    assert {"save_memory", "recall_memory"} <= names


async def test_tool_wrappers_ctx(memory_db: AsyncSession) -> None:
    """工具壳：memory_type 推导 scope（preference→user；convention/alias→global，
    owner 置空），_ctx 提供 open_id；recall_memory 支持可选 keyword。"""
    pref = await memory_tools.save_memory(
        "preference", "以后只看危化品的东西", _ctx={"open_id": "ou_tool"}
    )
    assert "error" not in pref
    assert pref["scope"] == "user" and pref["owner_open_id"] == "ou_tool"

    conv = await memory_tools.save_memory(
        "convention", "批号查询默认按入库日期倒序", _ctx={"open_id": "ou_tool"}
    )
    assert "error" not in conv
    assert conv["scope"] == "global" and conv["owner_open_id"] == ""

    bad = await memory_tools.save_memory("bogus", "x", _ctx={"open_id": "ou_tool"})
    assert "error" in bad

    found = await memory_tools.recall_memory(_ctx={"open_id": "ou_tool"})
    assert any("以后只看危化品" in m["content"] for m in found["memories"])
    assert any("批号查询默认" in m["content"] for m in found["memories"])

    hit = await memory_tools.recall_memory(keyword="批号", _ctx={"open_id": "ou_tool"})
    assert hit["total"] == 1 and "批号" in hit["memories"][0]["content"]


# ══ live 主接缝 1：显式纠正 → save_memory + 回复确认 ══


async def test_live_save_memory_on_correction(
    memory_db: AsyncSession,
    captured_sends: list[dict[str, str]],
) -> None:
    """「记住我以后只要看危化品的东西」→ save_memory 被调用（audit 记录）+
    memories 表落库该用户偏好 + 回复确认。"""
    open_id = f"ou_live_save_{uuid.uuid4().hex[:8]}"
    chat_id = f"oc_live_mem_{uuid.uuid4().hex[:10]}"
    await gateway.handle_im_message(
        _event(chat_id=chat_id, open_id=open_id, text="记住我以后只要看危化品的东西。")
    )

    # save_memory 工具被调用且成功（audit 记录）
    session = await get_or_create_session(
        memory_db, chat_id=chat_id, user_open_id=open_id
    )
    audits = (
        await memory_db.execute(
            select(WarehouseAgentAudit).where(
                WarehouseAgentAudit.session_id == session.id,
                WarehouseAgentAudit.tool_name == "save_memory",
            )
        )
    ).scalars().all()
    print(f"[audit] {[(a.result_status, dict(a.args_summary)) for a in audits]}")
    assert audits, "save_memory 应被调用并留下 audit 记录"
    assert any(a.result_status == "ok" for a in audits)

    # memories 表落库该用户的偏好
    memories = (
        await memory_db.execute(
            select(WarehouseAgentMemory).where(
                WarehouseAgentMemory.owner_open_id == open_id,
                WarehouseAgentMemory.is_deleted == False,  # noqa: E712
            )
        )
    ).scalars().all()
    print(f"[落库] {[(m.scope, m.memory_type, m.content) for m in memories]}")
    assert memories, "memories 表应落库该用户的偏好"
    assert any(
        m.scope == "user" and m.memory_type == "preference" and "危化品" in m.content
        for m in memories
    )

    # 回复确认已记住
    reply_text = _captured_text(captured_sends)
    print(f"[回复] {reply_text[:200]}")
    confirmed = any(
        word in reply_text for word in ("记住", "记下", "已记")
    )
    assert confirmed, f"回复应向用户确认已记住: {reply_text[:200]}"


# ══ live 主接缝 2：新会话注入生效 ══


async def test_live_injection_into_new_session(
    memory_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """预置用户偏好 → 新会话「硫酸还有多少」→ build_system_prompt 返回内容包含
    该偏好（monkeypatch 捕获）；LLM 回复自然即可，不断言内容。"""
    open_id = f"ou_live_inject_{uuid.uuid4().hex[:8]}"
    await memory_tools.save(
        scope="user",
        owner_open_id=open_id,
        memory_type="preference",
        content="以后只关注危化品相关的内容",
    )

    real_build = prompts_module.build_system_prompt
    captured_prompts: list[str] = []

    async def spy_build(*args: Any, **kwargs: Any) -> str:
        out = await real_build(*args, **kwargs)
        captured_prompts.append(out)
        return out

    monkeypatch.setattr(runner_module, "build_system_prompt", spy_build)

    await gateway.handle_im_message(
        _event(
            chat_id=f"oc_live_inject_{uuid.uuid4().hex[:10]}",
            open_id=open_id,
            text="硫酸还有多少",
        )
    )

    assert captured_prompts, "Runner 应组装系统提示词（至少调用一次）"
    print(f"[系统提示词] {captured_prompts[0][:500]}")
    assert any(
        "以后只关注危化品相关的内容" in prompt for prompt in captured_prompts
    ), "注入应生效：系统提示词应包含预置的用户偏好"
    assert captured_sends, "应向用户回复卡片（占位 + 结果）"
