"""业务 Agent 定义 —— Pydantic AI Agent + 依赖注入 + 工具注册入口。

每个请求通过 ``deps=SafetyDeps(db=..., person=..., role=..., session_id=...)`` 注入当前
用户身份、数据库连接和会话上下文；工具函数通过 ``ctx.deps`` 获取并传给各业务 service。

模型配置（2-A 配置运行时化）：走 ai_config 配置中心（DB 活行 → env
（SAFETY_AI_TEXT_*）→ registry 默认，字段级回退），每轮 resolve——
agent_chat 场景绑定（含 text_backup 降级绑定）与 temperature/max_tokens
改配置后下一轮生效，无需重启进程；配置指纹并入 Agent 缓存 key，
配置未变时实例复用、变更时自然换新实例。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from app.modules.safety.ai_audit.tracing import setup_tracing
from app.modules.safety.ai_config.scenario_store import (
    scenario_store as _scenario_store,
)
from app.modules.safety.ai_config.store import store as _ai_config_store
from app.modules.safety.business_agent.loader import load_instructions
from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.env_loader import load_safety_env

# ── 模型层（ai_config 配置中心：DB → env → registry 默认） ──────────
# ⚠️ 强制从 .env.{APP_ENV} 重新加载，覆盖系统环境变量中可能过期的 API key
# （ai_config 的 env 兜底层依赖此刻的 os.environ；全模块统一入口 env_loader）。
load_safety_env()

# ── Tracing（幂等；SAFETY_PHOENIX_ENDPOINT 未配置时 no-op）──────
# ⚠️ 必须在上方 load_dotenv 之后调用，否则读不到 SAFETY_PHOENIX_ENDPOINT。
_TRACING_ENABLED = setup_tracing()

# tracing 启用时挂 Instrumentation capability（pydantic-ai v2 的 OTel 插桩方式，
# 生成 agent run / model request / tool execution spans）
_CAPABILITIES: list = []
if _TRACING_ENABLED:
    from pydantic_ai.capabilities import Instrumentation

    _CAPABILITIES.append(Instrumentation())

# ── Agent ────────────────────────────────────────────────────────
# deps_type=SafetyDeps → 工具函数的第一个参数是 RunContext[SafetyDeps]
# output_type 包含 DeferredToolRequests → 当模型生成 approval-required
# 工具调用时，运行会以 DeferredToolRequests 输出结束（而非直接执行）。
# 注意：executor.py 导入本模块的工具注册并注册到 agent

_DEFAULT_TEMPERATURE = 0.1
_DEFAULT_MAX_TOKENS = 8192
_AGENT_CACHE_MAX = 64


@dataclass(frozen=True)
class AgentRuntimeConfig:
    """一轮对话生效的模型配置快照（per-turn resolve 的结果）。"""

    profile: str
    model: str
    api_key: str
    temperature: float
    max_tokens: int
    fingerprint: str


def resolve_runtime_config() -> AgentRuntimeConfig:
    """解析当前生效配置：agent_chat 场景绑定 → ai_config profile。

    两级 store 均为同步内存读（60s TTL + 写后 invalidate），配置变更
    （含场景绑定切换 text_backup）在下一轮 resolve 即生效。
    """
    profile = _scenario_store.get_effective_profile("agent_chat")
    config = _ai_config_store.get_profile_config(profile)
    api_key = config.get("api_key") or ""
    model = config.get("model") or "deepseek-flash"
    try:
        temperature = float(config.get("temperature", _DEFAULT_TEMPERATURE))
    except (TypeError, ValueError):
        temperature = _DEFAULT_TEMPERATURE
    try:
        max_tokens = int(config.get("max_tokens", _DEFAULT_MAX_TOKENS))
    except (TypeError, ValueError):
        max_tokens = _DEFAULT_MAX_TOKENS
    # 指纹只含 api_key 尾 4 位（防泄漏），足以区分配置版本
    fingerprint = hashlib.sha256(
        "|".join((
            profile, model, config.get("base_url") or "", api_key[-4:],
            str(temperature), str(max_tokens),
        )).encode()
    ).hexdigest()[:12]
    return AgentRuntimeConfig(
        profile=profile,
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        fingerprint=fingerprint,
    )


def _make_agent(config: AgentRuntimeConfig | None = None) -> Agent:
    """创建基础 Agent 实例（不含工具注册）；缺省按当前生效配置构建。

    base_url/timeout 字段暂不消费（DeepSeekProvider 默认端点，与一期口径一致）。
    """
    cfg = config or resolve_runtime_config()
    return _build_agent(cfg, load_instructions())


def _build_agent(cfg: AgentRuntimeConfig, instructions: str) -> Agent:
    """按配置快照与 instructions 构建 Agent（orchestrator 与域 Agent 共用）。"""
    provider = DeepSeekProvider(api_key=cfg.api_key)
    model = OpenAIChatModel(cfg.model, provider=provider)
    return Agent(
        model,
        deps_type=SafetyDeps,
        output_type=[str, DeferredToolRequests],
        instructions=instructions,
        capabilities=_CAPABILITIES,
        # 2-A：参数从 ai_config profile 读取（registry 默认 0.1/8192，后台可调）
        model_settings={"temperature": cfg.temperature, "max_tokens": cfg.max_tokens},
    )


# ── 域 Agent（2-D 委派试点）：域工具子集 + 域专属 instructions ──────
# 缓存 key = 域 + 配置指纹 + 域 prompt mtime（域 prompt 热改 → 新实例）。

_DOMAIN_AGENT_CACHE: dict[str, Agent] = {}
_DOMAIN_AGENT_CACHE_MAX = 16

_DOMAIN_PROMPTS_DIR = Path(__file__).parent / "domain_prompts"


def get_domain_agent(domain: str) -> Agent:
    """获取域 Agent 实例（当前试点域：urs）。

    域 Agent 与 orchestrator 共用确认门/权限/审计（工具注册层 requires_approval
    + 管道 execute_tool 权限校验 + contextvars 审计继承），不复制这些设施。
    """
    from app.modules.safety.business_agent.tool_selector import TOOL_GROUPS
    from app.modules.safety.business_agent.tools.registry import register_tools_subset

    if domain not in TOOL_GROUPS:
        raise ValueError(f"未知域 {domain!r}，可用域: {sorted(TOOL_GROUPS)}")

    prompt_path = _DOMAIN_PROMPTS_DIR / f"{domain}.md"
    mtime = prompt_path.stat().st_mtime
    cfg = resolve_runtime_config()
    cache_key = f"{domain}|{cfg.fingerprint}|{mtime}"
    cached = _DOMAIN_AGENT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if len(_DOMAIN_AGENT_CACHE) >= _DOMAIN_AGENT_CACHE_MAX:
        _DOMAIN_AGENT_CACHE.clear()

    agent = _build_agent(cfg, prompt_path.read_text(encoding="utf-8"))
    # delegate 是 orchestrator 的元工具，域子 Agent 不持有——防递归委派自身
    # （审查修复：TOOL_GROUPS["urs"] 含 delegate 是路由挂载口径，注册域
    # Agent 工具时需剔除）。
    domain_tools = [t for t in TOOL_GROUPS[domain] if t != "delegate"]
    register_tools_subset(agent, domain_tools)
    _DOMAIN_AGENT_CACHE[cache_key] = agent
    return agent


# ── Agent 缓存（工具名集合 × 配置指纹哈希，进程内复用）─────────────

_AGENT_CACHE: dict[str, Agent] = {}


def get_agent_for_tools(tool_names: list[str] | None) -> Agent:
    """获取仅包含指定工具的 Agent 实例（2-A：per-turn resolve）。

    缓存 key = 工具名集合哈希 + 模型配置指纹：配置未变 → 复用实例；
    配置变更 → 新 key 新实例（旧实例随缓存自然废弃，无需失效回调）。
    tool_names 为 None/空/等于全量名册 → 常驻集（RESIDENT_TOOLS）实例，
    与按需子集走同一 resolve 通路（不再有 import 期冻结的默认实例）。
    """
    from app.modules.safety.business_agent.tools.registry import (
        RESIDENT_TOOLS,
        TOOL_KIND,
        register_tools_subset,
    )

    names = sorted(tool_names) if tool_names else []
    if not names or names == sorted(TOOL_KIND.keys()):
        names = sorted(RESIDENT_TOOLS)

    cfg = resolve_runtime_config()
    cache_key = hashlib.sha256(
        ("|".join(names) + "#" + cfg.fingerprint).encode()
    ).hexdigest()[:16]

    if cache_key in _AGENT_CACHE:
        return _AGENT_CACHE[cache_key]

    if len(_AGENT_CACHE) >= _AGENT_CACHE_MAX:
        _AGENT_CACHE.clear()

    agent = _make_agent(cfg)
    register_tools_subset(agent, names)
    _AGENT_CACHE[cache_key] = agent
    return agent
