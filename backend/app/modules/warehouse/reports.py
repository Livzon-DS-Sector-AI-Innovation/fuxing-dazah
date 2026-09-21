"""报表中心聚合服务（分期C）：月报/周转率/消耗排名/库存报表 + Excel 导出。

口径统一走北京时间业务日；报表实时聚合不落库。
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.bitable_cells import cell_text
from app.modules.warehouse.finished_data import cell_qty, fetch_all_records
from app.modules.warehouse.intelligence import (
    _material_stock_totals,  # type: ignore[attr-defined]  # noqa: F401 — 同包内部复用
)
from app.modules.warehouse.models import WarehouseMovement, WarehouseStock

CN_TZ = ZoneInfo("Asia/Shanghai")


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=CN_TZ)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end = datetime(next_year, next_month, 1, tzinfo=CN_TZ)
    return start, end


async def get_monthly_report(db: AsyncSession, year: int, month: int) -> dict[str, Any]:
    """出入库月报：自然月聚合（北京时间），汇总 + 按物料明细。"""
    start, end = _month_bounds(year, month)
    rows = list(
        (
            await db.execute(
                select(WarehouseMovement).where(
                    WarehouseMovement.is_deleted == False,  # noqa: E712
                    WarehouseMovement.occurred_at >= start,
                    WarehouseMovement.occurred_at < end,
                )
            )
        ).scalars().all()
    )

    summary: dict[str, Any] = {
        "inbound_count": 0, "inbound_qty": 0.0,
        "outbound_count": 0, "outbound_qty": 0.0,
    }
    items: dict[tuple[str, str, str], dict[str, Any]] = {}
    for mv in rows:
        key = (mv.material_code, mv.material_name, mv.unit)
        item = items.setdefault(
            key,
            {"material_code": mv.material_code, "material_name": mv.material_name,
             "unit": mv.unit, "inbound_qty": 0.0, "outbound_qty": 0.0},
        )
        summary[f"{mv.direction}_count"] = summary.get(f"{mv.direction}_count", 0) + 1
        summary[f"{mv.direction}_qty"] = summary.get(f"{mv.direction}_qty", 0.0) + float(mv.quantity)
        item[f"{mv.direction}_qty"] = item.get(f"{mv.direction}_qty", 0.0) + float(mv.quantity)

    return {
        "year": year, "month": month, "summary": summary,
        "items": sorted(items.values(), key=lambda x: x["material_code"]),
    }


def build_monthly_xlsx(report: dict[str, Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "汇总"
    ws.append(["年份", "月份", "入库笔数", "入库数量", "出库笔数", "出库数量"])
    s = report["summary"]
    ws.append([report["year"], report["month"], s["inbound_count"], s["inbound_qty"],
               s["outbound_count"], s["outbound_qty"]])
    ws2 = wb.create_sheet("物料明细")
    ws2.append(["物料编码", "物料名称", "单位", "入库数量", "出库数量"])
    for item in report["items"]:
        ws2.append([item["material_code"], item["material_name"], item["unit"],
                    item["inbound_qty"], item["outbound_qty"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 年报 / 危化品专项（V3.0 分期D Ticket 04，设计 §4.5）──


async def get_annual_report(db: AsyncSession, year: int) -> dict[str, Any]:
    """出入库年报：12 个月月报聚合（本地 movement，口径与月报一致）。

    返回年度汇总、逐月趋势、按物料年度明细（出库降序）。
    """
    summary = {
        "inbound_count": 0, "inbound_qty": 0.0,
        "outbound_count": 0, "outbound_qty": 0.0,
    }
    months: list[dict[str, Any]] = []
    items: dict[tuple[str, str, str], dict[str, Any]] = {}
    for month in range(1, 13):
        report = await get_monthly_report(db, year, month)
        s = report["summary"]
        months.append({
            "month": month,
            "inbound_qty": s["inbound_qty"],
            "outbound_qty": s["outbound_qty"],
        })
        for key in summary:
            summary[key] += s[key]
        for item in report["items"]:
            mkey = (item["material_code"], item["material_name"], item["unit"])
            agg = items.setdefault(mkey, {
                "material_code": item["material_code"],
                "material_name": item["material_name"],
                "unit": item["unit"],
                "inbound_qty": 0.0, "outbound_qty": 0.0,
            })
            agg["inbound_qty"] += item["inbound_qty"]
            agg["outbound_qty"] += item["outbound_qty"]

    return {
        "year": year,
        "summary": summary,
        "months": months,
        "items": sorted(items.values(), key=lambda x: x["outbound_qty"], reverse=True),
    }


def build_annual_xlsx(report: dict[str, Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "年度汇总"
    ws.append(["年份", "入库笔数", "入库数量", "出库笔数", "出库数量"])
    s = report["summary"]
    ws.append([report["year"], s["inbound_count"], s["inbound_qty"],
               s["outbound_count"], s["outbound_qty"]])
    ws2 = wb.create_sheet("月度趋势")
    ws2.append(["月份", "入库数量", "出库数量"])
    for m in report["months"]:
        ws2.append([f"{report['year']}-{m['month']:02d}", m["inbound_qty"], m["outbound_qty"]])
    ws3 = wb.create_sheet("物料年度明细")
    ws3.append(["物料编码", "物料名称", "单位", "入库数量", "出库数量"])
    for item in report["items"]:
        ws3.append([item["material_code"], item["material_name"], item["unit"],
                    item["inbound_qty"], item["outbound_qty"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# 危化品专项过滤口径：物料大类=危化品，或法规危险性分类含「危化品」
# （危化品&易制爆/易制毒/重点监管/高毒物品 均命中并保留标注）
HAZARDOUS_CATEGORY = "危化品"


def is_hazardous_material(category: str, legal_class: str) -> bool:
    """危化品判定（物料大类 / 法规危险性分类双口径，纯函数可测）。"""
    return category.strip() == HAZARDOUS_CATEGORY or legal_class.strip().startswith(
        HAZARDOUS_CATEGORY
    )


async def get_hazardous_report(db: AsyncSession, *, days: int = 90) -> dict[str, Any]:
    """危化品/易制毒/易制爆专项：material_master 分类过滤 + 期间出库与库存。

    分类来自 Base material_master（2B）；出库聚合本地 WarehouseMovement
    近 N 天、当前库存本地镜像，按物料名称 join（未命中本地数据的物料
    保留分类行、数量置 0）。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    master_rows = await fetch_all_records(
        WarehouseBitableAdapter(),
        "material_master",
        ["物料名称", "物料大类", "法规危险性分类"],
    )
    hazardous: dict[str, dict[str, str]] = {}
    for raw in master_rows:
        fields = raw.get("fields") or {}
        name = cell_text(fields.get("物料名称")).strip()
        if not name:
            continue
        category = cell_text(fields.get("物料大类")).strip()
        legal_class = cell_text(fields.get("法规危险性分类")).strip()
        if not is_hazardous_material(category, legal_class):
            continue
        hazardous.setdefault(
            name, {"category": category or "-", "legal_class": legal_class or "-"}
        )

    start = datetime.now(CN_TZ) - timedelta(days=days)
    movements = list(
        (
            await db.execute(
                select(
                    WarehouseMovement.material_name,
                    func.sum(WarehouseMovement.quantity).label("outbound"),
                )
                .where(
                    WarehouseMovement.is_deleted == False,  # noqa: E712
                    WarehouseMovement.direction == "outbound",
                    WarehouseMovement.occurred_at >= start,
                )
                .group_by(WarehouseMovement.material_name)
            )
        ).all()
    )
    outbound_by_name = {r.material_name: float(r.outbound) for r in movements}

    stocks = list(
        (
            await db.execute(
                select(
                    WarehouseStock.material_name,
                    func.coalesce(func.sum(WarehouseStock.quantity), 0).label("qty"),
                )
                .where(
                    WarehouseStock.is_deleted == False,  # noqa: E712
                    WarehouseStock.quantity > 0,
                )
                .group_by(WarehouseStock.material_name)
            )
        ).all()
    )
    stock_by_name = {r.material_name: float(r.qty) for r in stocks}

    items: list[dict[str, Any]] = [
        {
            "material_name": name,
            "category": meta["category"],
            "legal_class": meta["legal_class"],
            "outbound_qty": outbound_by_name.get(name, 0.0),
            "current_stock": stock_by_name.get(name, 0.0),
        }
        for name, meta in sorted(hazardous.items())
    ]
    items.sort(key=lambda x: x["outbound_qty"], reverse=True)
    return {"days": days, "total": len(items), "items": items}


def build_hazardous_xlsx(report: dict[str, Any]) -> bytes:
    """危化品专项导出（列映射收口 reports，api 层不拼表头）。"""
    days = report["days"]
    return build_table_xlsx(
        "危化品专项",
        ["物料名称", "物料大类", "法规危险性分类", f"近{days}天出库", "当前库存"],
        [[r["material_name"], r["category"], r["legal_class"],
          r["outbound_qty"], r["current_stock"]] for r in report["items"]],
    )


def build_usage_compare_xlsx(report: dict[str, Any]) -> bytes:
    """月度用量对比导出（偏差率格式化在此收口）。"""
    return build_table_xlsx(
        "用量对比",
        ["物料名称", "实际用量", "预期基准", "偏差率", "备注"],
        [[
            r["material_name"], r["actual_qty"], r["expected_qty"],
            f"{r['deviation'] * 100:.1f}%" if r["deviation"] is not None else "",
            "无偏差数据（本月无用量）" if r["deviation"] is None else "",
        ] for r in report["items"]],
    )


async def get_usage_compare(db: AsyncSession, year: int, month: int) -> dict[str, Any]:
    """月度「实际 vs 预期」用量对比（V3.0 分期D Ticket 05，设计 §4.4⑥）。

    实际 = 本地 WarehouseMovement 该自然月 outbound 按物料聚合（与月报同源）；
    预期 = material_master「月度预期用量」列（D 期 API 建列，人工填基准，
    2B 权威）。偏差 = |实际-预期|/预期；未设基准/基准为 0 的物料不进偏差
    计算（has_baseline=False），无基准但有实际用量的单列计数。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    start, end = _month_bounds(year, month)
    rows = (
        await db.execute(
            select(
                WarehouseMovement.material_name,
                func.sum(WarehouseMovement.quantity).label("actual"),
            )
            .where(
                WarehouseMovement.is_deleted == False,  # noqa: E712
                WarehouseMovement.direction == "outbound",
                WarehouseMovement.occurred_at >= start,
                WarehouseMovement.occurred_at < end,
            )
            .group_by(WarehouseMovement.material_name)
        )
    ).all()
    actual_by_name = {r.material_name: float(r.actual) for r in rows}

    master_rows = await fetch_all_records(
        WarehouseBitableAdapter(),
        "material_master",
        ["物料名称", "月度预期用量"],
    )
    expected_by_name: dict[str, float] = {}
    for raw in master_rows:
        fields = raw.get("fields") or {}
        name = cell_text(fields.get("物料名称")).strip()
        expected = cell_qty(fields.get("月度预期用量"))
        if name and expected is not None and expected > 0:
            expected_by_name[name] = expected

    items: list[dict[str, Any]] = []
    no_baseline_with_usage = 0
    for name in sorted(set(actual_by_name) | set(expected_by_name)):
        actual = actual_by_name.get(name)
        expected = expected_by_name.get(name)
        if expected is None:
            if actual:
                no_baseline_with_usage += 1
            continue
        deviation = abs(actual - expected) / expected if actual is not None else None
        items.append({
            "material_name": name,
            "actual_qty": actual or 0.0,
            "expected_qty": expected,
            "deviation": deviation,
        })
    # 偏差降序（无偏差计算的行殿后）
    items.sort(key=lambda x: (-(x["deviation"] if x["deviation"] is not None else 0.0),
                              x["deviation"] is None))
    return {
        "year": year,
        "month": month,
        "total": len(items),
        "no_baseline_with_usage": no_baseline_with_usage,
        "items": items,
    }


def build_table_xlsx(title: str, headers: list[str], rows: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = title
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def get_consumption_ranking(db: AsyncSession, days: int, limit: int) -> list[dict[str, Any]]:
    start = datetime.now(CN_TZ) - timedelta(days=days)
    stmt = (
        select(
            WarehouseMovement.material_id,
            WarehouseMovement.material_code,
            WarehouseMovement.material_name,
            WarehouseMovement.unit,
            func.sum(WarehouseMovement.quantity).label("outbound"),
        )
        .where(
            WarehouseMovement.is_deleted == False,  # noqa: E712
            WarehouseMovement.direction == "outbound",
            WarehouseMovement.occurred_at >= start,
        )
        .group_by(
            WarehouseMovement.material_id,
            WarehouseMovement.material_code,
            WarehouseMovement.material_name,
            WarehouseMovement.unit,
        )
        .order_by(func.sum(WarehouseMovement.quantity).desc())
        .limit(limit)
    )
    return [
        {"material_code": r.material_code, "material_name": r.material_name,
         "unit": r.unit, "outbound_qty": float(r.outbound)}
        for r in (await db.execute(stmt)).all()
    ]


async def get_turnover_ranking(
    db: AsyncSession, days: int, limit: int, order: str
) -> list[dict[str, Any]]:
    start = datetime.now(CN_TZ) - timedelta(days=days)
    out_stmt = (
        select(
            WarehouseMovement.material_id,
            WarehouseMovement.material_code,
            WarehouseMovement.material_name,
            func.sum(WarehouseMovement.quantity).label("outbound"),
        )
        .where(
            WarehouseMovement.is_deleted == False,  # noqa: E712
            WarehouseMovement.direction == "outbound",
            WarehouseMovement.occurred_at >= start,
        )
        .group_by(
            WarehouseMovement.material_id,
            WarehouseMovement.material_code,
            WarehouseMovement.material_name,
        )
    )
    stock_map = {mid: row["total_quantity"] for mid, row in (await _material_stock_totals(db)).items()}
    ranking: list[dict[str, Any]] = []
    for r in (await db.execute(out_stmt)).all():
        stock = float(stock_map.get(r.material_id, 0.0))
        outbound = float(r.outbound)
        turnover = outbound / stock if stock > 0 else None
        ranking.append(
            {"material_code": r.material_code, "material_name": r.material_name,
             "outbound_qty": outbound, "current_stock": stock, "turnover": turnover}
        )
    has_value = [x for x in ranking if x["turnover"] is not None]
    none_value = [x for x in ranking if x["turnover"] is None]
    has_value.sort(key=lambda x: x["turnover"] or 0, reverse=(order == "desc"))
    return none_value + has_value if order == "desc" else has_value + none_value


async def get_stock_report(
    db: AsyncSession, *, page: int, page_size: int
) -> tuple[list[WarehouseStock], int]:
    stmt = select(WarehouseStock).where(
        WarehouseStock.is_deleted == False,  # noqa: E712
        WarehouseStock.quantity != 0,
    )
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    stmt = (
        stmt.order_by(WarehouseStock.material_code, WarehouseStock.batch_no)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return items, int(total or 0)


# ── 库位地图（分期D Ticket 02） ──


async def get_location_map(db: AsyncSession) -> list[dict[str, Any]]:
    """按 zone→aisle 分组返回库位与占用信息（库位地图数据源）。"""
    from app.modules.warehouse.models import WarehouseLocation

    stmt = (
        select(WarehouseLocation)
        .where(WarehouseLocation.is_deleted == False)  # noqa: E712
        .order_by(WarehouseLocation.zone, WarehouseLocation.aisle, WarehouseLocation.code)
    )
    locations = list((await db.execute(stmt)).scalars().all())

    stock_stmt = (
        select(
            WarehouseStock.location_id,
            func.count().label("rows"),
            func.coalesce(func.sum(WarehouseStock.quantity), 0).label("qty"),
        )
        .where(WarehouseStock.is_deleted == False, WarehouseStock.quantity > 0)  # noqa: E712
        .group_by(WarehouseStock.location_id)
    )
    occupancy = {
        r[0]: {"rows": int(r[1]), "qty": float(r[2])}
        for r in (await db.execute(stock_stmt)).all()
    }

    return [
        {
            "id": str(loc.id),
            "code": loc.code,
            "name": loc.name,
            "zone": loc.zone or "未分区",
            "aisle": loc.aisle or "-",
            "location_type": loc.location_type,
            "occupied_rows": occupancy.get(loc.id, {}).get("rows", 0),
            "total_qty": occupancy.get(loc.id, {}).get("qty", 0.0),
        }
        for loc in locations
    ]


async def get_batch_trace(
    db: AsyncSession, *, material_code: str, batch_no: str
) -> dict[str, Any]:
    """从批次出发的正查（出库去向）+ 反查（入库来源）完整流水。"""
    stmt = (
        select(WarehouseMovement)
        .where(
            WarehouseMovement.is_deleted == False,  # noqa: E712
            WarehouseMovement.material_code == material_code,
            WarehouseMovement.batch_no == batch_no,
        )
        .order_by(WarehouseMovement.occurred_at.desc())
    )
    movements = list((await db.execute(stmt)).scalars().all())
    inbound_flows = []
    outbound_flows = []
    for mv in movements:
        flow = {
            "movement_no": mv.movement_no,
            "direction": mv.direction,
            "source_type": mv.source_type,
            "quantity": float(mv.quantity),
            "unit": mv.unit,
            "location_name": mv.location_name,
            "occurred_at": mv.occurred_at.isoformat() if mv.occurred_at else None,
            "remark": mv.remark,
        }
        if mv.direction == "inbound":
            inbound_flows.append(flow)
        elif mv.direction == "outbound":
            outbound_flows.append(flow)
    return {
        "material_code": material_code,
        "batch_no": batch_no,
        "inbound_flows": inbound_flows,
        "outbound_flows": outbound_flows,
    }


def build_batch_trace_xlsx(trace: dict[str, Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "批次追溯"
    ws.append(["方向", "单号", "发生时间", "数量", "单位", "库位", "来源/去向", "备注"])
    for flow in trace["inbound_flows"] + trace["outbound_flows"]:
        ws.append([
            flow["direction"], flow["movement_no"],
            flow["occurred_at"][:19] if flow["occurred_at"] else "",
            flow["quantity"], flow["unit"], flow["location_name"],
            flow["source_type"], flow["remark"] or "",
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
