"""检测报告 + 文件匹配 service 层功能测试（从业务契约角度）。"""

from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.meter import repository as repo
from app.modules.meter import service
from tests.modules.meter.conftest import (
    create_gas_detector,
    create_instrument,
    create_report,
)


def _patch_storage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    stored: Any = None,
) -> None:
    """开关 MinIO 并记录上传内容（打桩到具体子模块的模块属性）。"""
    for mod in (service.reports, service.report_matching):
        monkeypatch.setattr(mod, "is_enabled", lambda: enabled, raising=False)
        monkeypatch.setattr(mod, "upload_object", MagicMock(), raising=False)
        if stored is not None:
            monkeypatch.setattr(mod, "get_object", lambda _module, _path: stored, raising=False)


def _make_upload_file(filename: str = "报告.pdf", content: bytes = b"%PDF-1.4 fake") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


class TestParseFilename:
    def test_split_on_last_underscore(self) -> None:
        """文件名按最后一个下划线拆分为名称与编号。"""
        assert service._parse_filename("压力表_SN-001.pdf") == ("压力表", "SN-001")

    def test_multiple_underscores_split_on_last(self) -> None:
        """多个下划线时以最后一个为分界。"""
        assert service._parse_filename("压力表_型号A_SN-001.pdf") == ("压力表_型号A", "SN-001")

    def test_no_underscore_returns_full_stem(self) -> None:
        """无下划线时整段为名称、编号为空。"""
        assert service._parse_filename("压力表.pdf") == ("压力表", "")


class TestUploadReport:
    async def test_minio_disabled_raises(self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        """MinIO 未启用时上传应抛 RuntimeError。"""
        _patch_storage(monkeypatch, enabled=False)
        inst = await create_instrument(db_session)
        with pytest.raises(RuntimeError):
            await service.upload_report(
                db_session, file=_make_upload_file(), instrument_id=inst.id
            )

    async def test_both_ids_given_rejected(self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        """同时指定两个关联 id 应抛 ValueError。"""
        _patch_storage(monkeypatch)
        inst = await create_instrument(db_session)
        det = await create_gas_detector(db_session)
        with pytest.raises(ValueError):
            await service.upload_report(
                db_session,
                file=_make_upload_file(),
                instrument_id=inst.id,
                gas_detector_id=det.id,
            )

    async def test_no_id_given_rejected(self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        """未指定关联 id 应抛 ValueError。"""
        _patch_storage(monkeypatch)
        with pytest.raises(ValueError):
            await service.upload_report(db_session, file=_make_upload_file())

    async def test_missing_target_raises_not_found(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """关联的器具不存在应抛 NotFoundException。"""
        _patch_storage(monkeypatch)
        with pytest.raises(NotFoundException):
            await service.upload_report(
                db_session, file=_make_upload_file(), instrument_id=uuid4()
            )

    async def test_success_creates_report_metadata(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """上传成功应创建报告元数据（文件名/日期/备注/对象路径）。"""
        _patch_storage(monkeypatch)
        inst = await create_instrument(db_session)
        report = await service.upload_report(
            db_session,
            file=_make_upload_file(filename="检2026-001.pdf"),
            instrument_id=inst.id,
            report_date=date(2026, 8, 1),
            remark="年度检定",
        )
        assert report.instrument_id == inst.id
        assert report.file_name == "检2026-001.pdf"
        assert report.report_date == date(2026, 8, 1)
        assert report.file_path.startswith(f"reports/{inst.id}/")
        assert report.file_size == len(b"%PDF-1.4 fake")


class TestGetAndDeleteReport:
    async def test_get_missing_raises_not_found(self, db_session: AsyncSession) -> None:
        """查询不存在的报告应抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await service.get_report(db_session, uuid4())

    async def test_delete_soft_removes(self, db_session: AsyncSession) -> None:
        """删除报告后查询应抛 NotFoundException（软删除）。"""
        inst = await create_instrument(db_session)
        report = await create_report(db_session, instrument_id=inst.id)
        await service.delete_report(db_session, report.id)
        with pytest.raises(NotFoundException):
            await service.get_report(db_session, report.id)

    async def test_list_reports_by_instrument(self, db_session: AsyncSession) -> None:
        """器具报告列表应按报告日期降序。"""
        inst = await create_instrument(db_session)
        r1 = await create_report(db_session, instrument_id=inst.id, report_date=date(2026, 1, 1))
        r2 = await create_report(db_session, instrument_id=inst.id, report_date=date(2026, 6, 1))
        reports = await service.list_instrument_reports(db_session, inst.id)
        assert [r.id for r in reports] == [r2.id, r1.id]

    async def test_list_reports_by_gas_detector(self, db_session: AsyncSession) -> None:
        """探测器报告列表应返回关联报告。"""
        det = await create_gas_detector(db_session)
        report = await create_report(db_session, gas_detector_id=det.id)
        reports = await service.list_gas_detector_reports(db_session, det.id)
        assert [r.id for r in reports] == [report.id]


class TestDownloadReport:
    async def test_minio_disabled_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MinIO 未启用时下载数据应返回 None。"""
        _patch_storage(monkeypatch, enabled=False)
        assert await service.download_report_data(MagicMock()) is None

    async def test_enabled_returns_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MinIO 启用时返回 (bytes, content_type)。"""
        blob = (b"pdf-bytes", "application/pdf")
        _patch_storage(monkeypatch, enabled=True, stored=blob)
        assert await service.download_report_data(MagicMock()) == blob


class TestUpdateReportCertificateNo:
    async def test_missing_report_raises_not_found(self, db_session: AsyncSession) -> None:
        """修改不存在的报告应抛 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await service.update_report_certificate_no(db_session, uuid4(), "C-001")

    async def test_duplicate_certificate_no_rejected(self, db_session: AsyncSession) -> None:
        """证书编号与已有报告冲突应抛 DuplicateException。"""
        inst = await create_instrument(db_session)
        await create_report(db_session, instrument_id=inst.id, certificate_no="CERT-1")
        target = await create_report(db_session, instrument_id=inst.id)
        with pytest.raises(DuplicateException):
            await service.update_report_certificate_no(db_session, target.id, "CERT-1")

    async def test_set_new_certificate_no(self, db_session: AsyncSession) -> None:
        """设置新证书编号应生效。"""
        inst = await create_instrument(db_session)
        target = await create_report(db_session, instrument_id=inst.id)
        updated = await service.update_report_certificate_no(db_session, target.id, "CERT-9")
        assert updated.certificate_no == "CERT-9"

    async def test_clear_certificate_no_with_empty(self, db_session: AsyncSession) -> None:
        """空串应清除证书编号。"""
        inst = await create_instrument(db_session)
        target = await create_report(db_session, instrument_id=inst.id, certificate_no="CERT-8")
        updated = await service.update_report_certificate_no(db_session, target.id, "")
        assert updated.certificate_no is None

    async def test_soft_deleted_certificate_no_reusable(self, db_session: AsyncSession) -> None:
        """删除报告后，同一证书编号可重新使用（软删除不占唯一性）。"""
        inst = await create_instrument(db_session)
        old = await create_report(db_session, instrument_id=inst.id, certificate_no="CERT-R")
        await service.delete_report(db_session, old.id)
        target = await create_report(db_session, instrument_id=inst.id)
        updated = await service.update_report_certificate_no(db_session, target.id, "CERT-R")
        assert updated.certificate_no == "CERT-R"


class TestMatchFilenames:
    async def test_exact_serial_match_instrument(self, db_session: AsyncSession) -> None:
        """名称+编号精确命中器具。"""
        inst = await create_instrument(db_session, instrument_name="压力表", serial_number="SN-X1")
        results = await service.match_filenames(db_session, ["压力表_SN-X1.pdf"])
        assert results[0]["matched_type"] == "instrument"
        assert results[0]["matched_id"] == str(inst.id)
        assert results[0]["matched_department"] == inst.department

    async def test_product_match_detector(self, db_session: AsyncSession) -> None:
        """名称+产品编号精确命中探测器。"""
        det = await create_gas_detector(
            db_session, instrument_name="可燃探测器", product_number="PN-D1"
        )
        results = await service.match_filenames(db_session, ["可燃探测器_PN-D1.pdf"])
        assert results[0]["matched_type"] == "gas_detector"
        assert results[0]["matched_id"] == str(det.id)

    async def test_no_code_no_match(self, db_session: AsyncSession) -> None:
        """文件名无编号段时不做匹配。"""
        results = await service.match_filenames(db_session, ["没有下划线的文件.pdf"])
        assert results[0]["matched_type"] is None
        assert results[0]["matched_id"] is None


class TestMatchOne:
    async def test_serial_match_wins_over_candidates(self, db_session: AsyncSession) -> None:
        """编号精确命中时直接返回匹配结果。"""
        inst = await create_instrument(db_session, instrument_name="压力表", serial_number="SN-M1")
        result = await service.match_one(db_session, "压力表", "SN-M1")
        assert result["matched_type"] == "instrument"
        assert result["matched_id"] == str(inst.id)

    async def test_name_only_returns_candidates(self, db_session: AsyncSession) -> None:
        """仅名称时返回两类候选（器具+探测器）。"""
        marker = uuid4().hex[:8]
        inst = await create_instrument(db_session, instrument_name=f"压力表{marker}")
        det = await create_gas_detector(db_session, instrument_name=f"压力表{marker}")
        result = await service.match_one(db_session, f"压力表{marker}", None)
        assert result["matched_type"] is None
        types = {c["type"] for c in result["candidates"]}
        ids = {c["id"] for c in result["candidates"]}
        assert types == {"instrument", "gas_detector"}
        assert ids == {str(inst.id), str(det.id)}


class TestBatchUploadReports:
    def _files(self, count: int = 1) -> list[tuple[str, bytes, str]]:
        return [(f"报告{i}.pdf", b"%PDF-fake", "application/pdf") for i in range(count)]

    async def test_minio_disabled_raises(self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        """MinIO 未启用时批量上传应抛 RuntimeError。"""
        _patch_storage(monkeypatch, enabled=False)
        with pytest.raises(RuntimeError):
            await service.batch_upload_reports(db_session, self._files(), [])

    async def test_file_not_in_map_fails(self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        """items 引用不存在的文件应记为失败。"""
        _patch_storage(monkeypatch)
        inst = await create_instrument(db_session)
        items = [{"filename": "不存在.pdf", "instrument_id": str(inst.id)}]
        result = await service.batch_upload_reports(db_session, self._files(), items)
        assert result["failed"] == 1
        assert "文件未找到" in result["errors"][0]

    async def test_item_without_target_fails(self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        """未关联仪表的 item 应记为失败。"""
        _patch_storage(monkeypatch)
        items = [{"filename": "报告0.pdf"}]
        result = await service.batch_upload_reports(db_session, self._files(), items)
        assert result["failed"] == 1
        assert "未关联仪表" in result["errors"][0]

    async def test_duplicate_certificate_in_batch_fails(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """同批次内证书编号重复：该编号的所有文件都判定失败。"""
        _patch_storage(monkeypatch)
        inst = await create_instrument(db_session)
        files = self._files(2)
        items = [
            {"filename": "报告0.pdf", "instrument_id": str(inst.id), "certificate_no": "C-DUP"},
            {"filename": "报告1.pdf", "instrument_id": str(inst.id), "certificate_no": "C-DUP"},
        ]
        result = await service.batch_upload_reports(db_session, files, items)
        assert result["failed"] == 2
        assert result["success"] == 0
        assert all("同批次中重复" in e for e in result["errors"])

    async def test_existing_certificate_in_db_fails(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DB 已存在的证书编号应被防重拦截。"""
        _patch_storage(monkeypatch)
        inst = await create_instrument(db_session)
        await create_report(db_session, instrument_id=inst.id, certificate_no="C-DB")
        items = [
            {"filename": "报告0.pdf", "instrument_id": str(inst.id), "certificate_no": "C-DB"}
        ]
        result = await service.batch_upload_reports(db_session, self._files(), items)
        assert result["failed"] == 1
        assert "已存在" in result["errors"][0]

    async def test_success_creates_reports(self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        """批量上传成功应创建报告并返回 id。"""
        _patch_storage(monkeypatch)
        inst = await create_instrument(db_session)
        items = [
            {"filename": "报告0.pdf", "instrument_id": str(inst.id), "certificate_no": "C-NEW"}
        ]
        result = await service.batch_upload_reports(db_session, self._files(), items)
        assert result["success"] == 1
        assert len(result["report_ids"]) == 1
        stored = await repo.get_report_by_id(db_session, UUID(result["report_ids"][0]))
        assert stored is not None
        assert stored.certificate_no == "C-NEW"

    async def test_newer_pdf_date_writes_back_to_ledger(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PDF 日期 ≥ 台账日期时回写台账并重算下次检定日期。"""
        _patch_storage(monkeypatch)
        inst = await create_instrument(
            db_session,
            calibration_date=date(2026, 1, 1),
            next_calibration_date=date(2027, 1, 1),
            calibration_cycle_months=12,
        )
        newer = date.today()
        items = [
            {
                "filename": "报告0.pdf",
                "instrument_id": str(inst.id),
                "calibration_date": newer.isoformat(),
            }
        ]
        result = await service.batch_upload_reports(db_session, self._files(), items)
        assert result["success"] == 1
        updated = await repo.get_instrument_by_id(db_session, inst.id)
        assert updated is not None
        assert updated.calibration_date == newer
        assert updated.next_calibration_date == newer + timedelta(days=365) - timedelta(days=1)

    async def test_older_pdf_date_only_archives(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PDF 日期早于台账日期时仅归档并给 note，不回写。"""
        _patch_storage(monkeypatch)
        inst = await create_instrument(db_session, calibration_date=date.today())
        older = date.today() - timedelta(days=10)
        items = [
            {
                "filename": "报告0.pdf",
                "instrument_id": str(inst.id),
                "calibration_date": older.isoformat(),
            }
        ]
        result = await service.batch_upload_reports(db_session, self._files(), items)
        assert result["success"] == 1
        assert len(result["notes"]) == 1
        updated = await repo.get_instrument_by_id(db_session, inst.id)
        assert updated is not None
        assert updated.calibration_date == date.today()


class TestAnalyzeReportFiles:
    async def test_extraction_and_match_flow(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """识别结果应与台账匹配并合并返回。"""
        inst = await create_instrument(db_session, instrument_name="压力表", serial_number="SN-A")
        fields = {
            "instrument_name": "压力表",
            "serial_number": "SN-A",
            "certificate_no": "CERT-AI",
            "calibration_date": date.today(),
            "method": "text",
            "error": None,
        }
        monkeypatch.setattr(
            "app.modules.meter.recognition.extract_report_fields",
            AsyncMock(return_value=fields),
        )
        results = await service.analyze_report_files(
            db_session, [("a.pdf", b"%PDF", "application/pdf")]
        )
        assert results[0]["filename"] == "a.pdf"
        assert results[0]["extraction"] == fields
        assert results[0]["matched_type"] == "instrument"
        assert results[0]["matched_id"] == str(inst.id)

    async def test_single_file_failure_marked_failed(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """单文件识别失败只标记 failed，不影响其他文件。"""
        async def fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("识别炸了")

        monkeypatch.setattr("app.modules.meter.recognition.extract_report_fields", fail)
        results = await service.analyze_report_files(
            db_session, [("bad.pdf", b"%PDF", "application/pdf")]
        )
        assert results[0]["extraction"]["method"] == "failed"
        assert "识别失败" in results[0]["extraction"]["error"]


class TestExportReports:
    async def test_export_instrument_reports_zip(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """导出 ZIP 内文件名应为 名称_资产编号.扩展名，内容正确。"""
        inst = await create_instrument(
            db_session, instrument_name="压力表", asset_number="ASSET-EXP"
        )
        await create_report(
            db_session, instrument_id=inst.id, file_name="检2026.pdf", report_date=date(2026, 8, 1)
        )
        blob = (b"pdf-content", "application/pdf")
        _patch_storage(monkeypatch, enabled=True, stored=blob)

        zip_data, filename, count = await service.export_instrument_reports(
            db_session, [inst.id]
        )
        assert filename == "instruments_reports.zip"
        assert count == 1

        import zipfile

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            names = zf.namelist()
            assert len(names) == 1
            assert names[0] == "压力表_ASSET-EXP.pdf"
            assert zf.read(names[0]) == b"pdf-content"

    async def test_export_without_reports_returns_empty(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无报告的器具导出应返回空 ZIP。"""
        inst = await create_instrument(db_session)
        _patch_storage(monkeypatch, enabled=True)
        _, _, count = await service.export_instrument_reports(db_session, [inst.id])
        assert count == 0

    async def test_export_gas_detector_reports(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """探测器报告导出 ZIP 命名规则一致。"""
        det = await create_gas_detector(
            db_session, instrument_name="探测器", product_number="PN-EXP"
        )
        await create_report(db_session, gas_detector_id=det.id, file_name="检D.pdf")
        _patch_storage(monkeypatch, enabled=True, stored=(b"d", "application/pdf"))
        zip_data, _, count = await service.export_gas_detector_reports(db_session, [det.id])
        assert count == 1

        import zipfile

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            assert zf.namelist() == ["探测器_PN-EXP.pdf"]

    async def test_export_minio_disabled_raises(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MinIO 未启用时导出应抛 RuntimeError。"""
        _patch_storage(monkeypatch, enabled=False)
        with pytest.raises(RuntimeError):
            await service.export_instrument_reports(db_session, [uuid4()])
