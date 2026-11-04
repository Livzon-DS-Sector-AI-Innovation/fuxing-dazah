"""直读内存过滤/分页（北京时间语义对齐 repository 口径）。"""

from __future__ import annotations

import re
from datetime import date
from typing import TypeVar

T = TypeVar("T")


def paginate(items: list[T], page: int, page_size: int) -> tuple[list[T], int]:
    """页切片 + 总数（1 起，越界返回空页）。"""
    total = len(items)
    start = (page - 1) * page_size
    return items[start : start + page_size], total


def filter_stocks(
    views: list,
    *,
    category: str | None = None,
    keyword: str | None = None,
    batch_no: str | None = None,
    expiry_from: date | None = None,
    expiry_to: date | None = None,
    status: str | None = None,
) -> list:
    """库存过滤：类别(枚举)/关键字(物料或批次包含)/批次模糊/效期窗/三态。

    keyword 对齐镜像口径：物料编码/名称/批号 任一包含即命中。
    """
    out = views
    if category:
        out = [v for v in out if v.category == category]
    if keyword:
        kw = keyword.strip()
        out = [
            v for v in out
            if kw in v.code or kw in v.name or kw in v.batch_no
        ]
    if batch_no:
        bn = batch_no.strip()
        out = [v for v in out if bn in v.batch_no]
    if expiry_from:
        out = [v for v in out if v.expiry_date and v.expiry_date >= expiry_from]
    if expiry_to:
        out = [v for v in out if v.expiry_date and v.expiry_date <= expiry_to]
    if status:
        out = [v for v in out if v.status == status]
    return out


def strip_spec_suffix(name: str) -> str:
    """去尾部括号规格后缀（出库名称解析链用）：磷酸二氢钾(工业级)→磷酸二氢钾。"""
    return re.sub(r"[（(][^（）()]*[）)]\s*$", "", name).strip()


def filter_movements(
    views: list,
    *,
    direction: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
    code: str | None = None,
    occurred_from=None,
    occurred_to=None,
) -> list:
    """流水过滤：方向/来源/关键字（单号前缀或物料/批次包含）/代码/时间窗。

    时间比较统一 UTC aware（naive 入参按 UTC 补 tz）。
    """
    from datetime import UTC as _UTC

    out = views
    if direction:
        out = [v for v in out if v.direction == direction]
    if source_type:
        out = [v for v in out if v.source_type == source_type]
    if keyword:
        kw = keyword.strip()
        out = [
            v for v in out
            if kw in v.name or kw in v.code or kw in v.batch_no
            or kw in movement_no_of(v)
        ]
    if code:
        out = [v for v in out if v.code == code]
    if occurred_from is not None:
        start = occurred_from if occurred_from.tzinfo else occurred_from.replace(tzinfo=_UTC)
        out = [v for v in out if v.occurred_at >= start]
    if occurred_to is not None:
        end = occurred_to if occurred_to.tzinfo else occurred_to.replace(tzinfo=_UTC)
        out = [v for v in out if v.occurred_at <= end]
    return out


def movement_no_of(view) -> str:
    """单号派生（与回灌脚本同式）：RCPT-/OTB- + record_id 前 16。"""
    prefix = "RCPT" if view.direction == "inbound" else "OTB"
    return f"{prefix}-{view.record_id[:16]}"
