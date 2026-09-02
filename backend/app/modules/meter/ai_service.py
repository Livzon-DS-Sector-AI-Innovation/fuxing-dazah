"""AI 日期提取服务 — PDF 图片提取 + 多模态视觉 LLM 识别校准日期."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
from datetime import date, timedelta
from typing import Any

import httpx
import pdfplumber
from dateutil.parser import parse as parse_date  # type: ignore[import-untyped]
from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# AI 调用重试配置
AI_MAX_RETRIES = 3
AI_RETRY_BACKOFF = 2.0  # 秒，指数退避基数

# 视觉识图最多发送前 N 页（第一页通常就有日期）
MAX_VISION_PAGES = 1


def get_meter_ai_config() -> dict[str, str] | None:
    """读取仪表 AI 配置（来自 Settings，由 .env.{APP_ENV} 提供）。未配置时返回 None。

    所需配置：
    - METER_AI_BASE_URL：API 端点
    - METER_AI_API_KEY：API 密钥
    - METER_AI_MODEL：模型名（默认 deepseek-v4-flash-vision-exp，多模态视觉）
    """
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.METER_AI_BASE_URL or not settings.METER_AI_API_KEY:
        return None
    return {
        "api_url": settings.METER_AI_BASE_URL,
        "api_key": settings.METER_AI_API_KEY,
        "model": settings.METER_AI_MODEL,
    }


VISION_PROMPT = """你是一个数据提取助手。从以下文档图片中找出"校准日期"、"检定日期"、"校准时间"、"检测日期"或"Calibration Date"对应的**本次**校准/检定的执行日期（不是下次检定日期，不是有效期至/下次校准日期）。
返回格式必须是严格的 JSON：{"date": "YYYY-MM-DD"} 或 {"error": "原因"}。
如果同时存在多个日期，优先返回"校准日期"或"检定日期"对应的值。
如果图片中找不到任何日期，返回 {"error": "未在图片中找到日期"}。"""

REPORT_FIELDS_PROMPT = """你是一个计量检测报告数据提取助手。请从图片中提取以下字段：
1. instrument_name：仪表名称/器具名称（别名：样品名称）
2. serial_number：出厂编号（器具编号、仪器编号）
3. certificate_no：证书编号
4. calibration_date：本次校准/检定的执行日期（注意：不是"下次检定日期"，不是"有效期至/下次校准日期"）

返回严格的 JSON，格式：{"instrument_name": "...", "serial_number": "...", "certificate_no": "...", "calibration_date": "YYYY-MM-DD"}
找不到的字段填 null。不要输出 JSON 以外的任何内容。"""


def calc_next_calibration_date(calibration_date: date, cycle_months: int | None) -> date:
    """下次检定日期 = 检定日期 + 检定周期 − 1 天；周期为空或 0 默认 12 个月。"""
    if not cycle_months:
        cycle_months = 12
    try:
        return calibration_date + relativedelta(months=cycle_months) - timedelta(days=1)  # type: ignore[no-any-return]
    except (OverflowError, ValueError) as e:
        logger.warning("下次检定日期计算失败（周期=%s），回退 +365 天: %s", cycle_months, e)
        return calibration_date + timedelta(days=365)


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


# pdfium（pypdfium2）在 macOS 上并发渲染会破坏堆（malloc: pointer being freed
# was not allocated → SIGABRT 杀死进程），必须全局串行化渲染。analyze 有 4 并发，
# 若每个并发各开一个线程渲染就会触发。锁只包渲染，AI 调用仍可并发。
_pdf_render_lock = asyncio.Lock()


async def render_pdf_images_as_base64(
    file_data: bytes, max_pages: int = MAX_VISION_PAGES
) -> list[str]:
    """串行化 PDF 渲染（避免 pdfium 并发堆破坏），渲染在独立线程执行。"""
    async with _pdf_render_lock:
        return await asyncio.to_thread(extract_pdf_images_as_base64, file_data, max_pages)


async def _call_ai_chat(
    api_url: str,
    api_key: str,
    model: str,
    images_base64: list[str],
    prompt: str,
    *,
    temperature: float = 1,
    max_tokens: int = 2048,
) -> str:
    """调用平台统一多模态 LLM 客户端（OpenAI 兼容 chat/completions），返回回复文本。

    失败自动重试（最多 3 次，指数退避）。
    """
    import asyncio

    from app.platform.integrations.ai.client import AIService

    image_urls = [f"data:image/png;base64,{img_b64}" for img_b64 in images_base64]
    client = AIService(api_key=api_key, base_url=api_url, model=model)
    last_error: Exception | None = None
    try:
        for attempt in range(1, AI_MAX_RETRIES + 1):
            try:
                # glm-5.3-flash：思考无法关闭，low 为最低档；response_format 官方仅文本模型
                # 支持（VLM schema 未定义），是否可用需实测，不行则删掉该字段
                content = await client.chat_vision(
                    prompt,
                    image_urls,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body={
                        "reasoning_effort": "low",
                        "response_format": {"type": "json_object"},
                    },
                )
                if content is None or content.strip() in ("", "None"):
                    raise Exception("AI 返回了空内容，请检查代理是否正常")
                content = content.strip()
                logger.info("AI content: %s", content[:200])
                return content

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                last_error = e
                if attempt < AI_MAX_RETRIES:
                    wait = AI_RETRY_BACKOFF ** attempt
                    logger.warning(
                        "AI API 网络错误（第 %d/%d 次），%ss 后重试: %s",
                        attempt, AI_MAX_RETRIES, wait, e,
                    )
                    await asyncio.sleep(wait)
            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code
                if status == 429 or status >= 500:
                    if attempt < AI_MAX_RETRIES:
                        wait = AI_RETRY_BACKOFF ** attempt
                        logger.warning(
                            "AI API 错误 %s（第 %d/%d 次），%ss 后重试",
                            status, attempt, AI_MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                raise
            except Exception as e:
                msg = str(e)
                if "空内容" in msg:
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
    finally:
        await client.close()


def _parse_json_content(content: str) -> dict[str, Any] | None:
    """从模型回复文本中解析 JSON 对象（容忍 ``` 代码块包裹与非 JSON 前缀）。

    兜底时按花括号配对提取第一个 JSON 对象，避免贪婪匹配把多个对象连成一体。
    """
    text = re.sub(r'```[\w-]*\s*', '', content)
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
                    return parsed if isinstance(parsed, dict) else None
    return None


async def call_ai_vision_extract_date(
    api_url: str,
    api_key: str,
    model: str,
    images_base64: list[str],
) -> dict[str, Any]:
    """调用多模态 LLM 从图片中提取日期。"""
    content = await _call_ai_chat(api_url, api_key, model, images_base64, VISION_PROMPT)

    result = _parse_json_content(content)
    if result is not None:
        return result
    # 从非 JSON 文本中提取 JSON 对象
    match = re.search(r'\{[^{}]*"date"\s*:\s*"[^"]*"[^{}]*\}', content, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    # 最后回退：正则提取任意常见日期格式（统一为 ISO，便于 dateutil 解析）
    match = re.search(r'(\d{4}[-/年\.]\d{1,2}[-/月\.]\d{1,2}[日]?)', content)
    if match:
        raw = match.group(1)
        raw = raw.replace("年", "-").replace("月", "-").replace("日", "").replace(".", "-").replace("/", "-")
        return {"date": raw}
    raise Exception("AI 返回内容无法解析")


async def call_ai_vision_extract_report_fields(
    api_url: str,
    api_key: str,
    model: str,
    images_base64: list[str],
) -> dict[str, str | None]:
    """调用多模态 LLM 从图片中提取报告字段（名称/出厂编号/证书编号/校准日期），缺失填 None。"""
    content = await _call_ai_chat(
        api_url, api_key, model, images_base64, REPORT_FIELDS_PROMPT, temperature=0
    )
    result = _parse_json_content(content) or {}

    def field(key: str) -> str | None:
        value = result.get(key)
        return str(value) if value else None

    # 校准日期统一为 ISO（YYYY-MM-DD），无法解析则置空，
    # 避免中文/斜杠等格式直接透传给 Pydantic date 字段导致 422/500
    cal_date: str | None = None
    raw_cal = (field("calibration_date") or "").strip()
    if raw_cal:
        # 严格格式：2024年3月5日 / 2024-03-05 / 2024/3/5 / 2024.3.5
        m = re.fullmatch(r"(\d{4})[年./\-](\d{1,2})[月./\-](\d{1,2})日?", raw_cal)
        if m:
            try:
                cal_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                cal_date = None
        elif re.search(r"\d{4}", raw_cal):
            # 含四位年份的其他格式走 dateutil 兜底；无年份的模糊值直接置空
            try:
                cal_date = parse_date(raw_cal).date().isoformat()
            except (ValueError, OverflowError, TypeError):
                cal_date = None

    return {
        "instrument_name": field("instrument_name"),
        "serial_number": field("serial_number"),
        "certificate_no": field("certificate_no"),
        "calibration_date": cal_date,
    }


async def extract_and_update_date(
    pdf_data: bytes,
    api_url: str,
    api_key: str,
    model: str,
    calibration_cycle_months: int | None,
) -> dict[str, Any]:
    """完整流程：提取 PDF 图片 → 多模态 AI 识别日期 → 返回结果。"""

    # 1. 提取 PDF 页面图片（pdfplumber 为同步 CPU 密集操作，放入线程池避免阻塞事件循环）
    images = await render_pdf_images_as_base64(pdf_data)
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
    try:
        calibration_date = parse_date(raw_date).date()
    except (ValueError, OverflowError):
        return {"success": False, "error": f"AI 返回日期格式无效: {raw_date}"}

    next_date = calc_next_calibration_date(calibration_date, calibration_cycle_months)

    return {
        "success": True,
        "calibration_date": calibration_date.isoformat(),
        "next_calibration_date": next_date.isoformat() if next_date else None,
        "calibration_cycle_months": calibration_cycle_months if calibration_cycle_months is not None else 12,
    }
