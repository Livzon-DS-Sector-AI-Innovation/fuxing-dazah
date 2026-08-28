"""检测报告与文件匹配 API 端点功能测试。

契约：multipart 上传（MinIO 存储打桩）；/reports/match-one 必须可访问
（静态路由不被 /reports/{id} 吞掉）；证书编号重复 409；批量上传走打桩存储。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.modules.meter import service
from tests.modules.meter.conftest import create_instrument, create_report


@pytest.fixture
def patched_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """MinIO 存储打桩：启用 + 上传/读取 noop（打桩到具体子模块）。"""
    for mod in (service.reports, service.report_matching):
        monkeypatch.setattr(mod, "is_enabled", lambda: True, raising=False)
        monkeypatch.setattr(mod, "upload_object", MagicMock(), raising=False)
        monkeypatch.setattr(mod, "get_object", lambda _m, _p: (b"pdf", "application/pdf"), raising=False)


class TestUploadReport:
    async def test_upload_returns_201(self, api_context: tuple[AsyncClient, Any], patched_storage: None) -> None:
        """multipart 上传报告应返回 201 与元数据。"""
        client, db = api_context
        inst = await create_instrument(db)
        resp = await client.post(
            "/api/v1/meter/reports",
            data={"instrument_id": str(inst.id)},
            files={"file": ("检2026.pdf", b"%PDF-fake", "application/pdf")},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["file_name"] == "检2026.pdf"
        assert data["instrument_id"] == str(inst.id)

    async def test_upload_without_file_returns_400(self, api_context: tuple[AsyncClient, Any], patched_storage: None) -> None:
        """缺少 file 参数应返回 400。"""
        client, db = api_context
        inst = await create_instrument(db)
        resp = await client.post(
            "/api/v1/meter/reports", data={"instrument_id": str(inst.id)}
        )
        assert resp.status_code == 400


class TestMatchOne:
    async def test_match_one_reachable(self, api_context: tuple[AsyncClient, Any]) -> None:
        """静态路由 /reports/match-one 应返回 200（不被 /reports/{id} 吞掉）。"""
        client, _ = api_context
        resp = await client.get(
            "/api/v1/meter/reports/match-one",
            params={"instrument_name": "压力表", "serial_number": "SN-1"},
        )
        assert resp.status_code == 200
        assert "matched_type" in resp.json()["data"]


class TestReportCrud:
    async def test_get_missing_returns_404(self, api_context: tuple[AsyncClient, Any]) -> None:
        """不存在的报告应返回 404。"""
        client, _ = api_context
        resp = await client.get(f"/api/v1/meter/reports/{uuid4()}")
        assert resp.status_code == 404

    async def test_delete_report(self, api_context: tuple[AsyncClient, Any]) -> None:
        """删除报告后查询应 404。"""
        client, db = api_context
        inst = await create_instrument(db)
        report = await create_report(db, instrument_id=inst.id)
        resp = await client.delete(f"/api/v1/meter/reports/{report.id}")
        assert resp.status_code == 200
        resp = await client.get(f"/api/v1/meter/reports/{report.id}")
        assert resp.status_code == 404

    async def test_list_reports_by_instrument(self, api_context: tuple[AsyncClient, Any]) -> None:
        """器具的报告列表接口应返回该器具的报告。"""
        client, db = api_context
        inst = await create_instrument(db)
        report = await create_report(db, instrument_id=inst.id)
        resp = await client.get(f"/api/v1/meter/instruments/{inst.id}/reports")
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert [i["id"] for i in items] == [str(report.id)]

    async def test_update_certificate_no(self, api_context: tuple[AsyncClient, Any]) -> None:
        """修改证书编号应返回更新后的元数据。"""
        client, db = api_context
        inst = await create_instrument(db)
        report = await create_report(db, instrument_id=inst.id)
        resp = await client.put(
            f"/api/v1/meter/reports/{report.id}", json={"certificate_no": "CERT-API"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["certificate_no"] == "CERT-API"

    async def test_update_certificate_no_duplicate_returns_409(self, api_context: tuple[AsyncClient, Any]) -> None:
        """证书编号与其他报告冲突应返回 409。"""
        client, db = api_context
        inst = await create_instrument(db)
        await create_report(db, instrument_id=inst.id, certificate_no="CERT-TAKEN")
        target = await create_report(db, instrument_id=inst.id)
        resp = await client.put(
            f"/api/v1/meter/reports/{target.id}", json={"certificate_no": "CERT-TAKEN"}
        )
        assert resp.status_code == 409


class TestFileMatching:
    async def test_match_filenames(self, api_context: tuple[AsyncClient, Any]) -> None:
        """文件名批量匹配应返回逐文件结果。"""
        client, db = api_context
        inst = await create_instrument(db, instrument_name="压力表", serial_number="SN-F1")
        resp = await client.post(
            "/api/v1/meter/reports/match",
            json={"filenames": ["压力表_SN-F1.pdf"]},
        )
        assert resp.status_code == 200
        item = resp.json()["data"][0]
        assert item["matched_type"] == "instrument"
        assert item["matched_id"] == str(inst.id)


class TestBatchUpload:
    async def test_batch_upload_returns_summary(self, api_context: tuple[AsyncClient, Any], patched_storage: None) -> None:
        """批量上传应返回 success/failed 汇总。"""
        import json as json_mod

        client, db = api_context
        inst = await create_instrument(db)
        items = [{"filename": "r1.pdf", "instrument_id": str(inst.id), "certificate_no": "BC-1"}]
        resp = await client.post(
            "/api/v1/meter/reports/batch",
            data={"items_json": json_mod.dumps(items)},
            files=[("files", ("r1.pdf", b"%PDF-fake", "application/pdf"))],
        )
        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["success"] == 1
        assert body["failed"] == 0


class TestAnalyzeReportFiles:
    async def test_analyze_returns_per_file_result(self, api_context: tuple[AsyncClient, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        """批量识别应返回逐文件的识别+匹配结果。"""
        client, db = api_context
        inst = await create_instrument(db, instrument_name="压力表", serial_number="SN-AI")
        monkeypatch.setattr(
            "app.modules.meter.recognition.extract_report_fields",
            AsyncMock(
                return_value={
                    "instrument_name": "压力表",
                    "serial_number": "SN-AI",
                    "certificate_no": None,
                    "calibration_date": None,
                    "method": "text",
                    "error": None,
                }
            ),
        )
        resp = await client.post(
            "/api/v1/meter/reports/analyze",
            files=[("files", ("a.pdf", b"%PDF", "application/pdf"))],
        )
        assert resp.status_code == 200
        item = resp.json()["data"][0]
        assert item["matched_type"] == "instrument"
        assert item["matched_id"] == str(inst.id)

    async def test_analyze_missing_files_returns_400(self, api_context: tuple[AsyncClient, Any]) -> None:
        """缺少 files 参数应返回 400。"""
        client, _ = api_context
        resp = await client.post("/api/v1/meter/reports/analyze")
        assert resp.status_code == 400
