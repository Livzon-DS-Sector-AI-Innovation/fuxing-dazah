"""DazahLLMAdapter — 将 dazah AIService 适配为 graphon LLMProtocol。

graphon 的 LLM 节点通过 LLMProtocol 调用大模型。
此适配器桥接 dazah 的 AIService（OpenAI-compatible HTTP 客户端）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Generator, Mapping, Sequence
from typing import Any

from graphon.model_runtime.entities.llm_entities import (
    LLMResult,
    LLMResultChunk,
    LLMResultChunkDelta,
    LLMResultChunkWithStructuredOutput,
    LLMResultWithStructuredOutput,
    LLMUsage,
)
from graphon.model_runtime.entities.message_entities import (
    PromptMessage,
    PromptMessageTool,
)
from graphon.model_runtime.entities.model_entities import (
    AIModelEntity,
    FetchFrom,
    ModelType,
    ParameterRule,
    ParameterType,
)
from graphon.nodes.llm.protocols import LLMProtocol

from app.platform.integrations.ai.client import AIService

logger = logging.getLogger(__name__)


class DazahLLMAdapter(LLMProtocol):
    """将 dazah AIService 适配为 graphon 的 LLMProtocol。

    关键转换：
    - graphon PromptMessage → OpenAI messages dict
    - AIService.chat() str response → LLMResult
    - 同步调用（graphon 在线程中运行节点）→ asyncio.run() 包装异步 AIService
    """

    def __init__(
        self,
        ai_service: AIService,
        provider: str = "deepseek",
        model_name: str = "deepseek-v4-flash",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        self._ai_service = ai_service
        self._provider = provider
        self._model_name = model_name
        self._parameters: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        self._stop: Sequence[str] | None = None

    # ── LLMProtocol properties ──

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def parameters(self) -> Mapping[str, Any]:
        return self._parameters

    @parameters.setter
    def parameters(self, value: Mapping[str, Any]) -> None:
        self._parameters = dict(value)

    @property
    def stop(self) -> Sequence[str] | None:
        return self._stop

    # ── Model schema ──

    def get_model_schema(self) -> AIModelEntity:
        """返回模型元信息（供 graphon 内部使用）。"""
        return AIModelEntity(
            model=self._model_name,
            label=AIModelEntity.Label(en_US=self._model_name, zh_Hans=self._model_name),
            model_type=ModelType.LLM,
            fetch_from=FetchFrom.CUSTOMIZABLE_MODEL,
            model_properties=AIModelEntity.ModelProperty(
                mode="chat",
                context_size=128000,
                max_chunks=1,
            ),
            parameter_rules=[
                ParameterRule(
                    name="temperature",
                    type=ParameterType.FLOAT,
                    default=0.1,
                    min=0.0,
                    max=2.0,
                    precision=2,
                ),
                ParameterRule(
                    name="max_tokens",
                    type=ParameterType.INT,
                    default=4096,
                    min=1,
                    max=128000,
                ),
            ],
        )

    def get_llm_num_tokens(self, prompt_messages: Sequence[PromptMessage]) -> int:
        """粗略估算 token 数（用于配额控制）。

        graphon 需要此值做 execution_limits 层的 token 预算管理。
        """
        total = 0
        for msg in prompt_messages:
            content = msg.content
            if isinstance(content, str):
                total += len(content) // 2  # 中英文混合粗略估算
            elif isinstance(content, list):
                for block in content:
                    if hasattr(block, "text"):
                        total += len(block.text) // 2
        return total

    # ── Core invoke ──

    def invoke_llm(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: Mapping[str, Any] | None = None,
        tools: Sequence[PromptMessageTool] | None = None,
        stop: Sequence[str] | None = None,
        stream: bool = False,
    ) -> LLMResult | Generator[LLMResultChunk, None, None]:
        """同步调用 LLM（graphon 在 worker 线程中调用）。"""
        if stream:
            return self._invoke_stream(prompt_messages, model_parameters, stop)
        return asyncio.run(
            self._invoke_async(prompt_messages, model_parameters, stop)
        )

    def invoke_llm_with_structured_output(
        self,
        *,
        prompt_messages: Sequence[PromptMessage],
        json_schema: Mapping[str, Any],
        model_parameters: Mapping[str, Any] | None = None,
        stop: Sequence[str] | None = None,
        stream: bool = False,
    ) -> (
        LLMResultWithStructuredOutput
        | Generator[LLMResultChunkWithStructuredOutput, None, None]
    ):
        """带结构化输出的 LLM 调用。"""
        if stream:
            return self._invoke_structured_stream(
                prompt_messages, json_schema, model_parameters, stop,
            )

        result = asyncio.run(
            self._invoke_structured_async(
                prompt_messages, json_schema, model_parameters, stop,
            )
        )
        return result

    def is_structured_output_parse_error(self, error: Exception) -> bool:
        """判断异常是否为结构化输出解析失败。"""
        import json as _json
        return isinstance(error, (_json.JSONDecodeError, ValueError, KeyError))

    # ── Private helpers ──

    async def _invoke_async(
        self,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: Mapping[str, Any] | None,
        stop: Sequence[str] | None,
    ) -> LLMResult:
        """异步调用 AIService → 返回 LLMResult。"""

        messages = self._prompt_messages_to_dicts(prompt_messages)
        params = {**self._parameters}
        if model_parameters:
            params.update(model_parameters)

        try:
            raw_text = await self._ai_service.chat(
                messages=messages,
                temperature=params.get("temperature", 0.1),
                max_tokens=params.get("max_tokens", 4096),
            )
        except Exception as e:
            logger.error("LLM 调用失败: %s", e)
            raise

        # 尝试解析 JSON 响应
        usage = LLMUsage(
            prompt_tokens=self.get_llm_num_tokens(prompt_messages),
            completion_tokens=len(raw_text) // 2,
            total_tokens=self.get_llm_num_tokens(prompt_messages) + len(raw_text) // 2,
        )

        return LLMResult(
            message=PromptMessage(role="assistant", content=raw_text),
            usage=usage,
            model=self._model_name,
        )

    async def _invoke_structured_async(
        self,
        prompt_messages: Sequence[PromptMessage],
        json_schema: Mapping[str, Any],
        model_parameters: Mapping[str, Any] | None,
        stop: Sequence[str] | None,
    ) -> LLMResultWithStructuredOutput:
        """带结构化输出的异步调用。"""
        import json as _json

        messages = self._prompt_messages_to_dicts(prompt_messages)
        params = {**self._parameters}
        if model_parameters:
            params.update(model_parameters)

        try:
            raw_text = await self._ai_service.chat(
                messages=messages,
                temperature=params.get("temperature", 0.1),
                max_tokens=params.get("max_tokens", 4096),
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.error("LLM 结构化输出调用失败: %s", e)
            raise

        # 解析 JSON
        try:
            parsed = _json.loads(raw_text)
        except _json.JSONDecodeError as e:
            logger.warning("JSON 解析失败: %s, raw=%s", e, raw_text[:500])
            raise

        usage = LLMUsage(
            prompt_tokens=self.get_llm_num_tokens(prompt_messages),
            completion_tokens=len(raw_text) // 2,
            total_tokens=self.get_llm_num_tokens(prompt_messages) + len(raw_text) // 2,
        )

        return LLMResultWithStructuredOutput(
            message=PromptMessage(role="assistant", content=raw_text),
            usage=usage,
            model=self._model_name,
            structured_output=parsed,
        )

    def _invoke_stream(
        self,
        prompt_messages: Sequence[PromptMessage],
        model_parameters: Mapping[str, Any] | None,
        stop: Sequence[str] | None,
    ) -> Generator[LLMResultChunk, None, None]:
        """流式调用（暂不支持 — 返回一个模拟的完整 chunk）。"""
        result = asyncio.run(
            self._invoke_async(prompt_messages, model_parameters, stop)
        )
        yield LLMResultChunk(
            delta=LLMResultChunkDelta(
                content=str(result.message.content),
                role="assistant",
            ),
            model=self._model_name,
        )

    def _invoke_structured_stream(
        self,
        prompt_messages: Sequence[PromptMessage],
        json_schema: Mapping[str, Any],
        model_parameters: Mapping[str, Any] | None,
        stop: Sequence[str] | None,
    ) -> Generator[LLMResultChunkWithStructuredOutput, None, None]:
        """结构化流式调用（暂不支持 — 返回一个模拟的完整 chunk）。"""
        result = asyncio.run(
            self._invoke_structured_async(
                prompt_messages, json_schema, model_parameters, stop,
            )
        )
        yield LLMResultChunkWithStructuredOutput(
            delta=LLMResultChunkDelta(
                content=str(result.message.content),
                role="assistant",
            ),
            model=self._model_name,
        )

    def _prompt_messages_to_dicts(
        self, prompt_messages: Sequence[PromptMessage],
    ) -> list[dict[str, Any]]:
        """将 graphon PromptMessage 列表转换为 OpenAI messages dict 列表。"""
        messages: list[dict[str, Any]] = []
        for msg in prompt_messages:
            content = msg.content
            if isinstance(content, str):
                messages.append({"role": msg.role, "content": content})
            elif isinstance(content, list):
                # 多模态 content blocks
                parts: list[dict[str, Any]] = []
                for block in content:
                    if hasattr(block, "text") and block.text:
                        parts.append({"type": "text", "text": block.text})
                    elif hasattr(block, "url") and block.url:
                        parts.append({
                            "type": "image_url",
                            "image_url": {"url": block.url},
                        })
                messages.append({"role": msg.role, "content": parts})
        return messages
