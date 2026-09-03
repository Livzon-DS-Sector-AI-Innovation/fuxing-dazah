"""S0 ticket 03 验收：WarehouseLLMClient（live DeepSeek 网关 + mock 错误路径单测）。

- live 用例（test_tool_call_roundtrip 等 4 个）打真实 DeepSeek API，
  配置来自 .env.development 的 WAREHOUSE_AGENT_*，验证格式坑（tool calling
  往返、reasoning 契约、max_tokens）——mock 无法复现的部分。
- mock 用例（httpx.MockTransport）验证重试/错误路径与请求体契约，不打网络。

运行：DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_llm_client.py -v
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.modules.warehouse.agent.llm_client import (
    WarehouseLLMClient,
    WarehouseLLMError,
)

QUERY_STOCK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_stock",
        "description": "查询仓库库存明细：按物料名称/编码/批号关键词查批号、数量、库位",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "物料名称或编码关键词，例如：硫酸",
                },
            },
            "required": ["keyword"],
        },
    },
}


# ── live 用例（真实 DeepSeek API） ──


async def test_tool_call_roundtrip() -> None:
    """「查硫酸库存」→ 模型应发起 query_stock 工具调用，arguments 含 keyword。"""
    async with WarehouseLLMClient() as client:
        msg = await client.chat_with_tools(
            messages=[{"role": "user", "content": "查一下硫酸的库存"}],
            tools=[QUERY_STOCK_TOOL],
        )

    assert msg.tool_calls, (
        f"应发起工具调用，实际 content={msg.content!r} finish_reason={msg.finish_reason!r}"
    )
    call = msg.tool_calls[0]
    assert call.name == "query_stock"
    assert call.id, "tool_call 应有 id（回填 tool 结果用）"
    assert call.arguments.get("keyword"), f"arguments 应含 keyword，实际 {call.arguments}"
    print(f"[tool_call] {call.name}({call.arguments}) finish_reason={msg.finish_reason}")


async def test_tool_result_to_final_answer() -> None:
    """tool 结果回填后第二轮：应返回非空终局 content，且不再发起 tool_calls。"""
    async with WarehouseLLMClient() as client:
        first = await client.chat_with_tools(
            messages=[{"role": "user", "content": "查一下硫酸的库存"}],
            tools=[QUERY_STOCK_TOOL],
        )
        assert first.tool_calls, "前置：第一轮应发起工具调用"
        call = first.tool_calls[0]

        tool_result = {
            "records": [
                {
                    "material_name": "硫酸",
                    "batch_no": "B20260801",
                    "quantity": 250,
                    "unit": "kg",
                    "location": "A-01-03",
                }
            ],
            "total": 1,
        }
        messages = [
            {"role": "user", "content": "查一下硫酸的库存"},
            {
                "role": "assistant",
                "content": first.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(tool_result, ensure_ascii=False),
            },
        ]
        second = await client.chat_with_tools(messages=messages, tools=[QUERY_STOCK_TOOL])

    assert second.content and second.content.strip(), "第二轮应返回非空终局文本"
    assert not second.tool_calls, "终局回复不应再带 tool_calls"
    print(f"[final_answer] {second.content[:200]}")


async def test_plain_chat() -> None:
    """无 tools 普通对话：content 非空、无 tool_calls。"""
    async with WarehouseLLMClient() as client:
        msg = await client.chat_with_tools(
            messages=[{"role": "user", "content": "用一句话说明什么是库存盘点"}],
        )

    assert msg.content and msg.content.strip()
    assert not msg.tool_calls
    print(f"[plain_chat] {msg.content[:200]}")


async def test_reasoning_contract() -> None:
    """reasoning 模型契约：max_tokens=2000 时 content 非空（不被 reasoning 耗尽）。

    reasoning_content 仅记录不做失败断言（字段存在即透传，可提取性由实现保证）。
    """
    async with WarehouseLLMClient() as client:
        msg = await client.chat_with_tools(
            messages=[
                {
                    "role": "user",
                    "content": "现货数量为 0 但在途数量大于 0 的物料，一般说明什么业务状态？两句话内回答。",
                }
            ],
            max_tokens=2000,
        )

    assert msg.content and msg.content.strip(), (
        f"max_tokens=2000 时 content 不应为空（finish_reason={msg.finish_reason!r}, "
        f"usage={msg.usage}）"
    )
    print(f"[reasoning] content={msg.content[:120]!r}")
    print(f"[reasoning] reasoning_content={msg.reasoning_content!r}")
    print(f"[reasoning] usage={msg.usage}")


# ── mock 单测（httpx.MockTransport，不打网络） ──


def _mock_client(
    handler: Any, retry_backoff: float = 0.0
) -> WarehouseLLMClient:
    """注入 base_url/api_key/model + MockTransport，使 mock 用例完全不依赖 env。"""
    return WarehouseLLMClient(
        base_url="https://mock.local",
        api_key="test-key",
        model="mock-model",
        transport=httpx.MockTransport(handler),
        retry_backoff=retry_backoff,
    )


def _ok_body(content: str = "ok") -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }


async def test_retry_on_5xx() -> None:
    """前两次 500、第三次 200 → 成功返回，共请求 3 次（重试 2 次，指数退避）。"""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) <= 2:
            return httpx.Response(500, json={"error": "internal error"})
        return httpx.Response(200, json=_ok_body("已恢复"))

    async with _mock_client(handler) as client:
        msg = await client.chat_with_tools(messages=[{"role": "user", "content": "hi"}])

    assert msg.content == "已恢复"
    assert len(calls) == 3, f"应请求 3 次（1 次原始 + 2 次重试），实际 {len(calls)}"
    # 请求体契约：不传 response_format；无 tools 时不含 tools/tool_choice 字段
    body = json.loads(calls[0].content)
    assert "response_format" not in body
    assert "tools" not in body and "tool_choice" not in body
    assert body["model"] == "mock-model"


async def test_retry_exhausted_on_5xx_raises() -> None:
    """持续 500 → 3 次尝试全部失败后抛 WarehouseLLMError（明确异常）。"""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(502, json={"error": "bad gateway"})

    async with _mock_client(handler) as client:
        with pytest.raises(WarehouseLLMError) as exc_info:
            await client.chat_with_tools(messages=[{"role": "user", "content": "hi"}])

    assert len(calls) == 3, f"5xx 应耗尽重试（共 3 次尝试），实际 {len(calls)}"
    assert exc_info.value.status_code == 502


async def test_4xx_no_retry() -> None:
    """4xx 不重试：立即抛 WarehouseLLMError，异常含状态码与响应片段。"""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    async with _mock_client(handler) as client:
        with pytest.raises(WarehouseLLMError) as exc_info:
            await client.chat_with_tools(messages=[{"role": "user", "content": "hi"}])

    assert len(calls) == 1, "4xx 不应重试"
    assert exc_info.value.status_code == 401
    assert "invalid api key" in (exc_info.value.response_snippet or "")


async def test_arguments_json_parse_failure_keeps_raw() -> None:
    """arguments 为非法 JSON 字符串 → arguments 置空 dict，原始串保留在 arguments_raw。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "query_stock",
                                        "arguments": "{not valid json",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {},
            },
        )

    async with _mock_client(handler) as client:
        msg = await client.chat_with_tools(messages=[{"role": "user", "content": "hi"}])

    assert len(msg.tool_calls) == 1
    call = msg.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "query_stock"
    assert call.arguments == {}
    assert call.arguments_raw == "{not valid json"
    assert msg.finish_reason == "tool_calls"
