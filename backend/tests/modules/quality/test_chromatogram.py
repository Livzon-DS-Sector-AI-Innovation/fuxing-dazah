"""图谱解析端点测试：带 task_id 时原图归档为任务附件（MinerU 与存储均 mock）。

此前 /chromatograms/parse 零覆盖；归档是 GMP 原图留痕口径（设计文档 07 §四）。
"""

import io
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import QualityStandardDocument
from app.modules.quality.repository import (
    create_test_task,
    list_task_attachments,
)

_PEAK_MD = """# 图谱报告

| 峰名 | 面积 |
| --- | --- |
| 万古霉素B | 1000.5 |
| 杂质F | 20.3 |
"""


async def _make_task(db: AsyncSession) -> object:
    doc = QualityStandardDocument(
        file_no=f"SOP.02.{uuid.uuid4().hex[:4].upper()}.{uuid.uuid4().hex[:3].upper()}",
        product_name=f"图谱测试产品{uuid.uuid4().hex[:6]}",
        product_code="HAF",
        valid_years="3年",
    )
    db.add(doc)
    await db.flush()
    return await create_test_task(
        db,
        product_name=doc.product_name,
        batch_number=f"HAF{uuid.uuid4().hex[:8].upper()}",
        production_date="2026-09-01",
        expiry_date="2028-08-31",
        specification=None,
        form_id=None,
        standard_document_id=doc.id,
    )


def _mock_parse(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """mock MinerU 解析与附件存储，返回实际发生的上传 key 列表。"""
    from app.modules.quality.api import _chromatograms as cg

    async def fake_markdown(data: bytes, filename: str) -> str:
        return _PEAK_MD

    uploads: list[str] = []
    monkeypatch.setattr(cg, "parse_chromatogram_markdown", fake_markdown)
    monkeypatch.setattr(
        cg.quality_storage, "upload_attachment", lambda key, data, ct: uploads.append(key)
    )
    return uploads


async def test_parse_with_task_id_archives_original(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.quality.api._chromatograms import parse_chromatogram_endpoint

    task = await _make_task(db_session)
    uploads = _mock_parse(monkeypatch)
    file = UploadFile(file=io.BytesIO(b"fake-image-bytes"), filename="chroma.jpg")
    fake_user = SimpleNamespace(id=uuid.uuid4())

    resp = await parse_chromatogram_endpoint(
        file=file, task_id=task.id, db=db_session, _user=fake_user
    )
    body = json.loads(resp.body)
    assert body["data"]["archived"] is True
    assert len(body["data"]["peaks"]) == 2
    # 存储上传一次且 key 落在任务目录下；附件行 source=chromatogram 留痕
    assert len(uploads) == 1 and uploads[0].startswith(f"{task.id}/")
    atts = await list_task_attachments(db_session, task.id)
    assert len(atts) == 1
    assert atts[0].source == "chromatogram"
    assert atts[0].filename == "chroma.jpg"


async def test_parse_without_task_id_no_archive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不带 task_id（旧调用方式）：纯预览，不归档不写库。"""
    from app.modules.quality.api._chromatograms import parse_chromatogram_endpoint

    task = await _make_task(db_session)
    uploads = _mock_parse(monkeypatch)
    file = UploadFile(file=io.BytesIO(b"fake-image-bytes"), filename="chroma.png")
    fake_user = SimpleNamespace(id=uuid.uuid4())

    resp = await parse_chromatogram_endpoint(
        file=file, task_id=None, db=db_session, _user=fake_user
    )
    body = json.loads(resp.body)
    assert body["data"]["archived"] is False
    assert uploads == []
    assert await list_task_attachments(db_session, task.id) == []
