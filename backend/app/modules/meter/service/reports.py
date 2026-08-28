"""检测报告：上传、下载、删除、证书编号与批量导出。"""

from __future__ import annotations

import uuid
from datetime import date
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.core.storage import delete_object, get_object, is_enabled, upload_object
from app.modules.meter import repository as repo
from app.modules.meter.models import CalibrationReport
from app.modules.meter.service.common import MODULE_CODE


def _build_report_path(record_id: UUID, filename: str) -> str:
    """构建 MinIO 对象路径：reports/{record_id}/{uuid}.{ext}"""
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    return f"reports/{record_id}/{uuid.uuid4().hex}.{ext}"


async def upload_report(
    db: AsyncSession,
    *,
    file: UploadFile,
    instrument_id: UUID | None = None,
    gas_detector_id: UUID | None = None,
    report_date: date | None = None,
    remark: str | None = None,
) -> CalibrationReport:
    """上传检测报告文件到 MinIO 并创建元数据记录。"""
    if not is_enabled():
        raise RuntimeError("MinIO 未启用，无法上传文件")

    # 校验：必须且只能关联一种仪表
    if (instrument_id is None) == (gas_detector_id is None):
        raise ValueError("必须且只能指定 instrument_id 或 gas_detector_id 中的一个")

    # 校验目标仪表存在
    if instrument_id:
        target_inst = await repo.get_instrument_by_id(db, instrument_id, include_reports=False)
        if target_inst is None:
            raise NotFoundException("标准计量器具", str(instrument_id))
    else:
        assert gas_detector_id is not None
        target_det = await repo.get_gas_detector_by_id(db, gas_detector_id, include_reports=False)
        if target_det is None:
            raise NotFoundException("有毒有害可燃探测器", str(gas_detector_id))

    # 读取文件内容
    file_data = await file.read()
    file_size = len(file_data)
    content_type = file.content_type or "application/octet-stream"
    filename = file.filename or "report.pdf"

    # 上传到 MinIO
    object_path = _build_report_path(instrument_id or gas_detector_id, filename)  # type: ignore[arg-type]
    upload_object(MODULE_CODE, object_path, file_data, file_size, content_type)

    # 创建元数据记录（失败时清理 MinIO 孤儿文件）
    try:
        report = await repo.create_report(
            db,
            {
                "instrument_id": instrument_id,
                "gas_detector_id": gas_detector_id,
                "file_name": filename,
                "file_path": object_path,
                "file_size": file_size,
                "content_type": content_type,
                "report_date": report_date,
                "remark": remark,
            },
        )
    except Exception:
        delete_object(MODULE_CODE, object_path)
        raise

    return report


async def get_report(db: AsyncSession, report_id: UUID) -> CalibrationReport:
    report = await repo.get_report_by_id(db, report_id)
    if report is None:
        raise NotFoundException("检测报告", str(report_id))
    return report


async def download_report_data(report: CalibrationReport) -> tuple[bytes, str] | None:
    """从 MinIO 下载报告文件的实际内容。"""
    if not is_enabled():
        return None
    return get_object(MODULE_CODE, report.file_path)


async def delete_report(db: AsyncSession, report_id: UUID) -> None:
    deleted = await repo.soft_delete_report(db, report_id)
    if not deleted:
        raise NotFoundException("检测报告", str(report_id))


async def list_instrument_reports(db: AsyncSession, instrument_id: UUID) -> list[CalibrationReport]:
    """获取某个标准计量器具的所有报告。"""
    return await repo.list_reports_by_instrument(db, instrument_id)


async def list_gas_detector_reports(db: AsyncSession, gas_detector_id: UUID) -> list[CalibrationReport]:
    """获取某个探测器的所有报告。"""
    return await repo.list_reports_by_gas_detector(db, gas_detector_id)


# ═══════════════════════════════════════════
# 文件匹配
# ═══════════════════════════════════════════


async def update_report_certificate_no(
    db: AsyncSession, report_id: UUID, certificate_no: str | None
) -> CalibrationReport:
    """手动修改报告证书编号（None/空串 = 清除编号）。"""
    report = await repo.get_report_by_id(db, report_id)
    if report is None:
        raise NotFoundException("检测报告", str(report_id))

    value = (certificate_no or "").strip() or None
    if value and value != report.certificate_no:
        existing = await repo.find_existing_certificate_nos(db, [value])
        if existing:
            raise DuplicateException("证书编号", value)

    # 前置检查与写入之间存在竞态：并发写入撞唯一索引时转成 409 语义
    try:
        await repo.update_report_certificate_no(db, report_id, value)
    except IntegrityError:
        raise DuplicateException("证书编号", value or "") from None
    updated = await repo.get_report_by_id(db, report_id)
    assert updated is not None
    return updated


# ═══════════════════════════════════════════
# 批量导出报告
# ═══════════════════════════════════════════


async def export_instrument_reports(
    db: AsyncSession, ids: list[UUID]
) -> tuple[bytes, str, int]:
    """导出指定仪表的最新报告为 ZIP。返回 (zip_bytes, filename, count)。"""
    import io as io_mod
    import zipfile

    if not is_enabled():
        raise RuntimeError("MinIO 未启用，无法导出报告")

    zip_buf = io_mod.BytesIO()
    count = 0
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for inst_id in ids:
            reports = await repo.list_reports_by_instrument(db, inst_id)
            if not reports:
                continue
            latest = reports[0]  # 按 report_date desc 排列，第一条是最新的
            data = get_object(MODULE_CODE, latest.file_path)
            if data is None:
                continue
            file_data, _ = data
            # 获取仪表名称和资产编号
            inst = await repo.get_instrument_by_id(db, inst_id, include_reports=False)
            if inst is None:
                continue
            safe_name = f"{inst.instrument_name}_{inst.asset_number or inst.id}"
            safe_name = safe_name.replace("/", "_").replace("\\", "_")
            ext = latest.file_name.rsplit(".", 1)[-1] if "." in latest.file_name else "pdf"
            zf.writestr(f"{safe_name}.{ext}", file_data)
            count += 1

    zip_buf.seek(0)
    return zip_buf.getvalue(), "instruments_reports.zip", count


async def export_gas_detector_reports(
    db: AsyncSession, ids: list[UUID]
) -> tuple[bytes, str, int]:
    """导出指定探测器的最新报告为 ZIP。"""
    import io as io_mod
    import zipfile

    if not is_enabled():
        raise RuntimeError("MinIO 未启用，无法导出报告")

    zip_buf = io_mod.BytesIO()
    count = 0
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for det_id in ids:
            reports = await repo.list_reports_by_gas_detector(db, det_id)
            if not reports:
                continue
            latest = reports[0]
            data = get_object(MODULE_CODE, latest.file_path)
            if data is None:
                continue
            file_data, _ = data
            det = await repo.get_gas_detector_by_id(db, det_id, include_reports=False)
            if det is None:
                continue
            safe_name = f"{det.instrument_name}_{det.product_number or det.id}"
            safe_name = safe_name.replace("/", "_").replace("\\", "_")
            ext = latest.file_name.rsplit(".", 1)[-1] if "." in latest.file_name else "pdf"
            zf.writestr(f"{safe_name}.{ext}", file_data)
            count += 1

    zip_buf.seek(0)
    return zip_buf.getvalue(), "gas_detectors_reports.zip", count


# ═══════════════════════════════════════════
# 检定到期提醒
# ═══════════════════════════════════════════
