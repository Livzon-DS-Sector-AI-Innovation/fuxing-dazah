"""SOP AI 层 — 逐章 AI 主生成。

每个内容章独立调用 AI（静态 system prompt + 聚焦上下文 + 严格 Schema 校验），
规则渲染只在该章 AI 失败/为空时兜底。本模块为第 7 章（生产工艺流程）优先落地，
后续 ch3/5/6/8/9 依同一模式扩展。

聚焦上下文原则（spec: sop-generation-quality）：
- 每章只拿到相关工序段落 + 相关参考表 + 知识参考包切片，不再一次性灌入全文。
- ch7 取**整个工艺区段段落**（stage 标注段落 + raw_process_text），
  规避 layer1 阶段检测漏检导致的工序缺失。
"""

from __future__ import annotations

import logging
import uuid

from ._prompts import (
    SOP_CH3_SYSTEM_PROMPT,
    SOP_CH5_SYSTEM_PROMPT,
    SOP_CH6_SYSTEM_PROMPT,
    SOP_CH7_SYSTEM_PROMPT,
    SOP_CH8_SYSTEM_PROMPT,
    SOP_CH9_SYSTEM_PROMPT,
)
from ._validate import (
    CH7_COVERAGE_THRESHOLD,
    ch5_traceability,
    ch7_coverage,
    validate_ch3,
    validate_ch5,
    validate_ch6,
    validate_ch7,
    validate_ch8,
    validate_ch9,
)

logger = logging.getLogger(__name__)

# ch7 漏工序时最多重试次数（强调"逐条列出、不得遗漏"）
CH7_MAX_RETRIES = 1
# ch7 聚焦上下文上限（控制成本，仅工艺区段足以）
CH7_CONTEXT_MAX_CHARS = 20000

# 各章聚焦上下文上限 + 知识参考包切片上限（控制成本）
_CHAPTER_CONTEXT_MAX_CHARS = 20000
_KB_REG_MAX_CHARS = 4000
_KB_MSDS_MAX_CHARS = 3000

# 与 layer2_transform._safety_kw_config["skip_stage_kw"] 保持一致，另加
# layer1 阶段检测失败时的通用兜底标题（整段工艺被收进单个 catch-all 标题，
# 无工序信息，不构成覆盖率基线）。
_SKIP_STAGE_KEYWORDS = (
    "生产前准备",
    "通用",
    "作业过程",
    "作业结束",
    "作业通用",
    "操作步骤",
    "操作过程",
    "工艺操作",
)


def _is_skip_stage(name: str) -> bool:
    """通用/前后准备类标题不是真实工艺工序，不参与覆盖率基线。"""
    return any(kw in name for kw in _SKIP_STAGE_KEYWORDS)


def _field(obj, name: str, default):
    """兼容 dataclass 与 dict 两种形态的字段读取。"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def baseline_stages(extracted) -> list[str]:
    """layer1 检测出的工艺工序名（跳过通用标题；无段落的不计）。

    供覆盖率自检与测试断言使用。返回结果与 layer2 规则渲染能产出的工序一致。
    """
    names: list[str] = []
    for s in _field(extracted, "process_stages", []) or []:
        name = str(_field(s, "name", "") or "").strip()
        if not name or _is_skip_stage(name):
            continue
        if not _field(s, "paragraphs", []) or []:
            continue
        names.append(name)
    return names


def _build_ch7_context(extracted, meta: dict | None = None) -> str:
    """ch7 聚焦上下文 = meta + 按工序标注的全部工艺段落 + raw_process_text。

    只要源文档工艺段落被任一 stage 收录，或位于 raw_process_text 中，
    都会进入上下文——最大程度规避 layer1 阶段检测漏检。
    """
    meta = meta or {}
    lines: list[str] = []
    if meta.get("product_name"):
        lines.append(f"产品：{meta['product_name']}")
    if meta.get("post_name"):
        lines.append(f"岗位：{meta['post_name']}")
    lines.append("")
    lines.append("源文档工艺段落（按工序标注，请逐条还原完整操作步骤）：")
    for s in _field(extracted, "process_stages", []) or []:
        name = str(_field(s, "name", "") or "").strip()
        paras = _field(s, "paragraphs", []) or []
        if not name or not paras:
            continue
        lines.append(f"### {name}")
        for p in paras:
            lines.append(p if isinstance(p, str) else str(p))

    raw_text = str(_field(extracted, "raw_process_text", "") or "").strip()
    if raw_text:
        lines.append("")
        lines.append("源文档工艺流程区段落（未按工序归类的原文，用于补漏）：")
        lines.append(raw_text)

    context = "\n".join(lines).strip()
    return context[:CH7_CONTEXT_MAX_CHARS]


def _stage_names(rows: list[dict]) -> list[str]:
    return [str(r.get("阶段", "") or "").strip() for r in rows if r.get("阶段")]


async def generate_ch7_flow(
    *,
    extracted,
    meta: dict | None = None,
    regulation_id: uuid.UUID | None = None,
) -> dict | None:
    """第 7 章 AI 主生成。

    Args:
        extracted: layer1 提取结果（ExtractedData dataclass 或等价 dict）。
        meta: 可选上下文（product_name/post_name），仅作提示用。
        regulation_id: 操规记录 ID，写入审计 resource_id。

    Returns:
        {"rows": [{阶段, 操作内容}], "coverage": float, "warnings": [str]}
        ；AI 全部失败/校验不过返回 None（上层回退规则渲染）。

    覆盖率自检：低于 CH7_COVERAGE_THRESHOLD 重试 1 次（强调逐条列出），
    取覆盖率高的一次；仍不达标保留最佳结果 + warning（不回退规则——
    规则模式是"工艺步骤缺失"的原问题来源）。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    baseline = baseline_stages(extracted)
    context = _build_ch7_context(extracted, meta)

    best_rows: list[dict] | None = None
    best_coverage = 0.0
    warnings: list[str] = []

    for attempt in range(CH7_MAX_RETRIES + 1):
        user_content = (
            "请逐条列出本岗位全部生产工艺操作步骤，输出 JSON 对象。\n\n"
            + ("⚠️ 强调：不得遗漏任何工序，逐条列出、不得合并。\n\n" if attempt > 0 else "")
            + f"工艺段落：\n{context}"
        )
        rows: list[dict] | None = None
        try:
            with ai_audit_scope(
                scenario="sop_generation",
                channel="web",
                resource_type="regulation",
                resource_id=regulation_id,  # UUID 类型列，直接传对象
                extra={"chapter": 7, "kind": "process_flow", "attempt": attempt + 1},
            ):
                ai = create_ai_service("text")
                result = await ai.chat_parsed(
                    messages=[
                        {"role": "system", "content": SOP_CH7_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    expected_keys=["process_flow"],
                    temperature=0.1,
                )
            rows = validate_ch7(result)
        except Exception as exc:  # noqa: BLE001 — 单章失败回退规则，不阻塞
            logger.warning("ch7 AI 生成失败（第 %d/%d 次）：%s",
                           attempt + 1, CH7_MAX_RETRIES + 1, exc)

        if not rows:
            continue
        coverage = ch7_coverage(_stage_names(rows), baseline)
        # 首次有效结果必保留（coverage 可能为 0 —— 基线被通用标题兜底/全部跳过时），
        # 之后只取覆盖率更高的。
        if best_rows is None or coverage > best_coverage:
            best_rows, best_coverage = rows, coverage
        if coverage >= CH7_COVERAGE_THRESHOLD:
            break  # 达标，不再重试

    if best_rows is None:
        return None

    if best_coverage < CH7_COVERAGE_THRESHOLD:
        covered_names = _stage_names(best_rows)
        missing = [
            s for s in baseline
            if not any(s in ai or ai in s for ai in covered_names)
        ]
        msg = f"ch7 工序覆盖率 {best_coverage:.0%} < 90%，疑似遗漏工序：{'、'.join(missing) or '（无法判定）'}"
        warnings.append(msg)
        logger.warning("%s", msg)

    return {
        "rows": best_rows,
        "coverage": round(best_coverage, 3),
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════
# 聚焦上下文构建（ch3/5/6/8/9 共用）
# ═══════════════════════════════════════════════════════════════════════


def _stage_lines(extracted) -> list[str]:
    """工序名 + 段落（保序）——各章聚焦上下文的主体。"""
    lines: list[str] = []
    for s in _field(extracted, "process_stages", []) or []:
        name = str(_field(s, "name", "") or "").strip()
        paras = _field(s, "paragraphs", []) or []
        if not name or not paras:
            continue
        lines.append(f"### {name}")
        for p in paras:
            lines.append(p if isinstance(p, str) else str(p))
    return lines


def _ref_table_block(ref_tables: dict, keys: list[str]) -> list[str]:
    """按 key 取参考表（headers + rows 前 30 行）→ 文本块。"""
    lines: list[str] = []
    for key in keys:
        t = (ref_tables or {}).get(key)
        if not isinstance(t, dict):
            continue
        rows = t.get("rows", []) or []
        headers = t.get("headers", []) or []
        if not rows:
            continue
        lines.append(f"### {key} 参考表")
        if headers:
            lines.append(" | ".join(str(h) for h in headers))
        for row in rows[:30]:
            lines.append(" | ".join(str(c) for c in row))
    return lines


def _kb_block(kb: dict | None, *, include_msds: bool) -> list[str]:
    """知识参考包切片（法规 RAG + MSDS 物性）→ 文本块。"""
    kb = kb or {}
    lines: list[str] = []
    regs = str(kb.get("regulations_md") or "").strip()
    if regs:
        lines.append("### 法规参考（RAG 检索，仅作补缺依据）")
        lines.append(regs[:_KB_REG_MAX_CHARS])
    msds = kb.get("msds") or {}
    if include_msds and isinstance(msds, dict) and msds:
        lines.append("### 化学品 MSDS 物性（数值溯源权威依据）")
        for name, summary in msds.items():
            if not isinstance(summary, dict):
                continue
            parts: list[str] = []
            phys = summary.get("physicochemical") or []
            if phys:
                parts.append("；".join(str(x) for x in phys))
            matched = summary.get("matched_by")
            if matched:
                parts.append(f"（命中: {matched}）")
            if parts:
                lines.append(f"- {name}：{'；'.join(parts)}")
            for fld in ("健康危害", "急救措施", "消防措施", "泄漏应急处理"):
                val = summary.get(fld)
                if val:
                    lines.append(f"  - {fld}: {str(val)[:200]}")
    return lines


def _build_chapter_context(
    extracted,
    meta: dict | None,
    ref_tables: dict,
    kb: dict | None,
    *,
    include_tables: list[str],
    include_msds: bool = True,
    max_chars: int = _CHAPTER_CONTEXT_MAX_CHARS,
) -> str:
    """每章聚焦上下文 = meta + 工序段落 + 相关参考表 + 知识参考包切片。

    变量数据全部放 user 消息尾部；system 保持静态（前缀缓存友好）。
    """
    meta = meta or {}
    lines: list[str] = []
    if meta.get("product_name"):
        lines.append(f"产品：{meta['product_name']}")
    if meta.get("post_name"):
        lines.append(f"岗位：{meta['post_name']}")
    lines.append("")
    lines.append("源文档工艺段落（按工序标注）：")
    lines.extend(_stage_lines(extracted))
    if include_tables:
        lines.append("")
        lines.append("源文档参考表：")
        lines.extend(_ref_table_block(ref_tables, include_tables))
    if kb:
        lines.append("")
        lines.extend(_kb_block(kb, include_msds=include_msds))
    return "\n".join(lines).strip()[:max_chars]


# ═══════════════════════════════════════════════════════════════════════
# ch3 / ch5 / ch6 / ch8 逐章 AI 主生成 + ch9 应急类型选型
# ═══════════════════════════════════════════════════════════════════════


async def generate_ch3_risk(
    *,
    extracted,
    ref_tables: dict,
    kb: dict | None,
    meta: dict | None = None,
    regulation_id: uuid.UUID | None = None,
) -> dict | None:
    """第 3 章 AI 主生成（风险分析表）。

    Returns:
        {"rows": [{风险类别, 产生风险原因, 事故/伤害, 涉及工序, 管控措施, 伤害对象}],
         "warnings": [str]}；AI 失败/校验不过返回 None（回退规则渲染）。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    context = _build_chapter_context(
        extracted, meta, ref_tables, kb, include_tables=["risk"]
    )
    user_content = (
        "请分析本岗位主要风险并输出 JSON 对象。\n\n" f"工序与风险上下文：\n{context}"
    )
    rows: list[dict] | None = None
    try:
        with ai_audit_scope(
            scenario="sop_generation",
            channel="web",
            resource_type="regulation",
            resource_id=regulation_id,
            extra={"chapter": 3, "kind": "risk_analysis"},
        ):
            ai = create_ai_service("text")
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": SOP_CH3_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                expected_keys=["risk_rows"],
                temperature=0.1,
            )
        rows = validate_ch3(result)
    except Exception as exc:  # noqa: BLE001 — 单章失败回退规则，不阻塞
        logger.warning("ch3 AI 生成失败：%s", exc)
    if not rows:
        return None
    return {"rows": rows, "warnings": []}


async def generate_ch5_params(
    *,
    extracted,
    ref_tables: dict,
    kb: dict | None,
    raw_text: str,
    meta: dict | None = None,
    regulation_id: uuid.UUID | None = None,
) -> dict | None:
    """第 5 章 AI 主生成（工艺控制参数表）+ 数值溯源自检。

    Returns:
        {"rows": [{阶段, 参数, 正常范围, 报警值, 联锁值, 偏离后果, 预防措施}],
         "traceability": float, "warnings": [str]}；AI 失败/校验不过返回 None。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    context = _build_chapter_context(
        extracted, meta, ref_tables, kb, include_tables=["parameters"]
    )
    user_content = (
        "请生成工艺控制参数表并输出 JSON 对象。\n\n" f"工序与参数上下文：\n{context}"
    )
    rows: list[dict] | None = None
    try:
        with ai_audit_scope(
            scenario="sop_generation",
            channel="web",
            resource_type="regulation",
            resource_id=regulation_id,
            extra={"chapter": 5, "kind": "control_parameters"},
        ):
            ai = create_ai_service("text")
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": SOP_CH5_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                expected_keys=["control_parameters"],
                temperature=0.1,
            )
        rows = validate_ch5(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ch5 AI 生成失败：%s", exc)
    if not rows:
        return None

    ratio, untraceable = ch5_traceability(rows, raw_text, (kb or {}).get("msds"))
    warnings = [f"ch5 参数数值无法溯源：{u['参数']}（{u['正常范围']}）" for u in untraceable]
    if ratio < 0.8:
        warnings.append(f"ch5 数值溯源 {ratio:.0%} < 80%，请检查参数数值来源")
        logger.warning("ch5 数值溯源 %s < 80%%", ratio)
    return {"rows": rows, "traceability": round(ratio, 3), "warnings": warnings}


async def generate_ch6_safety(
    *,
    extracted,
    kb: dict | None,
    meta: dict | None = None,
    regulation_id: uuid.UUID | None = None,
) -> dict | None:
    """第 6 章 AI 主生成（岗位安全操作要求）。

    Returns:
        {"rows": [{阶段, 类型, 要求}], "warnings": [str]}；AI 失败/校验不过返回 None。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    context = _build_chapter_context(
        extracted, meta, {}, kb, include_tables=[]
    )
    user_content = (
        "请生成岗位安全操作要求并输出 JSON 对象。\n\n" f"工序与安全上下文：\n{context}"
    )
    rows: list[dict] | None = None
    try:
        with ai_audit_scope(
            scenario="sop_generation",
            channel="web",
            resource_type="regulation",
            resource_id=regulation_id,
            extra={"chapter": 6, "kind": "safety_requirements"},
        ):
            ai = create_ai_service("text")
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": SOP_CH6_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                expected_keys=["safety_requirements"],
                temperature=0.1,
            )
        rows = validate_ch6(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ch6 AI 生成失败：%s", exc)
    if not rows:
        return None
    return {"rows": rows, "warnings": []}


async def generate_ch8_abnormal(
    *,
    extracted,
    ref_tables: dict,
    kb: dict | None,
    meta: dict | None = None,
    regulation_id: uuid.UUID | None = None,
) -> dict | None:
    """第 8 章 AI 主生成（异常工况处置）。

    Returns:
        {"rows": [{阶段, 异常工况, 异常工况描述, 处置步骤, 预防措施}], "warnings": [str]}；
        AI 失败/校验不过返回 None。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    context = _build_chapter_context(
        extracted, meta, ref_tables, kb, include_tables=["abnormal"]
    )
    user_content = (
        "请生成异常工况处置表并输出 JSON 对象。\n\n" f"工序与异常上下文：\n{context}"
    )
    rows: list[dict] | None = None
    try:
        with ai_audit_scope(
            scenario="sop_generation",
            channel="web",
            resource_type="regulation",
            resource_id=regulation_id,
            extra={"chapter": 8, "kind": "abnormal_conditions"},
        ):
            ai = create_ai_service("text")
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": SOP_CH8_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                expected_keys=["abnormal_conditions"],
                temperature=0.1,
            )
        rows = validate_ch8(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ch8 AI 生成失败：%s", exc)
    if not rows:
        return None
    return {"rows": rows, "warnings": []}


async def generate_ch9_selection(
    *,
    extracted,
    ref_tables: dict,
    kb: dict | None,
    meta: dict | None = None,
    regulation_id: uuid.UUID | None = None,
) -> dict | None:
    """第 9 章 AI 应急类型选型（内容来自既有 TEMPLATES，AI 只选类型）。

    Returns:
        {"types": [应急类型, ...], "warnings": [str]}；AI 失败/校验不过返回 None
        （回退规则检测选型）。
    """
    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    # ch9 只做选型，上下文给轻量版（风险表 + MSDS 化学品物性即可）
    context = _build_chapter_context(
        extracted, meta, ref_tables, kb,
        include_tables=["risk"], include_msds=True, max_chars=8000,
    )
    user_content = (
        "请从候选集中选择本岗位适用的应急类型并输出 JSON 对象。\n\n"
        f"工艺与风险上下文：\n{context}"
    )
    types: list[str] | None = None
    try:
        with ai_audit_scope(
            scenario="sop_generation",
            channel="web",
            resource_type="regulation",
            resource_id=regulation_id,
            extra={"chapter": 9, "kind": "emergency_selection"},
        ):
            ai = create_ai_service("text")
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": SOP_CH9_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                expected_keys=["emergency_types"],
                temperature=0.1,
            )
        types = validate_ch9(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ch9 AI 选型失败：%s", exc)
    if not types:
        return None
    return {"types": types, "warnings": []}
