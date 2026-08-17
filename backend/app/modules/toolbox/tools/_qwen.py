"""千问 VL 客户端（工具箱内部）：复用平台 AIService 的 chat_vision_parsed。

环境变量：TOOLBOX_AI_BASE_URL / TOOLBOX_AI_MODEL / TOOLBOX_AI_API_KEY
（默认值同 DashScope 千问）。服务为模块级单例，httpx 连接跨页复用，
应用关闭时由 lifespan 调用 close_service() 释放连接池。
"""

import json
import os
from typing import Any

from app.modules.toolbox.registry import ToolError
from app.platform.integrations.ai.client import AIOutputError, AIService

_service: AIService | None = None


def _get_service() -> AIService:
    global _service
    if _service is None:
        api_key = os.getenv("TOOLBOX_AI_API_KEY", "")
        if not api_key:
            raise ToolError("未配置 TOOLBOX_AI_API_KEY，请联系管理员")
        _service = AIService(
            api_key=api_key,
            base_url=os.getenv(
                "TOOLBOX_AI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            model=os.getenv("TOOLBOX_AI_MODEL", "qwen3.7-plus"),
            timeout=180,
        )
    return _service


async def close_service() -> None:
    """关闭模块级 AIService 连接池（应用 lifespan shutdown 调用）。"""
    global _service
    if _service is not None:
        await _service.close()
        _service = None


def _coerce_rows(rows: Any) -> list[list[str]]:
    """行数组形状校验与单元格字符串化：None → 空串；浮点避免科学计数法。"""
    if not isinstance(rows, list) or not all(isinstance(r, list) for r in rows):
        raise ToolError("视觉模型返回格式异常，请重试")

    def cell_str(cell: Any) -> str:
        if cell is None:
            return ""
        if isinstance(cell, bool):
            return "true" if cell else "false"
        if isinstance(cell, float):
            # 避免科学计数法（1e-07）并去除多余零（99.0 → 99）；
            # 尾零保真（98.50）由提示词要求模型以字符串输出保证
            return format(cell, ".10f").rstrip("0").rstrip(".")
        return str(cell)

    return [[cell_str(cell) for cell in row] for row in rows]


def parse_rows_response(content: str) -> list[list[str]]:
    """解析千问 VL 返回的行数组，形状异常抛 ToolError。"""
    try:
        parsed = json.loads(content)
        rows = parsed.get("rows", [])
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        raise ToolError("视觉模型返回格式异常，请重试") from e
    return _coerce_rows(rows)


async def extract_table_rows(
    image_base64: str, image_mime: str, fields: list[dict[str, str]]
) -> list[list[str]]:
    """调用千问 VL 提取一张表格图片中的数据行。

    返回行数组（list[list[str]]），列顺序与 fields 一致。
    """
    fields_line = "\n".join(
        f"- {f['name']}" + (f"（含义：{f['description']}）" if f.get("description") else "")
        for f in fields
    )
    user_prompt = (
        "你是表格数据提取助手。根据用户给出的字段清单，从表格图片中提取每个字段对应的数值。"
        "只输出 JSON，不要输出其他内容。\n\n"
        f"字段清单：\n{fields_line}\n\n"
        "要求：\n"
        "1. 输出 JSON 对象：{\"rows\": [[...]]}，每行是一个数据记录，列顺序与字段清单一致；\n"
        "2. 表格中重复出现的表头行也要当作普通行输出（后续会去重）；\n"
        "3. 字段在图中找不到时该格填空字符串；\n"
        "4. 数值保持原样（不要加单位、不要换算），并一律以字符串形式输出"
        "（例如 \"98.50\"，保留末尾的 0），不要输出为 JSON 数字。"
    )
    data_url = f"data:{image_mime};base64,{image_base64}"
    try:
        # chat_vision_parsed：视觉专用通道（不带 response_format，兼容 VL 模型），
        # 且会剥离模型输出的 markdown 代码围栏后再解析 JSON
        parsed = await _get_service().chat_vision_parsed(
            user_prompt, [data_url], expected_keys=["rows"]
        )
    except AIOutputError as e:
        raise ToolError("视觉模型返回格式异常，请重试") from e
    except Exception as e:
        raise ToolError(f"视觉模型调用失败，请稍后重试: {e}") from e
    return _coerce_rows(parsed["rows"])
