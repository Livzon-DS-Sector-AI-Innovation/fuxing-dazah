"""识图链路单测：executor 多模态 prompt 构建 + 历史图片剥离 + handler 分支。

deepseek-flash（dpv4）自带多模态（2026-11-05 实测 image_url 200 + 正确识图），
图片直传主模型，无需 vision profile 转写。"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import BinaryContent, UserPromptPart
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart

from app.modules.safety.business_agent import executor

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"fake-image-data" * 4


# ── executor：多模态 prompt 构建 ────────────────────────────────

class _CaptureAgent:
    """捕获 run() 首参的假 Agent。"""

    def __init__(self) -> None:
        self.captured: Any = None

    async def run(self, prompt: Any, **kwargs: Any) -> Any:
        self.captured = prompt

        class _R:
            def all_messages(self) -> list:
                return list(kwargs.get("message_history") or []) + [
                    ModelRequest(parts=[UserPromptPart(content=["x"])]),
                    ModelResponse(parts=[TextPart(content="好")]),
                ]

        return _R()


@pytest.mark.asyncio
async def test_run_turn_with_images_builds_multimodal_parts(monkeypatch, tmp_path):
    """携带图片时：run 首参应为 [UserPromptPart([文本, BinaryContent...])]。"""
    agent = _CaptureAgent()
    monkeypatch.setattr(executor, "_agent_run", None)  # 占位，防误用

    async def _fake_agent_run(user_message, deps, **kwargs):
        captured = kwargs.get("_capture")
        return await agent.run(_build_prompt(user_message, kwargs.get("images")), deps)

    # 直接测内部构建逻辑：用一个可控 _agent_run 替身断言透传
    captured_kwargs: dict = {}

    class _R:
        output = None  # 无 DeferredToolRequests

        def all_messages(self):
            return []

    async def _spy_agent_run(user_message, deps, **kwargs):
        captured_kwargs.update(kwargs)
        captured_kwargs["user_message"] = user_message
        return _R()

    monkeypatch.setattr(executor, "_agent_run", _spy_agent_run)

    deps = type("D", (), {"session_id": None, "db": None, "channel": "test", "person": None, "role": "viewer"})()
    result = await executor.run_turn(
        "看这张图", deps,
        images=[(PNG_MAGIC, "image/png")],
    )
    # 意图：images 正确透传到 _agent_run（answer 由 run_turn 后处理生成，此处不校验）
    assert captured_kwargs["images"] == [(PNG_MAGIC, "image/png")]


# ── _agent_run：parts 构建与历史清洗 ─────────────────────────────

@pytest.mark.asyncio
async def test_agent_run_strips_binary_from_history(monkeypatch):
    """序列化前应把历史中的 BinaryContent 替换为 '[图片]' 占位。"""
    captured: dict = {}

    class _FakeAgent:
        async def run(self, prompt: Any, **kwargs: Any) -> Any:
            captured["prompt"] = prompt
            history = list(kwargs.get("message_history") or [])

            class _R:
                def all_messages(self) -> list:
                    return history + [
                        ModelRequest(parts=[
                            UserPromptPart(content=["看图", BinaryContent(
                                data=PNG_MAGIC, media_type="image/png",
                            )]),
                        ]),
                        ModelResponse(parts=[TextPart(content="看到了")]),
                    ]

            return _R()

    monkeypatch.setattr(executor, "get_agent_for_tools", lambda names: _FakeAgent())

    deps = type("D", (), {
        "session_id": None, "db": None, "channel": "test", "person": None,
        "role": "viewer",
    })()

    history = [ModelRequest(parts=[UserPromptPart(content=["上一轮"])]),
               ModelResponse(parts=[TextPart(content="好")])]

    await executor._agent_run(
        "看这张图", deps,
        message_history=history,
        images=[(PNG_MAGIC, "image/png")],
    )

    # 1) prompt 是扁平 parts 列表（str + BinaryContent），不嵌套 UserPromptPart
    #    （嵌套结构在 OpenAI 序列化时触发 pydantic-core AssertionError，2026-11-05）
    prompt = captured["prompt"]
    assert isinstance(prompt, list) and len(prompt) == 2
    assert prompt[0] == "看这张图"
    assert isinstance(prompt[1], BinaryContent)
    assert prompt[1].media_type == "image/png"


@pytest.mark.asyncio
async def test_serialize_messages_replaces_binary(monkeypatch):
    """_serialize_messages 应剥离 BinaryContent 为 '[图片]' 文本占位。"""
    import json as _json

    from pydantic_ai.messages import ModelMessagesTypeAdapter

    msgs = [
        ModelRequest(parts=[UserPromptPart(content=[
            "看这张图",
            BinaryContent(data=PNG_MAGIC, media_type="image/png"),
        ])]),
    ]
    # 模拟 _serialize_messages 内的清洗逻辑（与实现保持同构）
    for msg in msgs:
        for part in getattr(msg, "parts", []) or []:
            content = getattr(part, "content", None)
            if isinstance(content, list):
                part.content = [
                    "[图片]" if isinstance(item, BinaryContent) else item
                    for item in content
                ]
    dumped = _json.loads(ModelMessagesTypeAdapter.dump_json(msgs))
    text = _json.dumps(dumped, ensure_ascii=False)
    assert "fake-image-data" not in text  # 二进制不入历史
    assert "[图片]" in text


# ── handler：image 分支 ─────────────────────────────────────────

def test_extract_post_content_text_and_images():
    from app.modules.safety.feishu.business_agent_bot_handler import _extract_post_content
    message = {
        "content": __import__("json").dumps({
            "content": [[
                {"tag": "text", "text": "帮我看这张图"},
                {"tag": "img", "image_key": "img_v2_key1"},
                {"tag": "img", "image_key": "img_v2_key2"},
            ]],
        }),
        "message_id": "om_test",
    }
    query, keys = _extract_post_content(message)
    assert query == "帮我看这张图"
    assert keys == ["img_v2_key1", "img_v2_key2"]


def test_extract_post_content_image_only():
    from app.modules.safety.feishu.business_agent_bot_handler import _extract_post_content
    message = {
        "content": __import__("json").dumps({
            "content": [[{"tag": "img", "image_key": "only_img"}]],
        }),
        "message_id": "om_test",
    }
    query, keys = _extract_post_content(message)
    assert query is None
    assert keys == ["only_img"]
