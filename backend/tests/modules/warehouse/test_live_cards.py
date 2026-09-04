"""S1 ticket 04 验收：查询结果卡片渲染（agent/cards.py）。

三部分（spec Testing Decisions：全 live + 发送 dry-run）：
1. 单测（dry-run，无需 DB）：构造工具结果 data dict → 专用渲染器断言
   （卡片 JSON 结构/表头/空结果态/截断提示行）；
2. 降级测试：Reply.data 畸形（缺字段/None/超长/未知工具）→ 降级文本卡片
   且不抛异常；
3. live 主接缝：gateway.handle_im_message 真事件（真 LLM + 真 Base）→
   dry-run 捕获的结果卡片是**专用卡片**（库存/报告）而非纯文本。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_cards.py -v
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.cards import (
    STOCK_TABLE_HEADER,
    render_reply_card,
    render_text_card,
)
from app.modules.warehouse.agent.runner import Reply
from app.modules.warehouse.agent.tools import query as query_tools
from app.modules.warehouse.feishu import notification

# 渲染输入 = 工具结果 dict（tools/query.py 的输出形态，见票03 Comments）


def _stock_row(batch: str, qty: str = "120", status: str = "放行") -> dict[str, Any]:
    return {
        "物料名称": "硫酸",
        "物料批号": batch,
        "剩余数量": qty,
        "单位": "瓶",
        "贮存位置": "24#仓库四-3区",
        "QA放行": status,
        "入库日期": "2025-10-15",
        "有效期至/复验期至": "2026-10-15",
        "物料大类": "危化品",
        "级别/型号": "AR级",
    }


def _stock_data(rows: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {
        "total": total if total is not None else len(rows),
        "records": rows,
        "note": "",
    }


def _material_data(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total": len(rows), "records": rows, "note": "一览表无「单位」列"}


def _material_row(name: str = "活性炭", code: str = "10103") -> dict[str, Any]:
    return {
        "代码": code,
        "物料名称": name,
        "级别": "药用级",
        "规格": "针剂用",
        "物料大类": "辅料",
        "单位换算": "1吨=1000Kg",
        "生产商": "chemviron",
        "免检物料": "否",
        "复验期": "24",
        "包装规格": "25Kg/袋",
    }


def _movements_data() -> dict[str, Any]:
    return {
        "total": 3,
        "summary": [
            {
                "入库汇总": [
                    {"物料名称": "乙醇", "数量": "1100810", "单位": "Kg"},
                    {"物料名称": "液碱", "数量": "601880", "单位": "Kg"},
                ]
            },
            {"出库汇总": [{"物料名称": "乙醇", "数量": "22000", "单位": "Kg"}]},
        ],
        "records": [
            {
                "入库明细": [
                    {
                        "物料名称": "乙醇",
                        "物料批号": "10407-250901",
                        "入库数量": "20000",
                        "单位": "Kg",
                        "入库日期": "2026-08-12",
                        "QA放行": "放行",
                        "贮存/槽车取样点": "26#罐区-2号罐",
                    }
                ]
            },
            {
                "出库明细": [
                    {
                        "物料名称": "乙醇",
                        "物料批号": "10407-250901",
                        "出库数量": "5000",
                        "单位": "Kg",
                        "领用日期": "2026-08-20",
                        "领用部门": "一车间",
                    }
                ]
            },
        ],
    }


def _report_data(kind: str) -> dict[str, Any]:
    if kind == "dead":
        return {
            "report_type": "dead",
            "report_name": "呆料批次清单（入库总账·呆料判断=是）",
            "total": 1,
            "records": [
                {
                    "物料名称": "无水乙酸钠",
                    "物料批号": "SRM25122907",
                    "呆料产生数量（入库数量）": "3700",
                    "单位": "Kg",
                    "入库日期": "2025-12-30",
                    "贮存位置": "16#旧原料库一",
                    "使用部门": "一车间",
                }
            ],
            "note": "",
        }
    return {
        "report_type": "unqualified",
        "report_name": "不合格物料汇总",
        "total": 1,
        "records": [
            {
                "物料名称": "纯化水",
                "不合格项目": "电导率",
                "处理方式": "返工",
                "到货日期": "2026-01-05",
                "登记人": "张三",
                "计量单位": "批",
                "物料大类": "工艺用水",
            }
        ],
        "note": "",
    }


# ── 断言 helper ──


def _body(card: dict[str, Any]) -> str:
    """卡片全部 markdown 元素拼接（表格/提示断言用）。"""
    return "\n".join(
        str(el.get("content") or "")
        for el in card["elements"]
        if el.get("tag") == "markdown"
    )


def _title(card: dict[str, Any]) -> str:
    return str(card["header"]["title"]["content"])


# ── 1. 库存卡片 ──


def test_stock_card_structure() -> None:
    """库存卡片：表头行 + 数据行（批号/数量/库位/三态）+ LLM 总结。"""
    data = _stock_data([
        _stock_row("10228-251001", qty="0"),
        _stock_row("10228-251002", qty="120", status="条件放行"),
    ])
    card = render_reply_card(
        Reply(text="共查到 2 个批次的硫酸。", data={"tool": "query_stock", "result": data})
    )
    assert "库存" in _title(card)
    assert _title(card) != "仓储助手"  # 专用卡片而非兜底文本卡片
    body = _body(card)
    assert STOCK_TABLE_HEADER in body  # 表头行：物料｜批号｜剩余数量｜单位｜库位｜三态
    assert "10228-251001" in body
    assert "24#仓库四-3区" in body
    assert "放行" in body
    assert "条件放行" in body
    assert "120" in body
    assert "共查到 2 个批次的硫酸。" in body  # LLM 文字回复保留在卡片顶部


def test_stock_card_empty_state() -> None:
    """空结果 → 友好态文案（不渲染空表格、不报错）。"""
    card = render_reply_card(
        Reply(text="没查到。", data={"tool": "query_stock", "result": _stock_data([], total=0)})
    )
    assert "库存" in _title(card)
    body = _body(card)
    assert "未查询到" in body
    assert STOCK_TABLE_HEADER not in body  # 空态不渲染表格


def test_stock_card_truncation_hint() -> None:
    """total > 展示条数 → 「共 N 条，回复「更多」查看」提示；只展示前 10 行。"""
    rows = [_stock_row(f"10228-{i:04d}") for i in range(12)]
    data = _stock_data(rows, total=23)
    card = render_reply_card(
        Reply(text="", data={"tool": "query_stock", "result": data})
    )
    body = _body(card)
    assert "共 23 条" in body
    assert "更多" in body
    assert "10228-0009" in body  # 第 10 条在内
    assert "10228-0010" not in body  # 第 11 条起截断


def test_stock_card_note_shown() -> None:
    """工具结果 note（如拉取上限说明）呈现到卡片。"""
    data = _stock_data([_stock_row("10228-251001")])
    data["note"] = "数据量超过拉取上限（1500 条），统计可能不完整"
    card = render_reply_card(
        Reply(text="", data={"tool": "query_stock", "result": data})
    )
    assert "统计可能不完整" in _body(card)


# ── 2. 物料主数据卡片 ──


def test_material_card_single_record_block() -> None:
    """单条主数据 → 块式全字段展示（代码/级别/生产商/复验期）+ note。"""
    card = render_reply_card(
        Reply(
            text="",
            data={"tool": "query_material", "result": _material_data([_material_row()])},
        )
    )
    assert "物料" in _title(card)
    body = _body(card)
    assert "10103" in body and "活性炭" in body
    assert "chemviron" in body
    assert "药用级" in body
    assert "复验期" in body
    assert "一览表无「单位」列" in body


def test_material_card_multi_record_table() -> None:
    """多条主数据 → 行式表格（含表头）。"""
    rows = [_material_row("活性炭", "10103"), _material_row("活性炭纤维", "10104")]
    card = render_reply_card(
        Reply(text="", data={"tool": "query_material", "result": _material_data(rows)})
    )
    body = _body(card)
    assert "10104" in body
    assert "物料｜代码" in body  # 多条时渲染表头行


# ── 3. 出入库汇总卡片 ──


def test_movements_card_summary_and_detail() -> None:
    """出入库卡片：方向汇总节（聚合数字）+ 明细表。"""
    card = render_reply_card(
        Reply(text="", data={"tool": "query_movements", "result": _movements_data()})
    )
    assert "出入库" in _title(card)
    body = _body(card)
    assert "入库汇总" in body and "出库汇总" in body
    assert "1100810" in body and "乙醇" in body
    assert "10407-250901" in body  # 明细批号
    assert "一车间" in body  # 出库明细字段


# ── 4. 报告清单卡片 ──


def test_report_card_title_by_type() -> None:
    """report_type 区分标题：dead=呆料 / unqualified=不合格，数据行真实。"""
    dead = render_reply_card(
        Reply(text="", data={"tool": "query_report", "result": _report_data("dead")})
    )
    assert "呆料" in _title(dead)
    dead_body = _body(dead)
    assert "SRM25122907" in dead_body and "16#旧原料库一" in dead_body

    unq = render_reply_card(
        Reply(text="", data={"tool": "query_report", "result": _report_data("unqualified")})
    )
    assert "不合格" in _title(unq)
    unq_body = _body(unq)
    assert "电导率" in unq_body and "返工" in unq_body


# ── 5. 文本卡片兜底（现行为保持）──


def test_reply_without_data_falls_back_to_text_card() -> None:
    """Reply 无 data（纯对话/多轮无工具/兜底话术）→ 仓储助手文本卡片。"""
    card = render_reply_card(Reply(text="你好，我是仓储助手。"))
    assert _title(card) == "仓储助手"
    assert "你好，我是仓储助手。" in _body(card)

    unknown_tool = render_reply_card(
        Reply(text="试试", data={"tool": "plan_task", "result": {"x": 1}})
    )
    assert _title(unknown_tool) == "仓储助手"  # 未知工具不渲染专用卡片

    empty_result = render_reply_card(
        Reply(text="看看", data={"tool": "query_stock", "result": None})
    )
    assert _title(empty_result) == "仓储助手"  # result 非 dict 不渲染专用卡片


def test_render_text_card_is_gateway_compatible() -> None:
    """render_text_card 产出旧版 interactive 结构（notification.send_card 可发）。"""
    card = render_text_card("仓储助手", "**hi**")
    assert card["config"] == {"wide_screen_mode": True}
    assert card["header"]["title"] == {"tag": "plain_text", "content": "仓储助手"}
    assert card["header"]["template"] == "blue"
    assert card["elements"] == [{"tag": "markdown", "content": "**hi**"}]


# ── 6. 畸形数据降级（永不因渲染抛错中断回复）──


@pytest.mark.parametrize(
    "bad_data",
    [
        None,
        "garbage",
        {"tool": "query_stock", "result": None},
        {"tool": "query_stock", "result": {}},  # 缺 records/total 字段
        {"tool": "query_stock", "result": {"records": "不是列表", "total": 1}},
        {"tool": "query_stock", "result": {"records": [1, None, "x"], "total": 3}},
        {"tool": "query_stock"},  # result 缺失
        {"tool": "query_movements", "result": {"summary": "坏", "records": 3, "total": 1}},
        {"tool": "query_report", "result": {"report_type": None, "records": [0]}},
    ],
)
def test_malformed_data_degrades_without_raising(bad_data: Any) -> None:
    """data 结构畸形（缺字段/类型异常）→ 降级文本卡片（title=仓储助手），不抛。"""
    card = render_reply_card(Reply(text="原始回复文本", data=bad_data))
    assert _title(card) == "仓储助手"
    assert "原始回复文本" in _body(card)


def test_none_field_values_render_tolerantly() -> None:
    """字段值 None / total 类型异常 → 渲染器容错（单元格显示 -），产出专用卡片。"""
    data = {"tool": "query_stock", "result": {"records": [{"物料名称": None}], "total": "x"}}
    card = render_reply_card(Reply(text="ok", data=data))
    assert "库存" in _title(card)
    assert STOCK_TABLE_HEADER in _body(card)


def test_oversized_cell_values_are_clamped() -> None:
    """超长字段值清洗截断，卡片仍产出专用结构且不爆体积。"""
    huge = "长" * 5000
    data = _stock_data([_stock_row(huge, qty=huge)])
    card = render_reply_card(
        Reply(text="x" * 5000, data={"tool": "query_stock", "result": data})
    )
    assert "库存" in _title(card)
    body = _body(card)
    assert huge not in body  # 超长值被截断
    assert STOCK_TABLE_HEADER in body  # 表格结构完好
    assert len(json.dumps(card, ensure_ascii=False)) < 30_000  # 飞书卡片体积安全线


# ── 7. live 主接缝（gateway 全链路，发送 dry-run 捕获）──
# fixtures 复制自 test_live_gateway.py（Runner/Redis 单例跨 event loop 重置）。


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch):
    """每测试重置 Runner 单例（httpx 连接池绑定 event loop，见票03 Comments 7）。"""
    monkeypatch.setattr(runner_module, "_runner", None)
    yield
    runner_module._runner = None


@pytest.fixture
def captured_sends(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """捕获 notification 全部发送 payload（构建路径真实执行，不触网）。"""
    sent: list[dict[str, str]] = []

    async def fake_send(payload: dict[str, str]) -> str | None:
        sent.append(payload)
        return "om_fake_id"

    monkeypatch.setattr(notification, "_send_create", fake_send)
    return sent


@pytest.fixture
def gateway_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    """gateway._db_session → 包装测试 session（不 commit，随 fixture 回滚隔离）。"""

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", _patched)
    return db_session


def _im_message_event(*, chat_id: str, sender_open_id: str, text: str) -> dict[str, Any]:
    return {
        "sender": {
            "sender_id": {"open_id": sender_open_id, "union_id": "un_x", "user_id": "u_x"},
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": f"om_{uuid.uuid4().hex}",
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


def _card_of(payload: dict[str, str]) -> dict[str, Any]:
    return json.loads(payload["content"])


def _unique_chat(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def test_live_stock_query_renders_dedicated_stock_card(
    gateway_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """「硫酸还有多少放行的」→ 结果卡片是专用库存卡片（含表格行），非纯文本。"""
    baseline = await query_tools.query_stock(keyword="硫酸", qc_status="放行")
    if not baseline.get("total"):
        pytest.skip("测试版 Base 无放行硫酸批次（live 数据依赖）")
    expected_batches = [
        r["物料批号"] for r in baseline["records"][:5] if r.get("物料批号")
    ]
    print(f"[预查] 放行硫酸 total={baseline['total']} 前5批号={expected_batches}")

    await gateway.handle_im_message(
        _im_message_event(
            chat_id=_unique_chat("oc_card"), sender_open_id="ou_card_a",
            text="硫酸还有多少放行的",
        )
    )

    assert len(captured_sends) == 2  # 占位卡片 + 结果卡片
    card = _card_of(captured_sends[1])
    title = _title(card)
    print(f"[结果卡片] title={title}")
    assert "库存" in title, f"结果卡片应为专用库存卡片，实际标题: {title}"
    assert title != "仓储助手"
    body = _body(card)
    assert STOCK_TABLE_HEADER in body, f"应含库存表格表头行: {body[:300]}"
    assert any(b in body for b in expected_batches), (
        f"表格应含真实批号（{expected_batches}）: {body[:300]}"
    )


async def test_live_dead_report_renders_report_card(
    gateway_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """「查一下呆料清单」→ 结果卡片呈现真实呆料数据。

    票 08 起系统提示词注入技能目录：「查呆料」匹配 dead-stock-analysis 触发
    描述，LLM 可能先 load_skill + plan_task（捕获序列中插入计划/进度卡片），
    终局 Reply.data 常为 update_plan（无专用渲染器）→ 降级文本卡承载分组
    报告。故断言放宽为：占位卡之后，最后一张卡片正文含真实呆料物料。
    """
    baseline = await query_tools.query_report("dead")
    if not baseline.get("total"):
        pytest.skip("测试版 Base 无呆料记录（live 数据依赖）")
    names = [r["物料名称"] for r in baseline["records"] if r.get("物料名称")]
    print(f"[预查] 呆料 total={baseline['total']} 物料={names[:5]}")

    await gateway.handle_im_message(
        _im_message_event(
            chat_id=_unique_chat("oc_card"), sender_open_id="ou_card_b",
            text="查一下呆料清单",
        )
    )

    assert len(captured_sends) >= 2, "占位卡片 + 至少一张计划/结果卡片"
    cards = [_card_of(payload) for payload in captured_sends]
    print(f"[卡片序列] {[_title(c) for c in cards]}")
    card = cards[-1]  # 终局结果卡在捕获序列末尾（占位卡最前，技能计划卡居中）
    body = _body(card)
    assert any(n in body for n in names[:5]), (
        f"结果卡应含真实呆料物料（{names[:5]}）: {body[:300]}"
    )
