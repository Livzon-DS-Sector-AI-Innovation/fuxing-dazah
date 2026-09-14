"""AI 调用审计上下文 — contextvars 作用域（镜像 safety/ai_audit/context.py）。

业务入口（网关文本消息 / 识别管线）设置作用域，审计客户端读取场景与会话
定位信息写入审计行；识别管线内两次 LLM 调用以 ``resource`` 区分
（rotate_detect / receipt_parse），经 ``set_audit_resource`` 更新。
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class AuditContext:
    """一次业务动作的审计上下文（trace_id 贯穿 LLM 调用与工具调用审计）。"""

    scenario: str
    trace_id: str
    resource: str | None = None
    session_id: str | None = None
    draft_id: str | None = None
    chat_id: str | None = None
    user_open_id: str | None = None
    channel: str = "feishu"


_current: contextvars.ContextVar[AuditContext | None] = contextvars.ContextVar(
    "warehouse_ai_audit_context", default=None
)


@contextmanager
def warehouse_audit_scope(
    scenario: str,
    *,
    resource: str | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    draft_id: str | None = None,
    chat_id: str | None = None,
    user_open_id: str | None = None,
    channel: str = "feishu",
) -> Iterator[AuditContext]:
    """设置审计作用域（入口包一层；scope 内所有 LLM 调用共享 trace_id）。"""
    ctx = AuditContext(
        scenario=scenario,
        trace_id=trace_id or str(uuid.uuid4()),
        resource=resource,
        session_id=session_id,
        draft_id=draft_id,
        chat_id=chat_id,
        user_open_id=user_open_id,
        channel=channel,
    )
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def current_audit_context() -> AuditContext | None:
    """当前审计上下文；无作用域时返回 None（如单元测试直接调用）。"""
    return _current.get()


def set_audit_resource(resource: str) -> None:
    """更新当前作用域的 resource（识别管线内区分两次调用）；无作用域时静默忽略。"""
    ctx = _current.get()
    if ctx is not None:
        ctx.resource = resource


__all__ = [
    "AuditContext",
    "current_audit_context",
    "set_audit_resource",
    "warehouse_audit_scope",
]
