"""OpenAI-compatible LLM HTTP client."""

import json
from typing import Any

import httpx


class AIOutputError(Exception):
    """Raised when AI response cannot be parsed into expected structure."""

    def __init__(self, message: str, raw_response: str | None = None):
        self.message = message
        self.raw_response = raw_response
        super().__init__(message)

    def __str__(self) -> str:
        if self.raw_response:
            return f"{self.message} (raw: {self.raw_response[:200]})"
        return self.message


class AIService:
    """OpenAI-compatible LLM client.

    Uses httpx.AsyncClient to call any OpenAI-compatible chat completions API
    (OpenAI, DeepSeek, Qwen, etc.).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        timeout: int = 120,
    ):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        response_format: str = "json_object",
        temperature: float = 0.1,
        max_tokens: int = 16384,
    ) -> str:
        """Send a chat completion request and return the response text."""
        # 使用 json_object 格式时，prompt 中必须出现 "json" 字样（DeepSeek/OpenAI 要求）
        msgs = [dict(m) for m in messages]  # shallow copy
        if response_format == "json_object":
            last = msgs[-1]
            if isinstance(last.get("content"), str) and "json" not in last["content"].lower():
                last["content"] = last["content"] + "\n\n请以 JSON 格式返回结果。"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = {"type": response_format}

        resp = await self._client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])

    async def chat_parsed(
        self,
        messages: list[dict[str, Any]],
        expected_keys: list[str],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Chat + parse JSON response, validating expected keys exist."""
        raw = await self.chat(messages, temperature=temperature)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise AIOutputError("AI response is not valid JSON", raw) from e

        # 兼容 AI 返回数组的情况：合并数组中的对象
        if isinstance(parsed, list):
            if len(parsed) == 0:
                raise AIOutputError("AI returned empty list", raw)
            if isinstance(parsed[0], dict):
                merged: dict[str, Any] = {}
                for item in parsed:
                    for k, v in item.items():
                        if k in merged and isinstance(v, str):
                            merged[k] = merged[k] + "；" + v
                        else:
                            merged[k] = v
                parsed = merged
            else:
                parsed = {"_raw": raw}

        if not isinstance(parsed, dict):
            raise AIOutputError("AI response is not a dict", raw)

        # coerce boolean-like strings
        for k, v in parsed.items():
            if isinstance(v, str) and v.lower() in ("true", "false"):
                parsed[k] = v.lower() == "true"  # pyright: ignore[reportArgumentType]

        missing = [k for k in expected_keys if k not in parsed]
        if missing:
            raise AIOutputError(f"AI response missing keys: {missing}", raw)
        return parsed

    async def chat_vision(
        self,
        text_prompt: str,
        image_urls: list[str],
        temperature: float = 0.1,
        max_tokens: int = 16384,
    ) -> str:
        """Send a multimodal chat request with images (vision-capable model).

        Uses OpenAI-compatible vision format:
        messages = [{"role":"user", "content":[{"type":"text",...}, {"type":"image_url",...}]}]
        """
        content_parts: list[dict[str, Any]] = [
            {"type": "text", "text": text_prompt},
        ]
        for url in image_urls:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": url},
            })

        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": content_parts},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = await self._client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])

    async def chat_vision_parsed(
        self,
        text_prompt: str,
        image_urls: list[str],
        expected_keys: list[str],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Vision chat + parse JSON response, validating expected keys."""
        raw = await self.chat_vision(text_prompt, image_urls, temperature=temperature)
        try:
            # Strip markdown code fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                # Find first line that doesn't start with ```
                for i, line in enumerate(lines):
                    if not line.strip().startswith("```"):
                        cleaned = "\n".join(lines[i:])
                        break
                # Remove trailing ```
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3].strip()
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise AIOutputError("Vision AI response is not valid JSON", raw) from e

        if not isinstance(parsed, dict):
            raise AIOutputError("Vision AI response is not a dict", raw)

        # coerce boolean strings
        for k, v in parsed.items():
            if isinstance(v, str) and v.lower() in ("true", "false"):
                parsed[k] = v.lower() == "true"

        missing = [k for k in expected_keys if k not in parsed]
        if missing:
            raise AIOutputError(f"Vision AI response missing keys: {missing}", raw)
        return parsed

    async def health_check(self) -> dict[str, Any]:
        """Check connectivity by listing models (lightweight endpoint)."""
        try:
            resp = await self._client.get("/models", timeout=5)
            return {
                "status": "ok" if resp.is_success else "error",
                "detail": str(resp.status_code),
            }
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    async def close(self) -> None:
        await self._client.aclose()
