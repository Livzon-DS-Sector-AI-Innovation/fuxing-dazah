"""主数据对齐器（S2 ticket 02，spec Implementation Decisions 7）。

职责单一：识别出的物料名称（``recognized.material_name``）→
material_master 主数据标准条目对齐。LLM 不参与（纯确定性算法），
匹配优先级（spec）：ERP编码精确 > 名称归一化精确 > 前缀 > difflib
ratio ≥0.6 模糊；多候选并列时用识别的生产商/供应商辅助 tie-break。

主数据源：material_master 表（物料名称代码一览表）全量分页拉取
（~602 条），模块级缓存 TTL 300s（参照 ``bitable_schema`` 的
``_runtime_fields_cache`` 模式）；读回值形态兼容单选数组/富文本
分段/类型包裹（``tools/query.py`` ``_cell_text`` 同款契约，本地实现
小型 :func:`_norm_cell`）。

未命中 → ``aligned.material_name`` 保留识别原文、
``match_confidence=none``（不阻塞其他字段，卡片提示人工选择）。
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.modules.warehouse.agent.pipeline.recognizer import RecognizedReceipt
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

logger = logging.getLogger(__name__)

# ── 常量 ──

MASTER_TABLE_KEY = "material_master"  # 物料名称代码一览表（bitable_schema.TABLES）
MASTER_CACHE_KEY = "material_master"
MASTER_CACHE_TTL = 300.0  # spec：记录级缓存 TTL 300s
FUZZY_MIN_RATIO = 0.6  # spec：difflib ratio ≥0.6 才算模糊命中
MASTER_PAGE_SIZE = 500  # records/search 单页上限

# 主数据提取字段（读回值形态：单选 str 或 list、ERP编码富文本分段）
MASTER_FIELDS: tuple[str, ...] = (
    "物料名称",
    "代码",
    "级别",
    "飞书规格",
    "物料大类",
    "物料细分类",
    "单位换算",
    "生产商",
    "供应商",
    "ERP编码",
)

# 归一化删除的空白字符（含 NFKC 后的全角空格落点 U+0020、U+00A0、U+3000）
_WS_CHARS = " \t\r\n\f\v\u00a0\u3000"
_WS_TABLE = str.maketrans("", "", _WS_CHARS)


@dataclass(frozen=True)
class MaterialMasterEntry:
    """material_master 单条主数据（对齐候选）。"""

    name: str  # 物料名称（Base 单选合法值，标准名）
    code: str  # 代码
    level: str  # 级别
    spec: str  # 飞书规格（多值 "、" 连接；aligned 暂不输出，备查）
    category: str  # 物料大类
    sub_category: str  # 物料细分类
    unit: str  # 单位换算（单位建议来源）
    manufacturer: str  # 生产商
    supplier: str  # 供应商
    erp_code: str  # ERP编码


class AlignedReceipt(BaseModel):
    """一张送货单的对齐结果。

    - recognized 原样保留（对齐不改写识别值，审计可回溯）；
    - aligned 为对齐后字段：material_name（主数据标准名，none 时保留
      识别原文）/code/level/material_category/sub_category/
      unit_suggestion + supplier_matched/manufacturer_matched；
    - match_confidence ∈ {exact, prefix, fuzzy, none}；
    - match_detail 记录匹配依据（归一化键/候选名/ratio/方向）。
    """

    recognized: RecognizedReceipt
    aligned: dict[str, Any]
    match_confidence: str
    match_detail: dict[str, Any] = Field(default_factory=dict)


# ── 值形态规范化 ──


def _norm_cell(value: Any) -> str:
    """单元格值 → 单段文本（兼容实测形态，见 tools/query.py _cell_list）。

    实测形态：标量 / 数组（单选读回、多规格）/ 富文本分段
    ``{"text": ...}`` / 类型包裹 ``{"type": ..., "value": [...]}``；
    单值场景取第一个非空段。
    """
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [p for p in (_norm_cell(item) for item in value) if p]
        return parts[0] if parts else ""
    if isinstance(value, dict):
        for key in ("text", "value", "name"):
            if key in value:
                return _norm_cell(value[key])
        return ""
    return str(value).strip()


def _norm_cell_join(value: Any) -> str:
    """多值单元格（如飞书规格数组）→ "、" 连接文本。"""
    if value is None:
        return ""
    if isinstance(value, list):
        return "、".join(p for p in (_norm_cell(item) for item in value) if p)
    return _norm_cell(value)


def normalize_name(text: str) -> str:
    """名称归一化键：NFKC 全角→半角 + 去全部空白 + casefold。

    送货单排版空格（'硫　酸'/'硫 酸'）与主数据录入差异（全角逗号/
    括号、大小写）都在此吸收；化学名内部空格无语义，直接去除。
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.translate(_WS_TABLE).casefold().strip()


# ── 匹配（纯函数，可直测） ──


def _aux_score(
    entry: MaterialMasterEntry, manu_norm: str, supp_norm: str
) -> tuple[int, int]:
    """生产商/供应商辅助分：生产商一致 (2, ·)，供应商一致 (·, 1)。"""
    m = 2 if manu_norm and normalize_name(entry.manufacturer) == manu_norm else 0
    s = 1 if supp_norm and normalize_name(entry.supplier) == supp_norm else 0
    return m, s


def _pick_best(
    candidates: list[MaterialMasterEntry],
    score_fn: Callable[[MaterialMasterEntry], tuple[float, ...]],
) -> MaterialMasterEntry:
    """按分数取最优（严格大于才替换 → 同分保持原顺序，结果确定）。"""
    best = candidates[0]
    best_key = score_fn(best)
    for cand in candidates[1:]:
        key = score_fn(cand)
        if key > best_key:
            best, best_key = cand, key
    return best


def match_material(
    name_text: str,
    entries: list[MaterialMasterEntry],
    *,
    manufacturer: str = "",
    supplier: str = "",
) -> tuple[MaterialMasterEntry | None, str, dict[str, Any]]:
    """四级匹配：exact → prefix（双向）→ fuzzy → none。

    返回 (命中条目 | None, match_confidence, match_detail)。
    - exact：归一化后精确相等；
    - prefix：识别名是主数据名前缀（forward，spec 例：'硫酸'→'硫酸铵'）
      或主数据名是识别名前缀（reverse，识别名带杂质后缀）——forward
      优先于 reverse，方向记入 detail 供下游区分置信；
    - fuzzy：difflib ratio ≥0.6 取最高（同 ratio 用生产商/供应商加分）；
    - 多候选并列时生产商(+2)/供应商(+1)辅助 tie-break。
    """
    key = normalize_name(name_text)
    detail: dict[str, Any] = {
        "key": key,
        "matched_by": "none",
        "candidate": "",
        "candidate_code": "",
        "ratio": None,
    }
    if not key:
        return None, "none", detail

    manu_norm = normalize_name(manufacturer)
    supp_norm = normalize_name(supplier)

    def _finalize(
        entry: MaterialMasterEntry | None, confidence: str, **extra: Any
    ) -> tuple[MaterialMasterEntry | None, str, dict[str, Any]]:
        detail.update(extra)
        detail["matched_by"] = confidence
        if entry is not None:
            detail["candidate"] = entry.name
            detail["candidate_code"] = entry.code
        detail["manufacturer_matched"] = bool(
            manu_norm and entry is not None and normalize_name(entry.manufacturer) == manu_norm
        )
        detail["supplier_matched"] = bool(
            supp_norm and entry is not None and normalize_name(entry.supplier) == supp_norm
        )
        return entry, confidence, detail

    # 1. exact：归一化精确相等（同名多记录 → 生产商/供应商择优）
    exact = [e for e in entries if e.name and normalize_name(e.name) == key]
    if exact:
        best = _pick_best(exact, lambda e: _aux_score(e, manu_norm, supp_norm))
        return _finalize(best, "exact")

    # 2. prefix：双向（forward 优先，方向记入 detail）
    def _overlap(e: MaterialMasterEntry) -> float:
        n = len(normalize_name(e.name))
        return min(n, len(key)) / max(n, len(key))

    forward = [e for e in entries if e.name and normalize_name(e.name).startswith(key)]
    reverse = [e for e in entries if e.name and key.startswith(normalize_name(e.name))]
    if forward or reverse:
        best = _pick_best(
            forward or reverse,
            lambda e: (*_aux_score(e, manu_norm, supp_norm), _overlap(e)),
        )
        return _finalize(best, "prefix", direction="forward" if forward else "reverse")

    # 3. fuzzy：ratio ≥0.6 取最高（同 ratio 生产商/供应商加分）
    fuzzy_best: MaterialMasterEntry | None = None
    fuzzy_key: tuple[float, ...] = (0.0,)
    for entry in entries:
        if not entry.name:
            continue  # 空名主数据不参与匹配
        ratio = SequenceMatcher(None, key, normalize_name(entry.name)).ratio()
        if ratio < FUZZY_MIN_RATIO:
            continue
        cand_key = (
            round(ratio, 3),
            *_aux_score(entry, manu_norm, supp_norm),
        )
        if cand_key > fuzzy_key:
            fuzzy_best, fuzzy_key = entry, cand_key
    if fuzzy_best is not None:
        return _finalize(fuzzy_best, "fuzzy", ratio=fuzzy_key[0])

    return _finalize(None, "none")


# ── 主数据加载（模块级缓存，TTL 300s） ──

_master_cache: dict[str, tuple[float, list[MaterialMasterEntry]]] = {}
_now: Callable[[], float] = time.monotonic  # 测试注入时钟用
_adapter: WarehouseBitableAdapter | None = None


def _get_adapter() -> WarehouseBitableAdapter:
    """适配器惰性单例（测试 monkeypatch 注入口：aligner._adapter = fake）。"""
    global _adapter
    if _adapter is None:
        _adapter = WarehouseBitableAdapter()
    return _adapter


def _to_entry(fields: dict[str, Any]) -> MaterialMasterEntry:
    """主数据记录 fields → MaterialMasterEntry（值形态规范化）。"""
    return MaterialMasterEntry(
        name=_norm_cell(fields.get("物料名称")),
        code=_norm_cell(fields.get("代码")),
        level=_norm_cell(fields.get("级别")),
        spec=_norm_cell_join(fields.get("飞书规格")),
        category=_norm_cell(fields.get("物料大类")),
        sub_category=_norm_cell_join(fields.get("物料细分类")),
        unit=_norm_cell(fields.get("单位换算")),
        manufacturer=_norm_cell(fields.get("生产商")),
        supplier=_norm_cell(fields.get("供应商")),
        erp_code=_norm_cell(fields.get("ERP编码")),
    )


async def _fetch_master_entries() -> list[MaterialMasterEntry]:
    """全量分页拉取 material_master 并解析为对齐候选条目。"""
    adapter = _get_adapter()
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        page = await adapter.search_records_page(
            MASTER_TABLE_KEY,
            field_names=list(MASTER_FIELDS),
            limit=MASTER_PAGE_SIZE,
            page_token=page_token,
        )
        records.extend(page["records"])
        page_token = page.get("page_token")
        if not page_token:
            break
    entries = [_to_entry(record.get("fields") or {}) for record in records]
    logger.info("主数据拉取完成: %s 条（material_master）", len(entries))
    return entries


async def get_master_entries(*, force_refresh: bool = False) -> list[MaterialMasterEntry]:
    """主数据全量条目（TTL 内复用进程内缓存，过期重新拉取）。"""
    cached = _master_cache.get(MASTER_CACHE_KEY)
    if not force_refresh and cached is not None and (_now() - cached[0]) < MASTER_CACHE_TTL:
        return cached[1]
    entries = await _fetch_master_entries()
    _master_cache[MASTER_CACHE_KEY] = (_now(), entries)
    return entries


# ── 对齐入口 ──


async def align_receipt(recognized: RecognizedReceipt) -> AlignedReceipt:
    """对齐一张识别结果（RecognizedReceipt → AlignedReceipt）。

    匹配对象为 recognized.material_name.value（空则直接 none）；
    recognized.manufacturer/supplier 作为多候选 tie-break 辅助。
    未命中时 aligned.material_name 保留识别原文（不阻塞，卡片提示人工选择）。
    """
    entries = await get_master_entries()
    raw_name = recognized.material_name.value
    name_text = "" if raw_name is None else str(raw_name)
    manufacturer = (
        "" if recognized.manufacturer is None or recognized.manufacturer.value is None
        else str(recognized.manufacturer.value)
    )
    supplier = (
        "" if recognized.supplier is None or recognized.supplier.value is None
        else str(recognized.supplier.value)
    )
    entry, confidence, detail = match_material(
        name_text, entries, manufacturer=manufacturer, supplier=supplier
    )
    aligned: dict[str, Any] = {
        "material_name": entry.name if entry is not None else name_text.strip(),
        "code": entry.code if entry is not None else "",
        "level": entry.level if entry is not None else "",
        "material_category": entry.category if entry is not None else "",
        "sub_category": entry.sub_category if entry is not None else "",
        "unit_suggestion": entry.unit if entry is not None else "",
        "supplier_matched": bool(detail.get("supplier_matched")),
        "manufacturer_matched": bool(detail.get("manufacturer_matched")),
    }
    return AlignedReceipt(
        recognized=recognized,
        aligned=aligned,
        match_confidence=confidence,
        match_detail=detail,
    )


async def align_batch(dataset_dir: Path) -> dict[str, Any]:
    """批量为 truth.jsonl 真值物料名做对齐（评估用，不走 LLM）。

    返回 {total, exact, prefix, fuzzy, none, hit_rate, misses}；
    命中率 =（exact + prefix + 0.5×fuzzy）/ total（fuzzy 计半命中）；
    misses 为 fuzzy/none 明细（如实报告用）。
    """
    truth_path = dataset_dir / "truth.jsonl"
    rows = [
        json.loads(line)
        for line in truth_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entries = await get_master_entries()
    counts: dict[str, int] = {"exact": 0, "prefix": 0, "fuzzy": 0, "none": 0}
    misses: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("物料名称") or "")
        entry, confidence, detail = match_material(
            name,
            entries,
            manufacturer=str(row.get("生产商") or ""),
            supplier=str(row.get("供应商") or ""),
        )
        counts[confidence] += 1
        if confidence in ("fuzzy", "none"):
            misses.append(
                {
                    "record_id": row.get("record_id", ""),
                    "name": name,
                    "confidence": confidence,
                    "aligned_name": entry.name if entry is not None else "",
                    "detail": detail,
                }
            )
    total = len(rows)
    hit_rate = (
        (counts["exact"] + counts["prefix"] + 0.5 * counts["fuzzy"]) / total
        if total
        else 0.0
    )
    return {"total": total, **counts, "hit_rate": round(hit_rate, 4), "misses": misses}
