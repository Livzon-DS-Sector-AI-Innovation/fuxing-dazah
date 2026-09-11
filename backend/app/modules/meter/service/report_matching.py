"""报告文件匹配、批量上传与批量内容识别。"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.storage import delete_object, is_enabled, upload_object
from app.modules.meter import ai_service as ai_svc
from app.modules.meter import recognition
from app.modules.meter import repository as repo
from app.modules.meter.models import (
    InstrumentRecord,
)
from app.modules.meter.service.common import MODULE_CODE
from app.modules.meter.service.reports import _build_report_path

logger = logging.getLogger(__name__)

def _parse_filename(filename: str) -> tuple[str, str]:
    """从文件名中解析器具名称和编号。右边最后一个 _ 为分界。"""
    stem = filename.rsplit(".", 1)[0]  # 去掉扩展名
    if "_" not in stem:
        return stem, ""
    idx = stem.rfind("_")
    return stem[:idx], stem[idx + 1:]


async def match_filenames(
    db: AsyncSession, filenames: list[str]
) -> list[dict[str, Any]]:
    """批量匹配文件名到仪表记录。"""
    results: list[dict[str, Any]] = []
    for fn in filenames:
        name, code = _parse_filename(fn)
        matched_type = None
        matched_id = None
        matched_name = None
        matched_dept = None

        if code:
            # 先匹配标准计量器具
            inst = await repo.find_instrument_by_name_and_serial(db, name, code)
            if inst:
                matched_type = "instrument"
                matched_id = str(inst.id)
                matched_name = f"{inst.instrument_name} [{inst.asset_number}]"
                matched_dept = inst.department
            else:
                # 再匹配探测器
                det = await repo.find_gas_detector_by_name_and_product(db, name, code)
                if det:
                    matched_type = "gas_detector"
                    matched_id = str(det.id)
                    matched_name = f"{det.instrument_name} [{det.product_number}]"
                    matched_dept = det.department

        results.append({
            "filename": fn,
            "matched_type": matched_type,
            "matched_id": matched_id,
            "matched_name": matched_name,
            "matched_department": matched_dept,
        })
    return results


# ═══════════════════════════════════════════
# 批量上传
# ═══════════════════════════════════════════


async def batch_upload_reports(
    db: AsyncSession,
    files: list[tuple[str, bytes, str]],  # (filename, data, content_type)
    items: list[dict[str, Any]],
    report_date: date | None = None,
    remark: str | None = None,
) -> dict[str, Any]:
    """批量上传报告文件，按 items 中的 instrument_id / gas_detector_id 关联。

    每项支持可选 certificate_no（证书编号，防重复上传）与 calibration_date（识别出的
    校准日期，条件回写台账：仅当 PDF 日期 ≥ 台账现有日期或台账为空才回写）。
    """
    if not is_enabled():
        raise RuntimeError("MinIO 未启用，无法上传文件")

    success = 0
    failed = 0
    errors: list[str] = []
    notes: list[str] = []
    report_ids: list[str] = []
    # 同名文件按上传顺序排队配对，避免同名文件互相覆盖
    file_queue: dict[str, list[tuple[str, bytes, str]]] = {}
    for f in files:
        file_queue.setdefault(f[0], []).append(f)

    # 前置防重：同批次重复 + DB 已存在（未删除）
    batch_nos = [str(item.get("certificate_no") or "").strip() for item in items]
    batch_nos = [n for n in batch_nos if n]
    dup_in_batch: set[str] = set()
    seen: set[str] = set()
    for n in batch_nos:
        if n in seen:
            dup_in_batch.add(n)
        seen.add(n)
    existing_nos = await repo.find_existing_certificate_nos(db, batch_nos) if batch_nos else set()

    for item in items:
        if not isinstance(item, dict):
            failed += 1
            errors.append("无效的 items 项（应为对象）")
            continue
        fn = item.get("filename")
        instrument_id = item.get("instrument_id")
        gas_detector_id = item.get("gas_detector_id")
        certificate_no = str(item.get("certificate_no") or "").strip() or None
        pdf_date = item.get("calibration_date")

        if not fn:
            failed += 1
            errors.append("items 项缺少 filename 字段")
            continue
        # 校准日期非法直接报错回传，绝不静默丢弃——否则用户以为日期已回写台账
        if pdf_date is not None:
            if isinstance(pdf_date, str):
                try:
                    pdf_date = date.fromisoformat(pdf_date)
                except ValueError:
                    failed += 1
                    errors.append(f"{fn}: 校准日期「{pdf_date}」格式非法（需 YYYY-MM-DD）")
                    continue
            elif not isinstance(pdf_date, date):
                failed += 1
                errors.append(f"{fn}: 校准日期类型非法（需 YYYY-MM-DD 字符串）")
                continue
        queue = file_queue.get(fn)
        if not queue:
            failed += 1
            errors.append(f"{fn}: 文件未找到")
            continue
        if not instrument_id and not gas_detector_id:
            failed += 1
            errors.append(f"{fn}: 未关联仪表")
            continue
        if instrument_id and gas_detector_id:
            failed += 1
            errors.append(f"{fn}: 必须且只能关联一种仪表（instrument_id / gas_detector_id）")
            continue
        if certificate_no:
            if certificate_no in dup_in_batch:
                failed += 1
                errors.append(f"{fn}: 证书编号 {certificate_no} 在同批次中重复")
                continue
            if certificate_no in existing_nos:
                failed += 1
                errors.append(f"{fn}: 证书编号 {certificate_no} 已存在（已上传过）")
                continue

        entry = queue.pop(0)
        file_data, content_type = entry[1], entry[2]

        # ponytail: 每项独立 SAVEPOINT，单项失败（如唯一索引竞态）不影响整批事务
        object_path: str | None = None
        try:
            async with db.begin_nested():
                if instrument_id:
                    target = await repo.get_instrument_by_id(db, UUID(instrument_id), include_reports=False)
                    if not target:
                        raise NotFoundException("标准计量器具", instrument_id)
                    target_id = UUID(instrument_id)
                else:
                    target = await repo.get_gas_detector_by_id(db, UUID(gas_detector_id), include_reports=False)  # type: ignore[assignment]
                    if not target:
                        raise NotFoundException("有毒有害可燃探测器", str(gas_detector_id))
                    target_id = UUID(gas_detector_id)

                object_path = _build_report_path(target_id, fn)
                upload_object(MODULE_CODE, object_path, file_data, len(file_data), content_type)

                report_date_val = report_date
                if isinstance(pdf_date, date):
                    existing = getattr(target, "calibration_date", None)
                    if existing is None or pdf_date >= existing:
                        report_date_val = pdf_date
                        cycle = getattr(target, "calibration_cycle_months", None)
                        next_date = ai_svc.calc_next_calibration_date(pdf_date, cycle)
                        if isinstance(target, InstrumentRecord):
                            await repo.update_instrument(db, target_id, {
                                "calibration_date": pdf_date,
                                "next_calibration_date": next_date,
                            })
                        else:
                            await repo.update_gas_detector(db, target_id, {
                                "calibration_date": pdf_date,
                                "next_calibration_date": next_date,
                            })
                    else:
                        notes.append(
                            f"{fn}: 证书日期 {pdf_date.isoformat()} 早于台账 {existing.isoformat()}，仅归档未回写日期"
                        )

                report = await repo.create_report(
                    db,
                    {
                        "instrument_id": UUID(instrument_id) if instrument_id else None,
                        "gas_detector_id": UUID(gas_detector_id) if gas_detector_id else None,
                        "file_name": fn,
                        "file_path": object_path,
                        "file_size": len(file_data),
                        "content_type": content_type,
                        "certificate_no": certificate_no,
                        "report_date": report_date_val,
                        "remark": remark,
                    },
                )
                report_ids.append(str(report.id))
                success += 1
        except IntegrityError:
            if object_path:
                delete_object(MODULE_CODE, object_path)  # 清理孤儿文件
            failed += 1
            errors.append(f"{fn}: 证书编号 {certificate_no or ''} 已存在（并发上传）")
        except Exception as e:
            if object_path:
                delete_object(MODULE_CODE, object_path)  # 清理孤儿文件
            failed += 1
            errors.append(f"{fn}: {str(e)}")

    return {"success": success, "failed": failed, "errors": errors, "notes": notes, "report_ids": report_ids}


async def match_one(
    db: AsyncSession, name: str | None, serial: str | None,
    source: str | None = None,
) -> dict[str, Any]:
    """名称模糊 + 编号精确匹配台账；未精确命中时按名称列候选。

    source 限定台账类型（instrument / gas_detector），避免探测器报告的编号
    撞上同编号器具而挂错台账；None 时两类都查。
    返回 {"matched_type","matched_id","matched_name","matched_department","candidates"}。
    """
    result: dict[str, Any] = {
        "matched_type": None,
        "matched_id": None,
        "matched_name": None,
        "matched_department": None,
        "candidates": [],
    }

    if serial and source != "gas_detector":
        inst = await repo.find_instrument_by_name_and_serial(db, name or "", serial)
        if inst:
            result["matched_type"] = "instrument"
            result["matched_id"] = str(inst.id)
            result["matched_name"] = f"{inst.instrument_name} [{inst.asset_number}]"
            result["matched_department"] = inst.department
            return result
    if serial and source != "instrument":
        det = await repo.find_gas_detector_by_name_and_product(db, name or "", serial)
        if det:
            result["matched_type"] = "gas_detector"
            result["matched_id"] = str(det.id)
            result["matched_name"] = f"{det.instrument_name} [{det.product_number}]"
            result["matched_department"] = det.department
            return result

    if name:
        if source != "gas_detector":
            insts = await repo.search_instruments_by_name(db, name)
            result["candidates"] += [
                {
                    "type": "instrument",
                    "id": str(i.id),
                    "name": i.instrument_name,
                    "code": i.asset_number,  # 与 matched_name 的显示口径一致
                    "department": i.department,
                }
                for i in insts
            ]
        if source != "instrument":
            dets = await repo.search_gas_detectors_by_name(db, name)
            result["candidates"] += [
                {
                    "type": "gas_detector",
                    "id": str(d.id),
                    "name": d.instrument_name,
                    "code": d.product_number,
                    "department": d.department,
                }
                for d in dets
            ]
    return result


async def analyze_report_files(
    db: AsyncSession, files: list[tuple[str, bytes, str]],
    source: str | None = None,
) -> list[dict[str, Any]]:
    """批量识别报告内容并匹配台账。

    提取并发（10 并发、逐文件容错），匹配串行（共用 db session）。
    单文件失败只标记 method=failed，不影响其他文件。
    source 限定台账类型（instrument / gas_detector），None 不限定。
    """
    config = ai_svc.get_meter_ai_config()
    sem = asyncio.Semaphore(10)

    async def extract_one(fn: str, data: bytes) -> dict[str, Any]:
        async with sem:
            try:
                return await recognition.extract_report_fields(data, config)
            except Exception as e:
                logger.warning("报告内容识别失败 %s: %s", fn, e)
                return {
                    "instrument_name": None,
                    "serial_number": None,
                    "certificate_no": None,
                    "calibration_date": None,
                    "method": "failed",
                    "error": f"识别失败: {e}",
                }

    extractions = await asyncio.gather(
        *(extract_one(fn, data) for fn, data, _ in files)
    )

    results: list[dict[str, Any]] = []
    for (fn, _, _), fields in zip(files, extractions):
        matched = await match_one(
            db, fields.get("instrument_name"), fields.get("serial_number"), source
        )
        results.append({"filename": fn, "extraction": fields, **matched})
    return results
