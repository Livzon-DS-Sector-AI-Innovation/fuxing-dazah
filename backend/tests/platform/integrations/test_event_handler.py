"""event_handler 注册制分发测试。

验证平台层只做「注册 + 分发」，不再内含业务逻辑：
- 卡片回调按 action 分发，透传 payload 与 user_id
- bitable 事件广播给所有已注册 handler
- 未注册安全忽略，重复注册报错，单个 handler 异常不阻断其他
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from app.platform.integrations.feishu import event_handler


@pytest.fixture
def clean_card_handlers() -> Iterator[None]:
    """测试间隔离模块级注册表，避免注册泄漏到其他用例。"""
    snapshot = dict(event_handler._CARD_ACTION_HANDLERS)
    event_handler._CARD_ACTION_HANDLERS.clear()
    yield
    event_handler._CARD_ACTION_HANDLERS.clear()
    event_handler._CARD_ACTION_HANDLERS.update(snapshot)


@pytest.fixture
def clean_bitable_handlers() -> Iterator[None]:
    """测试间隔离 bitable 广播注册表。"""
    snapshot = list(event_handler._BITABLE_RECORD_HANDLERS)
    event_handler._BITABLE_RECORD_HANDLERS.clear()
    yield
    event_handler._BITABLE_RECORD_HANDLERS.clear()
    event_handler._BITABLE_RECORD_HANDLERS.extend(snapshot)


async def test_dispatch_calls_registered_handler(clean_card_handlers: Iterator[None]) -> None:
    """注册的 action 被分发，handler 收到原始 payload 与 user_id。"""
    handler = AsyncMock()
    event_handler.register_card_action_handler("approve", handler)
    payload = {"action": "approve", "work_order_id": "wo-1"}

    await event_handler._handle_card_action_async(
        action_value=payload, user_id="user-1",
    )

    handler.assert_awaited_once_with(payload, "user-1")


async def test_unregistered_action_is_ignored(clean_card_handlers: Iterator[None]) -> None:
    """未注册的 action 不抛异常、不调用任何 handler。"""
    await event_handler._handle_card_action_async(
        action_value={"action": "unknown-action"}, user_id="user-1",
    )


async def test_duplicate_registration_raises(clean_card_handlers: Iterator[None]) -> None:
    """同一 action 重复注册报错，防止静默覆盖已注册 handler。"""
    handler = AsyncMock()
    event_handler.register_card_action_handler("approve", handler)

    with pytest.raises(ValueError):
        event_handler.register_card_action_handler("approve", handler)


# ═══════════════════════════════════════════════════════════════
# bitable 事件 — 广播注册制
# ═══════════════════════════════════════════════════════════════


async def test_bitable_dispatch_calls_registered_handler(
    clean_bitable_handlers: Iterator[None],
) -> None:
    """注册的 bitable handler 收到 file_token/table_id/action_list。"""
    handler = AsyncMock()
    event_handler.register_bitable_record_handler(handler)
    action_list = [{"action": "record_added", "record_id": "rec-1"}]

    await event_handler._handle_bitable_record_changed_async(
        file_token="app1", table_id="tbl1", action_list=action_list,
    )

    handler.assert_awaited_once_with("app1", "tbl1", action_list)


async def test_bitable_dispatch_broadcasts_to_all_handlers(
    clean_bitable_handlers: Iterator[None],
) -> None:
    """bitable 事件广播给所有已注册 handler（多模块场景）。"""
    first = AsyncMock()
    second = AsyncMock()
    event_handler.register_bitable_record_handler(first)
    event_handler.register_bitable_record_handler(second)

    await event_handler._handle_bitable_record_changed_async(
        file_token="app1", table_id="tbl1", action_list=[],
    )

    first.assert_awaited_once()
    second.assert_awaited_once()


async def test_bitable_unregistered_is_ignored(clean_bitable_handlers: Iterator[None]) -> None:
    """无注册 handler 时事件被安全忽略。"""
    await event_handler._handle_bitable_record_changed_async(
        file_token="app1", table_id="tbl1", action_list=[],
    )


async def test_bitable_duplicate_registration_raises(
    clean_bitable_handlers: Iterator[None],
) -> None:
    """同一 handler 重复注册报错，防止事件被重复处理。"""
    handler = AsyncMock()
    event_handler.register_bitable_record_handler(handler)

    with pytest.raises(ValueError):
        event_handler.register_bitable_record_handler(handler)


async def test_bitable_handler_exception_does_not_block_others(
    clean_bitable_handlers: Iterator[None],
) -> None:
    """单个 handler 异常不影响其他 handler 收到事件。"""
    broken = AsyncMock(side_effect=RuntimeError("boom"))
    healthy = AsyncMock()
    event_handler.register_bitable_record_handler(broken)
    event_handler.register_bitable_record_handler(healthy)

    await event_handler._handle_bitable_record_changed_async(
        file_token="app1", table_id="tbl1", action_list=[],
    )

    healthy.assert_awaited_once()
