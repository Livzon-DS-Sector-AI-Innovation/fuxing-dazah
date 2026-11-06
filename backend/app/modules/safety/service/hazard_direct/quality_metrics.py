"""① 隐患 AI 识别 —— 质量指标纯函数（唯一事实源）。

从 ``scripts/hazard_ai_quality_replay.py`` 原样抽取（P1-4 D1）：离线 replay
脚本与质量看板（``quality_dashboard``）共用同一套指标逻辑，**不重写、不并行
实现**。口径说明（三套 JSON 合法率口径、占位率两口径）见 replay 脚本头部。

全部为纯函数：吃审计行 dict（``created_at``/``input_text``/``output_text``/
``status``/``degradation_level``/``extra``），不碰 DB / 网络 / Redis。

与线上判定同源：
    - JSON 修复链 ``ai_audit.json_repair``；
    - 质量闸门 ``hazard_direct.quality_gate``；
    - 引用证据 ``ai_hazard_identification.citation_evidence``。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from app.modules.safety.ai_audit.json_repair import (
    repair_json_object,
    strip_fences,
)
from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
    verify_citations,
)
from app.modules.safety.ai_hazard_identification.citations import (
    is_placeholder_basis,
    is_placeholder_variant,
)
from app.modules.safety.service.hazard_direct.quality_gate import (
    QualityGateError,
    ensure_output,
)

SCENARIO = "hazard_identification"
VISION_MARKER = "[附图"

# 知识库 markdown 在 prompt 中的边界（见 ai_hazard_identification.prompts.build_full_prompt）
KNOWLEDGE_HEADER = "## 相关法规条款"
KNOWLEDGE_END = "\n\n---\n\n## 工作规则"

def extract_prompt_text(input_text: str | None) -> str:
    """审计 ``input_text``（messages JSON 序列化）→ 拼接全部 user content 文本。

    审计写入格式见 ``ai_audit.audited_client``：``json.dumps(messages)``。
    视觉调用的 content 可能是 block 列表（text / image_url），这里只取文本块。
    坏 JSON / 空输入返回 ``""``（不抛）。
    """
    if not input_text:
        return ""
    try:
        payload = json.loads(input_text)
    except (json.JSONDecodeError, ValueError):
        return ""
    if isinstance(payload, dict):
        messages: list[Any] = [payload]
    elif isinstance(payload, list):
        messages = payload
    else:
        return ""

    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            if content:
                parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        parts.append(text)
    return "\n\n".join(parts)


def extract_knowledge_markdown(prompt_text: str | None) -> str | None:
    """从拼装后的 prompt 截取本轮「法规知识库」markdown；缺失返回 None。

    ``build_full_prompt`` 把知识库上下文注入在 ``## 工作规则`` 之前，格式为::

        ## 相关法规条款
        [1] 《doc》 article
        正文…
        <空行>---<空行>
        ## 工作规则

    截取范围 = ``## 相关法规条款`` → ``\\n\\n---\\n\\n## 工作规则`` 之前（含知识库
    内部 chunk 之间的 ``---`` 分隔）。旧 prompt / RAG 降级 / 截断样本 → None。
    """
    if not prompt_text:
        return None
    start = prompt_text.find(KNOWLEDGE_HEADER)
    if start < 0:
        return None
    end = prompt_text.find(KNOWLEDGE_END, start + len(KNOWLEDGE_HEADER))
    if end < 0:
        return None
    markdown = prompt_text[start:end].strip()
    return markdown or None


def citation_evidence_from_input(input_text: str | None) -> CitationEvidence | None:
    """审计 ``input_text`` → 本轮知识库证据；坏 JSON / 缺知识库 → None（不抛）。

    与 ① 插件 / 写回闸门共用 ``citation_evidence.CitationEvidence`` 事实源，
    保证离线重放与线上判定同口径。
    """
    prompt_text = extract_prompt_text(input_text)
    markdown = extract_knowledge_markdown(prompt_text)
    if markdown is None:
        return None
    try:
        evidence = CitationEvidence.from_markdown(markdown)
    except (TypeError, ValueError):  # 证据解析失败按「无证据」处理，不影响重放
        return None
    return None if evidence.is_empty else evidence


def strict_parse(output_text: str | None) -> dict[str, Any] | None:
    """「现状」解析口径：剥 markdown 围栏 + json.loads（无本地修复）。"""
    if not output_text:
        return None
    try:
        parsed = json.loads(strip_fences(output_text))
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def gate_decision(
    parsed: dict[str, Any] | None,
    *,
    evidence: CitationEvidence | None = None,
) -> tuple[bool | None, str | None]:
    """A3 输出质量闸门判定：返回 (是否通过, 拒绝分类)。无法解析时分类 json_invalid。

    ``evidence`` 非空时启用 C2 引用来源强校验（零可验证 → ``invalid_citation``）。
    """
    if parsed is None:
        return None, "json_invalid"
    try:
        ensure_output(
            {"major_hazard_basis": parsed.get("major_hazard_basis", "")},
            evidence=evidence,
        )
    except QualityGateError as exc:
        return False, exc.category
    return True, None


def analyze_output(
    output_text: str | None,
    *,
    evidence: CitationEvidence | None = None,
) -> dict[str, Any]:
    """单条 output_text 的 A1/A3/C2 指标（``evidence=None`` 时向后兼容旧行为）。

    ``evidence=None`` 即 P0-A 旧闸门语义（只判精确占位标记 / empty /
    no_citation，不判占位变体、不判引用可验证）；``--legacy-gate`` 口径由
    :func:`analyze_rows` / ``_chain_summary`` 在调用侧置 ``evidence=None`` 实现。
    """
    strict = strict_parse(output_text)
    repair = repair_json_object(output_text or "")
    repaired_data = repair.data if isinstance(repair.data, dict) else None
    parsed = strict if strict is not None else repaired_data

    gate_pass, gate_category = gate_decision(parsed, evidence=evidence)
    basis = str((parsed or {}).get("major_hazard_basis") or "")
    basis_text = basis.strip()
    # C2 引用报告（与规则引擎/闸门同源）；无证据时为 None（不改变旧口径）
    report = verify_citations(basis, evidence) if evidence is not None else None
    return {
        "json_valid_before": strict is not None,
        "json_valid_after": parsed is not None,
        "repaired": strict is None and repaired_data is not None,
        "repair_stages": list(repair.stages),
        "parse_error": repair.error,
        "gate_pass": gate_pass,
        "gate_category": gate_category,
        "placeholder": is_placeholder_basis(basis),
        # C2/C3 维度
        "basis_empty": not basis_text,
        "placeholder_variant": is_placeholder_variant(basis),
        "citation_report": report,
        "citation_zero_verified": bool(
            evidence is not None and basis_text and report is not None
            and not report.has_verified
        ),
    }


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0

# ═══════════════════════════════════════════════════════════════
# P1-1 R5：检索维度聚合 + P0-C 基线对照
# ═══════════════════════════════════════════════════════════════

# P0-C 验收修复基线（2026-11-06，evidence/acceptance-fix.md：30d replay / 505 calls）
P0C_BASELINE: dict[str, Any] = {
    "window": "30d / 505 calls（2026-11-06 P0-C 验收修复）",
    "calls": 505,
    "json_valid_after_rate": 97.0,
    "gate_pass_calls": 266,
    "gate_fail_calls": 224,
    "unit_verified_rate": 95.7,       # 507/530
    "rerun_records": 140,
    "rerun_gate_pass_records": 139,
}
# 引用单元可验证率硬底线（P1-1 spec：不回退 P0-C 基线 → ≥95%）
UNIT_VERIFIED_FLOOR = 95.0


def _extra_dict(row: dict[str, Any]) -> dict[str, Any]:
    """审计行 extra（dict 或 JSON 字符串）→ dict；坏值返回空 dict。"""
    extra = row.get("extra")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (json.JSONDecodeError, ValueError):
            return {}
    return extra if isinstance(extra, dict) else {}


def summarize_retrieval(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """从审计 extra 聚合检索维度（老行无字段优雅降级，不计分母）。"""
    calls_with_meta = 0
    multi_query_calls = 0
    rewrite_hit_calls = 0
    count_sum = 0
    docs: Counter[str] = Counter()
    for row in rows:
        extra = _extra_dict(row)
        if "multi_query_count" not in extra:
            continue
        calls_with_meta += 1
        count = int(extra.get("multi_query_count") or 0)
        count_sum += count
        if count > 1:
            multi_query_calls += 1
        if extra.get("rewrite_hit"):
            rewrite_hit_calls += 1
        for doc in extra.get("retrieval_docs") or []:
            if doc:
                docs[str(doc)] += 1
    return {
        "calls_with_meta": calls_with_meta,
        "multi_query_calls": multi_query_calls,
        "rewrite_hit_calls": rewrite_hit_calls,
        "avg_multi_query_count": (
            round(count_sum / calls_with_meta, 2) if calls_with_meta else 0.0
        ),
        "top_docs": docs.most_common(10),
    }

def baseline_comparison(stats: dict[str, Any]) -> list[dict[str, Any]]:
    """当前指标 vs P0-C 基线（率值方向性对照；单元可验证率带 95% 硬底线）。"""
    totals = stats.get("totals", {})
    citation = stats.get("citation") or {}
    rerun = stats.get("rerun_records") or {}

    def _item(
        metric: str, baseline: float, current: float, floor: float | None = None
    ) -> dict[str, Any]:
        threshold = floor if floor is not None else baseline
        return {
            "metric": metric,
            "baseline": baseline,
            "current": current,
            "floor": floor,
            "ok": bool(current >= threshold),
        }

    items = [
        _item(
            "JSON 修复后合法率",
            P0C_BASELINE["json_valid_after_rate"],
            float(totals.get("json_valid_after_rate") or 0.0),
        ),
        _item(
            "引用单元可验证率",
            P0C_BASELINE["unit_verified_rate"],
            float(citation.get("unit_verified_rate") or 0.0),
            floor=UNIT_VERIFIED_FLOOR,
        ),
    ]
    # 重跑窗口记录级：窗口与基线同量（140 条）才可比，否则标记不可比
    same_window = rerun.get("records") == P0C_BASELINE["rerun_records"]
    items.append(
        {
            "metric": "重跑窗口闸门通过记录",
            "baseline": P0C_BASELINE["rerun_gate_pass_records"],
            "current": rerun.get("gate_pass_records") or 0,
            "floor": None,
            "ok": (
                bool(
                    (rerun.get("gate_pass_records") or 0)
                    >= P0C_BASELINE["rerun_gate_pass_records"]
                )
                if same_window
                else None
            ),
        }
    )
    # 闸门通过数：窗口调用量与基线同量（505 calls）才可比
    same_calls_window = totals.get("calls") == P0C_BASELINE["calls"]
    items.append(
        {
            "metric": "闸门通过调用",
            "baseline": P0C_BASELINE["gate_pass_calls"],
            "current": totals.get("gate_pass_calls") or 0,
            "floor": None,
            "ok": (
                bool(
                    (totals.get("gate_pass_calls") or 0)
                    >= P0C_BASELINE["gate_pass_calls"]
                )
                if same_calls_window
                else None
            ),
        }
    )
    # GT genuine 误拒/误收：硬底线 0（有 GT 对照数据才可比）
    truth = stats.get("ground_truth") or {}
    if truth:
        items.append(
            {
                "metric": "GT genuine 误拒/误收",
                "baseline": 0,
                "current": int(truth.get("wrong_reject_genuine") or 0)
                + int(truth.get("wrong_accept_genuine") or 0),
                "floor": None,
                "ok": bool(
                    not (truth.get("wrong_reject_genuine") or 0)
                    and not (truth.get("wrong_accept_genuine") or 0)
                ),
            }
        )
    return items


def analyze_rows(
    rows: list[dict[str, Any]], *, legacy_gate: bool = False
) -> dict[str, Any]:
    """对审计行集合做 A1/A3/C2 汇总（纯函数）。

    Args:
        rows: 每行含 ``created_at``(str/date)、``input_text``、``output_text``、
              ``status``、``degradation_level``、``extra``（dict 或 JSON 字符串）。
        legacy_gate: True 时 analyze 链强制 ``evidence=None``（P0-A 旧闸门语义，
              ``--legacy-gate`` 用）；默认 False = C2 新口径（引用证据强校验）。

    占位率两口径（字段来源不同，勿混用，spec C3）：
    - ``totals.placeholder_rate``（P0-A 旧口径）：精确占位标记 / **全量 calls**；
    - ``citation.placeholder_variant_rate``（C2 新口径）：占位变体（含精确口径）
      / **有证据调用 calls_with_evidence**。
    """
    totals = {
        "calls": len(rows),
        "vision_calls": 0,
        "text_calls": 0,
        "json_valid_before": 0,
        "json_valid_after": 0,
        "repaired_recovered": 0,
        "gate_pass_calls": 0,
        "gate_fail_calls": 0,
        "gate_unparseable_calls": 0,
        "placeholder_calls": 0,
        "degraded_calls": 0,
    }
    # C2/C3 引用可验证性汇总（证据 = 审计 input_text 还原的本轮知识库）
    citation_totals = {
        "calls_with_evidence": 0,
        "calls_has_verified": 0,
        "calls_zero_verified": 0,
        "units_total": 0,
        "units_verified": 0,
        "placeholder_variant_calls": 0,
    }
    stage_counter: Counter[str] = Counter()
    gate_categories: Counter[str] = Counter()
    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "calls": 0,
            "json_before": 0,
            "json_after": 0,
            "repaired": 0,
            "gate_pass": 0,
            "placeholder": 0,
            "citation_ok": 0,
            "placeholder_variant": 0,
        }
    )
    # 重跑窗口自动识别：按天聚合并取调用数最多的一天
    day_calls: Counter[str] = Counter()
    record_calls: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        created = str(row.get("created_at") or "")
        day = created[:10]
        day_calls[day] += 1
        input_text = str(row.get("input_text") or "")
        is_vision = VISION_MARKER in input_text
        evidence = (
            None if legacy_gate else citation_evidence_from_input(input_text)
        )
        metrics = analyze_output(row.get("output_text"), evidence=evidence)
        totals["vision_calls" if is_vision else "text_calls"] += 1
        if metrics["json_valid_before"]:
            totals["json_valid_before"] += 1
        if metrics["json_valid_after"]:
            totals["json_valid_after"] += 1
        if metrics["repaired"]:
            totals["repaired_recovered"] += 1
            for stage in metrics["repair_stages"]:
                stage_counter[stage] += 1
        if metrics["gate_pass"] is True:
            totals["gate_pass_calls"] += 1
        elif metrics["gate_pass"] is False:
            totals["gate_fail_calls"] += 1
            gate_categories[str(metrics["gate_category"])] += 1
        else:
            totals["gate_unparseable_calls"] += 1
        if metrics["placeholder"]:
            totals["placeholder_calls"] += 1
        report = metrics["citation_report"]
        if evidence is not None and report is not None:
            citation_totals["calls_with_evidence"] += 1
            if report.has_verified:
                citation_totals["calls_has_verified"] += 1
            else:
                citation_totals["calls_zero_verified"] += 1
            citation_totals["units_total"] += report.total_units
            citation_totals["units_verified"] += report.verified_units
            if report.has_verified:
                by_day[day]["citation_ok"] += 1
            if metrics["placeholder_variant"]:
                citation_totals["placeholder_variant_calls"] += 1
                by_day[day]["placeholder_variant"] += 1
        degradation = row.get("degradation_level")
        if degradation not in (None, "", "ragplus"):
            totals["degraded_calls"] += 1
        slot = by_day[day]
        slot["calls"] += 1
        slot["json_before"] += int(metrics["json_valid_before"])
        slot["json_after"] += int(metrics["json_valid_after"])
        slot["repaired"] += int(metrics["repaired"])
        slot["gate_pass"] += int(metrics["gate_pass"] is True)
        slot["placeholder"] += int(metrics["placeholder"])
        record_id = record_id_from_extra(row.get("extra"))
        if record_id:
            record_calls[record_id].append((day, metrics))

    rerun_day = ""
    if day_calls:
        rerun_day = day_calls.most_common(1)[0][0]
    rerun_record_ids = {
        record_id
        for record_id, calls in record_calls.items()
        if any(day == rerun_day for day, _ in calls)
    }
    gate_records_pass = sum(
        1
        for record_id in rerun_record_ids
        if any(
            day == rerun_day and metrics["gate_pass"] is True
            for day, metrics in record_calls[record_id]
        )
    )
    summary = {
        "totals": {
            **totals,
            "json_valid_before_rate": rate(
                totals["json_valid_before"], totals["calls"]
            ),
            "json_valid_after_rate": rate(
                totals["json_valid_after"], totals["calls"]
            ),
            "gate_pass_rate": rate(totals["gate_pass_calls"], totals["calls"]),
            "placeholder_rate": rate(totals["placeholder_calls"], totals["calls"]),
        },
        "citation": {
            **citation_totals,
            "call_verified_rate": rate(
                citation_totals["calls_has_verified"],
                citation_totals["calls_with_evidence"],
            ),
            "unit_verified_rate": rate(
                citation_totals["units_verified"],
                citation_totals["units_total"],
            ),
            # C2 新口径：变体占位率分母 = 有证据调用（与旧 placeholder_rate 不同源）
            "placeholder_variant_rate": rate(
                citation_totals["placeholder_variant_calls"],
                citation_totals["calls_with_evidence"],
            ),
        },
        "legacy_gate": legacy_gate,
        "vision": _chain_summary(rows, vision=True, legacy_gate=legacy_gate),
        "text": _chain_summary(rows, vision=False, legacy_gate=legacy_gate),
        "retrieval": summarize_retrieval(rows),
        "repair_stages": dict(stage_counter),
        "gate_categories": dict(gate_categories),
        "by_day": {day: dict(slot) for day, slot in sorted(by_day.items())},
        "rerun_day": rerun_day,
        "rerun_records": {
            "records": len(rerun_record_ids),
            "calls": day_calls.get(rerun_day, 0),
            "gate_pass_records": gate_records_pass,
            "gate_fail_records": len(rerun_record_ids) - gate_records_pass,
        },
    }
    return summary

def _chain_summary(
    rows: list[dict[str, Any]], *, vision: bool, legacy_gate: bool = False
) -> dict[str, Any]:
    """视觉/文本链路拆分：JSON 合法率 + C3 引用可验证性（无证据调用不计分母）。"""
    subset = [
        row
        for row in rows
        if (VISION_MARKER in str(row.get("input_text") or "")) is vision
    ]
    before = after = repaired = 0
    calls_with_evidence = calls_has_verified = 0
    units_total = units_verified = 0
    for row in subset:
        evidence = (
            None
            if legacy_gate
            else citation_evidence_from_input(str(row.get("input_text") or ""))
        )
        metrics = analyze_output(row.get("output_text"), evidence=evidence)
        before += int(metrics["json_valid_before"])
        after += int(metrics["json_valid_after"])
        repaired += int(metrics["repaired"])
        report = metrics["citation_report"]
        if evidence is not None and report is not None:
            calls_with_evidence += 1
            if report.has_verified:
                calls_has_verified += 1
            units_total += report.total_units
            units_verified += report.verified_units
    return {
        "calls": len(subset),
        "json_valid_before": before,
        "json_valid_after": after,
        "repaired": repaired,
        "json_valid_before_rate": rate(before, len(subset)),
        "json_valid_after_rate": rate(after, len(subset)),
        # C3 引用指标（分母 = 该链路有证据调用）
        "calls_with_evidence": calls_with_evidence,
        "calls_has_verified": calls_has_verified,
        "units_total": units_total,
        "units_verified": units_verified,
        "call_verified_rate": rate(calls_has_verified, calls_with_evidence),
        "unit_verified_rate": rate(units_verified, units_total),
    }


def record_id_from_extra(extra: Any) -> str:
    """从审计 extra（dict 或 JSON 字符串）取 bitable_record_id。"""
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (json.JSONDecodeError, ValueError):
            return ""
    if isinstance(extra, dict):
        return str(extra.get("bitable_record_id") or "")
    return ""
