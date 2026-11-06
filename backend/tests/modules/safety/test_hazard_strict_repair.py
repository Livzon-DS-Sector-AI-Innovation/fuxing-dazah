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
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.ai_audit.context import ai_audit_scope, current_audit_ctx
from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
)
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
            _ctx = current_audit_ctx()
            outer_extra_after = _ctx.extra if _ctx is not None else None

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


# ═══════════════════════════════════════════════════════════════════════════
# 6. C2 识别侧引用强校验（S4）：插件注入证据 + 严格重试 + 失败分类
# ═══════════════════════════════════════════════════════════════════════════
#
# 口径（ticket 03 / spec §C2）：
# - 无证据（citation_evidence=None）→ 行为与现状完全一致，last_citation_report 恒为 None；
# - 有证据：首轮零可验证 → 带错误反馈（含不可验证引用摘要）重试一次 → 仍失败按
#   empty_basis / placeholder_basis / no_citation / invalid_citation / validation_failed 分类抛错；
# - 每次规则校验（首次/重试/成功/失败）后更新 last_citation_report。

CITATION_CHUNKS = [
    SimpleNamespace(
        chunk_id="ret-c1",
        source_doc="GB 30871-2022 化学品生产单位特殊作业安全规范",
        source_article="第5.2条",
        chunk_text="5.2 高处作业人员应正确佩戴符合国家标准的安全带，安全带应高挂低用。",
    ),
]
CITATION_EVIDENCE = CitationEvidence.from_chunks(CITATION_CHUNKS)

VERBATIM_BASIS = (
    "GB 30871-2022 第5.2条：'高处作业人员应正确佩戴符合国家标准的安全带，安全带应高挂低用'"
)
FABRICATED_BASIS = (
    "GB 99999-2024 第1.1条：'企业必须每年开展两次全员安全培训并考核'；"
    "《虚构的安全管理条例》第三条：'所有人员必须持证上岗'"
)
PARTIAL_BASIS = f"{VERBATIM_BASIS}；GB 99999-2024 第1.1条：'编造的条文内容'"
VARIANT_PLACEHOLDER_BASIS = "知识库中无《重大隐患判定标准（试行）》相应条文，待人工补充"

CITED_OUTPUT: dict[str, Any] = {**VALID_OUTPUT, "major_hazard_basis": VERBATIM_BASIS}
FABRICATED_OUTPUT: dict[str, Any] = {
    **VALID_OUTPUT,
    "major_hazard_basis": FABRICATED_BASIS,
}
PARTIAL_OUTPUT: dict[str, Any] = {**VALID_OUTPUT, "major_hazard_basis": PARTIAL_BASIS}
PLACEHOLDER_OUTPUT: dict[str, Any] = {
    **VALID_OUTPUT,
    "major_hazard_basis": VARIANT_PLACEHOLDER_BASIS,
}
EMPTY_BASIS_OUTPUT: dict[str, Any] = {**VALID_OUTPUT, "major_hazard_basis": ""}


def _make_strict_plugin(
    ai: FakeAIService,
    *,
    evidence: CitationEvidence | None = CITATION_EVIDENCE,
) -> AIHazardIdentifier:
    return AIHazardIdentifier(
        ai,
        PluginConfig(strict_mode=True),
        citation_evidence=evidence,
    )


class TestCitationStrictRetry:
    """S4：严格模式下引用不可验证 → 反馈重试一次 → 分类抛错。"""

    @pytest.mark.asyncio
    async def test_first_fabricated_then_verbatim_succeeds(self) -> None:
        """假 AI 首次编造引用、二次逐字 chunks 引用 → 成功且 attempt_no=2 审计正确。"""
        ai = FakeAIService([FABRICATED_OUTPUT, CITED_OUTPUT])
        plugin = _make_strict_plugin(ai)

        with ai_audit_scope(
            scenario="hazard_identification",
            extra={"round_id": "20261106120000-abcd"},
        ):
            output = await plugin.identify(make_input())
            _ctx = current_audit_ctx()
            outer_extra_after = _ctx.extra if _ctx is not None else None

        assert ai.call_count == 2, "引用零可验证应刚好重试一次"
        assert output.major_hazard_basis == VERBATIM_BASIS
        assert ai.calls[0]["audit_extra"] == {
            "round_id": "20261106120000-abcd",
            "attempt_no": 1,
        }
        assert ai.calls[1]["audit_extra"] == {
            "round_id": "20261106120000-abcd",
            "attempt_no": 2,
        }
        assert outer_extra_after == {"round_id": "20261106120000-abcd"}

        # 重试反馈包含不可验证引用摘要（帮助模型改正），且仍要求只输出 JSON
        feedback = _last_user_content(ai.calls[1])
        assert "GB 99999-2024" in feedback
        assert "无法在本轮检索到的法规条款中验证" in feedback
        assert "只输出 JSON" in feedback

        # last_citation_report 更新为「重试后（成功）」的校验结果
        report = plugin.last_citation_report
        assert report is not None
        assert report.has_verified is True
        assert report.total_units == 1

    @pytest.mark.asyncio
    async def test_both_fabricated_raises_invalid_citation(self) -> None:
        """两次都不可验证 → invalid_citation，错误与反馈均含不可验证线索。"""
        ai = FakeAIService([FABRICATED_OUTPUT, FABRICATED_OUTPUT])
        plugin = _make_strict_plugin(ai)

        with pytest.raises(IdentificationError) as exc_info:
            await plugin.identify(make_input())

        assert ai.call_count == 2
        err = exc_info.value
        assert err.category == "invalid_citation"
        assert "GB 99999-2024" in str(err)
        assert "只输出 JSON" in _last_user_content(ai.calls[1])
        assert "GB 99999-2024" in _last_user_content(ai.calls[1])

        report = plugin.last_citation_report
        assert report is not None
        assert report.total_units == 2
        assert report.has_verified is False

    @pytest.mark.asyncio
    async def test_placeholder_variant_raises_placeholder_basis(self) -> None:
        ai = FakeAIService([PLACEHOLDER_OUTPUT, PLACEHOLDER_OUTPUT])
        plugin = _make_strict_plugin(ai)

        with pytest.raises(IdentificationError) as exc_info:
            await plugin.identify(make_input())

        assert ai.call_count == 2
        assert exc_info.value.category == "placeholder_basis"
        assert "占位" in str(exc_info.value)
        assert plugin.last_citation_report is not None
        assert plugin.last_citation_report.placeholder_note is True

    @pytest.mark.asyncio
    async def test_empty_basis_raises_empty_basis(self) -> None:
        ai = FakeAIService([EMPTY_BASIS_OUTPUT, EMPTY_BASIS_OUTPUT])
        plugin = _make_strict_plugin(ai)

        with pytest.raises(IdentificationError) as exc_info:
            await plugin.identify(make_input())

        assert ai.call_count == 2
        assert exc_info.value.category == "empty_basis"
        assert plugin.last_citation_report is not None
        assert plugin.last_citation_report.total_units == 0

    @pytest.mark.asyncio
    async def test_no_citation_basis_raises_no_citation(self) -> None:
        """有引用格式但 total_units==0（纯泛化表述）→ no_citation（区别于 invalid_citation）。"""
        ai = FakeAIService([INVALID_BASIS_OUTPUT, INVALID_BASIS_OUTPUT])
        plugin = _make_strict_plugin(ai)

        with pytest.raises(IdentificationError) as exc_info:
            await plugin.identify(make_input())

        assert ai.call_count == 2
        assert exc_info.value.category == "no_citation"
        assert plugin.last_citation_report is not None
        assert plugin.last_citation_report.total_units == 0


class TestCitationStrictSuccessPaths:
    """S4：可验证/部分可验证的成功路径与 last_citation_report 暴露。"""

    @pytest.mark.asyncio
    async def test_verbatim_citation_passes_without_retry(self) -> None:
        ai = FakeAIService([CITED_OUTPUT])
        plugin = _make_strict_plugin(ai)

        output = await plugin.identify(make_input())

        assert ai.call_count == 1
        assert output.major_hazard_basis == VERBATIM_BASIS
        report = plugin.last_citation_report
        assert report is not None
        assert report.has_verified is True
        assert report.all_verified is True

    @pytest.mark.asyncio
    async def test_partial_unverified_does_not_retry(self) -> None:
        """部分不可验证只是 warning：不重试、不阻断（避免 +37% 调用成本）。"""
        ai = FakeAIService([PARTIAL_OUTPUT])
        plugin = _make_strict_plugin(ai)

        await plugin.identify(make_input())

        assert ai.call_count == 1
        report = plugin.last_citation_report
        assert report is not None
        assert report.has_verified is True
        assert report.all_verified is False

    @pytest.mark.asyncio
    async def test_non_strict_updates_report_without_raising(self) -> None:
        ai = FakeAIService([FABRICATED_OUTPUT])
        plugin = AIHazardIdentifier(
            ai,
            PluginConfig(strict_mode=False),
            citation_evidence=CITATION_EVIDENCE,
        )

        output = await plugin.identify(make_input())

        assert ai.call_count == 1
        assert output.major_hazard_basis == FABRICATED_BASIS
        report = plugin.last_citation_report
        assert report is not None
        assert report.has_verified is False


class TestCitationEvidenceBackwardCompat:
    """S4：不传 citation_evidence 的旧调用方零行为变化。"""

    @pytest.mark.asyncio
    async def test_without_evidence_keeps_legacy_behavior(self) -> None:
        """无证据时编造引用仍按旧口径通过（格式合法），last_citation_report 为 None。"""
        ai = FakeAIService([FABRICATED_OUTPUT])
        plugin = AIHazardIdentifier(ai, PluginConfig(strict_mode=True))

        output = await plugin.identify(make_input())

        assert ai.call_count == 1
        assert output.major_hazard_basis == FABRICATED_BASIS
        assert plugin.last_citation_report is None

    @pytest.mark.asyncio
    async def test_default_constructor_has_no_citation_evidence(self) -> None:
        plugin = AIHazardIdentifier(FakeAIService([VALID_OUTPUT]))
        assert plugin.citation_evidence is None
        assert plugin.last_citation_report is None
