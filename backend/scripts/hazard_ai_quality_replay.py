"""① 隐患 AI 识别 —— 离线质量回归重放（只读，A1/A3/C2/C3 验收证据脚本）。

用途（A 组验收）：
    重放 ``safety.ai_call_audits`` 中近 N 天 ``scenario='hazard_identification'`` 的
    ``output_text``，用当前代码里的**本地 JSON 修复链**（``ai_audit.json_repair``）
    与**质量闸门**（``hazard_direct.quality_gate``）离线判定，输出：
      - JSON 合法率：现状（仅剥围栏 + json.loads）vs 修复后（A1），总体/视觉/文本；
      - 修复阶段分布（trailing_comma / slice_object / fullwidth_quotes …）；
      - A3 质量闸门通过/拒绝分类（placeholder_basis / no_citation / invalid_citation …）；
      - C2/C3 引用可验证性：从审计 ``input_text``（messages JSON）解析本轮注入的
        「法规知识库」markdown → ``CitationEvidence``，计算引用可验证率
        （调用级 + 引用单元级）、零可验证调用、占位变体调用；
      - 占位依据率与按天趋势；
      - 重跑窗口按 record 聚合的闸门判定（优先 ``extra.round_id`` 缺失的重跑窗口行）；
      - 存在 ``/tmp/rerun_results.jsonl`` 时附 197 条 ground truth 一致性对照
        （误拒拆「已知标签修正」与「真误拒」，误收保留 A1 救援单列）。

安全边界：
    - **只读**：连接后 `SET default_transaction_read_only = on`；
    - 只 SELECT，不写库、不调 AI、不访问 Bitable、无其它网络请求；
    - 不依赖 /tmp 历史文件（存在时仅作额外样本）。

口径说明（T3）：
    本脚本「现状合法」= 剥 markdown 围栏后 `json.loads`，**不等于**审计
    `extra.json_valid`（审计口径是「原文可直接解析、不剥围栏」），也不等于
    「修复后合法」；三套口径不可直接互比，看板/报告引用时须注明。

用法（cwd=backend）：:

    .venv/bin/python scripts/hazard_ai_quality_replay.py --days 30
    .venv/bin/python scripts/hazard_ai_quality_replay.py --days 30 --json
    .venv/bin/python scripts/hazard_ai_quality_replay.py --days 30 --legacy-gate
    .venv/bin/python scripts/hazard_ai_quality_replay.py --out /tmp/replay.md

DSN 解析顺序：``--dsn`` > ``DATABASE_URL`` 环境变量 > ``backend/.env.development``
中的 ``DATABASE_URL``。``postgresql+asyncpg://`` 会自动转成 asyncpg 可用 DSN。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# 允许从 backend/ 目录直接运行（与 /tmp 重跑脚本同款）
sys.path.insert(0, os.getcwd())

from app.modules.safety.ai_audit.json_repair import (  # noqa: E402
    repair_json_object,
    strip_fences,
)
from app.modules.safety.ai_hazard_identification.citation_evidence import (  # noqa: E402
    CitationEvidence,
    verify_citations,
)
from app.modules.safety.ai_hazard_identification.citations import (  # noqa: E402
    is_placeholder_basis,
    is_placeholder_variant,
)
from app.modules.safety.service.hazard_direct.quality_gate import (  # noqa: E402
    QualityGateError,
    ensure_output,
)

SCENARIO = "hazard_identification"
GROUND_TRUTH_FILE = Path("/tmp/rerun_results.jsonl")
VISION_MARKER = "[附图"

# 知识库 markdown 在 prompt 中的边界（见 ai_hazard_identification.prompts.build_full_prompt）
KNOWLEDGE_HEADER = "## 相关法规条款"
KNOWLEDGE_END = "\n\n---\n\n## 工作规则"


# ═══════════════════════════════════════════════════════════════
# 纯函数（可单测，不碰 DB）
# ═══════════════════════════════════════════════════════════════


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


def strict_parse(output_text: str | None) -> dict | None:
    """「现状」解析口径：剥 markdown 围栏 + json.loads（无本地修复）。"""
    if not output_text:
        return None
    try:
        parsed = json.loads(strip_fences(output_text))
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def gate_decision(
    parsed: dict | None,
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
    legacy_gate: bool = False,
) -> dict[str, Any]:
    """单条 output_text 的 A1/A3/C2 指标（``evidence=None`` 时向后兼容旧行为）。

    ``legacy_gate=True`` 时强制 ``evidence=None``（P0-A 旧闸门语义：只判精确
    占位标记 / empty / no_citation，不判占位变体、不判引用可验证），用于
    ``--legacy-gate`` 复现旧口径；默认 False = C2 新口径。
    """
    if legacy_gate:
        evidence = None
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


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


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
        record_id = _record_id(row.get("extra"))
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
            "json_valid_before_rate": _rate(
                totals["json_valid_before"], totals["calls"]
            ),
            "json_valid_after_rate": _rate(
                totals["json_valid_after"], totals["calls"]
            ),
            "gate_pass_rate": _rate(totals["gate_pass_calls"], totals["calls"]),
            "placeholder_rate": _rate(totals["placeholder_calls"], totals["calls"]),
        },
        "citation": {
            **citation_totals,
            "call_verified_rate": _rate(
                citation_totals["calls_has_verified"],
                citation_totals["calls_with_evidence"],
            ),
            "unit_verified_rate": _rate(
                citation_totals["units_verified"],
                citation_totals["units_total"],
            ),
            # C2 新口径：变体占位率分母 = 有证据调用（与旧 placeholder_rate 不同源）
            "placeholder_variant_rate": _rate(
                citation_totals["placeholder_variant_calls"],
                citation_totals["calls_with_evidence"],
            ),
        },
        "legacy_gate": legacy_gate,
        "vision": _chain_summary(rows, vision=True, legacy_gate=legacy_gate),
        "text": _chain_summary(rows, vision=False, legacy_gate=legacy_gate),
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
        "json_valid_before_rate": _rate(before, len(subset)),
        "json_valid_after_rate": _rate(after, len(subset)),
        # C3 引用指标（分母 = 该链路有证据调用）
        "calls_with_evidence": calls_with_evidence,
        "calls_has_verified": calls_has_verified,
        "units_total": units_total,
        "units_verified": units_verified,
        "call_verified_rate": _rate(calls_has_verified, calls_with_evidence),
        "unit_verified_rate": _rate(units_verified, units_total),
    }


def _record_id(extra: Any) -> str:
    """从审计 extra（dict 或 JSON 字符串）取 bitable_record_id。"""
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (json.JSONDecodeError, ValueError):
            return ""
    if isinstance(extra, dict):
        return str(extra.get("bitable_record_id") or "")
    return ""


def _round_id(extra: Any) -> str:
    """从审计 extra 取 ``round_id``（生产轮有；离线重跑窗口行没有）。"""
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (json.JSONDecodeError, ValueError):
            return ""
    if isinstance(extra, dict):
        return str(extra.get("round_id") or "")
    return ""


def _select_window_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """选 ground truth 对照窗口：优先重跑窗口行，否则退回调用数最多的一天。

    返回 ``(rows, window)``，window ∈ ``{"rerun", "busiest_day", "empty"}``。

    重跑窗口行判定标记 = ``extra.round_id`` 缺失（离线重跑不经过轮次调度）。
    注意：**历史生产调用同样没有该字段**（round_id 是近期才加入审计 extra 的），
    因此不能把「全 30 天无 round_id 行」都当成重跑窗口；这里取「缺 round_id
    调用数最多的一天」作为重跑窗口（离线重跑集中单日、调用量远大于生产日），
    避免历史调用污染 ground truth 对照。若所有行都带 round_id（无该标记）
    → 退回按天最多调用日（P0-A 旧口径）。
    """
    no_round_rows = [row for row in rows if not _round_id(row.get("extra"))]
    if no_round_rows:
        no_round_day_calls: Counter[str] = Counter(
            str(row.get("created_at") or "")[:10] for row in no_round_rows
        )
        rerun_day = no_round_day_calls.most_common(1)[0][0]
        return [
            row
            for row in no_round_rows
            if str(row.get("created_at") or "")[:10] == rerun_day
        ], "rerun"
    day_calls: Counter[str] = Counter(
        str(row.get("created_at") or "")[:10] for row in rows
    )
    if not day_calls:
        return [], "empty"
    busiest_day = day_calls.most_common(1)[0][0]
    return [
        row
        for row in rows
        if str(row.get("created_at") or "")[:10] == busiest_day
    ], "busiest_day"


def _is_label_correction(metrics: dict[str, Any]) -> bool:
    """被拒记录是否属已知 ground truth 标签缺陷（truth=success 但依据零可验证/纯占位）。

    判定依据：
    - 命中占位文案（含 P0-A 精确口径漏掉的变体）且无可验证引用 → 历史标签缺陷
      （如 ``recvzYTsyC94kz``：basis 为「知识库中无《…》相应条文，待人工补充」）；
    - 有证据但依据非空且零条引用可验证 → 同上（GT 把不可溯源依据标成 success）。
    空依据 / 无证据时不归入标签修正，按真误拒统计。
    """
    report = metrics.get("citation_report")
    if metrics.get("placeholder_variant"):
        return report is None or not report.has_verified
    if report is None:
        return False
    return not report.has_verified and not metrics.get("basis_empty", False)


def compare_ground_truth(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """与 197 条重跑 ground truth 做一致性对照（存在 /tmp 样本时）。

    行筛选（P0-C C3）：优先只取「重跑窗口」行（``extra.round_id`` 缺失，
    取其中调用数最多的一天，隔离历史生产调用），避免生产轮调用污染
    ground truth 对照；识别不到重跑行时退回按天最多调用日。
    误拒（truth=success 但闸门拒绝）拆为 ``wrong_reject_label_correction``
    （依据零可验证/纯占位 → 已知标签缺陷，单列说明）与 ``wrong_reject_genuine``；
    误收（truth=failed 但闸门通过）保留 A1 修复救援单列，另单列「占位口径切换」
    （旧 GT 由无条件拒绝占位的旧重跑脚本生成）。同时输出 140 条历史成功样本的
    引用回归（记录级/单元级可验证率、占位注记双口径），以及 ``legacy`` 子段
    ——**旧闸门口径**（``evidence=None``，P0-A 语义）的 wrong_accept/wrong_reject
    与 A1 救援归因，供新旧口径并列对照 / ``--legacy-gate`` 复现（不依赖 /tmp）。
    """
    if not GROUND_TRUTH_FILE.exists():
        return None
    try:
        raw_lines = GROUND_TRUTH_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    truths: dict[str, str] = {}
    truth_basis: dict[str, str] = {}
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        record_id = str(item.get("record_id") or "")
        if record_id:
            truths[record_id] = str(item.get("status") or "")
            # 同一记录多行时取最后一行（最终结论）的 basis_new
            truth_basis[record_id] = str(item.get("basis_new") or "")
    if not truths:
        return None

    window_rows, window = _select_window_rows(rows)
    gate_by_record: dict[str, bool] = {}
    rescue_by_record: dict[str, bool] = {}
    placeholder_note_by_record: dict[str, bool] = {}
    evidence_by_record: dict[str, CitationEvidence] = {}
    rejected_metrics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # legacy 旧闸门口径（evidence=None，P0-A 语义）：只判精确占位/empty/no_citation
    legacy_gate_by_record: dict[str, bool] = {}
    legacy_rescue_by_record: dict[str, bool] = {}
    for row in window_rows:
        record_id = _record_id(row.get("extra"))
        if not record_id or record_id not in truths:
            continue
        evidence = citation_evidence_from_input(str(row.get("input_text") or ""))
        if evidence is not None:
            evidence_by_record[record_id] = evidence
        metrics = analyze_output(row.get("output_text"), evidence=evidence)
        if metrics["gate_pass"] is True:
            gate_by_record[record_id] = True
            report = metrics["citation_report"]
            # 占位注记 + 至少一条可验证引用 → 新口径放行（spec C2 明示可接受）；
            # 旧重跑脚本（GT 生成方）会无条件拒绝占位文案，故这类记录在 GT 里是
            # failed 但新口径通过 —— 属 GT 口径差异，单列归因，不混入真语义不一致。
            if (
                metrics.get("placeholder_variant")
                and report is not None
                and report.has_verified
            ):
                placeholder_note_by_record[record_id] = True
            if metrics["repaired"]:
                rescue_by_record[record_id] = True
        else:
            gate_by_record.setdefault(record_id, False)
            rejected_metrics[record_id].append(metrics)
        legacy_metrics = analyze_output(row.get("output_text"), evidence=None)
        if legacy_metrics["gate_pass"] is True:
            legacy_gate_by_record[record_id] = True
            if legacy_metrics["repaired"]:
                legacy_rescue_by_record[record_id] = True
        else:
            legacy_gate_by_record.setdefault(record_id, False)

    wrong_accept = [
        record_id
        for record_id, passed in gate_by_record.items()
        if passed and truths.get(record_id) != "success"
    ]
    wrong_reject = [
        record_id
        for record_id, passed in gate_by_record.items()
        if not passed and truths.get(record_id) == "success"
    ]
    # 误收归因（按优先级单列，互斥）：
    # 1) A1 修复救援（历史因 JSON 畸形判失败、本地修复后可解析且引用合规，属预期收益）；
    # 2) 占位口径切换（旧 GT 由「无条件拒绝占位文案」的旧重跑脚本生成，新口径按 spec
    #    C2 允许「占位注记 + 可验证引用」，属 GT 标签口径差异）；
    # 3) 其余才算真正的语义不一致（wrong_accept_genuine）。
    rescued = [record_id for record_id in wrong_accept if rescue_by_record.get(record_id)]
    rescued_set = set(rescued)
    placeholder_accept = [
        record_id
        for record_id in wrong_accept
        if record_id not in rescued_set and placeholder_note_by_record.get(record_id)
    ]
    placeholder_accept_set = set(placeholder_accept)
    genuine = [
        record_id
        for record_id in wrong_accept
        if record_id not in rescued_set and record_id not in placeholder_accept_set
    ]
    # 误拒归因：known GT 标签缺陷（零可验证/纯占位却被标 success）单列，不混入真误拒
    label_correction = [
        record_id
        for record_id in wrong_reject
        if any(
            _is_label_correction(metrics)
            for metrics in rejected_metrics.get(record_id, [])
        )
    ]
    label_correction_set = set(label_correction)
    genuine_reject = [
        record_id for record_id in wrong_reject if record_id not in label_correction_set
    ]
    # legacy 旧口径归因（P0-A：A1 救援单列；无引用可验证概念，故无 label correction 拆分）
    legacy_wrong_accept = [
        record_id
        for record_id, passed in legacy_gate_by_record.items()
        if passed and truths.get(record_id) != "success"
    ]
    legacy_wrong_reject = [
        record_id
        for record_id, passed in legacy_gate_by_record.items()
        if not passed and truths.get(record_id) == "success"
    ]
    legacy_rescued = [
        record_id
        for record_id in legacy_wrong_accept
        if legacy_rescue_by_record.get(record_id)
    ]
    legacy_rescued_set = set(legacy_rescued)
    legacy_genuine = [
        record_id
        for record_id in legacy_wrong_accept
        if record_id not in legacy_rescued_set
    ]
    # 140 条历史成功样本的引用回归（spec 验收口径：记录级 ≥1 条可验证 / 单元级可验证率）
    success_ids = [rid for rid, status in truths.items() if status == "success"]
    success_verified = 0
    success_units_total = 0
    success_units_verified = 0
    success_placeholder_note = 0
    success_placeholder_pure = 0
    for record_id in success_ids:
        evidence = evidence_by_record.get(record_id)
        basis = truth_basis.get(record_id, "")
        if evidence is None:
            continue
        report = verify_citations(basis, evidence)
        success_units_total += report.total_units
        success_units_verified += report.verified_units
        if report.has_verified:
            success_verified += 1
        variant = is_placeholder_variant(basis)
        if variant:
            success_placeholder_note += 1
            if not report.has_verified:
                success_placeholder_pure += 1
    return {
        "window": window,
        "ground_truth_records": len(truths),
        "replayed_records": len(gate_by_record),
        "wrong_accept": len(wrong_accept),
        "wrong_reject": len(wrong_reject),
        "wrong_reject_label_correction": len(label_correction),
        "wrong_reject_genuine": len(genuine_reject),
        "wrong_accept_repaired_rescue": len(rescued),
        "wrong_accept_placeholder_note": len(placeholder_accept),
        "wrong_accept_genuine": len(genuine),
        "wrong_accept_ids": rescued + placeholder_accept + genuine,
        "wrong_reject_ids": wrong_reject[:10],
        "wrong_reject_label_correction_ids": label_correction[:10],
        "wrong_reject_genuine_ids": genuine_reject[:10],
        # 140 条历史成功样本引用回归（GT 的 basis_new × 审计 input_text 证据）
        "success_records": len(success_ids),
        "success_citation_verified": success_verified,
        "success_citation_units_total": success_units_total,
        "success_citation_units_verified": success_units_verified,
        "success_placeholder_note": success_placeholder_note,
        "success_placeholder_pure": success_placeholder_pure,
        # 旧闸门口径（evidence=None / P0-A 语义）：供 --legacy-gate 复现与新旧并列对照
        "legacy": {
            "window": window,
            "replayed_records": len(legacy_gate_by_record),
            "wrong_accept": len(legacy_wrong_accept),
            "wrong_reject": len(legacy_wrong_reject),
            "wrong_accept_repaired_rescue": len(legacy_rescued),
            "wrong_accept_genuine": len(legacy_genuine),
            "wrong_accept_ids": legacy_rescued + legacy_genuine,
            "wrong_reject_ids": legacy_wrong_reject[:10],
        },
    }


def rule_regression_from_ground_truth() -> dict[str, Any] | None:
    """对 197 条 ground truth 的成功样本跑当前 RuleEngine（A4 验收证据）。

    只用重跑结果里的 ``basis_new`` + 三个枚举字段重建输出，其余字段给固定合法
    值（只影响非依据类规则）；用于验证「新引用口径下 140 条历史成功样本规则
    error = 0」。存在 /tmp 样本时生效，纯只读。
    """
    if not GROUND_TRUTH_FILE.exists():
        return None
    try:
        raw_lines = GROUND_TRUTH_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    latest: dict[str, dict[str, Any]] = {}
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        record_id = str(item.get("record_id") or "")
        if record_id:
            latest[record_id] = item
    successes = [item for item in latest.values() if item.get("status") == "success"]
    if not successes:
        return None

    from app.modules.safety.ai_hazard_identification.rules import RuleEngine
    from app.modules.safety.ai_hazard_identification.schemas import (
        DefectSubstanceEnum,
        HazardCategoryEnum,
        HazardIdentificationInput,
        HazardIdentificationOutput,
        HazardLevelEnum,
        HazardTypeEnum,
        RectificationSuggestion,
    )

    engine = RuleEngine()
    rule_errors = 0
    error_examples: list[str] = []
    checked = 0
    for item in successes:
        basis = str(item.get("basis_new") or "").strip()
        if not basis:
            continue
        checked += 1
        try:
            output = HazardIdentificationOutput(
                key_defect="合规的隐患描述示例文本用于规则校验",
                hazard_type=HazardTypeEnum(str(item.get("hazard_type") or "unsafe_condition")),
                hazard_category=HazardCategoryEnum(
                    str(item.get("hazard_category") or "equipment")
                ),
                hazard_level=HazardLevelEnum(str(item.get("hazard_level") or "general")),
                rectification_suggestion=RectificationSuggestion(
                    corrective="由责任部门在3日内完成整改并组织复查验收，记录留档备查。",
                    preventive="将该部位纳入班组日常巡检清单，每月复核一次并开展专项培训。",
                ),
                major_hazard_basis=basis,
                defect_substance=DefectSubstanceEnum.SUBSTANTIVE,
                defect_substance_reasoning="推断链不超过2步，属直接物理风险，判定为实质缺陷。",
            )
            result = engine.validate(
                HazardIdentificationInput(
                    description="隐患描述", department="生产部", location="合成车间"
                ),
                output,
            )
        except Exception:  # noqa: BLE001 — 枚举异常的样本单独计为不通过
            rule_errors += 1
            if len(error_examples) < 5:
                error_examples.append(f"{item.get('record_id')}: schema/enum error")
            continue
        if result.errors:
            rule_errors += 1
            if len(error_examples) < 5:
                error_examples.append(f"{item.get('record_id')}: {result.errors[0][:100]}")
    return {
        "checked_records": checked,
        "rule_errors": rule_errors,
        "error_examples": error_examples,
    }


# ═══════════════════════════════════════════════════════════════
# Markdown 渲染
# ═══════════════════════════════════════════════════════════════


def render_markdown(stats: dict[str, Any], *, days: int) -> str:
    totals = stats["totals"]
    vision = stats["vision"]
    text = stats["text"]
    lines = [
        "# ① 隐患 AI 识别离线质量回归（只读重放）",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 数据源：`safety.ai_call_audits`（scenario=`{SCENARIO}`，近 {days} 天，只读）",
        f"- 样本：{totals['calls']} 次调用（视觉 {vision['calls']} / 文本 {text['calls']}）",
        "",
        "## JSON 合法率（A1 本地修复，零额外调用）",
        "",
        "> 口径（T3）：「现状合法」= 剥 markdown 围栏后 `json.loads`；审计",
        "> `extra.json_valid` 是「原文可直接解析、不剥围栏」，两者不可直接对比。",
        "",
        "| 链路 | 调用数 | 现状合法 | 修复后合法 | 修复后提升 | 本地修复数 |",
        "|---|---|---|---|---|---|",
        f"| 视觉 | {vision['calls']} | {vision['json_valid_before_rate']}% | "
        f"{vision['json_valid_after_rate']}% | "
        f"+{round(vision['json_valid_after_rate'] - vision['json_valid_before_rate'], 1)}pp | "
        f"{vision['repaired']} |",
        f"| 文本 | {text['calls']} | {text['json_valid_before_rate']}% | "
        f"{text['json_valid_after_rate']}% | "
        f"+{round(text['json_valid_after_rate'] - text['json_valid_before_rate'], 1)}pp | "
        f"{text['repaired']} |",
        f"| 合计 | {totals['calls']} | {totals['json_valid_before_rate']}% | "
        f"{totals['json_valid_after_rate']}% | "
        f"+{round(totals['json_valid_after_rate'] - totals['json_valid_before_rate'], 1)}pp | "
        f"{totals['repaired_recovered']} |",
        "",
        f"- 修复阶段分布：`{json.dumps(stats['repair_stages'], ensure_ascii=False)}`",
        "",
        "## 质量闸门（A3）",
        "",
        f"- 通过：**{totals['gate_pass_calls']}**（{totals['gate_pass_rate']}%）",
        f"- 拒绝：**{totals['gate_fail_calls']}**（分类：`{json.dumps(stats['gate_categories'], ensure_ascii=False)}`）",
        f"- 不可解析（json_invalid）：{totals['gate_unparseable_calls']}",
        f"- 占位依据调用（P0-A 旧口径：精确占位标记 / 全量 calls）："
        f"{totals['placeholder_calls']}（{totals['placeholder_rate']}%）",
        f"- RAG 降级调用（degradation_level 非 ragplus）：{totals['degraded_calls']}",
        "",
    ]
    citation = stats.get("citation") or {
        "calls_with_evidence": 0,
        "calls_has_verified": 0,
        "calls_zero_verified": 0,
        "units_total": 0,
        "units_verified": 0,
        "call_verified_rate": 0.0,
        "unit_verified_rate": 0.0,
        "placeholder_variant_calls": 0,
        "placeholder_variant_rate": 0.0,
    }
    vision_citation = stats.get("vision") or {}
    text_citation = stats.get("text") or {}
    if stats.get("legacy_gate"):
        lines += [
            "- 运行模式：`--legacy-gate` 旧闸门语义（analyze 链强制 evidence=None：",
            "  仅判 P0-A 精确占位标记 / empty / no_citation；citation 指标为空属预期）",
            "",
        ]
    lines += [
        "## 引用可验证性（C2，证据来自审计 input_text 的本轮知识库）",
        "",
        "> 口径：引用单元按 `；;`/换行切分；调用级 = 至少一条引用能在本轮",
        "> chunks 中验证；单元级 = 可验证单元数 / 引用单元总数；**分母 = 有证据调用**。",
        "",
        "| 链路 | 有证据调用 | 至少一条可验证 | 调用级可验证率 | 单元可验证 | 单元级可验证率 |",
        "|---|---|---|---|---|---|",
        f"| 视觉 | {vision_citation.get('calls_with_evidence', 0)} | "
        f"{vision_citation.get('calls_has_verified', 0)} | "
        f"{vision_citation.get('call_verified_rate', 0.0)}% | "
        f"{vision_citation.get('units_verified', 0)}/"
        f"{vision_citation.get('units_total', 0)} | "
        f"{vision_citation.get('unit_verified_rate', 0.0)}% |",
        f"| 文本 | {text_citation.get('calls_with_evidence', 0)} | "
        f"{text_citation.get('calls_has_verified', 0)} | "
        f"{text_citation.get('call_verified_rate', 0.0)}% | "
        f"{text_citation.get('units_verified', 0)}/"
        f"{text_citation.get('units_total', 0)} | "
        f"{text_citation.get('unit_verified_rate', 0.0)}% |",
        f"| 合计 | {citation['calls_with_evidence']} | "
        f"{citation['calls_has_verified']} | {citation['call_verified_rate']}% | "
        f"{citation['units_verified']}/{citation['units_total']} | "
        f"{citation['unit_verified_rate']}% |",
        "",
        f"- 有证据调用：{citation['calls_with_evidence']}；其中至少一条可验证："
        f"**{citation['calls_has_verified']}**"
        f"（调用级可验证率 **{citation['call_verified_rate']}%**）",
        f"- 零可验证调用：{citation['calls_zero_verified']}；引用单元可验证："
        f"{citation['units_verified']}/{citation['units_total']}"
        f"（单元级可验证率 **{citation['unit_verified_rate']}%**）",
        f"- 含占位变体调用：{citation['placeholder_variant_calls']}"
        f"（**含变体占位率 {citation['placeholder_variant_rate']}%**，"
        f"分母 = 有证据调用 {citation['calls_with_evidence']}）",
        f"- 占位两口径不同源：旧 P0-A `placeholder_rate` = 精确占位标记 / 全量 calls"
        f" = {totals['placeholder_rate']}%；新 C2 `placeholder_variant_rate`"
        f" = 占位变体（含精确）/ 有证据调用 = {citation['placeholder_variant_rate']}%",
        f"- 闸门 invalid_citation 分类："
        f"{stats['gate_categories'].get('invalid_citation', 0)}",
        "",
        "## 重跑窗口（按记录聚合；最高调用日）",
        "",
        f"- 日期：{stats['rerun_day'] or '(无数据)'}",
        f"- 记录数：{stats['rerun_records']['records']}；调用数：{stats['rerun_records']['calls']}",
        f"- 闸门通过记录：**{stats['rerun_records']['gate_pass_records']}** / "
        f"拒绝记录：**{stats['rerun_records']['gate_fail_records']}**",
        "",
    ]
    truth = stats.get("ground_truth")
    if truth:
        lines += [
            "## ground truth（含标签修正，/tmp 样本可选）",
            "",
            f"- ground truth 记录：{truth['ground_truth_records']}；重放命中："
            f"{truth['replayed_records']}（窗口：{truth.get('window', 'rerun')}）",
            f"- 误拒：**{truth['wrong_reject']}**（其中已知标签修正 "
            f"{truth.get('wrong_reject_label_correction', 0)} 条 —— truth=success 但依据"
            f"零可验证/纯占位，历史标签缺陷单列；真误拒 "
            f"**{truth.get('wrong_reject_genuine', 0)}** 条）",
            f"- 误收（truth=failed 但闸门通过）：**{truth['wrong_accept']}**"
            f"（其中 A1 修复救援 {truth.get('wrong_accept_repaired_rescue', 0)} 条、"
            f"占位口径切换 {truth.get('wrong_accept_placeholder_note', 0)} 条"
            f"（旧 GT 由无条件拒绝占位的旧重跑脚本生成，新口径按 spec C2 放行）、"
            f"真正语义不一致 {truth.get('wrong_accept_genuine', 0)} 条）",
            f"- 历史成功样本引用回归：记录级 "
            f"**{truth.get('success_citation_verified', 0)}/"
            f"{truth.get('success_records', 0)}** 有可验证引用；单元级 "
            f"{truth.get('success_citation_units_verified', 0)}/"
            f"{truth.get('success_citation_units_total', 0)}；含占位注记 "
            f"{truth.get('success_placeholder_note', 0)} 条（纯占位 "
            f"{truth.get('success_placeholder_pure', 0)}）",
            f"- legacy 旧口径并列（evidence=None，P0-A 语义；`--legacy-gate` 可复现）："
            f"误拒 **{(truth.get('legacy') or {}).get('wrong_reject', 0)}**、"
            f"误收 **{(truth.get('legacy') or {}).get('wrong_accept', 0)}**"
            f"（A1 修复救援 "
            f"{(truth.get('legacy') or {}).get('wrong_accept_repaired_rescue', 0)} 条 / "
            f"真正语义不一致 "
            f"{(truth.get('legacy') or {}).get('wrong_accept_genuine', 0)} 条）",
            "",
        ]
    rules = stats.get("rule_regression")
    if rules:
        lines += [
            "## A4 规则回归（197 条 ground truth 成功样本）",
            "",
            f"- 校验样本：{rules['checked_records']}；规则 error 记录：**{rules['rule_errors']}**",
        ]
        for example in rules["error_examples"]:
            lines.append(f"  - {example}")
        lines.append("")

    lines += [
        "## 按天趋势",
        "",
        "| 日期 | 调用 | 现状合法 | 修复后合法 | 修复 | 闸门通过 | 占位 | 引用OK | 占位变体 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for day, slot in stats["by_day"].items():
        lines.append(
            f"| {day} | {slot['calls']} | {slot['json_before']} | {slot['json_after']} | "
            f"{slot['repaired']} | {slot['gate_pass']} | {slot['placeholder']} | "
            f"{slot.get('citation_ok', 0)} | {slot.get('placeholder_variant', 0)} |"
        )
    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# DB（只读）
# ═══════════════════════════════════════════════════════════════


def _dsn_from_env() -> str:
    dsn = os.environ.get("DATABASE_URL", "")
    if dsn:
        return dsn
    env_file = Path(".env.development")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return ""


def _to_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def fetch_rows(dsn: str, *, days: int, scenario: str, limit: int) -> list[dict[str, Any]]:
    """只读查询审计行（显式 read-only 事务）。"""
    import asyncpg

    conn = await asyncpg.connect(_to_asyncpg_dsn(dsn))
    try:
        await conn.execute("SET default_transaction_read_only = on")
        await conn.execute("SET statement_timeout = '120s'")
        records = await conn.fetch(
            """
            SELECT id::text AS id,
                   created_at,
                   status,
                   degradation_level,
                   input_text,
                   output_text,
                   extra::text AS extra
            FROM safety.ai_call_audits
            WHERE scenario = $1
              AND output_text IS NOT NULL
              AND created_at > now() - ($2 || ' days')::interval
            ORDER BY created_at
            LIMIT $3
            """,
            scenario,
            str(max(1, days)),
            limit,
        )
        return [dict(record) for record in records]
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="① 隐患 AI 识别离线质量回归（只读）")
    parser.add_argument("--days", type=int, default=30, help="回看天数（默认 30）")
    parser.add_argument("--scenario", default=SCENARIO, help="审计场景（默认 hazard_identification）")
    parser.add_argument("--dsn", default="", help="PG DSN（默认读 DATABASE_URL / .env.development）")
    parser.add_argument("--limit", type=int, default=5000, help="最多读取行数（默认 5000）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    parser.add_argument("--out", default="", help="写入文件（默认 stdout）")
    parser.add_argument(
        "--legacy-gate",
        action="store_true",
        help=(
            "用 P0-A 旧闸门语义重放（analyze 链强制 evidence=None：只判精确占位"
            "标记 / empty / no_citation，不判占位变体与引用可验证）；用于复现旧口径"
            "对照，默认关"
        ),
    )
    args = parser.parse_args(argv)

    dsn = args.dsn or _dsn_from_env()
    if not dsn:
        print("未找到数据库 DSN（--dsn / DATABASE_URL / .env.development）", file=sys.stderr)
        return 2

    rows = asyncio.run(
        fetch_rows(dsn, days=args.days, scenario=args.scenario, limit=args.limit)
    )
    stats = analyze_rows(rows, legacy_gate=args.legacy_gate)
    truth = compare_ground_truth(rows)
    if truth is not None:
        stats["ground_truth"] = truth
    rule_regression = rule_regression_from_ground_truth()
    if rule_regression is not None:
        stats["rule_regression"] = rule_regression

    if args.json:
        payload = json.dumps(stats, ensure_ascii=False, indent=2)
    else:
        payload = render_markdown(stats, days=args.days)

    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(f"已写入 {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
