"""URS 智能审核 — 四步 AI Plugin。

四个可独立测试的 Plugin（低温度 0.05 + 强类型输出 + 规则兜底）：
  ① RiskProfileAssessor   五维风险画像
  ② StandardAdapter       标准适配（否决项由 rules.apply_veto_override 代码强制）
  ③ ItemReviewer          逐条审核（AI 预填）
  ④ ConclusionGenerator   结论生成（评分/等级/结论由代码计算，AI 辅助摘要+整改要求）

所有 AI 调用经注入的 ai_service（AuditedAIService）自动落审计表；
业务入口由调用方（URSService）包 ai_audit_scope(scenario="urs_review")。
"""

import json
import logging
from typing import Any

from app.modules.safety.ai_urs_review import prompts, rules
from app.modules.safety.ai_urs_review.schemas import (
    AdaptedItem,
    ApplicabilityEnum,
    ConclusionEnum,
    ConclusionInput,
    ConclusionOutput,
    DimensionRisk,
    ItemReviewInput,
    ItemReviewOutput,
    ItemVerdict,
    RectificationRequirement,
    ReviewVerdictEnum,
    RiskLevelEnum,
    RiskProfileInput,
    RiskProfileOutput,
    StandardAdaptationInput,
    StandardAdaptationOutput,
)

logger = logging.getLogger(__name__)

# AI 温度（低值保证可复现，对标 ai_hazard_identification）
_AI_TEMPERATURE = 0.05

# URS 正文送入 AI 前截断长度（与 schema 定义一致）
_URS_CONTENT_LIMIT = 12000
_TRUNCATION_NOTICE = "\n【内容过长已截断,以下内容未提供】"


def _truncate_urs_content(content: str | None) -> str:
    """截断 URS 正文；发生截断时追加提示，避免模型误以为文档到此结束。"""
    text = content or ""
    if len(text) > _URS_CONTENT_LIMIT:
        return text[:_URS_CONTENT_LIMIT] + _TRUNCATION_NOTICE
    return text


class URSPluginError(Exception):
    """URS Plugin 执行失败。"""
    pass


# ── 畸形/截断 JSON 修复 ──
# 实测故障（URS-20260918-003）：deepseek-flash thinking 模式下输出在
# reasoning 字符串中途被 max_tokens 截断（未闭合的字符串 + 未闭合的 `{`），
# json.loads 直接失败 → 整单评估 failed。此处做逐字符状态机扫描后补齐
# 截断尾部；另兜底剥 markdown 围栏与 `)` 误闭合数组两种畸形。


def _scan_json_state(text: str) -> tuple[bool, list[str]]:
    """逐字符扫描 JSON 状态，返回 (是否停在未闭合字符串内, 括号栈)。"""
    in_str = False
    escaped = False
    stack: list[str] = []
    for ch in text:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if stack:
                stack.pop()
    return in_str, stack


def _repair_truncated_json(text: str) -> str:
    """补齐被截断的 JSON 尾部：闭合未闭合字符串 + 按栈逆序补闭合符。"""
    in_str, stack = _scan_json_state(text)
    out = text
    if in_str:
        out += '"'
    for opener in reversed(stack):
        out += "]" if opener == "[" else "}"
    return out


def _strip_json_fences(text: str) -> str:
    """剥离 markdown 代码围栏（```json ... ```）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        for i, line in enumerate(lines):
            if not line.strip().startswith("```"):
                cleaned = "\n".join(lines[i:])
                break
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


def _repair_bracket_mismatch(text: str) -> str:
    """修复 AI 输出中 `)` 误闭合 `[` 数组的括号错配。

    逐字符扫描，遇到 `)` 时若栈顶为 `[`（数组），按数组语义改写为
    `]`；栈顶为 `(` 的 `)` 是普通文本括号（多出现在中文指标描述里），不动。
    """
    stack: list[str] = []
    out: list[str] = []
    in_str = False
    escaped = False
    for ch in text:
        if in_str:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
        elif ch in "[{":
            stack.append(ch)
            out.append(ch)
        elif ch in "]}":
            if stack:
                stack.pop()
            out.append(ch)
        elif ch == ")":
            # 栈顶是数组/对象 → 该 `)` 实为误写的闭合符；否则保留为文本
            if stack and stack[-1] in "[{":
                out.append("]" if stack[-1] == "[" else "}")
                stack.pop()
            else:
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def _repair_json_text(raw: str) -> dict | None:
    """尝试把 AI 原始输出修复为可解析 JSON，成功返回解析后的 dict。"""
    base = _strip_json_fences(raw)
    candidates = [raw, base, _repair_truncated_json(base)]
    repaired = _repair_bracket_mismatch(base)
    if repaired != base:
        candidates.append(repaired)
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


async def _chat_parsed(
    ai_service: Any,
    system_prompt: str,
    user_prompt: str,
    expected_keys: list[str],
) -> dict:
    """统一 AI 调用入口。

    底层解析失败时先做本地修复（截断补齐/剥围栏/修括号），修复后仍缺
    键则重试一次 AI 调用（低温度下重试通常可得合法 JSON）。
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        return await ai_service.chat_parsed(
            messages=messages,
            expected_keys=expected_keys,
            temperature=_AI_TEMPERATURE,
        )
    except Exception as first_err:
        # 本地修复：AIOutputError 携带 raw_response（截断/畸形输出原文）
        raw = getattr(first_err, "raw_response", None)
        obj = _repair_json_text(raw) if isinstance(raw, str) else None
        if obj is not None:
            missing = [k for k in expected_keys if k not in obj]
            if not missing:
                logger.warning("URS AI 输出畸形/截断 JSON 已本地修复（不重试调用）")
                return obj
        logger.warning("URS AI 调用失败，重试一次: %s", str(first_err)[:300])
        try:
            return await ai_service.chat_parsed(
                messages=messages,
                expected_keys=expected_keys,
                temperature=_AI_TEMPERATURE,
            )
        except Exception as e:
            logger.exception("URS AI 调用重试仍失败")
            raise URSPluginError(f"AI 调用失败: {e}") from e


# ════════════════════════════════════════════════════════════════
# Step 1 — 五维风险画像
# ════════════════════════════════════════════════════════════════


class RiskProfileAssessor:
    """五维风险画像评估。"""

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def run(self, inp: RiskProfileInput) -> RiskProfileOutput:
        user_prompt = self._build_prompt(inp)
        raw = await _chat_parsed(
            self.ai_service, prompts.RISK_PROFILE_SYSTEM_PROMPT, user_prompt,
            ["mechanical", "electrical", "data", "environmental", "chemical",
             "overall_risk_level", "confidence", "reasoning"],
        )
        return self._parse(raw)

    @staticmethod
    def _build_prompt(inp: RiskProfileInput) -> str:
        lines = [f"设备名称：{inp.equipment_name}"]
        if inp.equipment_category:
            lines.append(f"设备类别：{inp.equipment_category}")
        if inp.department:
            lines.append(f"申请部门：{inp.department}")
        if inp.procurement_purpose:
            lines.append(f"采购用途：{inp.procurement_purpose}")
        content = _truncate_urs_content(inp.urs_content)
        lines.append(f"\nURS 文档内容：\n{content}")
        return "\n".join(lines)

    def _parse(self, raw: dict) -> RiskProfileOutput:
        dims: dict[str, DimensionRisk] = {}
        for key in ("mechanical", "electrical", "data", "environmental", "chemical"):
            d = raw.get(key) or {}
            indicators = d.get("indicators") or []
            if isinstance(indicators, str):
                indicators = [indicators]
            dims[key] = DimensionRisk(
                level=rules.sanitize_enum(d.get("level"), RiskLevelEnum, RiskLevelEnum.LOW),
                indicators=[str(i) for i in indicators if i][:8],
                evidence=str(d.get("evidence") or "")[:500],
            )

        # 综合等级：以 AI 输出为准，非法时用代码兜底计算
        overall = rules.sanitize_enum(
            raw.get("overall_risk_level"), RiskLevelEnum, None,
        )
        if overall is None:
            fallback = rules.compute_overall_risk({k: v.level.value for k, v in dims.items()})
            overall = RiskLevelEnum(fallback)

        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0

        return RiskProfileOutput(
            mechanical=dims["mechanical"],
            electrical=dims["electrical"],
            data=dims["data"],
            environmental=dims["environmental"],
            chemical=dims["chemical"],
            overall_risk_level=overall,
            confidence=round(confidence, 2),
            reasoning=str(raw.get("reasoning") or "")[:2000],
        )


# ════════════════════════════════════════════════════════════════
# Step 2 — 标准适配
# ════════════════════════════════════════════════════════════════


class StandardAdapter:
    """标准适配：seed + 知识库条目 → 三级适配（否决项代码强制）。"""

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def run(self, inp: StandardAdaptationInput) -> StandardAdaptationOutput:
        # 预置条目（供 AI 参照）+ 请求 AI 适配
        user_prompt = self._build_prompt(inp)
        raw = await _chat_parsed(
            self.ai_service, prompts.STANDARD_ADAPTATION_SYSTEM_PROMPT, user_prompt,
            ["items"],
        )
        output = self._parse(raw, inp)
        # 否决项强制 mandatory（代码兜底，铁律）
        veto_nos = {it["item_no"] for it in inp.items if it.get("is_veto")}
        enforced = rules.apply_veto_override(
            [item.model_dump() for item in output.items], veto_nos,
        )
        # 维度门控（代码强制，适配口径 A）：按五维风险等级覆盖 AI 适配结果。
        # 与 service 层 run_adaptation 的门控共用 rules.apply_dimension_gate（幂等），
        # 保证插件可独立测试、Service 层覆盖 AI 遗漏条目的完整兜底。
        src_map = {it["item_no"]: it for it in inp.items}
        for item in enforced:
            src = src_map.get(item["item_no"]) or {}
            item["risk_dimension"] = src.get("risk_dimension")
            item["is_veto"] = bool(src.get("is_veto"))
        profile = inp.risk_profile
        dim_levels = {
            k: getattr(profile, k).level.value
            for k in ("mechanical", "electrical", "data", "environmental", "chemical")
        }
        gated = rules.apply_dimension_gate(
            enforced, dim_levels, profile.overall_risk_level.value,
        )
        output.items = [AdaptedItem.model_validate(item) for item in gated]
        return output

    @staticmethod
    def _build_prompt(inp: StandardAdaptationInput) -> str:
        profile = inp.risk_profile
        lines = [f"设备名称：{inp.equipment_name}"]
        lines.append("五维风险画像：")
        for key, label in (
            ("mechanical", "机械"), ("electrical", "电气"), ("data", "数据"),
            ("environmental", "环境"), ("chemical", "化学"),
        ):
            d = getattr(profile, key)
            lines.append(
                f"  {label}风险={d.level.value}（命中：{('、'.join(d.indicators) if d.indicators else '无')}；依据：{d.evidence}）"
            )
        lines.append(f"综合风险等级={profile.overall_risk_level.value}")

        lines.append("\n待适配标准清单：")
        for it in inp.items:
            veto_tag = "（否决项，必须强制）" if it.get("is_veto") else ""
            standard_ref = it.get("standard_ref") or ""
            ref_tag = f"（标准条款号：{standard_ref}）" if standard_ref else ""
            lines.append(
                f"- {it.get('item_no')} [{it.get('category')}|{it.get('risk_dimension')}] "
                f"{it.get('standard_title')}{ref_tag}{veto_tag}"
            )
        return "\n".join(lines)

    def _parse(self, raw: dict, inp: StandardAdaptationInput) -> StandardAdaptationOutput:
        raw_items = raw.get("items") or []
        item_no_set = {it.get("item_no") for it in inp.items}
        items: list[AdaptedItem] = []
        for ri in raw_items:
            if not isinstance(ri, dict) or ri.get("item_no") not in item_no_set:
                continue
            items.append(AdaptedItem(
                item_no=str(ri["item_no"]),
                applicability=rules.sanitize_enum(
                    ri.get("applicability"), ApplicabilityEnum, ApplicabilityEnum.RECOMMENDED,
                ),
                applicability_reason=str(ri.get("applicability_reason") or "")[:500],
            ))
        return StandardAdaptationOutput(items=items)


# ════════════════════════════════════════════════════════════════
# Step 3 — 逐条审核（AI 预填）
# ════════════════════════════════════════════════════════════════


class ItemReviewer:
    """逐条审核：AI 对每条适用标准对照 URS 给预填结论。"""

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def run(self, inp: ItemReviewInput) -> ItemReviewOutput:
        user_prompt = self._build_prompt(inp)
        raw = await _chat_parsed(
            self.ai_service, prompts.ITEM_REVIEW_SYSTEM_PROMPT, user_prompt,
            ["items"],
        )
        return self._parse(raw, inp)

    @staticmethod
    def _build_prompt(inp: ItemReviewInput) -> str:
        lines = [f"设备名称：{inp.equipment_name}"]
        lines.append("\n待审核适用标准：")
        for it in inp.items:
            lines.append(
                f"- {it.get('item_no')} [{it.get('applicability')}] {it.get('standard_title')}"
                + (f"（{it.get('standard_ref')}）" if it.get("standard_ref") else "")
            )
        content = _truncate_urs_content(inp.urs_content)
        lines.append(f"\nURS 文档内容：\n{content}")
        return "\n".join(lines)

    def _parse(self, raw: dict, inp: ItemReviewInput) -> ItemReviewOutput:
        raw_items = raw.get("items") or []
        item_no_set = {it.get("item_no") for it in inp.items}
        items: list[ItemVerdict] = []
        for ri in raw_items:
            if not isinstance(ri, dict) or ri.get("item_no") not in item_no_set:
                continue
            status = rules.sanitize_enum(ri.get("review_status"), ReviewVerdictEnum, ReviewVerdictEnum.PASSED)
            items.append(ItemVerdict(
                item_no=str(ri["item_no"]),
                review_status=status,
                review_comment=str(ri.get("review_comment") or "")[:500],
                ai_suggestion=str(ri.get("ai_suggestion") or "")[:500],
                rectification_required=bool(ri.get("rectification_required")),
            ))
        return ItemReviewOutput(items=items)


# ════════════════════════════════════════════════════════════════
# Step 4 — 结论生成（评分/结论代码计算 + AI 辅助摘要/整改要求）
# ════════════════════════════════════════════════════════════════


class ConclusionGenerator:
    """结论生成：score/grade/conclusion 由代码按 D7 计算，AI 辅助 summary + 整改要求。"""

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def run(self, inp: ConclusionInput) -> ConclusionOutput:
        # ── 代码计算（确定性，不依赖 AI）──
        score = rules.compute_score(inp.items)
        conclusion, veto_break = rules.conclude(inp.items)
        grade = rules.grade_for_score(score)

        # ── AI 辅助：failed 项 → 整改要求 + 摘要 ──
        failed_items = [
            it for it in inp.items
            if it.get("review_status") == "failed" and it.get("applicability") != "not_applicable"
        ]
        summary = ""
        requirements: list[RectificationRequirement] = []
        if failed_items:
            user_prompt = self._build_prompt(inp, score, conclusion)
            try:
                raw = await _chat_parsed(
                    self.ai_service, prompts.CONCLUSION_SYSTEM_PROMPT, user_prompt,
                    ["summary", "rectification_requirements"],
                )
                summary = str(raw.get("summary") or "")[:1000]
                for req in (raw.get("rectification_requirements") or []):
                    if isinstance(req, dict) and req.get("item_no"):
                        requirements.append(RectificationRequirement(
                            item_no=str(req["item_no"]),
                            requirement=str(req.get("requirement") or "")[:500],
                            responsible=str(req.get("responsible") or "")[:100],
                            deadline=str(req.get("deadline") or "")[:100],
                        ))
            except URSPluginError:
                logger.warning("结论 AI 辅助生成失败，仅输出代码计算结果")
                summary = (
                    f"{inp.equipment_name} 审核结论：{conclusion}，"
                    f"评分 {score} 分（{grade}级）。"
                )
        else:
            summary = (
                f"{inp.equipment_name} 全部适用条款通过，审核通过，评分 {score} 分（{grade}级）。"
            )

        return ConclusionOutput(
            score=score,
            grade=grade,
            conclusion=ConclusionEnum(conclusion),
            veto_break=veto_break,
            summary=summary,
            rectification_requirements=requirements,
        )

    @staticmethod
    def _build_prompt(inp: ConclusionInput, score: float, conclusion: str) -> str:
        lines = [f"设备名称：{inp.equipment_name}", f"代码计算评分：{score}，结论：{conclusion}"]
        lines.append("\n失败（不通过）的审核条目：")
        for it in inp.items:
            if it.get("review_status") == "failed":
                lines.append(
                    f"- {it.get('item_no')} [{it.get('applicability')}] {it.get('standard_title')}：{it.get('review_comment') or ''}"
                )
        return "\n".join(lines)
