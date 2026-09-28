"""成品产品名录对齐器（2026-09-28 识别完善 A 项）。

成品入库识别此前 ``mark_direct_aligned`` 落空 aligned：识别值直接上卡片，
产品名错一个字、批号认错一位、单位认错机器一概不拦，全靠人工对话修正。
本模块照原辅料 aligner（``aligner.py``）模式补齐纠错层：

- 名录来源：**台账历史即名录**——成品出库台账（finished_outbound）+ 成品
  入库台账（finished_receipt）历史行的 产品名称/品规/单位/产品批号 去重
  聚合（无独立成品名录表；台账产品名来自 Base 单选选项值，天然是合法
  提交值）。分页拉取上限与 finished_data 同款（500×10 页）。
- 五级匹配（match_material 同构）：exact 归一化精确 → prefix 双向前缀
  （forward 优先）→ fuzzy difflib ratio ≥0.6 → none；多候选 tie-break：
  单位一致 (+2) / 品规一致 (+1)。
- 字段校验（识别错值的机器侧拦截，只警示不改值）：
  - 单位：命中产品且识别单位不在该产品历史单位集 → unit 警示；
  - 批号：命中产品且识别批号字母前缀（如 DA2609001 → DA）不在该产品
    历史前缀集（历史前缀 1-3 种才判，防录入口径杂音）→ batch 警示。
- rows 逐行产品名对齐：对齐后的行集写 ``aligned["rows"]``（submit 归组
  与卡片多行展示优先读，识别原始 rows 留 recognized 审计可回溯）。
- 与原辅料对齐的口径差异：未命中时**不写** aligned["product_name"]
  （保留识别值+置信度 ⚠ 展示——成品卡片无独立对齐行兜底展示识别值）；
  命中才写标准名。
- 名录拉取失败不阻断主链路：返回 no-op 对齐结果（aligned 空、无警示），
  行为与原 mark_direct_aligned 等价。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.modules.warehouse.agent.pipeline.aligner import normalize_name
from app.modules.warehouse.agent.pipeline.recognizer import RecognizedFinishedReceipt
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

logger = logging.getLogger(__name__)

# 名录拉取表与字段（台账历史即名录；两表取并集）
DIRECTORY_TABLES: tuple[str, ...] = ("finished_outbound", "finished_receipt")
DIRECTORY_FIELDS: tuple[str, ...] = ("产品名称", "产品批号", "品规", "单位")

# 模块级缓存（aligner._master_cache 同模式）：名录口径变化低频（新品上架），
# TTL 内复用；测试经 _directory_cache 清空/时钟注入
DIRECTORY_CACHE_TTL = 300.0
DIRECTORY_PAGE_SIZE = 500
DIRECTORY_MAX_PAGES = 10  # 分页上限防御（>5000 行截断，finished_data 同款）

FUZZY_MIN_RATIO = 0.6  # fuzzy 命中下限（aligner.FUZZY_MIN_RATIO 同值；独立常量免 runtime 耦合）

# 批号字母前缀（DA2609001 → DA）；长度下限 2 防单字母杂音
_BATCH_PREFIX_RE = re.compile(r"^[A-Za-z]{2,}")
# 产品历史批号前缀 ≤N 种才启用批号警示（超过视为录入口径杂音，不判）
_BATCH_PREFIX_MAX_FOR_WARN = 3

# 警示键（aligned["warnings"] 的 canonical 键；卡片/网页按此渲染）
WARN_PRODUCT_NAME = "product_name"
WARN_UNIT = "unit"
WARN_BATCH = "product_batch_no"


@dataclass(frozen=True)
class FinishedProductEntry:
    """名录单条：一个产品名聚合的品规/单位/批号前缀全集。"""

    name: str  # Base 单选合法值（台账历史名）
    specs: tuple[str, ...]
    units: tuple[str, ...]
    batch_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class FinishedAlignedReceipt:
    """一张成品入库单的对齐结果（draft_flow.mark_finished_aligned 落库）。

    - aligned：product_name（命中时标准名；未命中不写该键）+ rows（识别
      rows 存在时的逐行对名行集）——submit/卡片取值口径与其余 canonical
      键相同；match_confidence/match_detail/warnings 三个元数据键一并落
      aligned（原辅料 mark_aligned 同款形态）；
    - warnings：canonical 键 → 警示文案（dict；只警示不改值）。
    """

    aligned: dict[str, Any] = field(default_factory=dict)
    match_confidence: str = ""
    match_detail: dict[str, Any] = field(default_factory=dict)
    warnings: dict[str, str] = field(default_factory=dict)


def batch_prefix(batch_no: str) -> str:
    """批号字母前缀（DA2609001 → DA；无 2 位以上字母前缀返回空串）。"""
    match = _BATCH_PREFIX_RE.match(batch_no.strip())
    return match.group(0).upper() if match else ""


# ── 匹配（纯函数，可直测） ──


def _aux_score(entry: FinishedProductEntry, unit_norm: str, spec_norm: str) -> tuple[int, int]:
    """tie-break 辅助分：单位一致 (2, ·)，品规一致 (·, 1)。"""
    u = 2 if unit_norm and unit_norm in {normalize_name(x) for x in entry.units} else 0
    s = 1 if spec_norm and spec_norm in {normalize_name(x) for x in entry.specs} else 0
    return u, s


def _pick_best(
    candidates: list[FinishedProductEntry],
    score_fn: Any,
) -> FinishedProductEntry:
    """按分数取最优（严格大于才替换 → 同分保持原顺序，结果确定）。"""
    best = candidates[0]
    best_key = score_fn(best)
    for cand in candidates[1:]:
        key = score_fn(cand)
        if key > best_key:
            best, best_key = cand, key
    return best


def match_product(
    name_text: str,
    entries: list[FinishedProductEntry],
    *,
    unit: str = "",
    spec: str = "",
) -> tuple[FinishedProductEntry | None, str, dict[str, Any]]:
    """四级匹配：exact → prefix（双向，forward 优先）→ fuzzy → none。

    返回 (命中条目 | None, match_confidence, match_detail)；detail 含
    key/matched_by/candidate/candidate_units/batch_prefixes/ratio。
    """
    key = normalize_name(name_text)
    detail: dict[str, Any] = {
        "key": key,
        "matched_by": "none",
        "candidate": "",
        "candidate_units": (),
        "batch_prefixes": (),
        "ratio": None,
    }
    if not key:
        return None, "none", detail

    unit_norm = normalize_name(unit)
    spec_norm = normalize_name(spec)

    def _finalize(
        entry: FinishedProductEntry | None, confidence: str, **extra: Any
    ) -> tuple[FinishedProductEntry | None, str, dict[str, Any]]:
        detail.update(extra)
        detail["matched_by"] = confidence
        if entry is not None:
            detail["candidate"] = entry.name
            detail["candidate_units"] = entry.units
            detail["batch_prefixes"] = entry.batch_prefixes
        return entry, confidence, detail

    exact = [e for e in entries if normalize_name(e.name) == key]
    if exact:
        best = _pick_best(exact, lambda e: _aux_score(e, unit_norm, spec_norm))
        return _finalize(best, "exact")

    def _overlap(e: FinishedProductEntry) -> float:
        n = len(normalize_name(e.name))
        return min(n, len(key)) / max(n, len(key))

    forward = [e for e in entries if normalize_name(e.name).startswith(key)]
    reverse = [e for e in entries if key.startswith(normalize_name(e.name))]
    if forward or reverse:
        best = _pick_best(
            forward or reverse,
            lambda e: (*_aux_score(e, unit_norm, spec_norm), _overlap(e)),
        )
        return _finalize(best, "prefix", direction="forward" if forward else "reverse")

    from difflib import SequenceMatcher

    fuzzy_best: FinishedProductEntry | None = None
    fuzzy_key: tuple[float, ...] = (0.0,)
    for entry in entries:
        ratio = SequenceMatcher(None, key, normalize_name(entry.name)).ratio()
        if ratio < FUZZY_MIN_RATIO:
            continue
        cand_key = (round(ratio, 3), *_aux_score(entry, unit_norm, spec_norm))
        if cand_key > fuzzy_key:
            fuzzy_best, fuzzy_key = entry, cand_key
    if fuzzy_best is not None:
        return _finalize(fuzzy_best, "fuzzy", ratio=fuzzy_key[0])

    return _finalize(None, "none")


# ── 名录加载（模块级缓存，TTL 300s） ──

_directory_cache: dict[str, tuple[float, list[FinishedProductEntry]]] = {}
_now: Any = time.monotonic  # 测试注入时钟用
_adapter: WarehouseBitableAdapter | None = None


def _get_adapter() -> WarehouseBitableAdapter:
    """适配器惰性单例（测试 monkeypatch 注入口：finished_aligner._adapter）。"""
    global _adapter
    if _adapter is None:
        _adapter = WarehouseBitableAdapter()
    return _adapter


def _cell_text(value: Any) -> str:
    """单元格值 → 单段文本（单选数组/富文本分段兼容，aligner._norm_cell 同款）。"""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [p for p in (_cell_text(item) for item in value) if p]
        return parts[0] if parts else ""
    if isinstance(value, dict):
        for key in ("text", "value", "name"):
            if key in value:
                return _cell_text(value[key])
        return ""
    return str(value).strip()


def _aggregate_entries(records: list[dict[str, Any]]) -> list[FinishedProductEntry]:
    """台账历史行 → 按归一化名聚合的名录条目（保持首现顺序）。"""
    agg: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records:
        fields = record.get("fields") or {}
        name = _cell_text(fields.get("产品名称"))
        if not name:
            continue
        key = normalize_name(name)
        bucket = agg.get(key)
        if bucket is None:
            bucket = {"name": name, "specs": set(), "units": set(), "prefixes": set()}
            agg[key] = bucket
            order.append(key)
        spec = _cell_text(fields.get("品规"))
        if spec:
            bucket["specs"].add(spec)
        unit = _cell_text(fields.get("单位"))
        if unit:
            bucket["units"].add(unit)
        prefix = batch_prefix(_cell_text(fields.get("产品批号")))
        if prefix:
            bucket["prefixes"].add(prefix)
    return [
        FinishedProductEntry(
            name=bucket["name"],
            specs=tuple(sorted(bucket["specs"])),
            units=tuple(sorted(bucket["units"])),
            batch_prefixes=tuple(sorted(bucket["prefixes"])),
        )
        for key in order
        for bucket in [agg[key]]
    ]


async def _fetch_directory_records() -> list[dict[str, Any]]:
    """两表台账历史行全量拉取（分页上限防御）。"""
    adapter = _get_adapter()
    records: list[dict[str, Any]] = []
    for table_key in DIRECTORY_TABLES:
        page_token: str | None = None
        pages = 0
        while pages < DIRECTORY_MAX_PAGES:
            page = await adapter.search_records_page(
                table_key,
                field_names=list(DIRECTORY_FIELDS),
                limit=DIRECTORY_PAGE_SIZE,
                page_token=page_token,
            )
            records.extend(page["records"])
            page_token = page.get("page_token")
            pages += 1
            if not page_token:
                break
        if page_token:
            logger.warning("成品名录拉取截断: table=%s 超过 %s 页", table_key, DIRECTORY_MAX_PAGES)
    return records


async def get_finished_product_entries(
    *, force_refresh: bool = False
) -> list[FinishedProductEntry]:
    """成品名录条目（TTL 内复用进程内缓存，过期重新拉取）。"""
    cached = _directory_cache.get("finished_products")
    if not force_refresh and cached is not None and (_now() - cached[0]) < DIRECTORY_CACHE_TTL:
        return cached[1]
    entries = _aggregate_entries(await _fetch_directory_records())
    _directory_cache["finished_products"] = (_now(), entries)
    logger.info("成品名录拉取完成: %s 个产品（finished_outbound + finished_receipt）", len(entries))
    return entries


# ── 对齐入口 ──


def _warn_text_for_match(recognized_name: str, entry: FinishedProductEntry, confidence: str, detail: dict[str, Any]) -> str:
    """产品名警示文案（未匹配/近似匹配；exact/prefix-forward 不警示）。"""
    if confidence == "none":
        return f"产品名称「{recognized_name}」未匹配成品名录，请核对"
    if confidence == "fuzzy" or detail.get("direction") == "reverse":
        return f"产品名称按近似匹配「{recognized_name}」→「{entry.name}」，请核对"
    return ""


def _align_row(
    row: dict[str, Any], entries: list[FinishedProductEntry]
) -> dict[str, Any]:
    """单行产品名对名（行级匹配命中才替换标准名；其余键原样）。"""
    aligned_row = {key: row.get(key) for key in row}
    name = str(row.get("product_name") or "").strip()
    if not name:
        return aligned_row
    entry, confidence, _ = match_product(
        name,
        entries,
        unit=str(row.get("unit") or ""),
        spec=str(row.get("spec") or ""),
    )
    if entry is not None and confidence in ("exact", "prefix", "fuzzy"):
        aligned_row["product_name"] = entry.name
    return aligned_row


def _field_text(recognized_field: Any) -> str:
    """RecognizedField | None → 文本（选提字段识别不到时字段本身为 None）。"""
    if recognized_field is None or recognized_field.value is None:
        return ""
    return str(recognized_field.value)


async def align_finished_receipt(
    recognized: RecognizedFinishedReceipt,
) -> FinishedAlignedReceipt:
    """对齐一张成品入库识别结果（识别 → 名录匹配 + 字段校验 + 行对名）。

    名录拉取/匹配异常一律降级为 no-op 结果（识别主链路不阻断——与
    classify_document/detect_rotation 同款容错哲学）。未命中产品名不写
    aligned["product_name"]（保留识别值+置信度 ⚠）；命中写标准名。
    """
    try:
        entries = await get_finished_product_entries()
    except Exception:  # noqa: BLE001 — 名录拉取失败不阻断识别链路
        logger.warning("成品名录拉取失败，本次识别不做对齐校验", exc_info=True)
        return FinishedAlignedReceipt(
            match_detail={"error": "directory_fetch_failed"},
        )

    recognized_name = _field_text(recognized.product_name)
    recognized_unit = _field_text(recognized.unit)
    recognized_spec = _field_text(recognized.spec)
    recognized_batch = _field_text(recognized.product_batch_no)

    aligned: dict[str, Any] = {}
    warnings: dict[str, str] = {}
    if not entries:
        return FinishedAlignedReceipt(
            aligned=aligned, match_confidence="", match_detail={"key": normalize_name(recognized_name)}, warnings=warnings
        )

    entry, confidence, detail = match_product(
        recognized_name,
        entries,
        unit=recognized_unit,
        spec=recognized_spec,
    )
    if entry is not None:
        # 命中写标准名（submit aligned 优先 → 台账写到合法单选值）
        aligned["product_name"] = entry.name
        warn = _warn_text_for_match(recognized_name, entry, confidence, detail)
        if warn:
            warnings[WARN_PRODUCT_NAME] = warn
        # 单位校验：识别单位不在该产品历史单位集 → 警示（不改值）
        if (
            recognized_unit
            and entry.units
            and normalize_name(recognized_unit) not in {normalize_name(x) for x in entry.units}
        ):
            warnings[WARN_UNIT] = (
                f"单位「{recognized_unit}」不在「{entry.name}」历史单位"
                f"（{'、'.join(entry.units)}）中，请核对"
            )
        # 批号前缀校验：历史前缀少而稳定时，不符 → 警示（不改值）
        recognized_prefix = batch_prefix(recognized_batch)
        if (
            recognized_prefix
            and 0 < len(entry.batch_prefixes) <= _BATCH_PREFIX_MAX_FOR_WARN
            and recognized_prefix not in entry.batch_prefixes
        ):
            warnings[WARN_BATCH] = (
                f"批号前缀「{recognized_prefix}」与「{entry.name}」历史批号前缀"
                f"（{'、'.join(entry.batch_prefixes)}）不符，请核对"
            )
    elif recognized_name:
        # 未命中：不写 aligned（保留识别值+置信度 ⚠ 展示），警示人工核对
        warnings[WARN_PRODUCT_NAME] = (
            f"产品名称「{recognized_name}」未匹配成品名录，请核对"
        )

    # rows 逐行对名 → aligned["rows"]（submit 归组/卡片多行展示优先读；
    # 识别原始 rows 留 recognized 审计回溯）
    if recognized.rows:
        aligned["rows"] = [_align_row(row, entries) for row in recognized.rows]

    return FinishedAlignedReceipt(
        aligned=aligned,
        match_confidence=confidence,
        match_detail=detail,
        warnings=warnings,
    )
