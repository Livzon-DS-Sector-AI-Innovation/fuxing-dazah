"""① 隐患AI识别质量闸门 —— RAG 预检 + 输出质量闸门（A3）。

两道闸门，失败均抛 ``QualityGateError``（带 ``category``），由
``ai_analysis`` 统一转为「本条失败、不写任何字段、保持 AI 分类为空」：

1. **RAG 预检（调 AI 之前）** —— ``ensure_knowledge``：
   - ``context is None`` 或 ``degradation`` 不在「允许集合」→ ``retrieval_degraded``
   - ``chunks == 0`` → ``no_chunks``
   命中即失败：不创建 AI 客户端、不调 AI、不下载附件。
   **允许集合是有意安全阀**（随检索内核开关联动，见 ``_allowed_degradations``）：
   ``ragplus_search_enabled()`` 开 → ``{ragplus}``；关 → ``{full, llm_expanded}``
   （避免 ragplus 关闭时健康的本地 hybrid 检索被误拒）。

2. **输出质量闸门（写回之前）** —— ``ensure_output``：
   - 判定依据为空 → ``empty_basis``
   - 命中占位文案（含「知识库中无《XX》相应条文」变体）→ ``placeholder_basis``
   - 不含任何法规引用 → ``no_citation``
   - 引用无法在本轮检索 chunks 中验证（零条可验证）→ ``invalid_citation``
     （P0-C C2；仅当传入 ``evidence`` 且引用强约束开关开启时生效）

引用 / 占位判定唯一事实源是 ``ai_hazard_identification.citations``；引用来源
可验证唯一事实源是 ``ai_hazard_identification.citation_evidence``（与规则引擎
同源，避免两套口径漂移）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
    CitationReport,
    verify_citations,
)
from app.modules.safety.ai_hazard_identification.citations import (
    has_citation,
    is_placeholder_basis,
    is_placeholder_variant,
)

if TYPE_CHECKING:
    from app.modules.safety.knowledge.retriever import KnowledgeContext

logger = logging.getLogger(__name__)

RETRIEVAL_DEGRADED = "retrieval_degraded"
NO_CHUNKS = "no_chunks"
EMPTY_BASIS = "empty_basis"
PLACEHOLDER_BASIS = "placeholder_basis"
NO_CITATION = "no_citation"
# P0-C C2：依据里有引用，但零条能在本轮检索 chunks 中验证（疑似凭记忆编造）
INVALID_CITATION = "invalid_citation"

# 引用强约束开关（app_config registry；默认开、热生效 ≤30s，可热关回滚）。
_CITATION_STRICT_KEY = "SAFETY_HAZARD_CITATION_STRICT_ENABLED"


def citation_strict_enabled() -> bool:
    """① 判定依据引用强约束开关（默认开；读取异常 fail-open 为开）。

    走 app_config store 读取链（env > DB 活行 > registry 默认）+ 30s TTL，
    与 ``SAFETY_AI_VISION_JSON_MODE_ENABLED`` 同款灰度语义（非 restart_required）。
    """
    try:
        from app.modules.safety.app_config.store import store as config_store

        return bool(config_store.get_bool(_CITATION_STRICT_KEY, True))
    except Exception:  # noqa: BLE001 — 开关读取失败不阻断识别（fail-open=护栏开启）
        logger.warning("引用强约束开关读取失败，按默认开启处理", exc_info=True)
        return True


class QualityGateError(Exception):
    """质量闸门拦截（``category`` 用于失败分类统计与告警聚合）。"""

    def __init__(self, category: str, message: str = "") -> None:
        self.category = category
        super().__init__(message or category)


# 健康 degradation 集合：与检索内核开关联动（不硬编码单一魔法串）。
# - ragplus 内核开启：只有 "ragplus" 算健康（本地降级链的 full/text_only 等均视为降级）
# - ragplus 内核关闭（走本地 hybrid）："full"/"llm_expanded" 算健康
_RAGPLUS_ALLOWED = frozenset({"ragplus"})
_LOCAL_ALLOWED = frozenset({"full", "llm_expanded"})


def _allowed_degradations() -> frozenset[str]:
    """按检索内核开关返回本轮健康的 degradation 集合。

    开关函数定义在 ``knowledge/ragplus_client.py``（``retriever.py`` 只是
    re-import 给内部使用，mypy strict 不把它当显式导出），这里从定义处导入。
    """
    from app.modules.safety.knowledge.ragplus_client import ragplus_search_enabled

    return _RAGPLUS_ALLOWED if ragplus_search_enabled() else _LOCAL_ALLOWED


def ensure_knowledge(context: KnowledgeContext | None) -> None:
    """RAG 预检：检索降级 / 零召回 → 本条失败（不调 AI、不写字段）。"""
    if context is None:
        raise QualityGateError(
            RETRIEVAL_DEGRADED, "RAG 检索不可用（context=None），本条不调 AI"
        )
    allowed = _allowed_degradations()
    if context.degradation not in allowed:
        raise QualityGateError(
            RETRIEVAL_DEGRADED,
            f"RAG 检索降级（degradation={context.degradation!r}，"
            f"允许={sorted(allowed)}），本条不调 AI",
        )
    if len(context.chunks) == 0:
        raise QualityGateError(NO_CHUNKS, "RAG 检索零召回，本条不调 AI")


def ensure_output(
    output: dict[str, Any],
    *,
    evidence: CitationEvidence | None = None,
) -> None:
    """输出质量闸门：依据为空 / 占位（含变体）/ 无引用 / 引用零可验证 → 不写回。

    Args:
        output: AI 识别输出 dict（仅读 ``major_hazard_basis``）
        evidence: 本轮检索证据（C2）。``None`` = 开关关闭/旧调用方：
            严格回退 P0-A 口径（精确占位标记 / empty / no_citation），
            **不判占位变体、不判引用可验证**（热回滚语义）；非 ``None`` 时
            额外要求「至少一条引用可在本轮 chunks 验证」，并识别占位变体。
    """
    basis = output.get("major_hazard_basis")
    text = str(basis).strip() if basis is not None else ""
    if not text:
        raise QualityGateError(EMPTY_BASIS, "判定依据为空，不写回")

    report = verify_citations(text, evidence) if evidence is not None else None

    # 占位：开关开时识别变体，且必须存在**实质可验证引用**（条号/引文/标准号，
    # 仅书名号不够）才放行；开关关时严格回退 P0-A 精确标记口径。
    # M1 验收修复：「知识库中无《X》相应条文」里的 X 命中 chunks 时不再放行。
    placeholder_hit = (
        is_placeholder_variant(text) if evidence is not None else is_placeholder_basis(text)
    )
    substantive_verified = (
        report.has_substantive_verified if report is not None else False
    )
    if placeholder_hit and not substantive_verified:
        raise QualityGateError(
            PLACEHOLDER_BASIS, f"判定依据命中占位文案: {text[:80]}"
        )
    if not has_citation(text):
        raise QualityGateError(NO_CITATION, f"判定依据不含法规引用: {text[:80]}")
    if report is not None and not report.has_verified:
        raise QualityGateError(
            INVALID_CITATION,
            "判定依据的引用无法在本轮检索到的法规条款中验证"
            f"（疑似凭记忆编造）: {text[:80]}",
        )


def citation_audit_fields(
    report: CitationReport | None,
    evidence: CitationEvidence | None,
    *,
    strict: bool,
) -> dict[str, Any]:
    """引用质量维度 → 审计 ``extra`` 字段（无 DDL；失败只影响可观测不影响业务）。"""
    return {
        "citation_strict": bool(strict),
        "citation_source": (
            "chunks"
            if evidence is not None and not evidence.is_empty
            else "none"
        ),
        "citation_total": report.total_units if report is not None else 0,
        "citation_verified": report.verified_units if report is not None else 0,
        "citation_verified_all": bool(report is not None and report.all_verified),
        "citation_unverified": (
            list(report.unverified_texts) if report is not None else []
        ),
        "citation_chunk_ids": (
            list(evidence.chunk_ids[:8]) if evidence is not None else []
        ),
        "citation_placeholder_note": bool(
            report is not None and report.placeholder_note
        ),
    }
