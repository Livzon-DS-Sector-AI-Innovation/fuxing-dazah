"""AI隐患识别插件 — 核心引擎。

将设计方案中的四阶段流程实现为可独立运行、可测试的插件：
  阶段一：输入采集与预处理
  阶段二：多模态AI分析
  阶段三：规则匹配与推理
  阶段四：输出生成

用法:
    from app.modules.safety.ai_hazard_identification import AIHazardIdentifier
    from app.platform.integrations.ai.client import AIService

    ai_service = AIService(api_key="...", base_url="...", model="...")
    plugin = AIHazardIdentifier(ai_service)

    input_data = HazardIdentificationInput(
        description="防爆电箱堵头缺失",
        department="生产部",
        location="合成车间一楼",
        defect_photos=["https://..."],
    )

    output = await plugin.identify(input_data)
    logger.debug("识别结果: key_defect=%s hazard_level=%s", output.key_defect, output.hazard_level)
"""

from __future__ import annotations

import json as _json
import logging
import time
from contextlib import AbstractContextManager
from typing import Any

from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
    CitationReport,
    verify_citations,
)
from app.modules.safety.ai_hazard_identification.prompts import (
    SYSTEM_ROLE,
    build_context_text,
    build_full_prompt,
    build_vision_context_text,
    get_expected_keys,
)
from app.modules.safety.ai_hazard_identification.rules import (
    KEY_DEFECT_MAX_LENGTH,
    RuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.schemas import (
    HazardIdentificationInput,
    HazardIdentificationOutput,
    PluginConfig,
    RectificationSuggestion,
)

logger = logging.getLogger(__name__)

# A4 带错误反馈重试：把规则校验错误 + 「只输出 JSON」要求回灌给 AI（只重试一次）。
_RETRY_FEEDBACK_TEMPLATE = """
## 上次输出未通过规则校验，请修正后重新输出

你上一次输出的 JSON 已成功解析，但未通过规则校验，错误如下：
{errors}

请逐条修正上述问题后重新输出**完整**的 JSON（字段结构与格式要求同上）。
只输出 JSON，不要输出 markdown 代码块或任何解释文字。"""


def _build_retry_feedback(errors: list[str]) -> str:
    """构造规则校验错误反馈文本（A4 重试 prompt 片段）。"""
    error_lines = "\n".join(f"- {error}" for error in errors)
    return _RETRY_FEEDBACK_TEMPLATE.format(errors=error_lines)


def _attempt_audit_scope(attempt_no: int) -> AbstractContextManager[Any]:
    """嵌套审计作用域，只在 `extra` 上覆盖 `attempt_no`（A7）。

    - 首次 AI 调用 attempt_no=1，A4 反馈重试 attempt_no=2；
    - 合并当前外层 `current_audit_ctx().extra`（保留 round_id /
      bitable_record_id 等轮级语义），不覆盖/丢弃外层字段；
    - 延迟 import：插件在无审计场景的独立脚本/单测中同样可用。
    """
    from app.modules.safety.ai_audit.context import (  # 避免插件模块导入即拉起审计层
        ai_audit_scope,
        current_audit_ctx,
    )

    parent = current_audit_ctx()
    merged_extra = dict(parent.extra) if parent is not None and parent.extra else {}
    merged_extra["attempt_no"] = attempt_no
    return ai_audit_scope(extra=merged_extra)



class IdentificationError(Exception):
    """AI 识别失败异常。

    `category` 是 A5/A7 的结构化失败分类（`json_invalid` / `validation_failed`
    等），供上层失败治理直接读取；`None` 表示插件无法判定，由上层回退到
    原有字符串匹配，保证向后兼容（原 `IdentificationError(msg)` 调用不变）。
    """

    def __init__(self, message: str, *, category: str | None = None) -> None:
        super().__init__(message)
        self.category: str | None = category


def _error_category(exc: BaseException | None) -> str | None:
    """沿异常链推断失败分类（供 AI 调用失败包装使用）。

    - 异常链上已有带 category 的 `IdentificationError` → 原样保留；
    - 链上出现平台 `AIOutputError`（输出 JSON 不可解析/缺键）→ `json_invalid`；
    - 其它（网络/超时/未知）→ None，让上层按原逻辑回退。
    """
    from app.platform.integrations.ai.client import AIOutputError  # 延迟 import

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, IdentificationError) and current.category:
            return current.category
        if isinstance(current, AIOutputError):
            return "json_invalid"
        current = current.__cause__ or current.__context__
    return None


class AIHazardIdentifier:
    """AI隐患识别插件 — 稳定、可复现、可独立测试。

    设计原则：
    - 低温度（0.05）保证输出可复现
    - DB-first 配置 + 硬编码 fallback
    - 规则引擎后处理确保质量
    - 法规知识库注入（RAG-lite）
    - 完整的日志记录用于审计

    Args:
        ai_service: AI 服务实例（已配置 API key / base_url / model）
        config: 插件运行时配置（可选，使用默认值）
        knowledge_context: 法规知识库上下文文本（可选，注入到 prompt 中）
        citation_evidence: 本轮检索证据（可选，C2 引用强约束）。``None`` 表示
            不做引用来源校验，行为与 P0-A 完全一致；非 ``None`` 时给规则校验
            注入证据（零可验证 → 错误反馈重试一次 → 仍失败按分类抛错）。

    Example:
        >>> ai_service = AIService(api_key="sk-xxx", model="deepseek-flash")
        >>> plugin = AIHazardIdentifier(ai_service, knowledge_context="...")
        >>> output = await plugin.identify(HazardIdentificationInput(
        ...     description="防爆电箱堵头缺失",
        ...     department="生产部",
        ... ))
    """

    def __init__(
        self,
        ai_service: Any,  # AIService from app.platform.integrations.ai.client
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
        citation_evidence: CitationEvidence | None = None,
    ):
        self.ai_service = ai_service
        self.config = config or PluginConfig()
        self.rule_engine = RuleEngine()
        self.knowledge_context = knowledge_context
        # C2：本轮检索证据；None = 不做引用来源强校验（旧调用方零行为变化）
        self.citation_evidence = citation_evidence
        # C2：每次规则校验后的引用报告（供 T4 审计 extra 读取；None = 未启用校验）
        self.last_citation_report: CitationReport | None = None

    # ── 公共 API ──

    async def identify(
        self,
        input_data: HazardIdentificationInput,
    ) -> HazardIdentificationOutput:
        """执行完整的 AI 隐患识别流程。

        Args:
            input_data: 标准化输入（含描述、图片、部门等上下文）

        Returns:
            经过规则验证和自动修正的识别结果

        Raises:
            IdentificationError: 识别失败（AI 调用失败或输出不合法）
        """
        start_time = time.monotonic()
        # C2：每次识别重置引用报告，失败/异常路径不残留上一条记录的结果
        self.last_citation_report = None

        # ── 阶段一：输入预处理 ──
        logger.info("阶段一：输入预处理 — hazard_no=%s", input_data.hazard_no)
        has_photos = bool(input_data.defect_photos)

        # ── 阶段1.5：加载知识库 ──
        if not self.knowledge_context and self.config.enable_knowledge:
            logger.info("阶段1.5：知识库未提供，使用空上下文（集成层应在调用前注入）")

        # ── 阶段二：AI 分析 ──
        logger.info("阶段二：AI 分析 — has_photos=%s has_knowledge=%s",
                     has_photos, bool(self.knowledge_context))

        # A7：每次 AI 调用带 attempt_no（首次=1；外层 round_id 等 extra 保留）
        with _attempt_audit_scope(1):
            raw_output = await self._call_ai(input_data)

        # ── 阶段三：解析 & 验证 ──
        logger.info("阶段三：解析输出并规则验证")
        output = auto_correct(self._parse_output(raw_output))

        # 规则验证（C2：有证据时同时做引用来源强校验）
        validation = self.rule_engine.validate(
            input_data, output, citation_evidence=self.citation_evidence
        )
        self._refresh_citation_report(output)
        if not validation.is_valid:
            error_detail = "; ".join(validation.errors)
            if self.config.strict_mode:
                # A4：JSON 已解析但规则不通过 → 带错误反馈重试一次。
                # JSON/schema 解析失败不进入本分支（由客户端/上一层重试）。
                logger.warning(
                    "AI 输出规则校验失败（严格模式），带错误反馈重试一次: %s",
                    error_detail,
                )
                with _attempt_audit_scope(2):
                    retry_raw = await self._call_ai(
                        input_data,
                        retry_errors=validation.errors,
                        previous_output=raw_output,
                    )
                output = auto_correct(self._parse_output(retry_raw))
                retry_validation = self.rule_engine.validate(
                    input_data, output, citation_evidence=self.citation_evidence
                )
                self._refresh_citation_report(output)
                if not retry_validation.is_valid:
                    retry_detail = "; ".join(retry_validation.errors)
                    # C2：按最后一次引用报告分类失败（无证据时保持旧 classification）
                    category = self._classify_validation_failure(output)
                    raise IdentificationError(
                        "AI 输出验证失败（已带错误反馈重试一次）: "
                        f"{retry_detail}\n"
                        f"首次校验错误: {error_detail}",
                        category=category,
                    )
            else:
                logger.warning("AI 输出验证失败（非严格模式，继续返回）: %s", error_detail)

        # ── 阶段四：返回结果 ──
        elapsed = time.monotonic() - start_time
        logger.info(
            "识别完成 — hazard_no=%s type=%s category=%s level=%s elapsed=%.2fs",
            input_data.hazard_no,
            output.hazard_type.value,
            output.hazard_category.value,
            output.hazard_level.value,
            elapsed,
        )

        return output

    async def identify_batch(
        self,
        inputs: list[HazardIdentificationInput],
    ) -> list[HazardIdentificationOutput]:
        """批量识别（顺序执行，不并发以避免 API 限流）。

        Args:
            inputs: 多条隐患记录的输入

        Returns:
            与输入顺序对应的识别结果列表
        """
        results: list[HazardIdentificationOutput] = []
        for i, input_data in enumerate(inputs):
            logger.info("批量识别 [%d/%d]: %s", i + 1, len(inputs), input_data.hazard_no)
            try:
                result = await self.identify(input_data)
                results.append(result)
            except IdentificationError as e:
                logger.error("批量识别 [%d/%d] 失败: %s", i + 1, len(inputs), e)
                raise
        return results

    # ── 内部方法 ──

    def _refresh_citation_report(
        self, output: HazardIdentificationOutput
    ) -> CitationReport | None:
        """每次规则校验后刷新引用报告（首次/重试/成功/失败路径统一调用）。

        无证据时保持 ``None``（旧调用方语义）；有证据时用纯函数复算一次
        （与 RuleEngine 内部复算同源、开销可忽略），供 T4 审计 extra 读取。
        """
        if self.citation_evidence is None:
            self.last_citation_report = None
        else:
            self.last_citation_report = verify_citations(
                output.major_hazard_basis or "", self.citation_evidence
            )
        return self.last_citation_report

    def _classify_validation_failure(
        self, output: HazardIdentificationOutput
    ) -> str:
        """规则校验（已带反馈重试一次仍失败）→ C2 结构化失败分类。

        分类口径（spec §C2 / ticket 03）：
        - 无证据（report=None）→ ``validation_failed``（旧分类，零行为变化）；
        - basis 为空 → ``empty_basis``；
        - 纯占位变体（含占位注记且零可验证）→ ``placeholder_basis``；
        - ``total_units == 0``（无任何引用单元）→ ``no_citation``；
        - 有引用单元但零可验证 → ``invalid_citation``；
        - 其它（引用可验证但字段级规则失败）→ ``validation_failed``。
        """
        report = self.last_citation_report
        if report is None:
            return "validation_failed"

        basis = output.major_hazard_basis or ""
        if not basis.strip():
            return "empty_basis"
        if report.placeholder_note and not report.has_verified:
            return "placeholder_basis"
        if not report.has_verified:
            return "no_citation" if report.total_units == 0 else "invalid_citation"
        return "validation_failed"

    async def _call_ai(
        self,
        input_data: HazardIdentificationInput,
        *,
        retry_errors: list[str] | None = None,
        previous_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按输入/配置选择视觉或文本 AI 入口。

        A4 重试时通过 `retry_errors` / `previous_output` 把规则校验错误回灌 prompt。
        """
        if input_data.defect_photos and self.config.enable_vision:
            return await self._call_vision_ai(input_data, retry_errors=retry_errors)
        return await self._call_text_ai(
            input_data,
            retry_errors=retry_errors,
            previous_output=previous_output,
        )

    async def _call_text_ai(
        self,
        input_data: HazardIdentificationInput,
        *,
        retry_errors: list[str] | None = None,
        previous_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """纯文本模式 AI 调用（A4 重试时可携带校验错误反馈）。"""
        context = build_context_text(
            hazard_no=input_data.hazard_no,
            description=input_data.description,
            department=input_data.department,
            location=input_data.location,
            discovered_by_name=input_data.discovered_by_name,
            discovered_at=(
                input_data.discovered_at.strftime("%Y-%m-%d %H:%M")
                if input_data.discovered_at else None
            ),
        )

        prompt = build_full_prompt(
            context, vision_mode=False, include_fewshot=True,
            knowledge_context=self.knowledge_context,
        )
        expected_keys = get_expected_keys()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_ROLE},
            {"role": "user", "content": prompt},
        ]
        if retry_errors:
            if previous_output is not None:
                messages.append({
                    "role": "assistant",
                    "content": _json.dumps(
                        previous_output, ensure_ascii=False, default=str
                    ),
                })
            messages.append(
                {"role": "user", "content": _build_retry_feedback(retry_errors)}
            )

        try:
            parsed: dict[str, Any] = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=expected_keys,
                temperature=self.config.temperature,
            )
            return parsed
        except Exception as e:
            logger.error("文本 AI 调用失败: %s", e)
            raise IdentificationError(
                f"AI 文本分析失败: {e}", category=_error_category(e)
            ) from e

    async def _call_vision_ai(
        self,
        input_data: HazardIdentificationInput,
        *,
        retry_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """多模态 AI 调用（带图片；A4 重试时在 prompt 末尾追加错误反馈）。"""
        context = build_vision_context_text(
            hazard_no=input_data.hazard_no,
            description=input_data.description,
            department=input_data.department,
            location=input_data.location,
        )

        expected_keys = get_expected_keys()

        try:
            # 检查 AI 服务是否支持 vision
            if hasattr(self.ai_service, "chat_vision_parsed"):
                text_prompt = build_full_prompt(
                    context, vision_mode=True, include_fewshot=True,
                    knowledge_context=self.knowledge_context,
                )
                if retry_errors:
                    text_prompt += "\n\n" + _build_retry_feedback(retry_errors)
                parsed: dict[str, Any] = await self.ai_service.chat_vision_parsed(
                    text_prompt=text_prompt,
                    image_urls=input_data.defect_photos,
                    expected_keys=expected_keys,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
                return parsed

            # Fallback: 将图片信息嵌入文本 prompt
            logger.warning("AI 服务不支持 vision，降级为纯文本模式")
            fallback_desc = input_data.description
            if input_data.defect_photos:
                fallback_desc += (
                    f"\n（附缺陷照片 {len(input_data.defect_photos)} 张，"
                    f"因当前模型不支持视觉分析，请基于文本描述进行判断）"
                )
            fallback_input = HazardIdentificationInput(
                hazard_no=input_data.hazard_no,
                description=fallback_desc,
                department=input_data.department,
                location=input_data.location,
                discovered_by_name=input_data.discovered_by_name,
                discovered_at=input_data.discovered_at,
                defect_photos=[],  # 清空图片，走纯文本
            )
            return await self._call_text_ai(
                fallback_input, retry_errors=retry_errors
            )

        except Exception as e:
            logger.error("多模态 AI 调用失败: %s", e)
            raise IdentificationError(
                f"AI 视觉分析失败: {e}", category=_error_category(e)
            ) from e

    def _parse_output(self, raw: dict[str, Any]) -> HazardIdentificationOutput:
        """将 AI 返回的字典解析为强类型输出。

        A4 字段级容错：`key_defect` 超 schema max_length 时先截断再构造，
        避免一个字过长导致整条识别硬失败（auto_correct 兜底同一上限）。
        """
        try:
            # 解析枚举
            from app.modules.safety.ai_hazard_identification.schemas import (
                DefectSubstanceEnum,
                HazardCategoryEnum,
                HazardLevelEnum,
                HazardTypeEnum,
            )

            raw_key_defect = raw.get("key_defect", "")
            key_defect = (
                raw_key_defect[:KEY_DEFECT_MAX_LENGTH]
                if isinstance(raw_key_defect, str)
                else raw_key_defect
            )

            # 如果 rectification_suggestion 是字符串（某些模型可能这样返回），做兼容处理
            rs = raw.get("rectification_suggestion", {})
            if isinstance(rs, str):
                # 尝试 JSON 解析
                try:
                    rs = _json.loads(rs)
                except (_json.JSONDecodeError, TypeError):
                    rs = {"corrective": rs, "preventive": ""}

            return HazardIdentificationOutput(
                key_defect=key_defect,
                hazard_type=HazardTypeEnum(raw.get("hazard_type", "")),
                hazard_category=HazardCategoryEnum(raw.get("hazard_category", "")),
                hazard_level=HazardLevelEnum(raw.get("hazard_level", "")),
                rectification_suggestion=RectificationSuggestion(
                    corrective=rs.get("corrective", ""),
                    preventive=rs.get("preventive", ""),
                ),
                major_hazard_basis=raw.get("major_hazard_basis", ""),
                defect_substance=DefectSubstanceEnum(raw.get("defect_substance", "uncertain")),
                defect_substance_reasoning=raw.get("defect_substance_reasoning", ""),
                confidence=raw.get("confidence") if self.config.enable_reasoning else None,
                reasoning=raw.get("reasoning") if self.config.enable_reasoning else None,
            )
        except (ValueError, KeyError, TypeError) as e:
            raise IdentificationError(
                f"AI 输出解析失败: {e}\n"
                f"原始输出: {_json.dumps(raw, ensure_ascii=False, default=str)[:500]}",
                category="json_invalid",
            ) from e
