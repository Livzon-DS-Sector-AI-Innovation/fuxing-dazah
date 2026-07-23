"""题库 — API 测试。

覆盖题库检索和 docx 导入。
"""

import pytest

from tests.modules.hr.conftest import _rand


@pytest.mark.asyncio
async def test_api_search_question_bank(client):
    """GET /question-bank 返回 200。"""
    resp = await client.get("/api/v1/hr/question-bank?page=1&page_size=5")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_import_docx_invalid_file(client):
    """上传非 docx 文件返回 400。"""
    resp = await client.post(
        "/api/v1/hr/question-bank/import-docx",
        files={"file": ("test.txt", b"not a docx", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_api_import_docx_no_qa(client):
    """上传不含问答表格的 docx 返回 400。"""
    import io
    from openpyxl import Workbook
    wb = Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    # 伪装成 docx 扩展名但内容是 xlsx
    resp = await client.post(
        "/api/v1/hr/question-bank/import-docx",
        files={"file": ("test.docx", buf.read(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 400
