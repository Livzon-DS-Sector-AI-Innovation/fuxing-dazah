"""A4-b 严格模式 + 带错误反馈修复重试（ticket 04）。

接缝：`AIHazardIdentifier.identify`（fake AI service，参考 test_plugin.MockAIService）。

验收语义：
- 严格模式下规则校验失败 → 把 `validation.errors` 回灌 AI 重试一次；
  重解析 → auto_correct → 再校验，仍失败才抛 `IdentificationError`（消息含错误）；
- 重试只发生一次，且仅针对「JSON 已解析但规则不通过」；
- JSON 解析失败不追加规则重试（解析重试由客户端/上一层负责）；
- 非严格模式行为保持不变（不重试、不抛）。
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.modules.safety.ai_audit.context import ai_audit_scope, current_audit_ctx
from app.modules.safety.ai_hazard_identification.plugin import (
    AIHazardIdentifier,
    IdentificationError,
)
from app.modules.safety.ai_hazard_identification.schemas import (
    HazardIdentificationInput,
    PluginConfig,
)
from app.platform.integrations.ai.client import AIOutputError

# ═══════════════════════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════════════════════

VALID_BASIS = (
    "《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准》第十条："
    "爆炸危险场所未按国家标准安装使用防爆电气设备；GB 3836.1-2010 第15章"
)

VALID_OUTPUT: dict[str, Any] = {
    "key_defect": "防爆电箱接线口未用堵头封堵，箱内积尘严重，存在爆炸风险",
    "hazard_type": "unsafe_condition",
    "hazard_category": "instrument_electrical",
    "hazard_level": "major",
    "rectification_suggestion": {
        "corrective": "立即加装防爆堵头，使用吸尘器清理箱内积尘，一周内排查全区域所有防爆电箱确保封堵完好",
        "preventive": "修订防爆设备巡检制度，将封堵检查纳入周检，建立防爆设备全生命周期台账",
    },
    "major_hazard_basis": VALID_BASIS,
    "defect_substance": "substantive",
    "defect_substance_reasoning": "电箱引入口未封堵可直接导致粉尘进入电箱引发短路或爆炸（1步物理必然），推断链短，属实质缺陷",
}

# 规则 error（无任何法规引用），但 JSON/字段结构完全合法 → 只应触发一次规则重试
INVALID_BASIS_OUTPUT: dict[str, Any] = {
    **VALID_OUTPUT,
    "major_hazard_basis": "现场检查发现该处隐患问题较为严重，需要立即安排人员进行整改处理并复查确认",
}


def make_input(**kwargs: Any) -> HazardIdentificationInput:
    kwargs.setdefault("description", "防爆电箱堵头缺失")
    kwargs.setdefault("department", "生产部")
    return HazardIdentificationInput(**kwargs)


def _current_audit_extra() -> dict[str, Any] | None:
    """读取当前审计上下文 extra（AI 调用瞬间的 A7 元数据）。"""
    ctx = current_audit_ctx()
    if ctx is None or ctx.extra is None:
        return None
    return dict(ctx.extra)


class FakeAIService:
    """按预设序列返回结果，并记录每次调用入参的 fake AI service。"""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = [copy.deepcopy(r) for r in responses]
        self.calls: list[dict[str, Any]] = []
        self.call_count = 0

    def _next(self) -> dict[str, Any]:
        index = min(self.call_count - 1, len(self._responses) - 1)
        return copy.deepcopy(self._responses[index])

    async def chat_parsed(
        self,
        messages: list[dict[str, Any]],
        expected_keys: list[str],
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.call_count += 1
        self.calls.append(
            {
                "kind": "text",
                "messages": copy.deepcopy(messages),
                "kwargs": kwargs,
                "audit_extra": _current_audit_extra(),
            }
        )
        return self._next()

    async def chat_vision_parsed(
        self,
        text_prompt: str,
        image_urls: list[str],
        expected_keys: list[str],
        temperature: float = 0.1,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.call_count += 1
        self.calls.append(
            {
                "kind": "vision",
                "text_prompt": text_prompt,
                "image_urls": list(image_urls),
                "kwargs": kwargs,
                "audit_extra": _current_audit_extra(),
            }
        )
        return self._next()


class RaisingAIService:
    """AI 调用直接抛指定异常（模拟平台客户端的 AIOutputError 等）。"""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.call_count = 0

    async def chat_parsed(
        self,
        messages: list[dict[str, Any]],
        expected_keys: list[str],
        temperature: float = 0.1,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.call_count += 1
        raise self._exc

    async def chat_vision_parsed(
        self,
        text_prompt: str,
        image_urls: list[str],
        expected_keys: list[str],
        temperature: float = 0.1,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.call_count += 1
        raise self._exc


def _last_user_content(call: dict[str, Any]) -> str:
    """取文本调用最后一条 user 消息内容（错误反馈回灌在这里）。"""
    messages = call["messages"]
    assert messages[-1]["role"] == "user"
    content = messages[-1]["content"]
    assert isinstance(content, str)
    return content


# ═══════════════════════════════════════════════════════════════════════════
# 1. 严格模式：校验失败 → 带错误反馈重试一次
# ═══════════════════════════════════════════════════════════════════════════


class TestStrictRetry:
    @pytest.mark.asyncio
    async def test_retry_once_with_feedback_then_success(self) -> None:
        ai = FakeAIService([INVALID_BASIS_OUTPUT, VALID_OUTPUT])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        output = await plugin.identify(make_input())

        assert ai.call_count == 2, "规则校验失败应恰好重试一次"
        assert output.major_hazard_basis == VALID_BASIS

        # 第二次调用把校验错误 + 「只输出 JSON」指令回灌给 AI
        feedback = _last_user_content(ai.calls[1])
        assert "判定依据" in feedback
        assert "法规" in feedback
        assert "只输出 JSON" in feedback

        # 第一次调用没有错误反馈（正常 prompt 消息结构）
        first_user = _last_user_content(ai.calls[0])
        assert "只输出 JSON" not in first_user

    @pytest.mark.asyncio
    async def test_raises_after_retry_also_fails(self) -> None:
        ai = FakeAIService([INVALID_BASIS_OUTPUT, INVALID_BASIS_OUTPUT])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        with pytest.raises(IdentificationError) as exc_info:
            await plugin.identify(make_input())

        assert ai.call_count == 2, "重试只允许一次，不得无限重试"
        message = str(exc_info.value)
        assert "判定依据" in message
        assert "法规" in message
        assert exc_info.value.category == "validation_failed"

    @pytest.mark.asyncio
    async def test_no_retry_when_validation_passes(self) -> None:
        ai = FakeAIService([VALID_OUTPUT])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        output = await plugin.identify(make_input())

        assert ai.call_count == 1
        assert output.major_hazard_basis == VALID_BASIS

    # ── 视觉路径（生产主路径）同样回灌反馈 ──

    @pytest.mark.asyncio
    async def test_vision_retry_with_feedback_then_success(self) -> None:
        ai = FakeAIService([INVALID_BASIS_OUTPUT, VALID_OUTPUT])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        output = await plugin.identify(
            make_input(defect_photos=["data:image/jpeg;base64,ZmFrZQ=="])
        )

        assert ai.call_count == 2
        assert output.major_hazard_basis == VALID_BASIS
        assert ai.calls[0]["kind"] == "vision"
        retry_prompt = ai.calls[1]["text_prompt"]
        assert "法规" in retry_prompt
        assert "只输出 JSON" in retry_prompt


# ═══════════════════════════════════════════════════════════════════════════
# 2. 重试边界：解析失败不叠加规则重试；非严格模式行为不变
# ═══════════════════════════════════════════════════════════════════════════


class TestRetryBoundaries:
    @pytest.mark.asyncio
    async def test_no_rule_retry_when_json_parse_fails(self) -> None:
        """JSON/schema 解析失败由客户端/上层负责，插件不做规则重试。"""
        ai = FakeAIService([{"key_defect": "短"}])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        with pytest.raises(IdentificationError) as exc_info:
            await plugin.identify(make_input())

        assert ai.call_count == 1, "解析失败不得触发规则重试"
        assert exc_info.value.category == "json_invalid"

    @pytest.mark.asyncio
    async def test_non_strict_mode_does_not_retry(self) -> None:
        ai = FakeAIService([INVALID_BASIS_OUTPUT, VALID_OUTPUT])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=False))

        output = await plugin.identify(make_input())

        assert ai.call_count == 1, "非严格模式保持原行为：不重试"
        assert output.major_hazard_basis == INVALID_BASIS_OUTPUT["major_hazard_basis"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. 字段级容错：key_defect 超 200 字截断，不整条失败（不触发规则重试）
# ═══════════════════════════════════════════════════════════════════════════


class TestKeyDefectTruncation:
    @pytest.mark.asyncio
    async def test_identify_truncates_key_defect_to_200(self) -> None:
        raw = {**VALID_OUTPUT, "key_defect": "防" * 250}
        ai = FakeAIService([raw])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        output = await plugin.identify(make_input())

        assert len(output.key_defect) == 200
        assert ai.call_count == 1, "字段级截断不应触发整条重试"


# ═══════════════════════════════════════════════════════════════════════════
# 4. A7 审计：每次 AI 调用带 attempt_no（1/2），保留外层 round_id 等 extra
# ═══════════════════════════════════════════════════════════════════════════


class TestAttemptNoAudit:
    """插件在每次 AI 调用时嵌套审计作用域写 attempt_no（A7）。"""

    OUTER_EXTRA = {
        "round_id": "20261105120000-abcd",
        "bitable_record_id": "rec-1",
    }

    @pytest.mark.asyncio
    async def test_attempt_no_on_first_call_and_feedback_retry(self) -> None:
        ai = FakeAIService([INVALID_BASIS_OUTPUT, VALID_OUTPUT])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        with ai_audit_scope(
            scenario="hazard_identification", extra=dict(self.OUTER_EXTRA)
        ):
            output = await plugin.identify(make_input())
            # 嵌套作用域退出后，外层 extra 不应被 attempt_no 污染
            outer_extra_after = current_audit_ctx().extra

        assert output.major_hazard_basis == VALID_BASIS
        assert ai.call_count == 2
        assert ai.calls[0]["audit_extra"] == {**self.OUTER_EXTRA, "attempt_no": 1}
        assert ai.calls[1]["audit_extra"] == {**self.OUTER_EXTRA, "attempt_no": 2}
        assert outer_extra_after == self.OUTER_EXTRA

    @pytest.mark.asyncio
    async def test_attempt_no_without_outer_audit_scope(self) -> None:
        """无外层审计上下文时也带 attempt_no，且退出后上下文复原。"""
        ai = FakeAIService([VALID_OUTPUT])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        await plugin.identify(make_input())

        assert ai.calls[0]["audit_extra"] == {"attempt_no": 1}
        assert current_audit_ctx() is None


# ═══════════════════════════════════════════════════════════════════════════
# 5. A5/A7 失败分类：IdentificationError.category（供上层 _categorize_failure）
# ═══════════════════════════════════════════════════════════════════════════


class TestIdentificationErrorCategory:
    """插件抛出异常自带结构化 category，上层失败治理无需依赖中文子串。"""

    def test_category_defaults_to_none_and_keeps_message(self) -> None:
        """向后兼容：原 `IdentificationError(message)` 调用不变。"""
        err = IdentificationError("AI 文本分析失败: boom")
        assert str(err) == "AI 文本分析失败: boom"
        assert err.args == ("AI 文本分析失败: boom",)
        assert err.category is None

    def test_explicit_category(self) -> None:
        err = IdentificationError("AI 输出解析失败", category="json_invalid")
        assert err.category == "json_invalid"
        assert str(err) == "AI 输出解析失败"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("with_photos", [False, True])
    async def test_ai_output_error_maps_to_json_invalid(
        self, with_photos: bool
    ) -> None:
        """AI 调用失败且 cause 为平台 AIOutputError → category=json_invalid。"""
        cause = AIOutputError("输出不是合法 JSON")
        ai = RaisingAIService(cause)
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        photos = ["data:image/jpeg;base64,ZmFrZQ=="] if with_photos else []
        with pytest.raises(IdentificationError) as exc_info:
            await plugin.identify(make_input(defect_photos=photos))

        err = exc_info.value
        assert err.category == "json_invalid"
        # 异常链保留 cause 供上层沿链分类/排查
        assert isinstance(err.__cause__, AIOutputError)
        assert ai.call_count == 1
