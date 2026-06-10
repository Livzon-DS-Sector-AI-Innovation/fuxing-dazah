"""千文 (Qwen) API 客户端 — OpenAI 兼容接口。"""

import httpx


class QwenClient:
    """千文多模态大模型客户端。

    通过阿里云 DashScope OpenAI 兼容接口调用千文 VL 模型，支持图片理解。
    参考: https://help.aliyun.com/zh/model-studio/qwen-vl-api
    """

    BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    MODEL = "qwen-vl-max"
    API_KEY = "sk-a2ef55e9d2904572bb039f51e236a250"

    def __init__(self, timeout: int = 120):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.API_KEY}",
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
            "model": self.MODEL,
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

        resp = await self._client.post("/chat/completions", json=body)
        if resp.is_error:
            # 提取 DashScope 返回的详细错误信息
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
