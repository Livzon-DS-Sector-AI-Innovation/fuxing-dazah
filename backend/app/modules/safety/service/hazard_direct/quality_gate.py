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
   - 命中占位文案 → ``placeholder_basis``
   - 不含任何法规引用 → ``no_citation``

引用 / 占位判定唯一事实源是 ``ai_hazard_identification.citations``
（与规则引擎的判定依据校验同源，避免两套口径漂移）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.modules.safety.ai_hazard_identification.citations import (
    has_citation,
    is_placeholder_basis,
)

if TYPE_CHECKING:
    from app.modules.safety.knowledge.retriever import KnowledgeContext

RETRIEVAL_DEGRADED = "retrieval_degraded"
NO_CHUNKS = "no_chunks"
EMPTY_BASIS = "empty_basis"
PLACEHOLDER_BASIS = "placeholder_basis"
NO_CITATION = "no_citation"


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


def ensure_output(output: dict[str, Any]) -> None:
    """输出质量闸门：依据为空 / 占位文案 / 无法规引用 → 本条失败不写回。"""
    basis = output.get("major_hazard_basis")
    text = str(basis).strip() if basis is not None else ""
    if not text:
        raise QualityGateError(EMPTY_BASIS, "判定依据为空，不写回")
    if is_placeholder_basis(text):
        raise QualityGateError(
            PLACEHOLDER_BASIS, f"判定依据命中占位文案: {text[:80]}"
        )
    if not has_citation(text):
        raise QualityGateError(NO_CITATION, f"判定依据不含法规引用: {text[:80]}")
