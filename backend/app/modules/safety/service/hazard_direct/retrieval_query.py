"""① 检索 query 构建 — 多路查询纯函数（P1-1 R1/R2）。

- ``build_retrieval_queries``：描述清洗（日期/发现前缀/空白/长度上限）+ 规则
  关键词抽取（设备/物质/行为/场所/标准号词表）+ 多路去重。路 1 = 清洗主查询、
  路 2 = 关键词查询；LLM 改写路（路 3）由 ``llm_rewrite_query`` 按开关追加，
  默认关、失败降级。
- ``merge_route_contexts``：跨路 RRF 合并（k=60，与检索层 ``_rrf_fusion`` 同款）
  + chunk_id 去重 + markdown 重建；**主路（contexts[0]）的 degradation /
  graph_path 决定合并结果**——quality_gate 闸门输入语义不变，辅路只贡献候选。

开关/参数全部走 app_config registry（热生效，30s TTL）：
- ``SAFETY_HAZARD_MULTI_QUERY_ENABLED``（默认开）关 = ① 回原单路路径（热回滚）；
- ``SAFETY_HAZARD_RETRIEVAL_TOP_K``（默认 8，与历史硬编码一致）；
- ``SAFETY_HAZARD_RETRIEVAL_CANDIDATES``（默认 12，每路候选数）；
- ``SAFETY_HAZARD_QUERY_LLM_REWRITE_ENABLED``（默认关）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace

from app.modules.safety.knowledge.retriever import (
    RRF_K,
    KnowledgeContext,
    RetrievalResult,
    SafetyKnowledgeRetriever,
)

logger = logging.getLogger(__name__)

# 主路 RRF 加权：主路（清洗主查询）贡献 ×2 —— 防辅路噪声挤出主路命中
# （2026-11-06 success_gt 实测：平权 89.0%→88.1% 回归，加权后恢复）。
PRIMARY_ROUTE_WEIGHT = 2.0

# 主查询长度上限（超长描述稀释语义向量，截断保核心）
MAX_QUERY_CHARS = 160

# ── 描述清洗 ──

# 完整日期：2026.11.3 / 2026-11-03 / 2026年11月3日（含两段分隔符，不误伤 1.5米）
_FULL_DATE_RE = re.compile(r"\d{4}[.\-/年]\d{1,2}[.\-/月]\d{1,2}日?")
# 月日：10月5日 / 11月3日
_MONTH_DAY_RE = re.compile(r"\d{1,2}月\d{1,2}日?")
# 序号前缀：(3) / 1、 / 2.（``(?!\d)`` 防误伤 "1.5米" 类小数开头描述）
_SEQ_PREFIX_RE = re.compile(r"^\s*(?:[（(]\d{1,2}[）)]|\d{1,2}[、.．](?!\d))\s*")
# 「检查发现：」类噪声前缀（容忍前置换行/空格）
_FINDING_PREFIX_RE = re.compile(
    r"^\s*(?:检查|巡查|排查|复查|督查|夜查)?发现[:：]?\s*"
)
# 清洗后残留的行首标点
_LEADING_PUNCT_RE = re.compile(r"^[\s，,、;；:：.．\-—]+")


def clean_description(description: str | None) -> str:
    """隐患描述 → 检索主查询：保守清洗（日期/发现前缀/序号/空白/长度上限）。

    只去确定性噪声，不改写语义；空输入返回空串。
    """
    text = (description or "").strip()
    if not text:
        return ""
    text = _FULL_DATE_RE.sub(" ", text)
    text = _MONTH_DAY_RE.sub(" ", text)
    text = _FINDING_PREFIX_RE.sub("", text)
    text = _SEQ_PREFIX_RE.sub("", text)
    text = _LEADING_PUNCT_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_QUERY_CHARS:
        text = text[:MAX_QUERY_CHARS].rstrip()
    return text


# ── 关键词词表（规则抽取，零 LLM）──
# 覆盖 57 失败样本聚类族：特殊作业（GB 30871 族）/ 设备设施 / 物质 / 行为 /
# PPE / 场所通道 / 管理要素。
_KEYWORD_LEXICON: tuple[str, ...] = (
    # 特殊作业
    "受限空间", "有限空间", "动火作业", "动火", "高处作业", "吊装", "临时用电",
    "盲板抽堵", "断路作业", "特殊作业",
    # 设备设施
    "配电箱", "配电室", "灭火器", "消火栓", "消防水", "消防泵", "安全阀",
    "压力表", "液位计", "可燃气体报警", "报警仪", "静电", "防雷", "跨接",
    "储罐", "管道", "阀门", "防护罩", "护栏", "应急照明",
    # 物质
    "氢气", "甲醇", "乙醇", "盐酸", "硫酸", "液氨", "氯气", "天然气",
    "液化气", "柴油", "汽油", "危化品", "危险化学品",
    # 行为状态
    "未佩戴", "未设置", "未办理", "未安装", "未封堵", "占用", "堵塞", "泄漏",
    "锈蚀", "脱落", "违章", "作业票",
    # PPE
    "安全帽", "安全带", "防护服", "护目镜", "防毒面具", "防护手套",
    # 场所通道
    "罐区", "控制室", "仓库", "车间", "污水站", "消防通道", "安全通道",
    "疏散通道",
    # 管理要素
    "操作规程", "应急预案", "安全警示标志", "警示标志", "标识",
)

# 标准号（GB/AQ/SH/HG 及 /T 变体 + 编号，如 GB 30871、GB/T 30000.31-2023）
_STANDARD_NO_RE = re.compile(
    r"(?:GB|AQ|SH|HG)(?:/T)?\s*\d{3,5}(?:\.\d+)?(?:-\d{4})?"
)


@dataclass(frozen=True)
class RetrievalQueryPlan:
    """多路检索计划（纯函数产物；LLM 改写路由调用侧追加）。"""

    primary: str                 # 路 1：清洗主查询
    queries: tuple[str, ...]     # 全部路由（含主路，已去重）
    rewrite_hit: bool            # 清洗改变了原描述
    keyword_route: bool          # 关键词路生效

    @property
    def multi_query_count(self) -> int:
        return len(self.queries)


def _extract_keywords(text: str) -> list[str]:
    """按出现顺序返回命中的词表关键词 + 标准号（去掉互为子串的冗余词）。"""
    matched: list[tuple[int, str]] = []
    for term in _KEYWORD_LEXICON:
        pos = text.find(term)
        if pos >= 0:
            matched.append((pos, term))
    for m in _STANDARD_NO_RE.finditer(text):
        matched.append((m.start(), m.group(0)))
    matched.sort(key=lambda item: item[0])
    seen: set[str] = set()
    ordered: list[str] = []
    for _, term in matched:
        if term in seen:
            continue
        # 「动火」是「动火作业」的子串 → 保留更长的那个
        if any(term in other for other in seen):
            continue
        seen = {other for other in seen if other not in term}
        seen.add(term)
        ordered.append(term)
    return ordered


def build_retrieval_queries(description: str | None) -> RetrievalQueryPlan:
    """描述 → 多路检索计划：路 1 清洗主查询，路 2 关键词查询（去重）。

    关键词 query 若是主查询的子串（描述本身即关键词），不加路——多路无增量。
    """
    original = (description or "").strip()
    primary = clean_description(original)
    rewrite_hit = primary != original

    queries: list[str] = [primary] if primary else []
    keyword_route = False
    if primary:
        keywords = _extract_keywords(primary)
        keyword_query = " ".join(keywords)
        # 关键词串 ≈ 主路连续子串（描述本身即关键词串联）→ 加路无增量，跳过；
        # 只有当关键词路是主路的「提炼」（去掉填充词）才追加。
        if keyword_query and keyword_query.replace(" ", "") not in primary.replace(" ", ""):
            queries.append(keyword_query)
            keyword_route = True

    # 去重（保序）：极端情况下关键词 query 与主路完全一致
    deduped: list[str] = []
    for query in queries:
        if query and query not in deduped:
            deduped.append(query)
    return RetrievalQueryPlan(
        primary=primary,
        queries=tuple(deduped),
        rewrite_hit=rewrite_hit,
        keyword_route=keyword_route,
    )


# ── 跨路合并 ──


def merge_route_contexts(
    contexts: list[KnowledgeContext],
    *,
    top_k: int,
    primary_weight: float = PRIMARY_ROUTE_WEIGHT,
) -> KnowledgeContext:
    """多路检索上下文 → 合并上下文（主路加权 RRF、chunk_id 去重、markdown 重建）。

    语义：``contexts[0]`` 为主路——degradation / graph_path / article_ids 以
    主路为准（quality_gate 判定输入不变）；辅路仅贡献候选 chunk。空辅路 tolerated。

    **主路加权**（P1-1 实测定案）：主路 chunk 的 RRF 贡献乘 ``primary_weight``
    （默认 2.0）——平权合并会让辅路噪声把主路命中挤出 top-k（success_gt 实测
    89.0%→88.1%）。加权后排序不变式：双路命中 > 主路命中 > 仅辅路命中。
    """
    if not contexts:
        raise ValueError("merge_route_contexts 需要至少一路检索上下文")
    primary = contexts[0]

    scores: dict[str, float] = {}
    first_seen: dict[str, RetrievalResult] = {}
    for route_index, context in enumerate(contexts):
        weight = primary_weight if route_index == 0 else 1.0
        for rank, chunk in enumerate(context.chunks):
            cid = chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + weight / (RRF_K + rank + 1)
            first_seen.setdefault(cid, chunk)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    chunks = [
        replace(first_seen[cid], score=score)
        for cid, score in ranked[: max(top_k, 1)]
    ]
    markdown = SafetyKnowledgeRetriever.build_markdown(chunks, primary.graph_path)
    return KnowledgeContext(
        chunks=chunks,
        graph_path=primary.graph_path,
        article_ids=primary.article_ids,
        markdown=markdown,
        degradation=primary.degradation,
    )


# ── 可观测元数据（T03 消费）──


@dataclass(frozen=True)
class RetrievalMeta:
    """本轮检索的可观测维度（合并进审计 extra，无 DDL）。"""

    query: str                     # 主路 query
    queries: tuple[str, ...]       # 全部路由
    rewrite_hit: bool              # 清洗改变了原描述
    docs: tuple[str, ...]          # 合并后 chunk 的文档名单（去重保序）

    @property
    def multi_query_count(self) -> int:
        return len(self.queries)


def _context_docs(context: KnowledgeContext) -> tuple[str, ...]:
    """合并上下文 → 文档名单（去重保序）。"""
    docs: list[str] = []
    for chunk in context.chunks:
        if chunk.source_doc and chunk.source_doc not in docs:
            docs.append(chunk.source_doc)
    return tuple(docs)


def build_retrieval_meta(
    plan: RetrievalQueryPlan,
    context: KnowledgeContext,
    *,
    queries: tuple[str, ...] | None = None,
) -> RetrievalMeta:
    """检索计划 + 合并上下文 → 审计元数据（清洗到空时 query 回退实际首路）。"""
    effective_queries = queries if queries is not None else plan.queries
    return RetrievalMeta(
        query=plan.primary or (effective_queries or ("",))[0],
        queries=effective_queries,
        rewrite_hit=plan.rewrite_hit,
        docs=_context_docs(context),
    )


def single_route_meta(query: str, context: KnowledgeContext) -> RetrievalMeta:
    """单路（开关关）路径的审计元数据（与多路口径统一）。"""
    return RetrievalMeta(
        query=query,
        queries=(query,),
        rewrite_hit=False,
        docs=_context_docs(context),
    )


def retrieval_audit_fields(meta: RetrievalMeta | None) -> dict[str, object]:
    """检索元数据 → 审计 ``extra`` 字段（T03；``None`` → 空 dict 即 no-op）。"""
    if meta is None:
        return {}
    return {
        "retrieval_query": meta.query,
        "retrieval_queries": list(meta.queries),
        "multi_query_count": meta.multi_query_count,
        "rewrite_hit": meta.rewrite_hit,
        "retrieval_docs": list(meta.docs[:8]),
    }


# ── LLM 改写路（默认关；轻量、失败降级）──

_LLM_REWRITE_SYSTEM = (
    "你是安全法规检索查询改写器。把给定的隐患描述改写为一条适合法规知识库"
    "检索的查询：提取设备、物质、作业行为、场所与标准关键词，去掉无关细节，"
    "只输出一行查询文本，不要解释、不要引号，不超过40个字。"
)


async def llm_rewrite_query(query: str) -> str | None:
    """轻量 LLM 改写主路查询（P1-1 路三，开关默认关）。

    任何失败返回 ``None`` —— 调用方降级为只用规则路（不阻断检索）。
    """
    try:
        from app.modules.safety.service.config import get_ai_service

        service = get_ai_service("text")
        answer = await service.chat(
            messages=[
                {"role": "system", "content": _LLM_REWRITE_SYSTEM},
                {"role": "user", "content": query},
            ],
            response_format="",
            temperature=0.1,
            max_tokens=120,
        )
    except Exception:  # noqa: BLE001 — 改写失败降级为规则路，不影响检索
        logger.warning("检索 LLM 改写失败（降级为规则路）", exc_info=True)
        return None
    text = str(answer or "").strip().strip('"“”‘’').strip()
    if not text or text == query or len(text) > 120:
        return None
    return text


# ── 参数读取（app_config：env > DB > registry 默认；读取失败用默认值）──

_MULTI_QUERY_KEY = "SAFETY_HAZARD_MULTI_QUERY_ENABLED"
_TOP_K_KEY = "SAFETY_HAZARD_RETRIEVAL_TOP_K"
_CANDIDATES_KEY = "SAFETY_HAZARD_RETRIEVAL_CANDIDATES"
_LLM_REWRITE_KEY = "SAFETY_HAZARD_QUERY_LLM_REWRITE_ENABLED"


def multi_query_enabled() -> bool:
    try:
        from app.modules.safety.app_config.store import store

        return bool(store.get_bool(_MULTI_QUERY_KEY, True))
    except Exception:  # noqa: BLE001 — 读取失败按默认开（多路是默认行为）
        return True


def retrieval_top_k() -> int:
    try:
        from app.modules.safety.app_config.store import store

        return int(store.get_int(_TOP_K_KEY, 8))
    except Exception:  # noqa: BLE001
        return 8


def retrieval_candidates() -> int:
    try:
        from app.modules.safety.app_config.store import store

        return int(store.get_int(_CANDIDATES_KEY, 12))
    except Exception:  # noqa: BLE001
        return 12


def llm_rewrite_enabled() -> bool:
    try:
        from app.modules.safety.app_config.store import store

        return bool(store.get_bool(_LLM_REWRITE_KEY, False))
    except Exception:  # noqa: BLE001 — 读取失败按默认关
        return False
