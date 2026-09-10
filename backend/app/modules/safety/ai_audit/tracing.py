"""OTel tracing 接入（Phoenix 观测层，二期）。

环境变量 ``SAFETY_PHOENIX_ENDPOINT``（如 ``http://localhost:6006``）存在时启用：
- 设置全局 TracerProvider + OTLP HTTP exporter（指向 Phoenix 的 /v1/traces）
- ``ai_audit_scope`` 会为每个业务操作开一个 ``safety.{scenario}`` 根 span，
  其 trace_id 即审计表 ``ai_call_audits.trace_id`` —— 两层贯通的关键
- ``AuditedAIService`` 为每次模型调用开 ``safety.ai.chat`` 子 span

未配置该变量时全部为 no-op（opentelemetry-api 的默认空实现，零开销），
一期行为完全不变（trace_id 回退 uuid4）。

不使用 HTTPXClientInstrumentor 等全局自动插桩 —— 避免给飞书等无关
HTTP 调用加 span 产生噪声；只在 AI 调用边界手动开 span。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

logger = logging.getLogger(__name__)

_initialized = False
_enabled = False


def setup_tracing() -> bool:
    """幂等初始化。返回 tracing 是否启用。

    在 ``create_ai_service()`` 与 ``business_agent/agent.py`` 两个入口
    均被调用（覆盖四套 AI 系统的全部加载路径）。
    """
    global _initialized, _enabled
    if _initialized:
        return _enabled
    _initialized = True

    endpoint = (os.getenv("SAFETY_PHOENIX_ENDPOINT") or "").strip().rstrip("/")
    if not endpoint:
        logger.debug("SAFETY_PHOENIX_ENDPOINT 未配置，tracing 保持关闭")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": "dazah-safety"})
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
        trace.set_tracer_provider(provider)
        _enabled = True
        logger.info("safety tracing 已启用 → %s/v1/traces", endpoint)
    except Exception:
        logger.exception("tracing 初始化失败，保持关闭（不影响业务）")
        _enabled = False
    return _enabled


def tracing_enabled() -> bool:
    return _enabled


def current_trace_id() -> str | None:
    """当前 OTel span 的 trace_id（32 位 hex），无有效 span 返回 None。"""
    try:
        from opentelemetry import trace

        span_ctx = trace.get_current_span().get_span_context()
        if span_ctx.is_valid:
            return format(span_ctx.trace_id, "032x")
    except Exception:  # noqa: BLE001 — tracing 永不影响业务
        pass
    return None


@contextmanager
def scenario_span(scenario: str) -> Iterator[None]:
    """业务操作级根 span（``safety.{scenario}``）；tracing 关闭时为 no-op。"""
    if not _enabled:
        with nullcontext():
            yield
        return
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("dazah.safety.ai_audit")
        cm = tracer.start_as_current_span(f"safety.{scenario}")
    except Exception:
        cm = nullcontext()
    with cm:
        yield


@contextmanager
def ai_call_span(model: str, scenario: str | None) -> Iterator[object | None]:
    """单次模型调用子 span；yield span 对象（no-op 时 yield None）。

    调用方可在成功后 set_attribute 记录 token 用量。

    注意：``except`` 只包住 span 构造期——若包住 ``yield span``，body 抛出的
    异常会被吞成 ``RuntimeError: generator didn't stop after throw()``
    （contextlib throw() 后 generator 又 yield），掩盖真实失败原因。
    """
    if not _enabled:
        yield None
        return
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("dazah.safety.ai_audit")
    except Exception:  # noqa: BLE001 — tracing 永不影响业务
        yield None
        return
    with tracer.start_as_current_span("safety.ai.chat") as span:
        try:
            span.set_attribute("gen_ai.request.model", model)
            if scenario:
                span.set_attribute("safety.scenario", scenario)
        except Exception:  # noqa: BLE001
            pass
        yield span
