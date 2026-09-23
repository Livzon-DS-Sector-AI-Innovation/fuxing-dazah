"""任务推送与提醒通知（fill_service.py 拆分）。"""

import asyncio
import logging
import uuid

from app.modules.quality.feishu.client import (
    QUALITY_FEISHU_CHAT_IDS,
)
from app.modules.quality.feishu.fill_service._common import (
    _frontend_task_link,
    _today_str,
    _unfilled_groups,
)
from app.modules.quality.feishu.message import send_chat_text
from app.modules.quality.models import QualityTestTask
from app.modules.quality.repository import (
    list_test_results,
)

logger = logging.getLogger(__name__)


async def push_task_reminder(task: QualityTestTask, rows: list) -> None:
    """向配置的群推送单个任务的提醒文本 + 分组填报卡片（无待填项时仅文本）。"""
    from app.modules.quality.feishu.client import (
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_fill_card

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    report_note = f"，出报日期 {task.report_date}" if task.report_date else ""
    bio_rows, chem_rows = _unfilled_groups(rows)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(
                chat_id,
                f"📋 检验任务：{task.product_name} 批号 {task.batch_number}（{task.specification or '-'}）{report_note}\n请在下方卡片填报；液相类项目上传计算表自动填入。",
            )
            if bio_rows or chem_rows:
                filled = sum(1 for r in rows if r.is_pass is not None)
                await send_fill_card(
                    chat_id, task.batch_number, [("生物组", bio_rows), ("理化组", chem_rows)],
                    progress=f"已填 {filled}/{len(rows)}",
                )
        except Exception:
            logger.exception("飞书任务提醒推送失败: %s", chat_id)


async def notify_unqualified(
    product_name: str,
    batch: str,
    item_name: str,
    value_text: str,
    limit_text: str,
    origin_chat_id: str = "",
) -> None:
    """不合格飞书提醒（@ 负责人；未配置提醒人时纯 post 文本群通知）。"""
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_ALERT_USER_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_alert_post

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    title = "🚨 检验不合格提醒"
    lines = [
        f"批号 {batch}（{product_name}）",
        f"项目 {item_name}：实测 {value_text}（限度 {limit_text}）",
        "请尽快人工处理",
    ]
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        if chat_id == origin_chat_id:
            continue  # 当前会话已在回执中展示明细，不重复打扰
        await send_alert_post(chat_id, QUALITY_FEISHU_ALERT_USER_IDS, title, lines)

async def notify_pending_review(task_id: str) -> None:
    """任务自动进入待复核后提醒配置群（fire-and-forget，专员进系统审核）。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.client import (
        feishu_configured,
    )
    from app.modules.quality.repository import get_test_task

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    task = None
    for _ in range(20):
        async with async_session_factory() as db:
            task = await get_test_task(db, uuid.UUID(task_id))
        if task:
            break
        await asyncio.sleep(0.5)
    if not task or task.status != "pending_review":
        return
    from app.modules.quality.feishu.message import send_interactive_card

    card = {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"🔍 待复核 {task.batch_number}"}, "template": "orange"},
        "body": {"elements": [
            {"tag": "markdown", "content": f"**{task.product_name}** 批号 **{task.batch_number}** 已全部填报完成，待复核（需两名不同复核人通过）。\n进入任务详情：对照原始证据核对结果、必要时修改，点「复核通过」。"},
            {"tag": "button", "text": {"tag": "plain_text", "content": "打开任务复核"},
             "type": "primary", "url": _frontend_task_link(task_id)},
        ]},
    }
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_interactive_card(chat_id, card)
        except Exception:
            logger.exception("飞书待复核卡片发送失败: %s", chat_id)


async def notify_task_created(task_id: str) -> None:
    """建任务/补录出报日期后的推送（fire-and-forget，不阻塞主流程）。

    推送时机规则（用户确认）：仅当任务的出报日期为「今天」才推送——
    无出报日期或出报日期在未来/过去均不在此处推送（未来出报日期由每日推送在当天触发）。
    """
    from app.core.database import async_session_factory
    from app.modules.quality.repository import get_test_task

    # 重试等待：调用方事务可能尚未提交，稍等片刻再查任务
    task: QualityTestTask | None = None
    for _ in range(20):
        async with async_session_factory() as db:
            task = await get_test_task(db, uuid.UUID(task_id))
        if task:
            break
        await asyncio.sleep(0.5)
    if not task or not task.report_date:
        return
    if task.report_date != _today_str():
        return
    async with async_session_factory() as db:
        rows = await list_test_results(db, task.id)
    await push_task_reminder(task, rows)
