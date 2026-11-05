"""A2 视觉 json mode 灰度开关（测试接缝 S1）。

覆盖：
    - registry 注册了 `SAFETY_AI_VISION_JSON_MODE_ENABLED`，默认 False；
    - 开关关：请求体不带 response_format；
    - 开关开：请求体带 `{"type":"json_object"}`；
    - 开关开 + 端点 400：自动去参重试一次并成功，审计 extra 标 fallback；
    - 开关开 + 两次 400：按失败路径抛错并写 failed 审计；
    - 环境变量可热切换（app_config env > DB > default）。

无真实网络/DB：httpx.MockTransport + fake `_write_audit`。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.modules.safety.ai_audit import audited_client
from app.modules.safety.ai_audit.audited_client import AuditedAIService
from app.modules.safety.ai_audit.context import ai_audit_scope
from app.modules.safety.app_config import registry

BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"
KEY = "SAFETY_AI_VISION_JSON_MODE_ENABLED"


def _make_service(
    handler: Callable[[httpx.Request], httpx.Response]
) -> AuditedAIService:
    service = AuditedAIService(api_key="test", base_url=BASE_URL, model=MODEL)
    service._client = httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    )
    return service


def _completion(content: str = '{"a": 1}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


class _Recorder:
    """记录请求体 + 审计写入 kwarg（外部副作用边界观察）。"""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.bodies: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        if not self.responses:
            raise AssertionError("HTTP 请求次数超出预期")
        return self.responses.pop(0)

    async def write_audit(self, **kwargs: object) -> None:  # noqa: ANN003
        self.audits.append(dict(kwargs))


def test_registry_registers_key_default_off() -> None:
    item = registry.get_item(KEY)
    assert item.type == "bool"
    assert item.default is False
    assert item.restart_required is False


def test_flag_reads_env_hot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY, raising=False)
    assert audited_client._vision_json_mode_enabled() is False
    monkeypatch.setenv(KEY, "true")
    assert audited_client._vision_json_mode_enabled() is True


async def test_flag_off_body_has_no_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(KEY, raising=False)
    recorder = _Recorder([_completion()])
    monkeypatch.setattr(audited_client, "_write_audit", recorder.write_audit)
    service = _make_service(recorder)
    try:
        with ai_audit_scope(scenario="hazard_identification"):
            text = await service.chat_vision("识别", [])
    finally:
        await service.close()

    assert text == '{"a": 1}'
    assert "response_format" not in recorder.bodies[0]
    assert recorder.audits[0]["audit_extra"]["vision_json_mode"] is False


async def test_flag_on_body_has_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(KEY, "true")
    recorder = _Recorder([_completion()])
    monkeypatch.setattr(audited_client, "_write_audit", recorder.write_audit)
    service = _make_service(recorder)
    try:
        with ai_audit_scope(scenario="hazard_identification"):
            await service.chat_vision("识别", [])
    finally:
        await service.close()

    assert recorder.bodies[0]["response_format"] == {"type": "json_object"}
    assert recorder.audits[0]["audit_extra"]["vision_json_mode"] is True
    assert recorder.audits[0]["audit_extra"]["vision_json_mode_fallback"] is False


async def test_flag_on_400_falls_back_without_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(KEY, "true")
    recorder = _Recorder(
        [
            httpx.Response(400, json={"error": "response_format unsupported"}),
            _completion(),
        ]
    )
    monkeypatch.setattr(audited_client, "_write_audit", recorder.write_audit)
    service = _make_service(recorder)
    try:
        with ai_audit_scope(scenario="hazard_identification"):
            text = await service.chat_vision("识别", [])
    finally:
        await service.close()

    assert text == '{"a": 1}'
    assert len(recorder.bodies) == 2
    assert recorder.bodies[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in recorder.bodies[1]
    assert recorder.audits[-1]["status"] == "success"
    extra = recorder.audits[-1]["audit_extra"]
    assert extra["vision_json_mode_fallback"] is True


async def test_flag_on_400_twice_raises_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(KEY, "true")
    recorder = _Recorder(
        [
            httpx.Response(400, json={"error": "unsupported"}),
            httpx.Response(400, json={"error": "unsupported"}),
        ]
    )
    monkeypatch.setattr(audited_client, "_write_audit", recorder.write_audit)
    service = _make_service(recorder)
    try:
        with ai_audit_scope(scenario="hazard_identification"):
            with pytest.raises(httpx.HTTPStatusError):
                await service.chat_vision("识别", [])
    finally:
        await service.close()

    assert len(recorder.bodies) == 2
    assert recorder.audits[-1]["status"] == "failed"
    assert recorder.audits[-1]["audit_extra"]["vision_json_mode_fallback"] is True


async def test_flag_on_unrelated_400_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """400 原因不是 response_format（如图片超限）→ 不白烧一次调用，直接失败。"""
    monkeypatch.setenv(KEY, "true")
    recorder = _Recorder([httpx.Response(400, json={"error": "image too large"})])
    monkeypatch.setattr(audited_client, "_write_audit", recorder.write_audit)
    service = _make_service(recorder)
    try:
        with ai_audit_scope(scenario="hazard_identification"):
            with pytest.raises(httpx.HTTPStatusError):
                await service.chat_vision("识别", [])
    finally:
        await service.close()

    assert len(recorder.bodies) == 1
    assert recorder.audits[-1]["status"] == "failed"
    assert recorder.audits[-1]["audit_extra"]["vision_json_mode_fallback"] is False
