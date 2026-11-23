"""负责人日报 LLM 聚合——只从最终版汇总，去重不重复累计，来源不足标待核实。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.modules.safety.ai_audit.context import ai_audit_scope
from app.modules.safety.service.config import create_ai_service

from .evaluation import SECTION_LABELS

logger = logging.getLogger(__name__)

AGG_TIMEOUT_SECONDS = 180

SYSTEM_PROMPT = """你是安全工程中心部门负责人的日报汇总助手。输入是多名员工当天\
已确认的最终版日报（五段式），请汇总生成部门负责人工作日报。

格式要求（markdown，保留中文序号段头）：
一、今日重点工作——按专项分类（如【特殊作业安全管理】【现场隐患排查与治理】【消防设施管理】【危化品及职业健康】【安全教育及相关方管理】等，按当日实际归类），每项写清具体工作、数量/进度、处理结果和未完成部分。
二、数据项目——只汇总有来源的数据（特殊作业票数量及类型、巡查及隐患整改、培训/外来人员、消防点检等）。
三、协调事项——按事项说明需协调的部门、卡点原因、目前进展、下一步安排。
四、风险报备——按风险说明涉及区域、后果、已采取措施、整改责任与后续计划。

红线：
1. 同一风险/项目/作业被多人提及，识别为同一事项，绝不重复累计数量。
2. 只用员工原文中有依据的信息；来源不足或口径不一的数据后标注"（待核实）"。
3. 不凭空补充、不推断。确无风险时风险段写"无"，不编造。
4. 结尾不写总结客套话。

输出 JSON：{"report_markdown": "<完整日报 markdown>"}
"""


def build_agg_messages(
    reports: list[Any],  # store.ReportRecord（避免循环 import 用鸭子类型）
    date_key: str,
) -> list[dict[str, str]]:
    """构造聚合对话：逐人四段最终版原文。"""
    blocks = []
    for rec in reports:
        lines = [f"【{rec.name}】"]
        for key in ("work", "done", "coord", "risk", "plan"):
            text = (rec.sections.get(key) or "").strip()
            if text:
                lines.append(f"  {SECTION_LABELS[key]}：{text}")
        blocks.append("\n".join(lines))
    user_content = (
        f"日期：{date_key}\n以下为当日全部已完成最终版日报，请汇总生成部门负责人日报：\n\n"
        + "\n\n".join(blocks)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def validate_agg_output(raw: Any) -> dict[str, Any] | None:
    """契约校验：report_markdown 非空且含 一、二、三、 段头。"""
    if not isinstance(raw, dict):
        return None
    markdown = raw.get("report_markdown")
    if not isinstance(markdown, str):
        return None
    text = markdown.strip()
    if not text:
        return None
    for header in ("一、", "二、", "三、"):
        if header not in text:
            return None
    return {"report_markdown": text}


async def aggregate_reports(reports: list[Any], date_key: str) -> dict[str, Any]:
    """聚合。返回 {"ok": True, "report_markdown"} 或 {"ok": False, "error"}。"""
    if not reports:
        return {"ok": False, "error": "当日无已完成的最终版日报，无法汇总"}
    service = create_ai_service("text")
    try:
        with ai_audit_scope(scenario="daily_report_agg", channel="system"):
            raw = await asyncio.wait_for(
                service.chat_parsed(
                    build_agg_messages(reports, date_key),
                    expected_keys=["report_markdown"],
                    temperature=0.2,
                ),
                timeout=AGG_TIMEOUT_SECONDS,
            )
    except TimeoutError:
        logger.warning("负责人日报聚合超时(%ss)", AGG_TIMEOUT_SECONDS)
        return {"ok": False, "error": "AI 汇总超时"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("负责人日报聚合失败: %s", exc)
        return {"ok": False, "error": f"AI 调用失败：{type(exc).__name__}"}
    finally:
        await service.close()

    parsed = validate_agg_output(raw)
    if parsed is None:
        logger.warning("负责人日报聚合契约不合法")
        return {"ok": False, "error": "AI 输出不符合契约"}
    return {"ok": True, **parsed}
