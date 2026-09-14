"""AI 调用失败飞书通知（fire-and-forget，绝不阻塞业务）。"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _notify_failure(
    *, scenario: str, model: str, error: str, trace_id: str | None
) -> None:
    """发失败告警卡片到 system_alert 目标（env 兜底）；无目标则跳过。"""
    try:
        from app.modules.warehouse.feishu import notification
        from app.modules.warehouse.ops_config.scheduler_store import scheduler_store

        target = scheduler_store.get_alert_target()
        if not target:
            return  # 未配置告警目标：静默跳过
        lines = [
            "**仓库模块 AI 调用失败**",
            f"- 场景：{scenario}",
            f"- 模型：{model}",
            f"- 错误：{error[:200]}",
        ]
        if trace_id:
            lines.append(f"- trace_id：`{trace_id}`")
        card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "仓库 AI 告警"},
                "template": "red",
            },
            "body": {"elements": [{"tag": "markdown", "content": "\n".join(lines)}]},
        }
        await notification.send_card(target, card)
    except Exception:  # noqa: BLE001 — 通知失败只记日志
        logger.warning("AI 调用失败通知发送失败", exc_info=True)


def fire_notify_failure(
    *, scenario: str, model: str, error: str, trace_id: str | None = None
) -> None:
    """fire-and-forget 入口：在事件循环存在时投递，否则静默放弃。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        _notify_failure(scenario=scenario, model=model, error=error, trace_id=trace_id)
    )


__all__ = ["fire_notify_failure"]
