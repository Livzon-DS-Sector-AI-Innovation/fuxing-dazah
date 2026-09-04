"""S1 冒烟测试：WAREHOUSE_TEST_CHAT_ID 配置后真发一条卡片到测试群。

真实业务群勿配此键；未配置时整文件 skip（live+发送 dry-run 策略的人工补充项）。
运行：DATABASE_URL=... uv run pytest tests/modules/warehouse/test_live_smoke.py -v
"""

import pytest

from app.core.config import get_settings
from app.modules.warehouse.feishu import notification


def _target_chat_id() -> str | None:
    return get_settings().WAREHOUSE_TEST_CHAT_ID or None


@pytest.mark.skipif(not _target_chat_id(), reason="WAREHOUSE_TEST_CHAT_ID 未配置，跳过真发冒烟")
async def test_send_card_to_test_chat_smoke() -> None:
    card = {
        "config": {"update_multi": True},
        "elements": [
            {"tag": "markdown", "content": "**S1 冒烟测试**\n仓库管理机器人消息链路真发验证，收到请忽略。"},
        ],
    }
    message_id = await notification.send_card(_target_chat_id(), card)
    assert message_id and message_id != "dry_run"
