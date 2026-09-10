"""隐患直读模式 — 失败告警（推送管理员）。

复用调度器的管理员常量（许康福），避免两处维护同一 open_id。
告警失败只记日志，绝不阻塞业务流程。
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def notify_admin(title: str, content: str) -> bool:
    """向管理员发飞书卡片。返回是否发送成功（失败不抛异常）。"""
    try:
        # 延迟导入：scheduler 在函数内导入 service 模块，避免循环依赖
        from app.modules.safety.feishu.notification import send_user_card
        from app.modules.safety.scheduler import ALERT_NOTIFY_OPEN_ID

        ok = await send_user_card(
            open_id=ALERT_NOTIFY_OPEN_ID,
            title=title,
            content=content,
        )
        if not ok:
            logger.warning("管理员告警发送失败(返回False): %s", title)
        return bool(ok)
    except Exception:
        logger.exception("管理员告警发送异常: %s", title)
        return False


async def notify_failures(
    job_label: str,
    *,
    failures: list[dict[str, str]],
    total: int,
    error: str = "",
) -> bool:
    """推送「单轮失败条数超阈值」告警。

    Args:
        job_label: 任务名（如「隐患AI分析轮询」）。
        failures: [{"record_id": ..., "reason": ...}] 失败明细。
        total: 本轮处理的记录总数。
        error: 可选的异常摘要。
    """
    lines = [
        f"**{job_label}** 本轮处理 **{total}** 条，失败 **{len(failures)}** 条",
        f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if error:
        lines.append(f"错误摘要：{error}")
    if failures:
        lines.append("")
        lines.append("失败明细（最多 10 条）：")
        for item in failures[:10]:
            lines.append(f"• `{item.get('record_id', '')}` {item.get('reason', '')}")
    return await notify_admin("⚠️ 隐患直读轮询失败告警", "\n".join(lines))


async def notify_rounds_exceeded(job_label: str, rounds: int, error: str = "") -> bool:
    """推送「连续失败轮数超阈值」告警。"""
    content = (
        f"**{job_label}** 已连续失败 **{rounds}** 轮\n"
        f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    if error:
        content += f"\n最后一次错误：{error}"
    return await notify_admin("⚠️ 隐患直读轮询连续失败告警", content)
