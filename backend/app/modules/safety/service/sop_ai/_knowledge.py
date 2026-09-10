"""SOP AI 层 — 知识参考包构建（法规 RAG + MSDS 台账）。

为逐章 AI 生成提供「知识层」：输入 layer1 提取结果 + 源文档全文 + meta，
输出结构化知识参考包 KB，作为 AI 生成时的权威数值与安全依据
（源文档优先，知识仅补缺 —— 见 spec: sop-generation-quality）。

两条独立知识源，任一失败仅告警、返回空切片，不阻塞后续生成：

- 法规 RAG：`HybridRetriever(session)`（无 embedder、无 ai_service）→ 纯
  全文检索，零 AI 实体提取调用（成本可控）。检索词由 产品/岗位/工序/化学品
  组合而成，取前 ~8 条切片。
- MSDS 台账：检测源文档中的化学品 → 模糊查 `safety.msds_documents` →
  组装物性（闪点/沸点/爆炸上下限）+ 危害 + 急救/消防/泄漏摘要，作为数值
  溯源的权威依据。未收录的化学品记录在 warnings 中。
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── 法规 RAG 参数 ──
RAG_TARGET_CHUNKS = 8

# 常用溶剂缩写 → 中文核心词（用于命中「缩写写法 + catalog 中文名」的搭配）。
# 值取 catalog 同义词的子串即可（如 二甲基甲酰胺 ∈ "N ,N-二甲基甲酰胺"）。
_CHEM_ABBREV = {
    "DMF": "二甲基甲酰胺",
    "DMSO": "二甲基亚砜",
    "IPA": "异丙醇",
    "THF": "四氢呋喃",
    "EA": "乙酸乙酯",
    "EtOH": "乙醇",
    "MeOH": "甲醇",
    "ACN": "乙腈",
    "MTBE": "甲基叔丁基醚",
}

_MSDS_PHYSICOCHEM_FIELDS = (
    ("外观与现状", "appearance"),
    ("溶解性", "solubility"),
    ("熔点", "melting_point"),
    ("沸点", "boiling_point"),
    ("闪点", "flash_point"),
    ("相对密度", "relative_density"),
    ("爆炸上限(%)", "explosion_upper_limit"),
    ("爆炸下限(%)", "explosion_lower_limit"),
    ("自燃温度", "autoignition_temperature"),
    ("分解温度", "decomposition_temperature"),
)

_MSDS_RESPONSE_FIELDS = (
    ("健康危害", "health_hazard"),
    ("急救措施", "first_aid"),
    ("消防措施", "fire_fighting"),
    ("泄漏应急处理", "leakage_response"),
    ("操作处置与储存注意事项", "handling_storage"),
)


def _split_synonyms(name: str) -> list[str]:
    """MSDS name 形如 '2-丙醇;异丙醇' —— 按分号/顿号拆同义词。

    注意：**不能**按逗号拆 —— 化学品名内部就含逗号（如 'N ,N-二甲基甲酰胺'），
    拆开会把 'N' 误当成同义词，导致 matched_by 指向单字符。
    """
    return [s.strip() for s in re.split(r"[;；、/]", name) if s.strip()]


def _normalize(text: str) -> str:
    """去空白与常见标点，用于宽松匹配（N ,N-二甲基甲酰胺 vs N.N—二甲基甲酰胺）。"""
    return re.sub(r"[\s\-—·.,，;；()（）/]", "", text)


def _match_keys(synonyms: list[str]) -> list[str]:
    """同义词 + 命中缩写时对应中文核心词 → 待查 key 列表。

    例：synonyms=['N ,N-二甲基甲酰胺', '甲酰二甲胺']
      → keys=['N ,N-二甲基甲酰胺', '甲酰二甲胺', '二甲基甲酰胺']
    源文本写 "DMF" 或 "N.N—二甲基甲酰胺" 均可命中。
    """
    keys = list(synonyms)
    for s in synonyms:
        for zh in _CHEM_ABBREV.values():
            if zh and zh in s and zh not in keys:
                keys.append(zh)
    return keys


def _text_contains_key(key: str, raw_text: str, raw_norm: str) -> bool:
    return key in raw_text or _normalize(key) in raw_norm


async def _detect_msds(raw_text: str, stage_text: str, session: AsyncSession) -> list[dict]:
    """检测源文档中的化学品并返回其 MSDS 摘要行（含匹配到的 synonym 标签）。"""
    from app.modules.safety.models import MsdsDocument

    combined = f"{raw_text}\n{stage_text}"
    combined_norm = _normalize(combined)

    rows = (
        await session.execute(
            select(MsdsDocument).where(
                MsdsDocument.is_deleted.is_(False),
                MsdsDocument.name.isnot(None),
            )
        )
    ).scalars().all()

    hits: list[dict] = []
    for row in rows:
        synonyms = _split_synonyms(row.name or "")
        if not synonyms:
            continue
        keys = _match_keys(synonyms)
        hit_synonym = next(
            (k for k in keys if _text_contains_key(k, combined, combined_norm)),
            None,
        )
        if not hit_synonym:
            continue
        summary: dict = {
            "name": row.name,
            "cas_no": row.cas_no or "",
            "matched_by": hit_synonym,
        }
        for label, attr in _MSDS_PHYSICOCHEM_FIELDS:
            val = getattr(row, attr, None)
            if val:
                summary.setdefault("physicochemical", []).append(f"{label}：{val}")
        for label, attr in _MSDS_RESPONSE_FIELDS:
            val = getattr(row, attr, None)
            if val:
                summary[label] = str(val)
        hits.append(summary)
    return hits


async def _retrieve_regulations(
    description: str, session: AsyncSession
) -> tuple[list[dict], str]:
    """法规 RAG（纯全文，零 AI 调用）→ 切片列表 + 合并 Markdown。"""
    from app.modules.safety.knowledge.retriever import HybridRetriever

    retriever = HybridRetriever(session)  # 无 embedder / ai_service → text-only 路径
    report = await retriever.retrieve(
        description,
        target_chunks=RAG_TARGET_CHUNKS,
    )
    slices: list[dict] = []
    md_lines: list[str] = []
    for r in report.results:
        doc_label = r.source_doc or r.source_article or "法规"
        slices.append(
            {
                "source_doc": r.source_doc,
                "source_article": r.source_article,
                "chunk_text": r.chunk_text,
            }
        )
        md_lines.append(f"### {doc_label}\n{r.chunk_text}")
    return slices, "\n\n".join(md_lines)


def _stage_text(extracted) -> str:
    """工序名 + 工序段落（用于化学品检测与检索词构造）。"""
    parts: list[str] = []
    for s in _stages(extracted):
        name = _field(s, "name", "")
        if name:
            parts.append(str(name))
        for p in _field(s, "paragraphs", []) or []:
            parts.append(p if isinstance(p, str) else str(p))
    return "\n".join(parts)


def _stages(extracted):
    return _field(extracted, "process_stages", []) or []


def _field(obj, name: str, default):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _meta_field(meta, name: str) -> str:
    if not meta:
        return ""
    val = meta.get(name) if isinstance(meta, dict) else getattr(meta, name, "")
    return str(val or "").strip()


async def build_knowledge_package(
    *,
    extracted,
    raw_text: str,
    meta: dict | None = None,
    session: AsyncSession,
) -> dict:
    """构建知识参考包 KB。

    Args:
        extracted: layer1 提取结果（ExtractedData dataclass 或等价 dict）。
        raw_text: 源文档全文（SafetyDocumentParser.extract_text 输出）。
        meta: 可选 {product_name, post_name, department}。
        session: 用于法规 RAG + MSDS 查询的 AsyncSession。

    Returns:
        {
            "regulations_md": str,          # 法规切片 Markdown（空 = 未检索到）
            "regulations": [{"source_doc", "source_article", "chunk_text"}],
            "msds": {化学品名: 摘要 dict},   # 空 = 未检出/未收录
            "warnings": [str],
        }
    任一知识源失败仅告警，不抛异常。
    """
    warnings: list[str] = []
    stage_text = _stage_text(extracted)

    # ── 法规 RAG ──
    product = _meta_field(meta, "product_name")
    post = _meta_field(meta, "post_name")
    description = " ".join(
        filter(
            None,
            [
                "原料药" if product else "",
                product,
                f"{post}岗位" if post else "",
                "生产工艺",
                " ".join(str(_field(s, "name", "")) for s in _stages(extracted)),
            ],
        )
    ).strip()
    if not description:
        description = raw_text[:2000] or "岗位生产工艺"

    try:
        slices, regulations_md = await _retrieve_regulations(description, session)
        if not slices:
            warnings.append("法规 RAG 未检索到相关切片（索引可能未构建）")
    except Exception as exc:  # noqa: BLE001 — RAG 失败仅告警
        logger.warning("SOP 知识包法规 RAG 失败：%s", exc)
        slices, regulations_md = [], ""
        warnings.append(f"法规 RAG 检索失败：{str(exc)[:120]}")

    # ── MSDS 台账 ──
    try:
        msds_hits = await _detect_msds(raw_text, stage_text, session)
        msds = {h["name"]: {k: v for k, v in h.items() if k != "name"} for h in msds_hits}
    except Exception as exc:  # noqa: BLE001 — MSDS 失败仅告警
        logger.warning("SOP 知识包 MSDS 查询失败：%s", exc)
        msds_hits = []
        msds = {}
        warnings.append(f"MSDS 台账查询失败：{str(exc)[:120]}")

    if not msds_hits:
        warnings.append("未在 MSDS 台账中检出源文档化学品（或台账未收录）")

    return {
        "regulations_md": regulations_md,
        "regulations": slices,
        "msds": msds,
        "warnings": warnings,
    }
