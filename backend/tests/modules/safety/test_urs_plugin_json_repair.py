"""URS Plugin — AI 输出畸形/截断 JSON 修复与重试。

背景（URS-20260918-003 实测）：deepseek-flash thinking 模式下，可见输出在
reasoning 字符串中途被 max_tokens 截断（finish_reason 未透出 length），
json.loads 失败 → 整单评估 failed。修复层做截断补齐/剥围栏/括号错配修复，
不可修复时重试一次 AI 调用。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.ai_urs_review.plugin import (
    URSPluginError,
    _chat_parsed,
    _repair_json_text,
)

# Step 1 风险画像的全部必需键
_PROFILE_KEYS = [
    "mechanical", "electrical", "data", "environmental", "chemical",
    "overall_risk_level", "confidence", "reasoning",
]


class _MalformedError(Exception):
    """模拟平台层 AIOutputError：携带 raw_response 属性。"""

    def __init__(self, raw: str):
        super().__init__("AI response is not valid JSON")
        self.raw_response = raw


class _FakeAIService:
    """脚本化 chat_parsed 行为：按 args 列表依次抛错/返回。"""

    def __init__(self, *args: Any):
        self._args = list(args)
        self.calls = 0

    async def chat_parsed(self, messages, expected_keys, temperature):  # noqa: ANN001
        self.calls += 1
        item = self._args[min(self.calls - 1, len(self._args) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


# ── _repair_json_text ──


def test_repair_truncated_json_real_shape() -> None:
    """截断在字符串中途 + 未闭合 `{`（真实故障形态）→ 补齐后可解析。"""
    raw = (
        '{\n  "mechanical": {\n    "level": "high",\n'
        '    "indicators": [\n      "360°旋转喷头",\n'
        '      "AGV舵轮全向移动及大量活动部件"\n    ],\n'
        '    "evidence": "存在大量运动、高压部件，机械风险明确为高。"\n  },\n'
        '  "overall_risk_level": "high",\n  "confidence": 0.7,\n'
        '  "reasoning": "设备为移动式高压罐体清洗机，具备360°旋转喷头、AGV移动、'
        "100Mpa高压水路及卷簧储能机构，机械风险明确为高；使用碱性清洗剂并产生噪音与清洗废水，环境与"
    )
    obj = _repair_json_text(raw)
    assert obj is not None
    assert obj["overall_risk_level"] == "high"
    assert obj["confidence"] == 0.7
    assert obj["mechanical"]["indicators"] == ["360°旋转喷头", "AGV舵轮全向移动及大量活动部件"]
    assert obj["reasoning"].startswith("设备为移动式高压罐体清洗机")


def test_repair_paren_closes_array() -> None:
    """`)` 误闭合 `[` 数组 → 改写为 `]`。"""
    raw = '{"items": [{"item_no": "S1", "level": "high")]}'
    obj = _repair_json_text(raw)
    assert obj is not None
    assert obj["items"][0]["item_no"] == "S1"


def test_repair_keeps_full_width_text_parens() -> None:
    """字符串内部的全角/成对 ASCII 括号属正常文本，不受影响。"""
    raw = '{"reasoning": "扬程165m（防憋压过载）、软管(耐压100Mpa)", "confidence": 0.9}'
    obj = _repair_json_text(raw)
    assert obj is not None
    assert obj["confidence"] == 0.9


def test_repair_strips_code_fence() -> None:
    raw = '```json\n{"score": 40.0, "grade": "D"}\n```'
    obj = _repair_json_text(raw)
    assert obj is not None
    assert obj["grade"] == "D"


def test_repair_unparseable_returns_none() -> None:
    assert _repair_json_text("这不是 JSON 输出") is None
    assert _repair_json_text("") is None


# ── _chat_parsed 修复/重试编排 ──


async def test_chat_parsed_local_repair_avoids_retry() -> None:
    """raw 可修复且键齐全 → 只调用一次 AI，直接返回修复结果。"""
    truncated = '{"mechanical": {"level": "high"}, "confidence": 0.7, "reasoning": "被截断的推理'
    svc = _FakeAIService(_MalformedError(truncated))
    out = await _chat_parsed(svc, "sys", "user", ["mechanical", "confidence", "reasoning"])
    assert svc.calls == 1
    assert out["mechanical"]["level"] == "high"


async def test_chat_parsed_retry_once_on_unrepairable() -> None:
    """raw 不可修复 → 重试一次，重试成功则返回。"""
    svc = _FakeAIService(_MalformedError("not json at all"), {"ok": 1})
    out = await _chat_parsed(svc, "sys", "user", ["ok"])
    assert svc.calls == 2
    assert out == {"ok": 1}


async def test_chat_parsed_both_fail_raises_plugin_error() -> None:
    """两次都失败 → URSPluginError，错误信息不泄露 raw 全文。"""
    long_raw = "x" * 2000
    svc = _FakeAIService(_MalformedError(long_raw))
    with pytest.raises(URSPluginError, match="AI 调用失败"):
        await _chat_parsed(svc, "sys", "user", _PROFILE_KEYS)
    assert svc.calls == 2


async def test_chat_parsed_success_path_single_call() -> None:
    svc = _FakeAIService({"mechanical": {"level": "low"}, "confidence": 0.9})
    out = await _chat_parsed(svc, "sys", "user", ["mechanical", "confidence"])
    assert svc.calls == 1
    assert out["confidence"] == 0.9
