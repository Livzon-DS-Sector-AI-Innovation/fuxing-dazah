"""回归测试：AuditedAIService 必须补齐平台层 AIService 缺失的实例属性/方法。

背景（2026-09-11 生产事故）：
    ``AuditedAIService.__init__`` 漏设 ``self.base_url``，而它被
    ``chat()`` / ``chat_vision()`` 在构造 thinking_policy 时**同步**读取
    （不在任何 try 内），于是每次 AI 调用都抛
    ``AttributeError: 'AuditedAIService' object has no attribute 'base_url'``，
    导致「 隐患AI分析轮询」每轮 2 条记录全失败、连续 3 轮后向管理员告警。
    同一处还漏了 ``_parse_json_response``（视觉解析用）。

这两个成员平台层父子契约里都没有，属于本类必须自己维护的部分，
因此用契约测试钉住，防止再次回归。
"""

from __future__ import annotations

import json

import httpx

from app.modules.safety.ai_audit import audited_client
from app.modules.safety.ai_audit.audited_client import AuditedAIService

BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"


async def _noop_write_audit(**kwargs) -> None:  # noqa: ANN003
    """替掉审计落库，保持测试不依赖数据库。"""
    return None


def _make_service(handler) -> AuditedAIService:  # noqa: ANN001
    service = AuditedAIService(api_key="test", base_url=BASE_URL, model=MODEL)
    service._client = httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(handler)
    )
    return service


async def test_base_url_is_exposed() -> None:
    """__init__ 必须从底层 httpx client 反推出 base_url（thinking_policy 依赖）。"""
    service = _make_service(lambda request: httpx.Response(200, json={}))
    try:
        assert service.base_url.rstrip("/") == BASE_URL
    finally:
        await service.close()


def test_parse_json_response_helper_exists_and_parses() -> None:
    """视觉路径的 _parse_json_response 必须存在且能解析带围栏的 JSON。"""
    parsed = AuditedAIService._parse_json_response(
        '```json\n{"a": 1, "flag": "true"}\n```', ["a", "flag"]
    )
    assert parsed == {"a": 1, "flag": True}


async def test_chat_does_not_raise_attribute_error(monkeypatch) -> None:  # noqa: ANN001
    """端到端：chat() 不能因缺 base_url 抛 AttributeError。

    修复前这里会直接抛 AttributeError（发生在发请求之前，连审计记录都没有），
    正是  轮询连续失败 3 轮告警的根因。
    """
    monkeypatch.setattr(audited_client, "_write_audit", _noop_write_audit)
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    service = _make_service(handler)
    try:
        text = await service.chat([{"role": "user", "content": "请返回 json"}])
    finally:
        await service.close()

    assert text == '{"ok": true}'
    assert captured["body"]["model"] == MODEL
    # DeepSeek 域名必须命中 thinking_policy 分支（修复前读 base_url 就在这里炸）
    assert "thinking" in captured["body"]


def test_round_failure_detail_carries_reason() -> None:
    """连续失败告警必须带上失败原因，避免只报「2 条失败」。"""
    from app.modules.safety.service.hazard_direct.ai_analysis import RoundResult
    from app.modules.safety.service.hazard_direct.loop import _round_failure_detail

    result = RoundResult(
        total=2,
        failed=2,
        failures=[
            {"record_id": "rec1", "reason": "AttributeError: no attribute 'base_url'"},
            {"record_id": "rec2", "reason": "TimeoutError: read timeout"},
        ],
    )
    detail = _round_failure_detail(result)
    assert detail.startswith("2 条失败")
    assert "rec1" in detail and "base_url" in detail
    assert _round_failure_detail(RoundResult()) == "0 条失败"
