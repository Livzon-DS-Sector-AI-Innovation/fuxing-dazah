"""AI 日期提取服务 — PDF 文本提取 + 调用 OpenAI 兼容 API 识别校准日期."""

from __future__ import annotations

import io
import json
import logging
import os
import re
from typing import Any

import httpx
import pdfplumber

logger = logging.getLogger(__name__)

# AI 调用重试配置
AI_MAX_RETRIES = 3
AI_RETRY_BACKOFF = 2.0  # 秒，指数退避基数


def get_meter_ai_config() -> dict[str, str] | None:
    """从环境变量读取仪表 AI 配置。未配置时返回 None。

    所需环境变量：
    - METER_AI_BASE_URL：API 端点
    - METER_AI_API_KEY：API 密钥
    - METER_AI_MODEL：模型名（默认 qwen3.6-flash）
    """
    api_url = os.getenv("METER_AI_BASE_URL", "")
    api_key = os.getenv("METER_AI_API_KEY", "")
    model = os.getenv("METER_AI_MODEL", "qwen3.6-flash")
    if not api_url or not api_key:
        return None
    return {"api_url": api_url, "api_key": api_key, "model": model}

EXTRACT_PROMPT = """你是一个数据提取助手。从以下文档文本中找出"校准日期"、"检定日期"、"校准时间"、"检测日期"或"Calibration Date"对应的**本次**校准/检定的执行日期（不是下次检定日期）。
返回格式必须是严格的 JSON：{{"date": "YYYY-MM-DD"}} 或 {{"error": "原因"}}。
如果同时存在多个日期，优先返回"校准日期"或"检定日期"对应的值。

文档内容：
__TEXT_PLACEHOLDER__"""


def _build_prompt(text: str) -> str:
    """安全构建 prompt，避免 format() 的 {} 冲突。"""
    return EXTRACT_PROMPT.replace("__TEXT_PLACEHOLDER__", text)


def extract_pdf_text(file_data: bytes) -> str:
    """从 PDF 二进制数据中提取纯文本。"""
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


async def call_ai_extract_date(
    api_url: str,
    api_key: str,
    model: str,
    text: str,
) -> dict[str, Any]:
    """调用 OpenAI 兼容 API 提取日期，失败时自动重试（最多 3 次）。"""
    import asyncio

    url = f"{api_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": _build_prompt(text[:16000])},
        ],
        "temperature": 1,
        "max_tokens": 500,
    }

    last_error: Exception | None = None
    for attempt in range(1, AI_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    # 限流或服务端错误，可重试
                    raise Exception(f"AI API 返回 {resp.status_code}（可重试）")
                if resp.status_code != 200:
                    # 客户端错误（4xx 非 429），不重试
                    logger.error(f"AI API error: {resp.status_code} body={resp.text[:500]}")
                    raise Exception(f"AI API 返回 {resp.status_code}: {resp.text[:300]}")

                data = resp.json()
                logger.info(f"AI raw response: {json.dumps(data, ensure_ascii=False)[:500]}")
                content = data["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    logger.error(f"AI returned empty content. Full response: {json.dumps(data, ensure_ascii=False)[:1000]}")
                    raise Exception("AI 返回了空内容，请检查代理是否正常")
                content = content.strip()
                logger.info(f"AI content: {content[:200]}")
                # 提取 JSON（用正则清除 ``` 代码块包裹，支持 ```json / ``` 等）
                content = re.sub(r'```[\w-]*\s*', '', content)
                content = content.strip()

                try:
                    result: dict[str, Any] = json.loads(content)
                except json.JSONDecodeError:
                    # 从非 JSON 文本中提取 JSON 对象
                    match = re.search(r'\{[^{}]*"date"\s*:\s*"[^"]*"[^{}]*\}', content, re.DOTALL)
                    if match:
                        try:
                            result = json.loads(match.group(0))
                        except json.JSONDecodeError:
                            raise
                    else:
                        # 最后回退：正则提取任意常见日期格式
                        match = re.search(r'(\d{4}[-/年\.]\d{1,2}[-/月\.]\d{1,2}[日]?)', content)
                        if match:
                            return {"date": match.group(1)}
                        raise
                return result

        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            last_error = e
            if attempt < AI_MAX_RETRIES:
                wait = AI_RETRY_BACKOFF ** attempt
                logger.warning(
                    "AI API 网络错误（第 %d/%d 次），%ss 后重试: %s",
                    attempt, AI_MAX_RETRIES, wait, e,
                )
                await asyncio.sleep(wait)
        except Exception as e:
            # 判断是否可重试的错误
            msg = str(e)
            if ("429" in msg or "500" in msg or "502" in msg or "503" in msg or "504" in msg
                    or "可重试" in msg or "空内容" in msg):
                last_error = e
                if attempt < AI_MAX_RETRIES:
                    wait = AI_RETRY_BACKOFF ** attempt
                    logger.warning(
                        "AI API 错误（第 %d/%d 次），%ss 后重试: %s",
                        attempt, AI_MAX_RETRIES, wait, e,
                    )
                    await asyncio.sleep(wait)
                    continue
            raise

    # 所有重试耗尽
    raise Exception(f"AI API 调用失败（已重试 {AI_MAX_RETRIES} 次）: {last_error}")


async def extract_and_update_date(
    pdf_data: bytes,
    api_url: str,
    api_key: str,
    model: str,
    calibration_cycle_months: int | None,
) -> dict[str, Any]:
    """完整流程：提取 PDF 文本 → AI 识别日期 → 返回结果。"""
    # 1. 提取文本
    try:
        text = extract_pdf_text(pdf_data)
    except Exception as e:
        logger.error(f"PDF text extraction error: {e}")
        return {"success": False, "error": f"PDF 文本提取失败: {e}"}

    if not text.strip():
        return {"success": False, "error": "PDF 无可提取文字，可能是扫描件"}

    logger.info(f"PDF text extracted: {len(text)} chars, preview: {text[:200]}")

    # 2. AI 识别
    try:
        result = await call_ai_extract_date(api_url, api_key, model, text)
        logger.info(f"AI response: {result}")
    except Exception as e:
        logger.error(f"AI extraction error: {e}")
        return {"success": False, "error": f"AI 提取失败: {e}"}

    if "date" not in result:
        return {"success": False, "error": result.get("error", "AI 未返回日期")}

    raw_date = result["date"]
    # 3. 计算下次检定日期
    from datetime import timedelta

    from dateutil.parser import parse as parse_date  # type: ignore[import-untyped]
    from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]

    try:
        calibration_date = parse_date(raw_date).date()
    except (ValueError, OverflowError):
        return {"success": False, "error": f"AI 返回日期格式无效: {raw_date}"}

    next_date = None
    # 探测器默认检定周期为 12 个月
    if calibration_cycle_months is None:
        calibration_cycle_months = 12
    if calibration_cycle_months:
        try:
            next_date = calibration_date + relativedelta(months=calibration_cycle_months) - timedelta(days=1)
        except Exception:
            next_date = calibration_date + timedelta(days=365)  # fallback

    return {
        "success": True,
        "calibration_date": calibration_date.isoformat(),
        "next_calibration_date": next_date.isoformat() if next_date else None,
        "calibration_cycle_months": calibration_cycle_months,
    }
