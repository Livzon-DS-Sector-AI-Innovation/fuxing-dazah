#!/usr/bin/env python3
"""一次性导入脚本：将 计量器具台账2026.et 数据批量写入 meter schema。

用法:
    uv run python app/modules/meter/import_meter_data.py 计量器具台账2026.et

幂等：按 asset_number / product_number 做 upsert，重复执行不会产生重复数据。
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from app.core.database import async_session_factory


# ═══════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════


def excel_serial_to_date(serial) -> date | None:
    if serial is None or serial == "":
        return None
    try:
        f = float(serial)
        if f < 1:
            return None
        return (datetime(1899, 12, 30) + timedelta(days=f)).date()
    except (ValueError, TypeError):
        return None


def detect_anomalies(row: dict, sheet_name: str) -> dict:
    flags: dict = {}
    cm = row.get("color_marking", "")
    if cm and cm != "":
        try:
            f = float(str(cm))
            if 40000 < f < 50000:
                flags["color_marking"] = {
                    "raw_value": str(cm),
                    "issue": "疑似日期值填入彩色标志列",
                    "severity": "warning",
                }
        except (ValueError, TypeError):
            pass
    cr = row.get("calibration_result", "")
    if cr and cr != "":
        try:
            f = float(str(cr))
            if 40000 < f < 50000:
                flags["calibration_result"] = {
                    "raw_value": str(cr),
                    "issue": "疑似日期值填入检定结论列",
                    "severity": "warning",
                }
        except (ValueError, TypeError):
            pass
    status = row.get("status", "")
    if status and status not in ("在用", "停用", ""):
        flags["status"] = {
            "raw_value": str(status),
            "issue": f"非标准状态值: {status}",
            "severity": "warning" if status in ("合格", "合格B") else "error",
        }
    return flags


# ═══════════════════════════════════════════
# 导入函数
# ═══════════════════════════════════════════

BATCH_SIZE = 500


async def import_sheet_0(db, sh: xlrd.sheet.Sheet):
    """导入 Sheet 0（有毒有害可燃探测器台账）- 批量写入，按 product_number 去重。"""
    from sqlalchemy import insert
    from app.modules.meter.models import GasDetectorRecord

    sheet_name = sh.name.strip()
    data_rows = sh.nrows - 4
    print(f"  [DETECTOR] {sheet_name}: {data_rows} rows")

    seen_product_numbers: set = set()
    all_rows = []
    for r in range(4, sh.nrows):
        row_data = {
            "instrument_name": str(sh.cell_value(r, 1)).strip(),
            "detection_model": str(sh.cell_value(r, 2)).strip(),
            "measurement_range": str(sh.cell_value(r, 3)).strip(),
            "product_number": str(sh.cell_value(r, 4)).strip(),
            "installation_type": str(sh.cell_value(r, 5)).strip(),
            "installation_location": str(sh.cell_value(r, 6)).strip(),
            "medium": str(sh.cell_value(r, 7)).strip(),
            "calibration_factor": str(sh.cell_value(r, 8)).strip(),
            "manufacturer_supplier": str(sh.cell_value(r, 9)).strip(),
            "calibration_date": excel_serial_to_date(sh.cell_value(r, 10)),
            "detection_unit": str(sh.cell_value(r, 11)).strip(),
            "next_calibration_date": excel_serial_to_date(sh.cell_value(r, 12)),
            "manufacturer": str(sh.cell_value(r, 13)).strip(),
            "department": str(sh.cell_value(r, 14)).strip(),
            "sheet_name": sheet_name,
            "anomaly_flags": {},
            "id": uuid.uuid4(),
        }
        for k, v in list(row_data.items()):
            if v == "":
                row_data[k] = None
        if not row_data["instrument_name"]:
            continue
        pn = row_data["product_number"]
        if pn and pn in seen_product_numbers:
            continue  # 跳过同一产品编号的重复行
        if pn:
            seen_product_numbers.add(pn)
        all_rows.append(row_data)

    count = 0
    for i in range(0, len(all_rows), BATCH_SIZE):
        batch = all_rows[i:i + BATCH_SIZE]
        try:
            await db.execute(insert(GasDetectorRecord).values(batch))
            await db.flush()
            count += len(batch)
            print(f"    ... {count}/{len(all_rows)}")
        except Exception as e:
            print(f"    [WARN] batch error: {e}")

    print(f"    [OK] {sheet_name}: {count} rows (skipped {data_rows - len(all_rows)} dups)")


async def import_standard_sheets(db, sheets: list[tuple[int, xlrd.sheet.Sheet]]):
    """导入标准计量器具台账 sheets — 先收集全部行，全局按 asset_number 去重后批量写入。"""
    from sqlalchemy import insert
    from app.modules.meter.models import InstrumentRecord

    # Phase 1: 收集所有 sheet 的所有行
    seen_asset_numbers: set = set()
    all_rows = []
    sheet_stats: dict[str, dict] = {}

    for idx, sh in sheets:
        sheet_name = sh.name.strip()
        data_rows = sh.nrows - 4
        if data_rows <= 0:
            print(f"  [STANDARD] {sheet_name}: skip (empty)")
            continue

        headers = {}
        for c in range(sh.ncols):
            key = str(sh.cell_value(3, c)).replace("\n", " ").replace("  ", " ").strip()
            headers[c] = key

        sheet_skipped = 0
        for r in range(4, sh.nrows):
            row = {}
            for c in range(sh.ncols):
                val = sh.cell_value(r, c)
                raw_key = headers.get(c, "")
                row[raw_key] = val

            asset_number = ""
            instrument_name = ""
            model_spec = ""
            measurement_range = ""
            accuracy_grade = ""
            serial_number = ""
            calibration_cycle = None
            location = ""
            manufacturer = ""
            status = ""
            color_marking = ""
            calibration_date_val = ""
            calibration_unit = ""
            calibration_result = ""
            next_calibration_date_val = ""

            for k, v in row.items():
                v_str = str(v).strip() if v != "" else ""
                if k in ("资产编号",):
                    asset_number = v_str
                elif k in ("器具名称",):
                    instrument_name = v_str
                elif k in ("型号规格", "型号 规格"):
                    model_spec = v_str
                elif k in ("测量范围", "测量 范围"):
                    measurement_range = v_str
                elif k in ("精度等级", "精度 等级", "精度等级", "精度 等级"):
                    accuracy_grade = v_str
                elif k in ("器具编号", "出厂编号"):
                    serial_number = v_str
                elif k.startswith("检定周期") or k.startswith("检定 周期"):
                    try:
                        calibration_cycle = int(float(str(v)))
                    except (ValueError, TypeError):
                        pass
                elif k in ("使用地点", "使用 地点") or ("使用" in k and "地" in k):
                    location = v_str
                elif k in ("器具制造商", "制造单位/厂家", "制造单位"):
                    manufacturer = v_str
                elif k in ("器具状态", "器具 状态"):
                    status = v_str
                elif k in ("彩色标志", "彩色 标志", "色标 标志", "色标/标志"):
                    color_marking = v_str
                elif k in ("检定日期", "检定 日期"):
                    calibration_date_val = v
                elif k in ("检定单位", "检定 单位", "检定单位"):
                    calibration_unit = v_str
                elif k in ("检定结论", "检定 结论", "检定结果"):
                    calibration_result = v_str
                elif k.startswith("下次检定") or (k.startswith("下") and "次检定" in k):
                    next_calibration_date_val = v

            if not instrument_name:
                continue

            # 全局按 asset_number 去重（跨 sheet）
            an = asset_number or None
            if an and an in seen_asset_numbers:
                sheet_skipped += 1
                continue
            if an:
                seen_asset_numbers.add(an)

            record = {
                "asset_number": an,
                "instrument_name": instrument_name,
                "model_spec": model_spec or None,
                "measurement_range": measurement_range or None,
                "accuracy_grade": accuracy_grade or None,
                "serial_number": serial_number or None,
                "calibration_cycle_months": calibration_cycle,
                "location": location or None,
                "manufacturer": manufacturer or None,
                "status": status or None,
                "color_marking": color_marking or None,
                "calibration_date": excel_serial_to_date(calibration_date_val),
                "calibration_unit": calibration_unit or None,
                "calibration_result": calibration_result or None,
                "next_calibration_date": excel_serial_to_date(next_calibration_date_val),
                "department": sheet_name,
                "sheet_name": sheet_name,
                "anomaly_flags": detect_anomalies(
                    {"color_marking": color_marking, "calibration_result": calibration_result, "status": status},
                    sheet_name,
                ),
                "id": uuid.uuid4(),
            }

            for k, v in list(record.items()):
                if v == "":
                    record[k] = None

            all_rows.append(record)

        sheet_stats[sheet_name] = {"collected": len([r for r in all_rows if r["sheet_name"] == sheet_name]), "skipped": sheet_skipped}

    # Phase 2: 批量写入
    print(f"\n  Total records to insert: {len(all_rows)}")
    count = 0
    for i in range(0, len(all_rows), BATCH_SIZE):
        batch = all_rows[i:i + BATCH_SIZE]
        try:
            await db.execute(insert(InstrumentRecord).values(batch))
            await db.flush()
            count += len(batch)
            print(f"    ... {count}/{len(all_rows)}")
        except Exception as e:
            print(f"    [WARN] batch error: {e}")

    # Print per-sheet summary
    for sn, stats in sorted(sheet_stats.items()):
        ski = f" (skipped {stats['skipped']} dups)" if stats['skipped'] else ""
        print(f"    {sn}: {stats['collected']} rows{ski}")

    print(f"\n  Total standard instruments imported: {len(all_rows)}")


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════


async def main(filepath: str):
    import sys
    from app.core.database import engine

    path = Path(filepath)
    if not path.exists():
        print(f"[ERROR] File not found: {filepath}")
        sys.exit(1)

    print(f"[OPEN] {path.absolute()}")
    wb = xlrd.open_workbook(str(path), formatting_info=False)

    print(f"[SHEETS] Total: {wb.nsheets}")
    print(f"   Sheet 0: detector ({wb.sheet_by_index(0).nrows} rows)")

    standard_sheets = [(i, wb.sheet_by_index(i)) for i in range(1, wb.nsheets) if wb.sheet_by_index(i).nrows > 5]
    print(f"   Standard sheets: {len(standard_sheets)}")

    # 临时关闭 SQL echo 以减少输出
    engine.echo = False

    try:
        async with async_session_factory() as db:
            print("\n[PHASE 1] Gas Detector Records (Sheet 0)")
            await import_sheet_0(db, wb.sheet_by_index(0))
            await db.commit()

            print("\n[PHASE 2] Standard Instrument Records")
            await import_standard_sheets(db, standard_sheets)
            await db.commit()

        print("\n[DONE] Import complete!")
    finally:
        engine.echo = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入计量器具台账 .et 文件")
    parser.add_argument("filepath", help="计量器具台账 .et 文件路径")
    args = parser.parse_args()
    asyncio.run(main(args.filepath))
