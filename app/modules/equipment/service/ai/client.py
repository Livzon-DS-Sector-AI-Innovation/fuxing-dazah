"""千文 (Qwen) API 客户端 — OpenAI 兼容接口。"""

import os

import httpx


class QwenClient:
    """千文多模态大模型客户端。

    通过阿里云 DashScope OpenAI 兼容接口调用千文 VL 模型，支持图片理解。
    参考: https://help.aliyun.com/zh/model-studio/qwen-vl-api

    BASE_URL / MODEL / API_KEY 从环境变量读取，支持部署时覆盖，
    默认值为阿里云 DashScope 千文模型。
    """

    def __init__(
        self,
        timeout: int = 120,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        self._base_url = base_url or os.getenv(
            "EQUIPMENT_AI_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self._model = model or os.getenv("EQUIPMENT_AI_MODEL", "qwen3.7-plus")
        self._api_key = api_key or os.getenv("EQUIPMENT_AI_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def analyze_image(
        self,
        image_base64: str,
        image_mime_type: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> str:
        """发送多模态请求，返回 AI 响应文本。

        Args:
            image_base64: 图片的 base64 编码（不含 data:xxx;base64, 前缀）
            image_mime_type: 图片 MIME 类型，如 image/jpeg
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 温度参数
        """
        body: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_mime_type};base64,{image_base64}"
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            "temperature": temperature,
            "max_tokens": 16384,
            "response_format": {"type": "json_object"},
        }

        return await self._request(body)

    async def parse_correction(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> str:
        """发送纯文本修正请求，返回 AI 响应文本。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词（含当前结果和修改说明）
            temperature: 温度参数
        """
        body: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 16384,
            "response_format": {"type": "json_object"},
        }

        return await self._request(body)

    async def _request(self, body: dict) -> str:
        """发送请求到千文 API，返回响应文本。"""
        resp = await self._client.post("/chat/completions", json=body)
        if resp.is_error:
            detail = ""
            try:
                err_data = resp.json()
                detail = err_data.get("message", "") or str(err_data)
            except Exception:
                detail = resp.text[:500]
            raise AIAnalysisError(
                f"千文 API 返回错误 (HTTP {resp.status_code}): {detail}"
            )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def close(self) -> None:
        await self._client.aclose()


class AIAnalysisError(Exception):
    """AI 分析异常。"""

    def __init__(self, message: str, raw_response: str | None = None):
        self.message = message
        self.raw_response = raw_response
        super().__init__(message)

    def __str__(self) -> str:
        if self.raw_response:
            return f"{self.message} (raw: {self.raw_response[:200]})"
        return self.message
