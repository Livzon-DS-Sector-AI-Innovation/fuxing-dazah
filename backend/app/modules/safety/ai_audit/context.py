"""AI 调用审计上下文 — contextvars 传递业务语义。

业务入口用 ``ai_audit_scope(...)`` 设置场景/资源/用户等语义；
``AuditedAIService`` 落表时通过 ``current_audit_ctx()`` 读取。
未设置上下文的调用落 ``scenario="unknown"``（仍留痕，可事后补场景归因）。

检索层（SafetyKnowledgeRetriever）可回填 ``degradation_level`` / ``cited_sources``，
使审计记录能回答"这次回答引用了哪些法规、检索降级到了第几层"。
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace


@dataclass
class AIAuditContext:
    """一次业务操作的审计语义（同一操作内的多次 AI 调用共享 trace_id）。"""

    scenario: str = "unknown"
    trace_id: str = field(default_factory=lambda: _uuid.uuid4().hex)
    resource_type: str | None = None
    resource_id: _uuid.UUID | None = None
    session_id: str | None = None
    channel: str | None = None  # web / feishu / system
    user_id: _uuid.UUID | None = None
    user_name: str | None = None
    ip_address: str | None = None
    # 检索层回填（可变字段）
    degradation_level: str | None = None
    cited_sources: list[dict] | None = None
    extra: dict | None = None


_ctx: ContextVar[AIAuditContext | None] = ContextVar("safety_ai_audit_ctx", default=None)


def current_audit_ctx() -> AIAuditContext | None:
    """读取当前审计上下文（可能为 None）。"""
    return _ctx.get()


@contextmanager
def ai_audit_scope(**fields) -> Iterator[AIAuditContext]:
    """进入一个审计作用域。

    嵌套时以外层上下文为基础覆盖指定字段（trace_id 默认继承外层，
    保证同一业务操作的多次 AI 调用可按 trace_id 串联）。

    tracing 启用时（二期 Phoenix），最外层作用域会开一个
    ``safety.{scenario}`` OTel 根 span，并以其 trace_id 作为审计
    trace_id —— 审计表与 Phoenix 调用链由此贯通。

    用法::

        with ai_audit_scope(scenario="rectification_review",
                            resource_type="hazard", resource_id=hazard.id):
            await run_review(...)
    """
    from contextlib import ExitStack

    from app.modules.safety.ai_audit.tracing import (
        current_trace_id,
        scenario_span,
        tracing_enabled,
    )

    parent = _ctx.get()
    with ExitStack() as stack:
        if parent is not None:
            ctx = replace(parent, **fields)
        else:
            # 最外层作用域：tracing 启用时开业务操作根 span
            if tracing_enabled() and "trace_id" not in fields:
                stack.enter_context(
                    scenario_span(str(fields.get("scenario", "unknown")))
                )
                otel_trace_id = current_trace_id()
                if otel_trace_id:
                    fields["trace_id"] = otel_trace_id
            ctx = AIAuditContext(**fields)
        token = _ctx.set(ctx)
        try:
            yield ctx
        finally:
            _ctx.reset(token)


def fill_retrieval_info(
    degradation_level: str | None = None,
    cited_sources: list[dict] | None = None,
) -> None:
    """检索层回填降级级别与引用来源（无上下文时静默忽略）。"""
    ctx = _ctx.get()
    if ctx is None:
        return
    if degradation_level is not None:
        ctx.degradation_level = degradation_level
    if cited_sources is not None:
        ctx.cited_sources = cited_sources
