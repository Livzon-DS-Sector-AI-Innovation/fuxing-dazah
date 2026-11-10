"""PQR 趋势与年终汇总：数值序列 + OOS/OOT 判定、汇总矩阵；统计量一律
查询时计算不入库。"""

from __future__ import annotations

import statistics
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.models import AprNdPolicy, AprValueType
from app.modules.qa.repository import apr as repo
from app.modules.qa.service.apr.common import (
    _get_item_or_404,
    _get_product_or_404,
    _get_section_or_404,
    _item_dict,
    _product_dict,
    _section_dict,
)

# 趋势/汇总统计最少样本数：低于该值不给 ±3σ（单点无意义）。
MIN_STATS_SAMPLES = 2


def get_cpk_level(cpk: float) -> str:
    """CPK 分级（对齐年度回顾工具 qa_year_review：特优/优/良/一般/差）。"""
    if cpk >= 3:
        return "特优"
    if cpk >= 1.33:
        return "优"
    if cpk >= 1.0:
        return "良"
    if cpk >= 0.6:
        return "一般"
    return "差"


def compute_column_stats(
    values: list[float],
    *,
    spec_min: float | None = None,
    spec_max: float | None = None,
) -> dict[str, Any]:
    """单列完整统计（趋势/汇总/报告共用源；qa_year_review 同口径）。

    基础量 count/mean/max/min 恒有；样本 ≥2 补 σ 与 ±3σ/±4σ；CPK 家族
    需 σ>0 且至少一个标准限：单上限只算 CPKu、单下限只算 CPKl（CPK=该值），
    双限另有 T/U/ca/cp 与警告限（U±0.5·T/2）/行动限（U±0.8·T/2）。
    全同值（σ=0）CPK 无意义不输出。
    """
    if not values:
        return {"count": 0}
    mean = statistics.fmean(values)
    stats: dict[str, Any] = {
        "count": len(values),
        "mean": mean,
        "max": max(values),
        "min": min(values),
    }
    if len(values) < MIN_STATS_SAMPLES:
        return stats
    stdev = statistics.stdev(values)
    stats.update(
        {
            "stdev": stdev,
            "plus3s": mean + 3 * stdev,
            "minus3s": mean - 3 * stdev,
            "plus4s": mean + 4 * stdev,
            "minus4s": mean - 4 * stdev,
        }
    )
    if stdev <= 0 or (spec_min is None and spec_max is None):
        return stats
    if spec_max is not None:
        stats["cpku"] = abs(spec_max - mean) / (3 * stdev)
    if spec_min is not None:
        stats["cpkl"] = abs(mean - spec_min) / (3 * stdev)
    if "cpku" in stats and "cpkl" in stats:
        cpk = min(stats["cpku"], stats["cpkl"])
    else:
        cpk = stats["cpku"] if "cpku" in stats else stats["cpkl"]
    stats["cpk"] = cpk
    stats["cpk_level"] = get_cpk_level(cpk)
    if spec_min is not None and spec_max is not None:
        tolerance = spec_max - spec_min
        center = (spec_max + spec_min) / 2
        stats.update(
            {
                "tolerance": tolerance,
                "spec_center": center,
                "ca": (mean - center) / (tolerance / 2),
                "cp": tolerance / (6 * stdev),
                "warn_max": center + 0.5 * tolerance / 2,
                "warn_min": center - 0.5 * tolerance / 2,
                "action_max": center + 0.8 * tolerance / 2,
                "action_min": center - 0.8 * tolerance / 2,
            }
        )
    return stats


def classify_point(
    value: float,
    *,
    spec_min: float | None,
    spec_max: float | None,
    oot_min: float | None,
    oot_max: float | None,
) -> str:
    """OOS=超标准限；OOT=超预警线但在标准内；其余 normal。"""
    if (spec_min is not None and value < spec_min) or (
        spec_max is not None and value > spec_max
    ):
        return "oos"
    if (oot_min is not None and value < oot_min) or (
        oot_max is not None and value > oot_max
    ):
        return "oot"
    return "normal"


def build_trend_points(
    series: list[Any],
    *,
    nd_policy: str,
    spec_min: float | None,
    spec_max: float | None,
    oot_min: float | None,
    oot_max: float | None,
) -> tuple[list[dict[str, Any]], list[float], int]:
    """把 load_numeric_series 行集转成（趋势点, 值样本, ND 批数）。

    页面趋势接口与 Word 报告图共用本函数（单一数据管线，两边数据恒一致）：
    文字结果行（未检出等）exclude 口径不进点不进样本、zero 口径按 0 计入；
    OOS/OOT 判定 ND 一律不参与（按 0 判会在设预警下限的列误报）。
    """
    points: list[dict[str, Any]] = []
    values: list[float] = []
    nd_count = 0
    for batch_id, batch_no, seq, batch_year, row_seq, value, text in series:
        is_nd = value is None
        if is_nd:
            nd_count += 1
            if nd_policy == AprNdPolicy.EXCLUDE.value:
                continue
            value = 0.0
            status = "normal"
        else:
            status = classify_point(
                value,
                spec_min=spec_min,
                spec_max=spec_max,
                oot_min=oot_min,
                oot_max=oot_max,
            )
        values.append(value)
        points.append(
            {
                "batch_id": str(batch_id),
                "batch_no": batch_no,
                "seq": seq,
                "year": batch_year,
                "row_seq": row_seq,
                "value": value,
                "nd": is_nd,
                "text": text,
                "status": status,
            }
        )
    return points, values, nd_count


async def trend(
    db: AsyncSession, item_id: uuid.UUID, *, year: int | None = None
) -> dict[str, Any]:
    item = await _get_item_or_404(db, item_id)
    if not item.trend_enabled:
        raise AppException(status_code=422, message="该列未启用趋势分析。")
    if item.value_type != AprValueType.NUMBER.value:
        raise AppException(status_code=422, message="文字型列不支持趋势分析。")
    section = await _get_section_or_404(db, item.section_id)
    product = await _get_product_or_404(db, section.product_id)
    series = await repo.load_numeric_series(db, item_id, year=year)
    points, values, nd_count = build_trend_points(
        series,
        nd_policy=item.nd_policy,
        spec_min=item.spec_min,
        spec_max=item.spec_max,
        oot_min=item.oot_min,
        oot_max=item.oot_max,
    )
    stats: dict[str, Any] = compute_column_stats(
        values, spec_min=item.spec_min, spec_max=item.spec_max
    )
    if nd_count:
        stats["nd_count"] = nd_count
    return {
        "item": _item_dict(item),
        "section": _section_dict(section),
        "product": _product_dict(product),
        "year": year,
        "points": points,
        "stats": stats,
    }


async def summary(
    db: AsyncSession,
    product_id: uuid.UUID,
    *,
    year: int,
    data_kind: str | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    """年终汇总矩阵：每段 = 动态列定义 + 批次行 + 单元格值 + 数值列统计。"""
    product = await _get_product_or_404(db, product_id)
    review = await repo.get_annual_review(db, product_id, year)
    sections = await repo.list_sections(db, product_id)
    section_payloads: list[dict[str, Any]] = []
    for s in sections:
        if data_kind and s.data_kind != data_kind:
            continue
        if market and (s.market or "") != market:
            continue
        batches = await repo.list_batches_of_section(db, s.id, year=year)
        if not batches:
            continue
        items = [i for i in await repo.list_items(db, s.id, active_only=True)]
        item_ids = [i.id for i in items]
        raw_values = (
            await repo.load_section_values(db, s.id, year=year, item_ids=item_ids)
            if item_ids
            else []
        )
        # (batch_id, row_seq) -> {item_id: (num, text)}；行标签取首个非空。
        cells: dict[tuple[uuid.UUID, int], dict[uuid.UUID, Any]] = {}
        label_lookup: dict[tuple[uuid.UUID, int], str | None] = {}
        for batch_id, item_id, row_seq, value_num, value_text, row_label in raw_values:
            cells.setdefault((batch_id, row_seq), {})[item_id] = (
                value_num,
                value_text,
            )
            if row_label and (batch_id, row_seq) not in label_lookup:
                label_lookup[(batch_id, row_seq)] = row_label
        # 行结构：普通段一批一行；multi_row 段按已录行号展开。
        rows: list[dict[str, Any]] = []
        row_meta: dict[uuid.UUID, list[int]] = {}
        for b in batches:
            row_seqs = sorted(
                {row_seq for (bid, row_seq) in cells if bid == b.id} or {1}
            )
            row_meta[b.id] = row_seqs
        for b in batches:
            for row_seq in row_meta[b.id]:
                row_cells: dict[str, dict[str, Any]] = {}
                for i in items:
                    num, text = cells.get((b.id, row_seq), {}).get(i.id, (None, None))
                    status = None
                    if num is not None:
                        status = classify_point(
                            num,
                            spec_min=i.spec_min,
                            spec_max=i.spec_max,
                            oot_min=i.oot_min,
                            oot_max=i.oot_max,
                        )
                    row_cells[str(i.id)] = {
                        "num": num,
                        "text": text,
                        "status": status,
                    }
                rows.append(
                    {
                        "batch_id": str(b.id),
                        "seq": b.seq,
                        "batch_no": b.batch_no,
                        "row_seq": row_seq,
                        "row_label": label_lookup.get((b.id, row_seq)),
                        "cells": row_cells,
                    }
                )
        # 数值列统计：文字结果行（未检出等）按列口径映射，exclude 不进样本。
        column_stats: dict[str, Any] = {}
        for i in items:
            if i.value_type != AprValueType.NUMBER.value:
                continue
            nums: list[float] = []
            nd_count = 0
            for per in cells.values():
                num, text = per.get(i.id, (None, None))
                if num is not None:
                    nums.append(num)
                elif text is not None:
                    nd_count += 1
                    if i.nd_policy == AprNdPolicy.ZERO.value:
                        nums.append(0.0)
            if nums or nd_count:
                stats = compute_column_stats(
                    nums, spec_min=i.spec_min, spec_max=i.spec_max
                )
                if nd_count:
                    stats["nd_count"] = nd_count
                column_stats[str(i.id)] = stats
        section_payloads.append(
            {
                **_section_dict(s),
                "items": [_item_dict(i) for i in items],
                "rows": rows,
                "column_stats": column_stats,
            }
        )
    return {
        "product": _product_dict(product),
        "year": year,
        "locked": review is not None and review.status == "locked",
        "batch_years": await repo.distinct_batch_years(db, product_id),
        "sections": section_payloads,
    }
