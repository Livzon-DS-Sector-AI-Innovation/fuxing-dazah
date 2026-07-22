"""Minimal AI chat service for HR turnover analysis.

Self-contained within the HR module — no dependency on app.platform.ai.
Uses the OpenAI SDK pointed at Moonshot API for streaming completions.
"""

from collections.abc import AsyncGenerator
from typing import Any

import openai

from app.core.config import get_settings


class AiChatService:
    """Service for streaming chat completions via Moonshot API."""

    def __init__(self, api_key: str, model: str = "moonshot-v1-32k") -> None:
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.moonshot.cn/v1",
        )
        self.model = model

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Stream chat completion tokens from the LLM.

        Yields dicts with keys:
            - type: "reasoning" | "content"
            - text: the token text
        """
        all_messages: list[dict[str, str]] = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=all_messages,  # type: ignore[arg-type]
            stream=True,
            temperature=1,
            max_tokens=4096,
        )

        stream: Any = response
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            content = getattr(delta, "content", None)
            if reasoning:
                yield {"type": "reasoning", "text": reasoning}
            if content:
                yield {"type": "content", "text": content}

    @staticmethod
    def build_system_prompt(page: str | None = None) -> str:
        """Build the system prompt for the HR assistant."""
        settings = get_settings()
        prompt = settings.HR_AI_SYSTEM_PROMPT

        if page:
            prompt += f"\n当前页面：{page}"

        return prompt
