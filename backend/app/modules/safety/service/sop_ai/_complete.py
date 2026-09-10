"""SOP AI 层 — 生成补全（智能补全缺失章节）。

AI 基于源文档全文 + 化工安全领域知识，推理生成结构化数据，供 Layer2 拼接。
AI 失败返回 None，上层回退规则渲染，绝不阻塞生成。

注意：本模块是**单次调用版**（4 数组补全）。后续按「逐章 AI 主生成」重构，
prompt 迁至 _prompts.py 的逐章 prompt、逐章函数迁至 _chapters.py，本函数签名
保持或由编排层最小调整。
"""

from __future__ import annotations

import json
import logging
import uuid

from ._prompts import SOP_COMPLETE_SYSTEM_PROMPT
from ._validate import _validate_supplement

logger = logging.getLogger(__name__)

# ── 输入文本上限（审计客户端 MAX_TEXT_CHARS=64KB，此处再收紧控制成本）──
MAX_RAW_TEXT_CHARS = 40000


async def sop_complete_document(
    *,
    raw_text: str,
    stage_names: list[str],
    meta: dict | None = None,
    regulation_id: uuid.UUID | None = None,
) -> dict | None:
    """AI 补全缺失章节的结构化数据（工艺参数 / 安全要求 / 工艺流程 / 异常工况）。

    Args:
        raw_text: 源文档全文（段落+表格，截断至 MAX_RAW_TEXT_CHARS）。
        stage_names: Layer1 规则提取出的工序清单（保证 AI 输出阶段名与渲染对齐）。
        meta: 可选上下文（product_name/post_name），仅作提示用，不要求 AI 输出 meta。
        regulation_id: 操规记录 ID，写入审计 resource_id。

    Returns:
        规范化后的 supplement dict；AI 失败或校验不过返回 None。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    raw_text = (raw_text or "")[:MAX_RAW_TEXT_CHARS]
    meta = meta or {}
    product = str(meta.get("product_name", "") or "")
    post = str(meta.get("post_name", "") or "")

    user_content = (
        f"产品：{product}\n"
        f"岗位：{post}\n\n"
        f"已提取的工艺工序清单：\n{json.dumps(stage_names, ensure_ascii=False)}\n\n"
        f"请输出 JSON 对象。\n\n"
        f"源文档全文（表格可能为空，请按系统提示补全）：\n{raw_text}"
    )

    try:
        with ai_audit_scope(
            scenario="sop_generation",
            channel="web",
            resource_type="regulation",
            resource_id=regulation_id,  # UUID 类型列，直接传对象
        ):
            ai = create_ai_service("text")
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": SOP_COMPLETE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                expected_keys=[
                    "control_parameters",
                    "safety_requirements",
                    "abnormal_conditions",
                ],
                temperature=0.1,
            )
        return _validate_supplement(result)
    except Exception as exc:  # noqa: BLE001 — AI 失败绝不阻塞生成
        logger.exception("SOP AI 补全调用失败：%s", exc)
        return None
