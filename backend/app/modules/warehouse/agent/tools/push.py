"""推送任务对话触发工具（V3.0 UAT，2026-09-23）。

``trigger_push_task``：用户对机器人说「推送晨报」「触发低库存预警」「立即
推送周库存报表」等时调用——把口语化任务名匹配到推送注册表的 scheduled
任务，经 engine.run_task 立即执行（trigger=manual：绕过到期判断，保留
互斥/推送日志/后置钩子语义，与 Web 配置中心手动触发同一条路径）。

- 匹配口径：先剥掉口语前后缀（立即/请/推送/触发/一下…），再对
  task_name / scene / 中文名 / 短语别名做包含匹配；命中多个或不命中
  返回 error 并列出全部可触发任务（LLM 转述引导用户说准确）；
- 仅 scheduled 任务可触发（事件型如快递通知由业务动作驱动，无独立
  内容可推）；
- 结果语义照抄 engine：executed / skipped_no_target（未配目标）/
  skipped_disabled（任务停用）/ failed（生成或发送失败，已告警）。

工具上下文/数据库访问模式与 supplier.py 相同：``execute_tool`` 注入
``_ctx``；工具内自开事务（``_db_session`` 注入口），失败返回
``{"error": ...}`` 不中断 Runner。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

# 口语前后缀（循环剥离，兼容「立即推送一下晨报吧」这类说法）
_STRIP_WORDS = (
    "手动", "立即", "马上", "现在", "麻烦", "帮我", "请", "测试",
    "触发", "推送", "发一下", "一下", "吧", "。",
    "，", "？", "?", " ",
)

# 短语别名（registry 中文 label 的常用简称；key=task_name）
_TASK_ALIASES: dict[str, tuple[str, ...]] = {
    "morning_report": ("晨报",),
    "weekly_stock_report": ("周报", "周库存"),
    "monthly_report_push": ("月报",),
    "annual_report": ("年报",),
    "stale_lists": ("超6月", "不合格清单", "呆滞清单", "呆滞"),
    "low_stock_alert": ("低库存",),
    "finished_daily_summary": ("成品日汇总", "成品每日"),
    "invoice_four_state": ("四态", "开票"),
    "finished_disposition_lists": ("成品清单", "成品退货", "退货不合格"),
    "shipment_analysis": ("发货分析", "发货去向"),
    "material_usage_compare": ("用量对比",),
    "workshop_weekly_usage": ("车间周用量", "周用量"),
}


def normalize_trigger_text(text: str) -> str:
    """剥掉口语前后缀（反复剥离直到不再变化）。"""
    result = str(text or "").strip()
    changed = True
    while changed:
        changed = False
        for word in _STRIP_WORDS:
            if result.startswith(word) and len(result) > len(word):
                result = result[len(word):]
                changed = True
            if result.endswith(word) and len(result) > len(word):
                result = result[: -len(word)]
                changed = True
    return result.strip()


def match_push_task(text: str) -> tuple[str | None, list[str]]:
    """口语任务名 → (task_name | None, 候选列表)。

    匹配 scheduled 任务的 task_name / scene / label / 别名（包含即可）；
    唯一命中返回该任务，零个或多个命中返回 None + 候选（供错误提示）。
    """
    from app.modules.warehouse.push_center.registry import iter_tasks

    needle = normalize_trigger_text(text)
    if not needle:
        return None, []
    lowered = needle.lower()
    candidates: list[str] = []
    for info in iter_tasks():
        if info.trigger != "scheduled":
            continue
        names = (info.task_name, info.scene, info.label, *_TASK_ALIASES.get(info.task_name, ()))
        for name in names:
            n = str(name)
            if n and (n in needle or needle in n or n.lower() in lowered):
                candidates.append(info.task_name)
                break
    if len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def _available_tasks_line() -> str:
    from app.modules.warehouse.push_center.registry import iter_tasks

    return "、".join(
        f"{info.label}（{info.task_name}）"
        for info in iter_tasks()
        if info.trigger == "scheduled"
    )


# ── 数据库会话注入口（与 supplier.py 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入）──


async def trigger_push_task(
    task: str, _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """对话手动触发一次推送任务（用户说「推送晨报」等时调用）。"""
    from app.modules.warehouse.push_center import engine

    task_name, candidates = match_push_task(task or "")
    if task_name is None:
        if not candidates:
            return {
                "error": f"未匹配到推送任务：{task!r}",
                "hint": f"可触发的任务：{_available_tasks_line()}",
            }
        labels = "、".join(candidates)
        return {
            "error": f"「{task}」匹配到多个任务（{labels}），请说得更具体",
            "hint": f"可触发的任务：{_available_tasks_line()}",
        }

    try:
        async with _db_session() as db:
            result = await engine.run_task(
                db, task_name, datetime.now(CN_TZ), trigger="manual"
            )
    except Exception as exc:  # noqa: BLE001 — 触发失败不中断 Runner
        logger.exception("对话触发推送失败: task=%r", task_name)
        return {"error": f"推送触发失败: {type(exc).__name__}: {exc}"}

    status_texts = {
        "executed": "推送已执行并送达目标",
        "skipped_no_target": "任务未配置推送目标，已跳过（请联系管理员在推送任务里配置目标群）",
        "skipped_disabled": "任务处于停用状态，已跳过（请联系管理员启用）",
        "skipped_busy": "任务正在执行中，请稍后再试",
        "failed": "推送执行失败（已告警管理员），请稍后重试",
    }
    status = result.status
    message = status_texts.get(status, f"任务状态: {status}")
    logger.info("对话触发推送: task=%s status=%s", task_name, status)
    return {
        "status": status,
        "task_name": result.task_name,
        "scene": result.scene,
        "message": message,
        "hint": (
            "请把执行结果如实转告用户；失败/跳过时不要重试硬调，先按提示处理。"
        ),
    }


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

PUSH_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "trigger_push_task": trigger_push_task,
}

PUSH_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "trigger_push_task",
            "description": (
                "手动触发一次推送任务（用户说「推送晨报」「触发低库存预警」"
                "「立即推送周库存报表」等时用）。task 传用户原话中的任务名"
                "（如「晨报」「低库存预警」「周库存报表」「开票四态」）。"
                "可触发：晨报推送、周库存报表、月报推送、年度报表推送、"
                "超6月与不合格清单、低库存预警推送、成品每日汇总、开票四态"
                "推送、成品退货不合格清单、发货去向月度分析、物料用量对比"
                "报告、车间周用量汇总。返回 error 时如实转告（未匹配/多个"
                "候选/未配目标/停用），不要重试硬调。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "任务名（用户口语原话，如「晨报」「四态」「用量对比」）",
                    },
                },
                "required": ["task"],
            },
        },
    },
]
