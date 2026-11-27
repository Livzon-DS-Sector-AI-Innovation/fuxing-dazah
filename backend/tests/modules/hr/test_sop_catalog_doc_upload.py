"""SOP 目录上传：GMP 文件目录 Word（.doc/.docx）解析导入。

.doc 旧二进制用 tests/modules/hr/fixtures/sop_catalog_sample.doc 真实样例
（「37文件目录(岗位职责二-提炼工程三部) -中英文.doc」，单分类单条目），
.docx 用 python-docx 按同结构构造。
"""

import io
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import SopCatalog
from app.modules.hr.sop_catalog_doc_parser import _truncate_version, parse_catalog_document

_FIXTURE_DOC = Path(__file__).parent / "fixtures" / "sop_catalog_sample.doc"
_FILENAME = "37文件目录(岗位职责二-提炼工程三部) -中英文.doc"

_EXPECTED = {
    "category": "岗位职责：提炼工程三部",
    "file_name": "岗位职责：提炼工程三部",
    "sop_number": "SOP.01.3701",
    "department": "提炼工程三部",
}


def _build_catalog_docx() -> bytes:
    """构造与 GMP 文件目录同结构的 docx：大分类合并行 + 表头行 + 中英双语数据行。"""
    doc = Document()
    table = doc.add_table(rows=3, cols=4)
    table.cell(0, 0).merge(table.cell(0, 3))
    table.cell(0, 0).text = "岗位职责：提炼工程三部\nPosition Responsibilities: Extraction Department Ⅲ"
    for i, h in enumerate(
        ["序号\nNo.", "文件名称\nDocument Name", "文件编号\nDocument No.", "生效日期\nEffective Date"]
    ):
        table.cell(1, i).text = h
    table.cell(2, 0).text = "01"
    table.cell(2, 1).text = "岗位职责：提炼工程三部\nPosition Responsibilities: Extraction Department Ⅲ"
    table.cell(2, 2).text = "SOP.01.3701.002"
    table.cell(2, 3).text = "2022年06月01日"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════
# 解析层
# ═══════════════════════════════════════════════════════════════


def test_parse_docx_catalog():
    entries = parse_catalog_document(_build_catalog_docx(), _FILENAME)
    assert entries == [_EXPECTED]


def test_parse_doc_catalog_fixture():
    entries = parse_catalog_document(_FIXTURE_DOC.read_bytes(), _FILENAME)
    assert entries == [_EXPECTED]


def test_truncate_version_boundary():
    assert _truncate_version("SOP.01.3701.002") == "SOP.01.3701"
    assert _truncate_version("SOP.01.3701") == "SOP.01.3701"  # 无版本号不动
    assert _truncate_version("SOP.01.3701.0020") == "SOP.01.3701.0020"  # 非 3 位版本段不动


def test_reject_non_word_bytes():
    with pytest.raises(ValueError):
        parse_catalog_document(b"not a word doc", _FILENAME)


# ═══════════════════════════════════════════════════════════════
# 服务层：doc 条目复用 Excel 同一条 upsert 通道
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upload_doc_writes_catalog(db_session: AsyncSession):
    from app.modules.hr.service import EmployeeService

    # fixture 是真实 GMP 文档、编号固定：先软删库里的同编号旧行（此前实测留下的），
    # 测试才能对「新增 1」做精确断言，并保持可重复执行
    await db_session.execute(
        text("UPDATE hr.sop_catalog SET is_deleted = true WHERE sop_number = 'SOP.01.3701'")
    )
    await db_session.commit()

    content = _FIXTURE_DOC.read_bytes()
    result = await EmployeeService(db_session).upload_sop_catalog(content, filename=_FILENAME)

    assert (result["created"], result["updated"], result["errors"]) == (1, 0, [])
    row = (await db_session.execute(
        select(SopCatalog).where(
            SopCatalog.sop_number == "SOP.01.3701", SopCatalog.is_deleted == False,  # noqa: E712
        )
    )).scalar_one()
    for k, v in _EXPECTED.items():
        assert getattr(row, k) == v

    # 重复上传 → 更新不重复建行
    result2 = await EmployeeService(db_session).upload_sop_catalog(content, filename=_FILENAME)
    assert (result2["created"], result2["updated"]) == (0, 1)
    rows = (await db_session.execute(
        select(SopCatalog).where(
            SopCatalog.sop_number == "SOP.01.3701", SopCatalog.is_deleted == False,  # noqa: E712
        )
    )).scalars().all()
    assert len(rows) == 1


# ═══════════════════════════════════════════════════════════════
# HTTP 层：扩展名白名单
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upload_endpoint_accepts_doc(client, db_session: AsyncSession):
    # 同上：先软删同编号旧行，「新增 1」的断言才可重复
    await db_session.execute(
        text("UPDATE hr.sop_catalog SET is_deleted = true WHERE sop_number = 'SOP.01.3701'")
    )
    await db_session.commit()

    res = await client.post(
        "/api/v1/hr/sop-catalog/upload",
        files={"file": (_FILENAME, _FIXTURE_DOC.read_bytes(), "application/msword")},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert (data["created"], data["updated"], data["errors"]) == (1, 0, [])
    assert "新增 1" in res.json()["message"]


@pytest.mark.asyncio
async def test_upload_endpoint_rejects_other_ext(client):
    res = await client.post(
        "/api/v1/hr/sop-catalog/upload",
        files={"file": ("目录.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert res.status_code == 400
    assert ".doc" in res.json()["message"]
