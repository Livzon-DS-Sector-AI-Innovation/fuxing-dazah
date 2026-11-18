"""AI 一轮评价——四问查漏，契约严校，失败→评价异常（不降级部分写入）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.modules.safety.ai_audit.context import ai_audit_scope
from app.modules.safety.service.config import create_ai_service

logger = logging.getLogger(__name__)

#: 评价超时（秒）——LLM 生成 3-5 条建议通常 <30s，给足余量
EVAL_TIMEOUT_SECONDS = 120

SECTION_LABELS = {
    "work": "今日重点工作",
    "done": "完成情况",
    "issue": "问题与协调",
    "plan": "明日计划",
}

SYSTEM_PROMPT = """你是安全部门日报辅导员。员工刚提交四段式安全日报初稿，你的任务是\
找遗漏、逼具体——只提问、评价和适度整理表达，绝不替员工编造成果。

按以下四个维度逐段检查：
1. 内容具体性：是否写明工作对象、部门/区域、项目、检查内容。缺地点/对象/动作就指出。
2. 实际成果与进度：是否写明数量、验收结论、完成比例、未完成事项。提示补充有依据的结果。
3. 风险与整改闭环：发现的问题是否说明临时措施、责任人、整改进度、复核计划；优先提醒未关闭风险。
4. 前后一致性：正文写了问题但"问题与协调"段没有对应措施、或完成情况与工作不对应等矛盾。

红线：不得捏造作业票数量、检查结论、隐患整改结果、风险管控措施或完成时限。\
员工没写的信息只能以提问方式要求补充。

输出 3-5 条最重要的建议，按重要程度排序，每条一句可执行的话。

输出必须是 JSON 对象且只含两个键（缺一不可，不要包裹 markdown 代码块）：
{"suggestions": ["建议1", "建议2", "建议3"], "overall": "一句话总评"}"""

FEW_SHOT_USER = """今日重点工作：作业票办理；现场巡查；变更验收。
完成情况：都已完成。
问题与协调：无。
明日计划：继续。"""

FEW_SHOT_ASSISTANT = """{"suggestions": ["补充作业票：涉及哪些部门、动火/高处/临电等类型及数量？是否存在退回或异常？", "补充现场巡查：具体巡查了哪些区域、检查重点是什么、发现了哪些问题及整改现状？", "补充变更验收：涉及哪些项目、完成几项、验收结论如何、剩余哪些事项需要跟进？", "完成情况'都已完成'过于笼统，请逐项写明数量或结论，例如'动火票3张全部办结、巡查2个车间发现1项隐患已整改'。"], "overall": "初稿三项工作都缺对象、数量与结果，问题栏与正文矛盾，需按建议逐条补充。"}"""


def build_eval_messages(sections: dict[str, str]) -> list[dict[str, str]]:
    """构造评价对话（few-shot + 员工四段原文）。"""
    lines = []
    for key in ("work", "done", "issue", "plan"):
        label = SECTION_LABELS[key]
        text = (sections.get(key) or "").strip() or "（空）"
        lines.append(f"{label}：{text}")
    user_content = "以下是员工今日日报初稿，请按要求输出评价建议：\n\n" + "\n".join(lines)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": FEW_SHOT_USER},
        {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
        {"role": "user", "content": user_content},
    ]


def validate_eval_output(raw: Any) -> dict[str, Any] | None:
    """契约校验：{"suggestions": list[str] 3~6 条, "overall": str}；不合法整体 None。"""
    if not isinstance(raw, dict):
        return None
    suggestions = raw.get("suggestions")
    if not isinstance(suggestions, list):
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in suggestions:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    overall = raw.get("overall")
    overall_text = overall.strip() if isinstance(overall, str) else ""
    if not (3 <= len(cleaned) <= 6) or not overall_text:
        return None
    return {"suggestions": cleaned, "overall": overall_text}


async def evaluate_sections(sections: dict[str, str]) -> dict[str, Any]:
    """执行一轮评价。返回 {"ok": True, "suggestions", "overall"} 或 {"ok": False, "error"}。

    任何异常（调用失败/超时/契约不合法）都不抛出——由调用方落「评价异常」状态。
    """
    service = create_ai_service("text")
    try:
        with ai_audit_scope(scenario="daily_report_eval", channel="system"):
            raw = await asyncio.wait_for(
                service.chat_parsed(
                    build_eval_messages(sections),
                    expected_keys=["suggestions", "overall"],
                    temperature=0.2,
                ),
                timeout=EVAL_TIMEOUT_SECONDS,
            )
    except TimeoutError:
        logger.warning("日报AI评价超时(%ss)", EVAL_TIMEOUT_SECONDS)
        return {"ok": False, "error": "AI 评价超时"}
    except Exception as exc:  # noqa: BLE001 — 评价失败不阻断提交流程
        logger.warning("日报AI评价失败: %s", exc)
        return {"ok": False, "error": f"AI 调用失败：{type(exc).__name__}"}
    finally:
        await service.close()

    parsed = validate_eval_output(raw)
    if parsed is None:
        logger.warning("日报AI评价契约不合法: %r", raw)
        return {"ok": False, "error": "AI 输出不符合契约"}
    return {"ok": True, **parsed}
