"""AI 配置连通性探测（backend-design §5.4，/ai-config/test 端点专用）。

- 最小 HTTP 请求（httpx.AsyncClient），不复用模型 SDK：
  text/text_backup/vision → POST ``{base_url}/chat/completions``；
  embedding → POST ``{base_url}/embeddings``（成功需 ``data[0].embedding`` 非空）；
  rerank → POST ``{base_url}/rerank``。
- ``overrides`` 与 store 当前生效配置（DB→env→default 合并值）做覆盖式合并后探测，
  不保存任何值；
- 缺 api_key/base_url → 直接返回未配置（不发起请求）；
- 不落库、不写审计（对齐 bitable test-connection，backend-design §5.4）。

依赖方向：probe → resolver → store（resolver 不 import probe，无环）。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.modules.safety.ai_config import registry
from app.modules.safety.ai_config.resolver import get_profile_config

logger = logging.getLogger(__name__)


def _build_probe_request(
    profile: str, config: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    """按 profile 组装 (url, json payload)；None = 该 profile 无探测协议。"""
    base_url = (config.get("base_url") or "").rstrip("/")
    model = config.get("model")
    if profile in ("text", "text_backup", "vision"):
        return (
            f"{base_url}/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 4,
            },
        )
    if profile == "embedding":
        return f"{base_url}/embeddings", {"model": model, "input": ["test"]}
    if profile == "rerank":
        return (
            f"{base_url}/rerank",
            {"model": model, "query": "test", "documents": ["test"]},
        )
    return None


def _extract_error_message(resp: httpx.Response) -> str:
    """上游非 2xx 错误摘录：优先取 JSON error.message，否则原文，截断 300 字。"""
    text = (resp.text or "").strip()
    if text:
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            err = payload.get("error")
            msg: Any = None
            if isinstance(err, dict):
                msg = err.get("message")
            elif isinstance(err, str):
                msg = err
            else:
                msg = payload.get("message")
            if isinstance(msg, str) and msg:
                text = msg.strip() or text
        return text[:300]
    return f"HTTP {resp.status_code}"


async def probe_profile(
    profile: str, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """探测某 profile 连通性，返回 ``{ok, status_code, message}``。

    - 未知 profile 抛 ValueError（「未知 profile」开头，404 语义）；
    - 缺 api_key/base_url → ``{"ok": False, "status_code": None,
      "message": "未配置 api_key/base_url"}``（不发起请求）；
    - 成功 → ``{"ok": True, "status_code": 200, "message": "ok"}``；
    - 上游非 2xx → ``{"ok": False, "status_code": <code>, "message": 错误摘录}``；
    - 网络/超时异常 → ``{"ok": False, "status_code": None,
      "message": "<异常类名>: <异常消息>"}``。
    """
    registry.get_profile(profile)  # 未知 profile 抛 ValueError（API 层映射 404）
    config = get_profile_config(profile)
    if overrides:
        config.update({k: v for k, v in overrides.items() if v is not None})

    api_key = config.get("api_key") or ""
    base_url = (config.get("base_url") or "").strip()
    if not api_key or not base_url:
        return {"ok": False, "status_code": None, "message": "未配置 api_key/base_url"}

    request = _build_probe_request(profile, config)
    if request is None:
        return {"ok": False, "status_code": None, "message": f"profile {profile} 不支持探测"}
    url, payload = request

    timeout = config.get("timeout", 15)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        ) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        # 网络/连接/超时等异常 → 无上游状态码（API 层映射 502）
        return {
            "ok": False,
            "status_code": None,
            "message": f"{type(exc).__name__}: {exc}",
        }
    except Exception as exc:
        # 探测兜底：任何残余异常都不外抛（API 层按网络异常映射 502）
        logger.exception("AI 配置探测异常（profile=%s）", profile)
        return {
            "ok": False,
            "status_code": None,
            "message": f"{type(exc).__name__}: {exc}",
        }

    if not resp.is_success:
        return {
            "ok": False,
            "status_code": resp.status_code,
            "message": _extract_error_message(resp),
        }

    # embedding 额外校验：200 但 data[0].embedding 非空才算成功
    if profile == "embedding":
        try:
            resp_data = resp.json()
        except ValueError:
            resp_data = None
        vectors = (
            (resp_data.get("data") or []) if isinstance(resp_data, dict) else []
        )
        if not vectors or not isinstance(vectors[0], dict) or not vectors[0].get("embedding"):
            return {
                "ok": False,
                "status_code": resp.status_code,
                "message": "响应缺少 data[0].embedding（可能非向量接口）",
            }

    return {"ok": True, "status_code": 200, "message": "ok"}
