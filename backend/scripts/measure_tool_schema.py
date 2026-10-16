"""实测 business_agent 工具 schema 开销：mock transport 捕获 pydantic-ai 真实请求体。

输出：工具总数 / tools JSON 字节数 / 估算 tokens / 单工具大小排名 / 典型子集对比。
"""
import asyncio
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("APP_ENV", "development")

captured: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    captured["body"] = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 1,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


async def main() -> None:
    import httpx
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    provider = OpenAIProvider(api_key="x", http_client=client)
    model = OpenAIChatModel("test-model", provider=provider)
    agent = Agent(model)
    from app.modules.safety.business_agent.tools.registry import register_all_tools

    register_all_tools(agent)
    await agent.run("你好")
    tools = captured["body"].get("tools", [])
    total_bytes = len(json.dumps(tools, ensure_ascii=False).encode())
    # 中文 JSON 混合文本粗估：字节/2.8 ≈ tokens（GPT 分词器口径偏保守）
    est_tokens = int(total_bytes / 2.8)
    print(f"工具总数: {len(tools)}")
    print(f"tools JSON 总字节: {total_bytes:,}")
    print(f"估算 tokens(字节/2.8): {est_tokens:,}")
    sizes = sorted(
        (
            (len(json.dumps(t, ensure_ascii=False).encode()), t["function"]["name"])
            for t in tools
        ),
        reverse=True,
    )
    print("\nTop 15 最大工具:")
    for size, name in sizes[:15]:
        print(f"  {size:>6,} B  {name}")
    print("\n最小 5 个:")
    for size, name in sizes[-5:]:
        print(f"  {size:>6,} B  {name}")

    # 典型意图子集对比
    from app.modules.safety.business_agent.tool_selector import select_tool_names

    samples = [
        "本月环保部有多少未整改隐患",
        "查一下消防报警记录",
        "帮我把环保部8月监护补贴算一下",
    ]
    by_name = {t["function"]["name"]: t for t in tools}
    print("\n典型问题子集规模:")
    for q in samples:
        subset = select_tool_names(q)
        if subset is None:
            print(f"  「{q}」→ 全量回退({len(tools)} 个)")
            continue
        sub_bytes = sum(
            len(json.dumps(by_name[n], ensure_ascii=False).encode())
            for n in subset
            if n in by_name
        )
        print(
            f"  「{q}」→ {len(subset)} 个工具, "
            f"{sub_bytes:,} B (~{int(sub_bytes / 2.8):,} tokens, "
            f"占全量 {sub_bytes * 100 // total_bytes}%)"
        )
        print(f"    工具: {', '.join(sorted(subset)[:12])}{'…' if len(subset) > 12 else ''}")

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
