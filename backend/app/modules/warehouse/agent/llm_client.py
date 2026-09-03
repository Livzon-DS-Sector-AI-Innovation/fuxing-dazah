"""仓储 Agent LLM 客户端 — 直连 OpenAI 兼容网关（DeepSeek），tool calling + reasoning 契约。

S0 范围：仅 `chat_with_tools()` 单次调用原语；工具调用循环/提示词/会话管理在 S1 Runner。

与 `platform/integrations/ai/client.py`（AIService）的关系：本模块独立实现，
platform 文件零改动（用户拍板）。差异点来自设计文档「A. 模型配置」的实测契约：
- tool calling 往返：解析 tool_calls，arguments JSON 字符串 → dict（失败保留原始串）
- reasoning 模型（deepseek-v4-flash-vision-exp）：透传 reasoning_content；
  max_tokens 过小会被 reasoning 耗尽导致 content 为空，调用方须给足
- 请求体不传 response_format（tools 模式下与 json_object 不兼容）
- 错误语义：5xx/网络瞬时错误指数退避重试（对齐 meter/ai_service 的 AI_MAX_RETRIES
  模式，MAX_RETRIES 为总尝试次数上限）；4xx 不重试，直接抛 WarehouseLLMError
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 重试配置：MAX_RETRIES 为总尝试次数上限（语义对齐 meter/ai_service.py 的 AI_MAX_RETRIES）
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # 秒，指数退避基数：第 n 次失败后等待 RETRY_BACKOFF ** n

# 瞬时网络错误（对齐 meter 的可重试网络异常集合）
_RETRYABLE_NETWORK_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)


class WarehouseLLMError(Exception):
    """仓储 Agent LLM 调用失败（模块内统一异常，含状态码与响应片段）。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_snippet: str | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.response_snippet = response_snippet
        super().__init__(message)

    def __str__(self) -> str:
        text = self.message
        if self.status_code is not None:
            text = f"{text} (status={self.status_code})"
        if self.response_snippet:
            text = f"{text} (response: {self.response_snippet[:300]})"
        return text


@dataclass
class ToolCall:
    """模型发起的一次工具调用（arguments 已由 JSON 字符串解析为 dict）。"""

    id: str
    name: str
    arguments: dict[str, Any]
    arguments_raw: str | None = None  # arguments JSON 解析失败时保留的原始字符串


@dataclass
class AssistantMessage:
    """chat.completions 响应的 assistant 消息（含 reasoning 模型契约字段）。

    Runner 判定「终局回复」的依据：无 tool_calls 且 content 非空（设计文档 A 契约）；
    发起工具调用轮的 content 可能为 None。
    """

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class WarehouseLLMClient:
    """仓储 Agent 专用 LLM 客户端：httpx.AsyncClient 直连 OpenAI 兼容网关。

    配置默认读 `app.core.config.get_settings()` 的 WAREHOUSE_AGENT_*，
    构造参数可注入覆盖（base_url/api_key/model/timeout/transport，便于测试）。
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_backoff: float = RETRY_BACKOFF,
    ) -> None:
        settings = get_settings()
        resolved_base = base_url or settings.WAREHOUSE_AGENT_BASE_URL
        resolved_key = api_key or settings.WAREHOUSE_AGENT_API_KEY
        resolved_model = model or settings.WAREHOUSE_AGENT_MODEL
        resolved_timeout = (
            timeout if timeout is not None else float(settings.WAREHOUSE_AGENT_TIMEOUT)
        )
        missing = [
            name
            for name, value in (
                ("WAREHOUSE_AGENT_BASE_URL", resolved_base),
                ("WAREHOUSE_AGENT_API_KEY", resolved_key),
                ("WAREHOUSE_AGENT_MODEL", resolved_model),
            )
            if not value
        ]
        if missing:
            raise WarehouseLLMError(f"缺少配置项: {', '.join(missing)}")

        self.model = resolved_model
        self._retry_backoff = retry_backoff
        self._client = httpx.AsyncClient(
            base_url=resolved_base.rstrip("/"),
            headers={
                "Authorization": f"Bearer {resolved_key}",
                "Content-Type": "application/json",
            },
            timeout=resolved_timeout,
            transport=transport,
        )

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.1,
        max_tokens: int = 16384,
    ) -> AssistantMessage:
        """单次对话补全调用，返回结构化 assistant 消息。

        - tools 为 None/空时等价普通对话（请求体不含 tools/tool_choice 字段）；
        - 不传 response_format（tools 模式下与 json_object 不兼容）；
        - 5xx/网络瞬时错误指数退避重试，4xx 直接抛 WarehouseLLMError。
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice

        data = await self._post_chat(body)
        return _parse_assistant_message(data)

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /chat/completions，带瞬时错误重试；返回原始响应 dict。"""
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.post("/chat/completions", json=body)
            except _RETRYABLE_NETWORK_ERRORS as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = self._retry_backoff**attempt
                    logger.warning(
                        "LLM 网络错误（第 %d/%d 次尝试），%ss 后重试: %s",
                        attempt,
                        MAX_RETRIES,
                        wait,
                        e,
                    )
                    await asyncio.sleep(wait)
                    continue
                break

            if resp.status_code >= 500:
                last_error = WarehouseLLMError(
                    "LLM 网关服务端错误",
                    status_code=resp.status_code,
                    response_snippet=resp.text,
                )
                if attempt < MAX_RETRIES:
                    wait = self._retry_backoff**attempt
                    logger.warning(
                        "LLM 网关 %s（第 %d/%d 次尝试），%ss 后重试",
                        resp.status_code,
                        attempt,
                        MAX_RETRIES,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                break

            if resp.status_code >= 400:
                # 4xx（鉴权失败/参数错误等）：请求本身有问题，重试无意义
                raise WarehouseLLMError(
                    "LLM 网关拒绝了请求（4xx，不重试）",
                    status_code=resp.status_code,
                    response_snippet=resp.text,
                )

            try:
                payload: dict[str, Any] = resp.json()
                return payload
            except json.JSONDecodeError as e:
                raise WarehouseLLMError(
                    "LLM 响应不是合法 JSON",
                    status_code=resp.status_code,
                    response_snippet=resp.text,
                ) from e

        raise WarehouseLLMError(
            f"LLM 调用失败（已尝试 {MAX_RETRIES} 次）: {last_error}",
            status_code=getattr(last_error, "status_code", None),
            response_snippet=getattr(last_error, "response_snippet", None),
        )

    async def close(self) -> None:
        """关闭底层 httpx 连接。"""
        await self._client.aclose()

    async def __aenter__(self) -> WarehouseLLMClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()


def _parse_tool_calls(raw_tool_calls: Any) -> list[ToolCall]:
    """解析响应中的 tool_calls；arguments 为 JSON 字符串，解析失败保留原始串。"""
    tool_calls: list[ToolCall] = []
    for raw in raw_tool_calls or []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") or {}
        raw_arguments = function.get("arguments")
        arguments: dict[str, Any] = {}
        arguments_raw: str | None = None
        if isinstance(raw_arguments, dict):
            arguments = raw_arguments
        elif isinstance(raw_arguments, str):
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments_raw = raw_arguments
            else:
                if isinstance(parsed, dict):
                    arguments = parsed
                else:
                    arguments_raw = raw_arguments
        tool_calls.append(
            ToolCall(
                id=str(raw.get("id") or ""),
                name=str(function.get("name") or ""),
                arguments=arguments,
                arguments_raw=arguments_raw,
            )
        )
    return tool_calls


def _parse_assistant_message(data: dict[str, Any]) -> AssistantMessage:
    """把 chat.completions 响应解析为 AssistantMessage（reasoning_content 透传）。"""
    choices = data.get("choices")
    if not choices:
        raise WarehouseLLMError(
            "LLM 响应缺少 choices",
            response_snippet=json.dumps(data, ensure_ascii=False),
        )
    choice = choices[0]
    message = choice.get("message") or {}
    usage = data.get("usage")
    return AssistantMessage(
        content=message.get("content"),
        tool_calls=_parse_tool_calls(message.get("tool_calls")),
        reasoning_content=message.get("reasoning_content"),
        finish_reason=choice.get("finish_reason"),
        usage=usage if isinstance(usage, dict) else {},
    )
