"""SOP AI 层 — Schema 校验 / 结构规范化 / 质量自检。

对外只暴露**校验函数**；各校验器对应的输出 Schema 由调用方 prompt 约定。
"""

from __future__ import annotations

import re
from typing import Any

# ── 各 section 输出条数上限（防 AI 输出失控）──
MAX_PARAMS = 30
MAX_SAFETY_REQS = 40
MAX_ABNORMALS = 20
MAX_FLOW_STAGES = 40
MAX_RISK_ROWS = 30

# 审核维度固定四类（缺失时补齐为 warn）
REVIEW_DIMENSIONS = ["操作内容完整性", "细节准确性", "结构完整性", "安全合规性"]

# ch9 应急类型候选集（对应 layer2 chapter9_emergency 的 TEMPLATES keys）
EMERGENCY_TYPES = ["酸灼烫", "碱灼烫", "灼烫", "溶媒接触", "中毒", "触电", "火灾"]

# ch7 工序覆盖率达标阈值（AI 输出工序数 ≥ 基线工序数的 90%）。
# 定义在 _validate 供 _chapters 与 assess_generation_quality 共用，
# 避免 _validate 反向 import _chapters 造成循环。
CH7_COVERAGE_THRESHOLD = 0.9

# 无占位符铁律——生成结果不得残留的占位关键词（assess_generation_quality 扫描用）
PLACEHOLDER_MARKERS = ("请人工补充", "根据实际工艺补充", "待补充")


def _norm_params(result: Any) -> list[dict]:
    """control_parameters → 规范化参数行 [{参数, 正常范围, 报警值, 联锁值, 偏离后果, 预防措施, 阶段}]。"""
    params: list[dict] = []
    if isinstance(result, dict) and isinstance(result.get("control_parameters"), list):
        for it in result["control_parameters"]:
            if not isinstance(it, dict):
                continue
            name = str(it.get("参数", "") or "").strip()
            normal = str(it.get("正常范围", "") or "").strip()
            if not name or not normal:
                continue
            params.append({
                "参数": name,
                "正常范围": normal,
                "报警值": str(it.get("报警值", "") or "").strip() or "—",
                "联锁值": str(it.get("联锁值", "") or "").strip() or "—",
                "偏离后果": str(it.get("偏离后果", "") or "").strip() or "参数偏离影响工艺安全",
                "预防措施": str(it.get("预防措施", "") or "").strip() or "严格按SOP监控",
                "阶段": str(it.get("阶段", "") or "").strip(),
            })
            if len(params) >= MAX_PARAMS:
                break
    return params


def _norm_safety_reqs(result: Any) -> list[dict]:
    """safety_requirements → 规范化要求行 [{阶段, 类型, 要求}]。"""
    reqs: list[dict] = []
    if isinstance(result, dict) and isinstance(result.get("safety_requirements"), list):
        for it in result["safety_requirements"]:
            if not isinstance(it, dict):
                continue
            text = str(it.get("要求", "") or "").strip()
            if not text:
                continue
            reqs.append({
                "阶段": str(it.get("阶段", "") or "").strip(),
                "类型": str(it.get("类型", "") or "").strip(),
                "要求": text,
            })
            if len(reqs) >= MAX_SAFETY_REQS:
                break
    return reqs


def _norm_abnormals(result: Any) -> list[dict]:
    """abnormal_conditions → 规范化异常工况行 [{阶段, 异常工况, 异常工况描述, 处置步骤, 预防措施}]。"""
    abnormals: list[dict] = []
    if isinstance(result, dict) and isinstance(result.get("abnormal_conditions"), list):
        for it in result["abnormal_conditions"]:
            if not isinstance(it, dict):
                continue
            name = str(it.get("异常工况", "") or "").strip()
            desc = str(it.get("异常工况描述", "") or "").strip()
            if not name or not desc:
                continue
            abnormals.append({
                "阶段": str(it.get("阶段", "") or "").strip(),
                "异常工况": name,
                "异常工况描述": desc,
                "处置步骤": str(it.get("处置步骤", "") or "").strip() or "立即停止相关操作并上报",
                "预防措施": str(it.get("预防措施", "") or "").strip() or "严格按SOP操作，加强巡检",
            })
            if len(abnormals) >= MAX_ABNORMALS:
                break
    return abnormals


def _norm_flow(result: Any) -> list[dict]:
    """process_flow → 规范化工艺流程行 [{阶段, 操作内容}]。"""
    flow: list[dict] = []
    if isinstance(result, dict) and isinstance(result.get("process_flow"), list):
        for it in result["process_flow"]:
            if not isinstance(it, dict):
                continue
            stage = str(it.get("阶段", "") or "").strip()
            ops = str(it.get("操作内容", "") or "").strip()
            if not stage or not ops:
                continue
            flow.append({"阶段": stage, "操作内容": ops})
            if len(flow) >= MAX_FLOW_STAGES:
                break
    return flow


def _validate_supplement(result: Any) -> dict | None:
    """结构校验 + 规范化：丢弃畸形条目、补默认值、封顶条数；全空返回 None。"""
    if not isinstance(result, dict):
        return None

    params = _norm_params(result)
    reqs = _norm_safety_reqs(result)
    abnormals = _norm_abnormals(result)
    flow = _norm_flow(result)

    if not params and not reqs and not abnormals and not flow:
        return None

    return {
        "control_parameters": params,
        "safety_requirements": reqs,
        "abnormal_conditions": abnormals,
        "process_flow": flow,
    }


# 视觉审核输出条数上限（防 AI 输出失控）
MAX_VISION_DIMENSIONS = 8
MAX_LAYOUT_ISSUES = 30


def _validate_vision_review(result: Any) -> dict | None:
    """规范化视觉审核结果：维度按名去重 + status 规范化、layout_issues 过滤畸形。

    校验通过返回 {summary, dimensions, layout_issues}；空/畸形返回 None。

    与 _validate_review 的区别：视觉维度名**不限定** REVIEW_DIMENSIONS
    （视觉维度自由命名，如「排版布局」「格式规范」），layout_issues 是页级
    结构化问题数组（page/issue_type/severity/description）。
    """
    if not isinstance(result, dict):
        return None

    summary = str(result.get("summary") or "").strip()

    # ── dimensions：按名称去重（首见保留），status 规范化，封顶 ──
    dimensions: list[dict] = []
    seen: set[str] = set()
    for it in result.get("dimensions") or []:
        if not isinstance(it, dict):
            continue
        dimension = str(it.get("dimension") or "").strip()
        if not dimension or dimension in seen:
            continue
        status = str(it.get("status") or "warn").strip()
        if status not in ("pass", "warn", "fail"):
            status = "warn"
        seen.add(dimension)
        dimensions.append(
            {
                "dimension": dimension,
                "status": status,
                "detail": str(it.get("detail") or "").strip(),
            }
        )
        if len(dimensions) >= MAX_VISION_DIMENSIONS:
            break

    # ── layout_issues：过滤畸形条目（page 越界/description 空丢弃），封顶 ──
    layout_issues: list[dict] = []
    for it in result.get("layout_issues") or []:
        if not isinstance(it, dict):
            continue
        try:
            page = int(it.get("page") or 0)
        except (TypeError, ValueError):
            continue
        if page < 1:
            continue
        description = str(it.get("description") or "").strip()
        if not description:
            continue
        severity = str(it.get("severity") or "warn").strip()
        if severity not in ("warn", "fail"):
            severity = "warn"
        layout_issues.append(
            {
                "page": page,
                "issue_type": str(it.get("issue_type") or "排版问题").strip(),
                "severity": severity,
                "description": description,
            }
        )
        if len(layout_issues) >= MAX_LAYOUT_ISSUES:
            break

    if not dimensions and not layout_issues:
        return None

    return {"summary": summary, "dimensions": dimensions, "layout_issues": layout_issues}


def _validate_review(result: Any) -> dict | None:
    """规范化 AI 审核结果：维度补齐为四类、章节修正过滤畸形条目。

    校验通过返回 {summary, dimensions, chapter_fixes}；空/畸形返回 None。
    """
    if not isinstance(result, dict):
        return None

    summary = str(result.get("summary") or "").strip()

    dimensions: list[dict] = []
    seen: set[str] = set()
    for it in result.get("dimensions") or []:
        if not isinstance(it, dict):
            continue
        dimension = str(it.get("dimension") or "").strip()
        if dimension not in REVIEW_DIMENSIONS or dimension in seen:
            continue
        status = str(it.get("status") or "warn").strip()
        if status not in ("pass", "warn", "fail"):
            status = "warn"
        seen.add(dimension)
        dimensions.append(
            {
                "dimension": dimension,
                "status": status,
                "detail": str(it.get("detail") or "").strip(),
            }
        )
    # 补齐缺失维度，并按 REVIEW_DIMENSIONS 规范顺序排列
    dim_by_name = {d["dimension"]: d for d in dimensions}
    dimensions = [
        dim_by_name.get(dim, {"dimension": dim, "status": "warn", "detail": "AI 未给出该维度结论"})
        for dim in REVIEW_DIMENSIONS
    ]

    chapter_fixes: list[dict] = []
    for it in result.get("chapter_fixes") or []:
        if not isinstance(it, dict):
            continue
        try:
            chapter = int(it.get("chapter") or 0)
        except (TypeError, ValueError):
            continue
        if chapter < 1 or chapter > 9:
            continue
        action = str(it.get("action") or "keep").strip()
        if action not in ("keep", "rewrite", "append"):
            action = "keep"
        chapter_fixes.append(
            {
                "chapter": chapter,
                "title": str(it.get("title") or "").strip(),
                "action": action,
                "corrected_content": str(it.get("corrected_content") or "").strip(),
                "note": str(it.get("note") or "").strip(),
            }
        )

    if not dimensions and not chapter_fixes:
        return None

    return {"summary": summary, "dimensions": dimensions, "chapter_fixes": chapter_fixes}


# ═══════════════════════════════════════════════════════════════════════
# 第 7 章：生产工艺流程校验 + 工序覆盖率自检
# ═══════════════════════════════════════════════════════════════════════

# ch7 输出工序条数上限（防 AI 输出失控）
MAX_CH7_STAGES = 40


def validate_ch7(result: Any) -> list[dict] | None:
    """ch7 工艺流程输出校验：返回 [{阶段, 操作内容}]；空/畸形返回 None。

    AI 输出的 process_flow 必须是非空 dict 中的非空数组，每项含「阶段」与
    「操作内容」。过滤畸形条目，封顶 MAX_CH7_STAGES 条。
    """
    if not isinstance(result, dict):
        return None
    rows: list[dict] = []
    if isinstance(result.get("process_flow"), list):
        for it in result["process_flow"]:
            if not isinstance(it, dict):
                continue
            stage = str(it.get("阶段", "") or "").strip()
            ops = str(it.get("操作内容", "") or "").strip()
            if not stage or not ops:
                continue
            rows.append({"阶段": stage, "操作内容": ops})
            if len(rows) >= MAX_CH7_STAGES:
                break
    return rows or None


def ch7_coverage(ai_stage_names: list[str], baseline_stage_names: list[str]) -> float:
    """AI ch7 工序覆盖率 = AI 工序名覆盖基线工序的比例。

    匹配规则：基线工序名与任一 AI 工序名**互相包含**（a in b or b in a）视为覆盖
    ——AI 会按内容重新归纳工序名，因此用宽松匹配而非精确相等。
    基线为空返回 1.0（无从对比，视为达标）。
    """
    if not baseline_stage_names:
        return 1.0
    if not ai_stage_names:
        return 0.0
    covered = 0
    for base in baseline_stage_names:
        if any(base in ai or ai in base for ai in ai_stage_names):
            covered += 1
    return covered / len(baseline_stage_names)


# ═══════════════════════════════════════════════════════════════════════
# 第 3 / 5 / 6 / 8 / 9 章：逐章 AI 输出校验
# ═══════════════════════════════════════════════════════════════════════


def validate_ch3(result: Any) -> list[dict] | None:
    """ch3 风险分析输出校验：返回 [{风险类别, 产生风险原因, 事故/伤害, 涉及工序, 管控措施, 伤害对象}]。

    接受 AI 的「可能造成的事故/伤害」→「事故/伤害」、「可能伤害的对象」→「伤害对象」
    字段映射；过滤畸形条目，封顶 MAX_RISK_ROWS 条。
    """
    if not isinstance(result, dict):
        return None
    rows: list[dict] = []
    raw = result.get("risk_rows")
    if not isinstance(raw, list):
        raw = result.get("risk_analysis") or []
    if isinstance(raw, list):
        for it in raw:
            if not isinstance(it, dict):
                continue
            cat = str(it.get("风险类别", "") or "").strip()
            reason = str(it.get("产生风险原因", "") or "").strip()
            if not cat or not reason:
                continue
            rows.append({
                "风险类别": cat,
                "产生风险原因": reason,
                "事故/伤害": str(it.get("可能造成的事故/伤害", "") or it.get("事故/伤害", "") or "").strip(),
                "涉及工序": str(it.get("涉及工序", "") or "").strip(),
                "管控措施": str(it.get("管控措施", "") or "").strip(),
                "伤害对象": str(it.get("可能伤害的对象", "") or it.get("伤害对象", "") or "操作人员").strip() or "操作人员",
            })
            if len(rows) >= MAX_RISK_ROWS:
                break
    return rows or None


def validate_ch5(result: Any) -> list[dict] | None:
    """ch5 工艺控制参数输出校验：返回 [{参数, 正常范围, 报警值, 联锁值, 偏离后果, 预防措施, 阶段}]。"""
    params = _norm_params(result)
    return params or None


def validate_ch6(result: Any) -> list[dict] | None:
    """ch6 安全操作要求输出校验：返回 [{阶段, 类型, 要求}]。"""
    reqs = _norm_safety_reqs(result)
    return reqs or None


def validate_ch8(result: Any) -> list[dict] | None:
    """ch8 异常工况输出校验：返回 [{阶段, 异常工况, 异常工况描述, 处置步骤, 预防措施}]。"""
    abnormals = _norm_abnormals(result)
    return abnormals or None


def validate_ch9(result: Any) -> list[str] | None:
    """ch9 应急类型选型校验：返回去重后的应急类型列表（仅限 EMERGENCY_TYPES 候选集）。"""
    if not isinstance(result, dict):
        return None
    raw = result.get("emergency_types")
    if not isinstance(raw, list):
        return None
    seen: list[str] = []
    for it in raw:
        t = str(it or "").strip()
        if t in EMERGENCY_TYPES and t not in seen:
            seen.append(t)
    return seen or None


# ═══════════════════════════════════════════════════════════════════════
# ch5 数值溯源（质量自检）
# ═══════════════════════════════════════════════════════════════════════


def ch5_traceability(rows: list[dict], source_text: str, msds: dict | None) -> tuple[float, list[dict]]:
    """ch5 参数数值溯源率 = 可溯源参数行 / 含数值的参数行。

    判定条件（双条件 AND，缺一不算可溯源）：
      ① 数值出现在源文档原文或 MSDS 物性字段中（数字边界匹配，避免
         "100" 命中 "1000" 之类的假阳性）；
      ② 参数名（≥3 字符，非 "—"）也出现在源文档/MSDS 字段中——
         值级命中但参数名编造（如"脱盐柱再生pH"编造参数恰好带着源文档
         中别的参数数值）会虚高通过，验收复现：结晶与脱盐 generation_quality
         numeric_traceability=1.0 但 AI 审核抓出 ch5 大量编造参数。

    Returns:
        (ratio, 未溯源行列表 [{"参数", "正常范围"}]；无数值行时 ratio=1.0)
    """
    if not rows:
        return 1.0, []
    _num = re.compile(r"\d+(?:\.\d+)?")

    def _norm(text: str) -> str:
        return re.sub(r"[\s·,，;；（）()]", "", text or "")

    source_norm = _norm(source_text or "")
    msds_text: list[str] = []
    for summary in (msds or {}).values():
        if not isinstance(summary, dict):
            continue
        for v in summary.values():
            if isinstance(v, str):
                msds_text.append(v)
            elif isinstance(v, list):
                msds_text.extend(str(x) for x in v)
    msds_norm = _norm(" ".join(msds_text))

    numeric_rows = [r for r in rows if _num.search(str(r.get("正常范围", "") or ""))]
    if not numeric_rows:
        return 1.0, []

    def _boundary_re(num: str) -> re.Pattern:
        return re.compile(r"(?<![\d])" + re.escape(num) + r"(?![\d])")

    traceable = 0
    untraceable: list[dict] = []
    for r in numeric_rows:
        normal = str(r.get("正常范围", "") or "")
        param = str(r.get("参数", "") or "").strip()
        name_checked = len(param) >= 3 and param != "—"

        value_ok = any(
            _boundary_re(n).search(source_norm) or _boundary_re(n).search(msds_norm)
            for n in _num.findall(normal)
        )
        name_ok = (not name_checked) or (_norm(param) in source_norm) or (_norm(param) in msds_norm)

        if value_ok and name_ok:
            traceable += 1
        else:
            untraceable.append({"参数": param, "正常范围": normal})
    return traceable / len(numeric_rows), untraceable


# ═══════════════════════════════════════════════════════════════════════
# 生成质量硬基线评估（纯函数，非阻塞）
# ═══════════════════════════════════════════════════════════════════════


def assess_generation_quality(
    content: str,
    *,
    source_text: str = "",
    kb: dict | None = None,
    baseline_stages: list[str] | None = None,
    ch7_rows: list[dict] | None = None,
    ch5_rows: list[dict] | None = None,
) -> dict:
    """生成质量硬基线评估（纯函数，非阻塞）。

    聚合 ch7 工序覆盖率、ch5 数值溯源率、占位符扫描三指标（spec:
    sop-generation-quality 的硬量化自检）。逐章生成函数已在各自内部完成
    重试/回退，此处仅做最终汇总，结果放入 service result 的
    generation_quality（供测试断言与后续 UI，本期前端不改）。

    Args:
        content: 组装后的 9 章 Markdown（占位符扫描对象）。
        source_text: 源文档全文（数值溯源依据之一）。
        kb: 知识参考包（取 msds 物性字段作数值溯源依据之二）。
        baseline_stages: layer1 基线工序名（ch7 覆盖率对比基准）。
        ch7_rows: AI ch7 输出行 [{阶段, 操作内容}]（传 None 则覆盖率无从对比）。
        ch5_rows: AI ch5 输出行 [{参数, 正常范围, ...}]（传 None 则溯源率无从对比）。

    Returns:
        {
            "chapter_coverage": float | None,       # ch7 覆盖率（无可对比返回 None）
            "numeric_traceability": float | None,   # ch5 数值溯源率（无数值行返回 None）
            "placeholders": [str],                  # 命中的占位关键词
            "warnings": [str],                      # 覆盖率/溯源不达标 + 占位符告警
        }
    """
    warnings: list[str] = []

    # ── ch7 工序覆盖率 ──
    chapter_coverage: float | None = None
    if ch7_rows:
        stage_names = [
            str(r.get("阶段", "") or "").strip() for r in ch7_rows if r.get("阶段")
        ]
        # ch7_coverage 对空基线返回 1.0（虚高通过）——layer1 漏检时覆盖率不可比，
        # 由调用方（测试）另做源文档已知工序抽查对冲（spec: sop-generation-quality）。
        chapter_coverage = ch7_coverage(stage_names, baseline_stages or [])
        if baseline_stages and chapter_coverage < CH7_COVERAGE_THRESHOLD:
            warnings.append(
                f"ch7 工序覆盖率 {chapter_coverage:.0%} < 90%（基线 {len(baseline_stages)} 个工序）"
            )

    # ── ch5 数值溯源 ──
    numeric_traceability: float | None = None
    if ch5_rows:
        ratio, untraceable = ch5_traceability(ch5_rows, source_text, (kb or {}).get("msds"))
        numeric_traceability = ratio
        for u in untraceable:
            warnings.append(f"ch5 参数数值无法溯源：{u['参数']}（{u['正常范围']}）")
        if ratio < 0.8:
            warnings.append(f"ch5 数值溯源 {ratio:.0%} < 80%")

    # ── 占位符扫描 ──
    placeholders = [m for m in PLACEHOLDER_MARKERS if m in (content or "")]
    if placeholders:
        warnings.append(f"生成结果残留占位符：{'、'.join(placeholders)}")

    return {
        "chapter_coverage": (
            round(chapter_coverage, 3) if chapter_coverage is not None else None
        ),
        "numeric_traceability": (
            round(numeric_traceability, 3) if numeric_traceability is not None else None
        ),
        "placeholders": placeholders,
        "warnings": warnings,
    }
