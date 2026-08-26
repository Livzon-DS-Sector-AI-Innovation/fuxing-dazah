"""HR 职称评审飞书事件注册测试。

验证 HR 通过注册函数挂到平台 bitable 广播注册表，
平台层不再反向依赖 HR 模块。
"""

import app.modules.hr.title_review.bitable_handler as bh
from app.platform.integrations.feishu import event_handler


def test_register_feishu_callbacks_registers_handle_record_changed() -> None:
    """HR 注册函数把 handle_record_changed 挂到平台广播注册表。"""
    snapshot = list(event_handler._BITABLE_RECORD_HANDLERS)
    event_handler._BITABLE_RECORD_HANDLERS.clear()
    try:
        bh.register_feishu_callbacks()

        assert bh.handle_record_changed in event_handler._BITABLE_RECORD_HANDLERS
    finally:
        event_handler._BITABLE_RECORD_HANDLERS.clear()
        event_handler._BITABLE_RECORD_HANDLERS.extend(snapshot)
