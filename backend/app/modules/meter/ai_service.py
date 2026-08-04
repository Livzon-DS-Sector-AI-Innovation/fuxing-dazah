"""AI 日期提取服务 — PDF 图片提取 + 多模态视觉 LLM 识别校准日期."""

from __future__ import annotations

import base64
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

# 视觉识图最多发送前 N 页（第一页通常就有日期）
MAX_VISION_PAGES = 1


def get_meter_ai_config() -> dict[str, str] | None:
    """从环境变量读取仪表 AI 配置。未配置时返回 None。

    所需环境变量：
    - METER_AI_BASE_URL：API 端点
    - METER_AI_API_KEY：API 密钥
    - METER_AI_MODEL：模型名（默认 qwen3.7-plus，多模态）
    """
    api_url = os.getenv("METER_AI_BASE_URL", "")
    api_key = os.getenv("METER_AI_API_KEY", "")
    model = os.getenv("METER_AI_MODEL", "qwen3.7-plus")
    if not api_url or not api_key:
        return None
    return {"api_url": api_url, "api_key": api_key, "model": model}


VISION_PROMPT = """你是一个数据提取助手。从以下文档图片中找出"校准日期"、"检定日期"、"校准时间"、"检测日期"或"Calibration Date"对应的**本次**校准/检定的执行日期（不是下次检定日期，不是有效期至/下次校准日期）。
返回格式必须是严格的 JSON：{"date": "YYYY-MM-DD"} 或 {"error": "原因"}。
如果同时存在多个日期，优先返回"校准日期"或"检定日期"对应的值。
如果图片中找不到任何日期，返回 {"error": "未在图片中找到日期"}。"""


def extract_pdf_images_as_base64(file_data: bytes, max_pages: int = MAX_VISION_PAGES) -> list[str]:
    """将 PDF 前 N 页转为 base64 编码的 PNG 图片列表。"""
    images: list[str] = []
    with pdfplumber.open(io.BytesIO(file_data)) as pdf:
        for page in pdf.pages[:max_pages]:
            try:
                img = page.to_image(resolution=150)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                images.append(base64.b64encode(buf.getvalue()).decode())
            except Exception as e:
                logger.warning("PDF 页面转图片失败: %s", e)
    return images


async def call_ai_vision_extract_date(
    api_url: str,
    api_key: str,
    model: str,
    images_base64: list[str],
) -> dict[str, Any]:
    """调用多模态 LLM 从图片中提取日期，失败时自动重试（最多 3 次）。"""
    import asyncio

    url = f"{api_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 构建多模态消息内容
    content_parts: list[dict[str, Any]] = []
    for img_b64 in images_base64:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })
    content_parts.append({"type": "text", "text": VISION_PROMPT})

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content_parts}],
        "temperature": 1,
        "max_tokens": 500,
    }

    last_error: Exception | None = None
    for attempt in range(1, AI_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise Exception(f"AI API 返回 {resp.status_code}（可重试）")
                if resp.status_code != 200:
                    logger.error("AI API error: %s body=%s", resp.status_code, resp.text[:500])
                    raise Exception(f"AI API 返回 {resp.status_code}: {resp.text[:300]}")

                data = resp.json()
                logger.info("AI raw response: %s", json.dumps(data, ensure_ascii=False)[:500])
                content = data["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    logger.error("AI returned empty content. Full response: %s", json.dumps(data, ensure_ascii=False)[:1000])
                    raise Exception("AI 返回了空内容，请检查代理是否正常")
                content = content.strip()
                logger.info("AI content: %s", content[:200])

                # 提取 JSON（用正则清除 ``` 代码块包裹）
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

    raise Exception(f"AI API 调用失败（已重试 {AI_MAX_RETRIES} 次）: {last_error}")


async def extract_and_update_date(
    pdf_data: bytes,
    api_url: str,
    api_key: str,
    model: str,
    calibration_cycle_months: int | None,
) -> dict[str, Any]:
    """完整流程：提取 PDF 图片 → 多模态 AI 识别日期 → 返回结果。"""
    # 1. 提取 PDF 页面图片
    images = extract_pdf_images_as_base64(pdf_data)
    if not images:
        return {"success": False, "error": "PDF 无法提取页面图片，文件可能已损坏"}

    logger.info("PDF images extracted: %d pages", len(images))

    # 2. AI 视觉识别
    try:
        result = await call_ai_vision_extract_date(api_url, api_key, model, images)
        logger.info("AI vision response: %s", result)
    except Exception as e:
        logger.error("AI vision extraction error: %s", e)
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
