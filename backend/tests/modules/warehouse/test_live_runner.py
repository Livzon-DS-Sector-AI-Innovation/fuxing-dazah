"""S1 ticket 03 验收：Runner 循环 + 4 个查询工具（主接缝级，全 live）。

不经 gateway 直接调 Runner.run（真 session、真 LLM、真 Base 查询），发送
环节不涉及（Runner 只产出 Reply 文本）。工具结果/audit/会话摘要经
runner._db_session 注入口写入测试事务（rollback 隔离）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_runner.py -v
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.llm_client import AssistantMessage, ToolCall
from app.modules.warehouse.agent.repository import get_or_create_session
from app.modules.warehouse.agent.runner import FALLBACK_REPLY, Runner, get_runner
from app.modules.warehouse.agent.tools import query as query_tools
from app.modules.warehouse.models import WarehouseAgentAudit, WarehouseAgentSession

TOOL_NAMES = set(query_tools.TOOL_FUNCS)


# ── fixtures ──


@pytest.fixture
def runner_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    """runner._db_session → 包装测试 session（不 commit，随 fixture 回滚隔离）。"""

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(runner_module, "_db_session", _patched)
    return db_session


@pytest.fixture
async def agent_session(db_session: AsyncSession) -> WarehouseAgentSession:
    """真实会话记录（rollback 隔离）：唯一 chat_id 避免跨用例污染。"""
    return await get_or_create_session(
        db_session,
        chat_id=f"oc_runner_{uuid.uuid4().hex[:10]}",
        user_open_id="ou_runner_test",
    )


@pytest.fixture
def runner() -> Runner:
    """每测试新建 Runner（真 LLM 配置；避免单例 httpx 连接跨 event loop 复用）。"""
    return Runner()


# ── 真实数据预查 helper（工具直查，作为断言基准）──


def _month_window(month: date) -> tuple[str, str]:
    start = month.replace(day=1)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1, day=1)
    else:
        nxt = start.replace(month=start.month + 1, day=1)
    return start.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")


def _prev_month(today: date) -> date:
    if today.month == 1:
        return today.replace(year=today.year - 1, month=12)
    return today.replace(month=today.month - 1, day=1)


async def _month_receipt_materials(month: date) -> list[str]:
    """某月入库物料的聚合名单（按数量降序，query_movements 直查）。"""
    date_from, date_to = _month_window(month)
    result = await query_tools.query_movements(
        direction="inbound", date_from=date_from, date_to=date_to
    )
    summary = result.get("summary") or []
    if not summary:
        return []
    rows = summary[0].get("入库汇总") or []
    return [str(row["物料名称"]) for row in rows if row.get("物料名称")]


# ── 1. query_stock live：「硫酸还有多少放行的」──


async def test_query_stock_live(
    runner_db: AsyncSession,
    agent_session: WarehouseAgentSession,
    runner: Runner,
) -> None:
    """放行硫酸批次 → 回复含真实批号或数量（预查工具结果核对）。"""
    baseline = await query_tools.query_stock(keyword="硫酸", qc_status="放行")
    if not baseline.get("total"):
        pytest.skip("测试版 Base 无放行硫酸批次（live 数据依赖）")
    expected_batches = [
        r["物料批号"] for r in baseline["records"][:5] if r.get("物料批号")
    ]
    print(f"[预查] 放行硫酸 total={baseline['total']} 前5批号={expected_batches}")

    reply = await runner.run(agent_session, "硫酸还有多少放行的")
    print(f"[回复] {reply.text[:300]}")

    assert reply.text.strip(), "回复不应为空"
    assert "硫酸" in reply.text
    hit = any(batch in reply.text for batch in expected_batches) or any(
        r.get("剩余数量") and r["剩余数量"] in reply.text
        for r in baseline["records"][:5]
    )
    assert hit, f"回复应含真实批号/数量（预查批号 {expected_batches}）: {reply.text[:200]}"


# ── 2. query_movements live：「上个月入库了哪些物料」──


async def test_query_movements_live(
    runner_db: AsyncSession,
    agent_session: WarehouseAgentSession,
    runner: Runner,
) -> None:
    """上月入库 → 回复含真实物料名（上月无数据则回退最近有数据的月份）。"""
    month = _prev_month(date.today())
    materials = await _month_receipt_materials(month)
    question = "上个月入库了哪些物料"
    if not materials:
        for _ in range(3):  # 回退最多 3 个月
            month = _prev_month(month.replace(day=28))
            materials = await _month_receipt_materials(month)
            if materials:
                question = f"{month.year}年{month.month}月入库了哪些物料"
                break
    if not materials:
        pytest.skip("测试版 Base 最近几个月均无入库记录（live 数据依赖）")
    print(f"[预查] {month.year}-{month.month} 入库物料 top={materials[:5]}")

    reply = await runner.run(agent_session, question)
    print(f"[回复] {reply.text[:300]}")

    assert reply.text.strip(), "回复不应为空"
    top5 = materials[:5]
    assert any(name in reply.text for name in top5), (
        f"回复应含真实入库物料名（top5 {top5}）: {reply.text[:200]}"
    )


# ── 3. query_report live：「查一下呆料清单」──


async def test_query_report_live(
    runner_db: AsyncSession,
    agent_session: WarehouseAgentSession,
    runner: Runner,
) -> None:
    """呆料清单 → 回复含真实呆料物料（预查 dead 报表核对）。"""
    baseline = await query_tools.query_report("dead")
    if not baseline.get("total"):
        pytest.skip("测试版 Base 无呆料记录（live 数据依赖）")
    names = [r["物料名称"] for r in baseline["records"] if r.get("物料名称")]
    print(f"[预查] 呆料 total={baseline['total']} 物料={names[:5]}")

    reply = await runner.run(agent_session, "查一下呆料清单")
    print(f"[回复] {reply.text[:300]}")

    assert reply.text.strip(), "回复不应为空"
    assert any(name in reply.text for name in names[:5]), (
        f"回复应含真实呆料物料（{names[:5]}）: {reply.text[:200]}"
    )


# ── 4. 多工具任务 live：query_material + query_stock + audit ≥2 ──


async def test_multi_tool_task_live(
    runner_db: AsyncSession,
    agent_session: WarehouseAgentSession,
    runner: Runner,
) -> None:
    """「活性炭基本信息 + 现在库存」→ 依次调 ≥2 个工具并留 audit 记录。"""
    baseline = await query_tools.query_material("活性炭")
    if not baseline.get("total"):
        pytest.skip("测试版 Base 无活性炭主数据（live 数据依赖）")
    material_name = str(baseline["records"][0]["物料名称"])
    print(f"[预查] 活性炭主数据 total={baseline['total']} 名称={material_name}")

    reply = await runner.run(
        agent_session, "帮我看看活性炭的基本信息还有现在库存多少"
    )
    print(f"[回复] {reply.text[:300]}")

    assert reply.text.strip(), "回复不应为空"
    assert material_name in reply.text, f"回复应含真实物料名 {material_name}"

    audits = (
        await runner_db.execute(
            select(WarehouseAgentAudit)
            .where(
                WarehouseAgentAudit.session_id == agent_session.id,
                WarehouseAgentAudit.tool_name.in_(TOOL_NAMES),
            )
            .order_by(WarehouseAgentAudit.created_at)
        )
    ).scalars().all()
    tool_seq = [a.tool_name for a in audits]
    print(f"[audit] {[(a.tool_name, a.result_status, a.duration_ms) for a in audits]}")
    assert len(audits) >= 2, f"应至少 2 条工具 audit 记录，实际 {tool_seq}"
    assert all(a.result_status == "ok" for a in audits)
    # 活性炭信息来自 query_material，库存来自 query_stock——两个工具都应被调用
    assert "query_material" in tool_seq and "query_stock" in tool_seq


# ── 5. 工具结果 4KB 截断 ──


class _HugeAdapter:
    """返回超长结果的假 adapter（单条记录很大，10 条明细即超 4KB）。

    注意工具内部分页会把明细裁到前 10 条，所以靠单条超长（而非条数）触发
    Runner 侧的 4KB 截断。
    """

    _BIG_SUFFIX = "X" * 600

    async def search_records_page(
        self, table_key: str, **kwargs: Any
    ) -> dict[str, Any]:
        records = [
            {
                "record_id": f"rec{i}",
                "fields": {
                    "物料名称": "硫酸",
                    "物料批号": f"10228-25{i:04d}-{self._BIG_SUFFIX}",
                    "剩余数量": "123.45",
                    "单位": "Kg",
                    "贮存位置": "25#仓库(一)二层 原辅料库2区-超长库位描述后缀",
                    "QA放行": "放行",
                    "入库日期": "2026-08-01",
                    "有效期至/复验期至": "2027-08-01",
                    "物料大类": "危化品",
                    "级别/型号": "AR级",
                },
            }
            for i in range(300)
        ]
        return {"records": records, "total": 300, "page_token": None}


class _CapturingLLM:
    """第一轮发起 query_stock，其余轮返回终局回复；捕获全部 messages。"""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AssistantMessage:
        self.calls.append(messages)
        if len(self.calls) == 1:
            return AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(id="call_trunc", name="query_stock", arguments={})
                ],
            )
        return AssistantMessage(content="查询完成。")


async def test_truncation(
    runner_db: AsyncSession,
    agent_session: WarehouseAgentSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超长工具结果 → 回填给 LLM 的 tool content 截断至 ≤4KB 并带提示。"""
    fake_llm = _CapturingLLM()
    monkeypatch.setattr(query_tools, "_adapter", _HugeAdapter())
    runner = Runner(llm=fake_llm)

    reply = await runner.run(agent_session, "查一下硫酸库存")
    assert reply.text == "查询完成。"
    assert len(fake_llm.calls) == 2

    tool_messages = [
        m for m in fake_llm.calls[1] if m.get("role") == "tool"
    ]
    assert len(tool_messages) == 1, "第一轮的工具结果应以 role=tool 回填"
    content = str(tool_messages[0]["content"])
    size = len(content.encode("utf-8"))
    print(f"[截断] tool content {size} bytes")
    assert size <= query_tools.TOOL_RESULT_MAX_BYTES, (
        f"tool content 应 ≤4KB，实际 {size} bytes"
    )
    assert "已截断" in content, "截断后的结果应带截断提示"


# ── 6. MAX_TURNS 兜底 ──


class _AlwaysToolLLM:
    """永远返回 tool_calls 的假 LLM（模拟模型空转）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AssistantMessage:
        self.calls += 1
        return AssistantMessage(
            content=None,
            tool_calls=[
                ToolCall(
                    id=f"call_{self.calls}", name="query_stock", arguments={}
                )
            ],
        )


class _TinyAdapter:
    async def search_records_page(
        self, table_key: str, **kwargs: Any
    ) -> dict[str, Any]:
        return {"records": [], "total": 0, "page_token": None}


async def test_max_turns_guard(
    runner_db: AsyncSession,
    agent_session: WarehouseAgentSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 永远发起工具调用 → 6 轮后返回兜底话术 Reply（不抛异常）。"""
    fake_llm = _AlwaysToolLLM()
    monkeypatch.setattr(query_tools, "_adapter", _TinyAdapter())
    runner = Runner(llm=fake_llm, max_turns=6)

    reply = await runner.run(agent_session, "随便查点什么")

    assert fake_llm.calls == 6, f"应恰好执行 6 轮，实际 {fake_llm.calls}"
    assert reply.text == FALLBACK_REPLY, f"应返回兜底话术，实际: {reply.text[:100]}"
    # 每轮工具调用都有 audit（error/ok 视查询结果，此处空结果 ok）
    audits = (
        await runner_db.execute(
            select(WarehouseAgentAudit).where(
                WarehouseAgentAudit.session_id == agent_session.id,
                WarehouseAgentAudit.tool_name == "query_stock",
            )
        )
    ).scalars().all()
    assert len(audits) == 6


# ── 7. 工厂接口保持（gateway 契约）──


async def test_get_runner_factory_contract() -> None:
    """get_runner() 返回 Runner 单例（gateway 契约：接口不感知实现）。"""
    first = get_runner()
    second = get_runner()
    assert isinstance(first, Runner)
    assert first is second
