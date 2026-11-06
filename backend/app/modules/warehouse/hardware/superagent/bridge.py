"""warehouse 侧 superagent 桥 —— kind/executor 注册（幂等；进程启动一次）。

register_hardware_tasks 一并挂载（main.py 既有调用点，不加新入口）；
Policy 组合播种的会合点在 safety 桥（ensure_guardian_r2_policy 追加
hardware_alert_rules，R1+R2+HW 三组合——防互相升版挤规则）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_hardware_superagent() -> None:
    """注册五金库事件源 kind + 三执行器（重复调用幂等）。"""
    from app.platform.superagent.executors import get_executor, register_executor
    from app.platform.superagent.sources import source_registry

    if source_registry.get("hardware_alert_scan") is None:
        from app.modules.warehouse.hardware.superagent.scan_source import (
            HardwareAlertScanSource,
        )

        source_registry.register(HardwareAlertScanSource())

    from app.modules.warehouse.hardware.superagent.executors import (
        hardware_digest_push,
        hardware_plan_draft,
        hardware_urge,
    )

    for name, fn in (
        ("hardware_urge", hardware_urge),
        ("hardware_digest_push", hardware_digest_push),
        ("hardware_plan_draft", hardware_plan_draft),
    ):
        if get_executor(name) is None:
            register_executor(name, fn)

    # 仓储凭证卡片通道：feishu_card 全局 sender 走 safety 应用，但五金催办
    # 群（WAREHOUSE_HARDWARE_ALERT_CHAT_ID/WAREHOUSE_TEST_CHAT_ID）只有仓储
    # 机器人在群（2026-11-06 启用验证实测 230002 Bot NOT in chat）——独立
    # 通道类型走仓储凭证发送。
    from app.platform.superagent.effects import register_outbox_sender

    async def _warehouse_card_sender(channel: dict, body: dict) -> bool:
        from app.modules.warehouse.feishu.notification import send_card_to_target

        card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": str(body.get("title") or "五金库通知")},
                "template": "red",
            },
            "body": {
                "elements": [
                    {"tag": "markdown", "content": str(body.get("content") or "")}
                ]
            },
        }
        try:
            mid = await send_card_to_target(str(channel.get("chat_id") or ""), card)
            return bool(mid)
        except Exception:
            logger.exception("warehouse_feishu_card 发送失败: chat=%s", channel.get("chat_id"))
            return False

    try:
        register_outbox_sender("warehouse_feishu_card", _warehouse_card_sender)
    except ValueError:
        pass  # 已注册（进程内幂等；reload 换血后重注册）
    logger.info("五金库 superagent 桥已注册（hardware_alert_scan + 3 executors）")
