"""业务 Agent 定义 —— Pydantic AI Agent + 依赖注入 + 工具注册入口。

每个请求通过 ``deps=SafetyDeps(db=..., person=..., role=..., session_id=...)`` 注入当前
用户身份、数据库连接和会话上下文；工具函数通过 ``ctx.deps`` 获取并传给各业务 service。

模型配置：复用 ``service/config.py`` 的 ``SAFETY_AI_TEXT_*`` 环境变量。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from app.modules.safety.ai_audit.tracing import setup_tracing
from app.modules.safety.business_agent.loader import load_instructions
from app.modules.safety.business_agent.schemas import SafetyDeps

# ── 模型层（从环境变量读取，与 service/config.py 一致） ──────────
# ⚠️ 强制从 .env.development 重新加载，覆盖系统环境变量中可能过期的 API key。
# agent.py → business_agent/ → safety/ → modules/ → app/ → dazah-backend/
_project_root = Path(__file__).resolve().parents[4]
_env_file = _project_root / f".env.{os.getenv('APP_ENV', 'development')}"
if _env_file.exists():
    load_dotenv(str(_env_file), override=True)

# ── Tracing（幂等；SAFETY_PHOENIX_ENDPOINT 未配置时 no-op）──────
# ⚠️ 必须在上方 load_dotenv 之后调用，否则读不到 SAFETY_PHOENIX_ENDPOINT。
_TRACING_ENABLED = setup_tracing()

# tracing 启用时挂 Instrumentation capability（pydantic-ai v2 的 OTel 插桩方式，
# 生成 agent run / model request / tool execution spans）
_CAPABILITIES: list = []
if _TRACING_ENABLED:
    from pydantic_ai.capabilities import Instrumentation

    _CAPABILITIES.append(Instrumentation())

_PROVIDER = DeepSeekProvider(
    api_key=os.environ["SAFETY_AI_TEXT_API_KEY"],
)

_MODEL = OpenAIChatModel(
    os.environ.get("SAFETY_AI_TEXT_MODEL", "deepseek-v4-flash-vision-exp"),
    provider=_PROVIDER,
)

# ── Agent ────────────────────────────────────────────────────────
# deps_type=SafetyDeps → 工具函数的第一个参数是 RunContext[SafetyDeps]
# output_type 包含 DeferredToolRequests → 当模型生成 approval-required
# 工具调用时，运行会以 DeferredToolRequests 输出结束（而非直接执行）。
# 注意：executor.py 导入本模块的工具注册并注册到 agent


def _make_agent() -> Agent:
    """创建基础 Agent 实例（不含工具注册）。"""
    return Agent(
        _MODEL,
        deps_type=SafetyDeps,
        output_type=[str, DeferredToolRequests],
        instructions=load_instructions(),
        capabilities=_CAPABILITIES,
        model_settings={"temperature": 0.3, "max_tokens": 2048},
    )


business_agent: Agent = _make_agent()

# ── Agent 缓存（按工具名组合哈希，进程内复用，避免重复创建）─────────

import hashlib  # noqa: E402

_AGENT_CACHE: dict[str, Agent] = {}


def get_agent_for_tools(tool_names: list[str] | None) -> Agent:
    """获取仅包含指定工具的 Agent 实例。

    按工具名组合的 sha256 哈希做进程内缓存。tool_names 为 None 或
    包含全部工具时，返回全量 business_agent。

    警告：返回的 Agent 实例和 business_agent 共享底层模型实例（_MODEL
    是模块级单例），因此多实例并存不会额外占用模型连接资源。
    """
    from app.modules.safety.business_agent.tools.registry import (
        TOOL_KIND,
        register_tools_subset,
    )

    if not tool_names:
        return business_agent

    all_tool_names = sorted(TOOL_KIND.keys())
    if sorted(tool_names) == all_tool_names:
        return business_agent

    cache_key = hashlib.sha256(
        ",".join(sorted(tool_names)).encode()
    ).hexdigest()[:16]

    if cache_key in _AGENT_CACHE:
        return _AGENT_CACHE[cache_key]

    agent = _make_agent()
    register_tools_subset(agent, tool_names)
    _AGENT_CACHE[cache_key] = agent
    return agent
