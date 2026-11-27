"""报告单审核环节推送：COA 生成待初审提醒、审核结果通知（退回需统计员行动）。

事件即时推（端点 fire-and-forget，沿用 spawn_background 模式）+ 早报汇总入口
（daily_push 早报块见 _push_today_tasks），目标群均为 QUALITY_FEISHU_CHAT_IDS。
"""

import logging

logger = logging.getLogger(__name__)


def _report_page_link() -> str:
    """审核工作台链接（报告单页带待初审筛选，同看板卡片直达口径）。"""
    from app.core.config import get_settings

    base = (get_settings().FRONTEND_URL or "http://localhost:3000").rstrip("/")
    return f"{base}/quality/report?audit_status=pending"


async def push_reports_generated(
    product_name: str,
    batch_number: str,
    serial_nos: list[str],
    file_nos: list[str] | None = None,
) -> None:
    """COA 生成后即时提醒审核员进系统初审（出报低频事件，逐次推送不吵）。"""
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    serial_label = "、".join(s for s in serial_nos if s) or "—"
    file_label = f"（标准文件 {'、'.join(file_nos)}）" if file_nos else ""
    text = (
        f"新 COA 已生成，待初审：{product_name} 批号 {batch_number}{file_label}\n"
        f"流水号：{serial_label}\n"
        f"审核工作台：{_report_page_link()}"
    )
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            logger.exception("报告单生成待初审提醒发送失败: %s", chat_id)


async def push_audit_result(
    product_name: str,
    batch_number: str,
    serial_no: str | None,
    approved: bool,
    auditor_name: str,
    comment: str | None = None,
) -> None:
    """审核结果通知：退回=统计员需重新出报（核心），通过=知会留痕。"""
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    serial = serial_no or "—"
    if approved:
        text = (
            f"报告单审核通过：{product_name} 批号 {batch_number}（流水号 {serial}）\n"
            f"审核人：{auditor_name}"
        )
    else:
        text = (
            f"报告单已退回：{product_name} 批号 {batch_number}（流水号 {serial}）\n"
            f"退回原因：{comment or '（未填写）'}\n"
            f"审核人：{auditor_name}\n"
            "请统计员核对原始记录后重新出报"
        )
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            logger.exception("报告单审核结果通知发送失败: %s", chat_id)
