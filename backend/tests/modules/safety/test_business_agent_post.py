"""安全助手 post 富文本消息解析测试（2026-09-23 文图混合支持）。

_extract_post_query 纯函数：新老格式、@段跳过、纯图返回 None、
解析失败返回 None。路由接入（handle_message post 分支）的端到端
行为依赖飞书事件与 Agent 运行时，不在本文件覆盖。
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.safety.feishu.business_agent_bot_handler import _extract_post_query


def _message_of(content: Any) -> dict[str, Any]:
    return {
        "message_type": "post",
        "content": content if isinstance(content, str) else json.dumps(
            content, ensure_ascii=False
        ),
    }


class TestExtractPostQuery:
    def test_new_format_text_with_at_skipped(self) -> None:
        message = _message_of({
            "title": "",
            "content": [[
                {"tag": "at", "user_id": "ou_bot", "user_name": "安全助手"},
                {"tag": "text", "text": " 危化品储存有哪些法规要求"},
            ]],
        })
        assert _extract_post_query(message) == "危化品储存有哪些法规要求"

    def test_old_locale_format_with_title(self) -> None:
        message = _message_of({
            "zh_cn": {
                "title": "咨询",
                "content": [[{"tag": "text", "text": "第一条"}],
                            [{"tag": "text", "text": "第二条"}]],
            }
        })
        assert _extract_post_query(message) == "咨询\n第一条\n第二条"

    def test_image_only_returns_none(self) -> None:
        message = _message_of({
            "title": "",
            "content": [[
                {"tag": "text", "text": ""},
                {"tag": "img", "image_key": "img_v2_x"},
            ]],
        })
        assert _extract_post_query(message) is None

    def test_link_text_taken(self) -> None:
        message = _message_of({
            "title": "",
            "content": [[
                {"tag": "a", "text": "制度文档", "href": "https://example.com"},
            ]],
        })
        assert _extract_post_query(message) == "制度文档"

    def test_bad_json_returns_none(self) -> None:
        assert _extract_post_query(_message_of("不是 JSON")) is None

    def test_emotion_only_returns_none(self) -> None:
        message = _message_of({
            "title": "",
            "content": [[{"tag": "emotion", "emoji_type": "OK"}]],
        })
        assert _extract_post_query(message) is None
