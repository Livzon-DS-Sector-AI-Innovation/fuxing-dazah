"""五金库四级主数据匹配器（设计 §9.1 L2；独立可复用奠基资产 §9.4-2）。

四级链：code 精确 → 名称+规格模糊 → 同义词 → 人工兜底（unmatched）。
每行输出 (匹配方式, 置信度 0-100, 物料)；低置信（默认 <75）标黄——
**只标记不代改**（MSDS 审核模式红线：AI 不改数据）。

纯函数设计：不依赖 DB session（调用方先 load 物料列表），任何库域的
主数据对齐可直接复用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Iterable, Protocol

# 匹配方式枚举（与 models.MATCH_METHODS 对齐）
METHOD_ERP_CODE = "erp_code"
METHOD_NAME_SPEC = "name_spec"
METHOD_SYNONYM = "synonym"
METHOD_MANUAL = "manual"
METHOD_UNMATCHED = "unmatched"

# 低置信阈值（低于=标黄人工确认；M2 验收口径）
LOW_CONFIDENCE_THRESHOLD = Decimal("75")

# 分数表
SCORE_CODE_EXACT = Decimal("100")
SCORE_NAME_SPEC_EXACT = Decimal("98")
SCORE_NAME_SPEC_CONTAIN = Decimal("92")
SCORE_MERGED_CONTAIN = Decimal("85")
SCORE_SYNONYM = Decimal("80")
SCORE_SIMILARITY_BASE = Decimal("82")  # difflib 相似匹配门槛

# ── 归一化 ──

_FULLWIDTH = {ord(f): ord(t) for f, t in zip("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｚ＊×", "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZaz**")}

# 规格常见变体：φ/Φ/ø/DN 大小写、×/x/*、mm、空格
_SPEC_NORMALIZE = [
    (re.compile(r"[φΦøØ]", re.I), "DN"),
    (re.compile(r"[×xX*]", ), "*"),
    (re.compile(r"\s+"), ""),
    (re.compile(r"(?<=\d)mm$", re.I), ""),
    (re.compile(r"^#", ), ""),
]


def normalize_text(value: str | None) -> str:
    """文本归一化：全角→半角、去空白、大写。"""
    if not value:
        return ""
    text = str(value).translate(_FULLWIDTH).strip().upper()
    return re.sub(r"\s+", "", text)


def normalize_spec(value: str | None) -> str:
    """规格归一化：φ→DN、×→*、去 mm/空格（DN25/φ25/25mm 等价）。"""
    text = normalize_text(value)
    for pattern, repl in _SPEC_NORMALIZE:
        text = pattern.sub(repl, text)
    return text


def normalize_name(value: str | None) -> str:
    """品名归一化：仅去空白全角化（保留中文语义，不删材质词）。"""
    return normalize_text(value)


# ── 同义词表（一期内置 + 逐步沉淀；3x 平台同义词机制先例）──

# 车间口语 → 规范词（可叠加：值也可以再映射）
_SYNONYMS: dict[str, str] = {
    "球阀": "球阀",
    "闸阀": "闸阀",
    "止回阀": "止回阀",
    "单向阀": "止回阀",
    "截止阀": "截止阀",
    "法兰": "法兰",
    "弯头": "弯头",
    "三通": "三通",
    "四通": "四通",
    "变径": "变径",
    "大小头": "变径",
    "直接": "直接头",
    "束节": "直接头",
    "由令": "活接",
    "活接头": "活接",
    "轴承": "轴承",
    "垫片": "垫片",
    "生料带": "生料带",
    "水管": "UPVC管",
    "pvC管": "UPVC管",
    "不锈纲": "不锈钢",
}

# 品名中的材质/类别停用词（同义词兜底时剥离口语量词后比对）
_STOPWORDS = re.compile(r"(多少|几个|有没有|请?帮?我?查?一下?|还有)")


def expand_synonyms(text: str) -> list[str]:
    """文本的同义词展开（含原文，去重）。"""
    out = [text]
    for src, dst in _SYNONYMS.items():
        if src in text and dst != src:
            out.append(text.replace(src, dst))
    # 链式一次（A→B→C）
    for candidate in out[1:]:
        for src, dst in _SYNONYMS.items():
            if src in candidate and dst != src:
                expanded = candidate.replace(src, dst)
                if expanded not in out:
                    out.append(expanded)
    return out


class MaterialLike(Protocol):
    """匹配器物料协议（HardwareMaterial 或任何带这些属性的对象）。"""

    id: Any
    code: str | None
    name: str
    spec: str | None
    managed_class: str


@dataclass(frozen=True)
class MatchResult:
    """单行匹配结果。material=None 即未匹配（人工兜底）。"""

    material: MaterialLike | None
    method: str
    score: Decimal

    @property
    def low_confidence(self) -> bool:
        return self.material is None or self.score < LOW_CONFIDENCE_THRESHOLD


def match_one(
    *,
    code: str | None = None,
    name: str | None = None,
    spec: str | None = None,
    materials: Iterable[MaterialLike],
) -> MatchResult:
    """四级匹配一行 OCR 提取（品名/规格/编码任一可缺）。

    L1 code 精确（100）→ L2 名称规格（归一化相等 98 / 包含 92 / 合并包含 85
    / 相似度 82-90）→ L3 同义词展开（80-88）→ L4 unmatched。
    """
    pool = list(materials)
    code_n = normalize_text(code)
    name_n = normalize_name(name)
    spec_n = normalize_spec(spec)

    # L1 编码精确
    if code_n:
        for m in pool:
            if m.code and normalize_text(m.code) == code_n:
                return MatchResult(m, METHOD_ERP_CODE, SCORE_CODE_EXACT)

    # L2 名称+规格
    if name_n:
        q_cats = _category_set(name)
        best: tuple[Decimal, MaterialLike] | None = None
        for m in pool:
            m_name = normalize_name(m.name)
            m_cats = _category_set(m.name)
            if q_cats and m_cats and not (q_cats & m_cats):
                continue  # 品类词护栏：跨品类不模糊吸附
            m_spec = normalize_spec(m.spec)
            score = _score_name_spec(name_n, spec_n, m_name, m_spec)
            if score is not None and (best is None or score > best[0]):
                # 同分时 stocked 优先（清单内共用类是业务主集合）
                if best is not None and score == best[0] and m.managed_class != "stocked":
                    continue
                best = (score, m)
        if best is not None and best[0] >= SCORE_SIMILARITY_BASE:
            return MatchResult(best[1], METHOD_NAME_SPEC, best[0])

        # L3 同义词展开（名称侧替换后再打一轮；q_cats 已含别名归一，护栏沿用）
        for candidate in expand_synonyms(name_n)[1:]:
            for m in pool:
                m_name = normalize_name(m.name)
                m_cats = _category_set(m.name)
                if q_cats and m_cats and not (q_cats & m_cats):
                    continue
                m_spec = normalize_spec(m.spec)
                score = _score_name_spec(candidate, spec_n, m_name, m_spec)
                if score is not None and score >= SCORE_SYNONYM:
                    return MatchResult(m, METHOD_SYNONYM, min(score, Decimal("88")))

    return MatchResult(None, METHOD_UNMATCHED, Decimal("0"))


# 品类词护栏（2026-11-06 真库演练实测）：止回阀→截止阀 一字之差跨品类
# 误配 stocked（清单无止回阀、有 14 个截止阀，相似度 85 直接吸附）。
# 阀/管件族品类词两侧都识别到且不相交 → 不许 L2/L3 模糊吸附。
_PART_CATEGORY_WORDS = (
    "球阀", "闸阀", "止回阀", "截止阀", "法兰", "弯头", "三通", "四通",
    "变径", "直接头", "活接", "轴承", "垫片", "UPVC管",
)


def _category_set(text: str | None) -> set[str]:
    """文本命中的品类词集合（含同义词别名归一——单向阀→止回阀）。"""
    if not text:
        return set()
    cats = {w for w in _PART_CATEGORY_WORDS if w in text}
    for src, dst in _SYNONYMS.items():
        if src in text:
            cats.add(dst)
    return cats


def _skeleton(name: str) -> str:
    """品名骨架：剥离常见材质/工艺间隔词（简称比对用）。"""
    for filler in ("不锈钢", "碳钢", "合金", "UPVC", "PVC", "ABS", "304", "316", "PPR"):
        name = name.replace(filler, "")
    return name


def _score_name_spec(
    name_n: str, spec_n: str, m_name: str, m_spec: str
) -> Decimal | None:
    """名称+规格组合打分：None=名称都不沾边。"""
    if not name_n or not m_name:
        return None
    if name_n == m_name:
        if not spec_n or not m_spec:
            return SCORE_NAME_SPEC_EXACT - Decimal("6")  # 缺规格侧降权
        if spec_n == m_spec:
            return SCORE_NAME_SPEC_EXACT
        if spec_n in m_spec or m_spec in spec_n:
            return SCORE_NAME_SPEC_CONTAIN
        return None
    # 包含（长名含短名）按主数据为锚
    if m_name and (m_name in name_n or name_n in m_name):
        if spec_n and m_spec:
            if spec_n == m_spec:
                return SCORE_NAME_SPEC_CONTAIN + Decimal("2")
            if spec_n in m_spec or m_spec in spec_n:
                return SCORE_MERGED_CONTAIN
        elif not spec_n or not m_spec:
            return SCORE_MERGED_CONTAIN - Decimal("8")
    # 品名+规格合并串包含（OCR 单行「304球阀DN25」形态）
    merged = f"{name_n}{spec_n}"
    m_merged = f"{m_name}{m_spec}"
    if len(merged) >= 4 and len(m_merged) >= 4 and (m_merged in merged or merged in m_merged):
        return SCORE_MERGED_CONTAIN
    # 简称/别写骨架比对（「304球阀」vs「304不锈钢球阀」）：去常见材质间隔词
    # 后相等 → 视作包含命中（分数降权，OCR 简称常态）
    if _skeleton(name_n) == _skeleton(m_name):
        if spec_n and m_spec and spec_n == m_spec:
            return SCORE_MERGED_CONTAIN - Decimal("3")
        return SCORE_MERGED_CONTAIN - Decimal("8")
    # 相似度兜底（长名比对）
    ratio = SequenceMatcher(None, name_n, m_name).ratio()
    if ratio >= 0.82:
        base = SCORE_SIMILARITY_BASE + Decimal(str(int((ratio - 0.82) * 50)))
        if spec_n and m_spec:
            if spec_n == m_spec:
                return base + Decimal("8")
            if spec_n in m_spec or m_spec in spec_n:
                return base
        return base - Decimal("6")
    return None


def strip_query_words(text: str) -> str:
    """搜索/口语查询词清洗（「还有多少个25的阀门」→「25的阀门」）。"""
    return _STOPWORDS.sub("", text or "").strip()


def extract_spec_from_colloquial(text: str) -> str | None:
    """口语规格提取：「25的阀门」「540法兰」→ DN25 / DN540（搜索辅助）。"""
    cleaned = strip_query_words(text)
    m = re.search(r"(?:DN)?(\d{2,4})\s*(?:的|mm|MM)?", cleaned)
    if m:
        return f"DN{m.group(1)}"
    return None
