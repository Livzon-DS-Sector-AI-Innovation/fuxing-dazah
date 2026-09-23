"""S1 冒烟测试：真发一条卡片到测试群（双门槛，2026-09-23 收紧）。

需同时满足：WAREHOUSE_TEST_CHAT_ID 已配置 + WAREHOUSE_ALLOW_REAL_SEND_TESTS=1
（显式真发开关——日常全量回归不再向群里发冒烟卡，2026-09-23 用户要求取消）。
显式真发：WAREHOUSE_ALLOW_REAL_SEND_TESTS=1 pytest tests/modules/warehouse/test_live_smoke.py -v
"""

import os

import pytest

from app.core.config import get_settings
from app.modules.warehouse.feishu import notification


def _target_chat_id() -> str | None:
    return get_settings().WAREHOUSE_TEST_CHAT_ID or None


def _real_send_allowed() -> bool:
    return os.getenv("WAREHOUSE_ALLOW_REAL_SEND_TESTS", "") == "1"


@pytest.mark.skipif(
    not _target_chat_id() or not _real_send_allowed(),
    reason="真发冒烟默认关闭：需 WAREHOUSE_TEST_CHAT_ID 且 WAREHOUSE_ALLOW_REAL_SEND_TESTS=1",
)
async def test_send_card_to_test_chat_smoke() -> None:
    card = {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": "🧪 仓储助手卡片冒烟"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": "**S1 冒烟测试**\n仓库管理机器人消息链路真发验证（JSON 2.0 卡片），收到请忽略。",
                },
            ]
        },
    }
    message_id = await notification.send_card(_target_chat_id(), card)
    assert message_id and message_id != "dry_run"
