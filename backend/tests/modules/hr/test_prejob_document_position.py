"""入职培训文档导出 —— 「体现岗位」写培训岗位的规则。

员工的实际岗位名常与培训岗位不同（如「万古纯化」对「工艺员」）。
导出时指定了培训岗位，岗前培训计划和培训记录里的「体现岗位」都写培训岗位；
没指定时仍写员工实际岗位，保证文档不留空。
"""

import io
from datetime import date

import pytest
from docx import Document
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.schemas import EmployeeCreate
from app.modules.hr.service import EmployeeService
from tests.modules.hr.conftest import _rand

ITEMS = [{"content": "工艺操作", "trainer": "张三", "method": "面授", "plan_date": "2026-12-01"}]


def _docx_text(content: bytes) -> str:
    """取出 docx 的段落与表格文字，用于断言占位符被替换成了什么。"""
    doc = Document(io.BytesIO(content))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


async def _make_employee(db: AsyncSession) -> tuple[str, str]:
    """建一名实际岗位为「万古纯化」的员工，返回 (工号, 员工 UUID)。"""
    employee = await EmployeeService(db).create_employee(EmployeeCreate(
        employee_number=_rand("TP"),
        name="培训岗位测试",
        department="岗前测试部",
        position="万古纯化",
        hire_date=date.today(),
    ))
    return employee.employee_number, str(employee.id)


@pytest.mark.asyncio
async def test_training_record_post_follows_training_position(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """培训记录：指定培训岗位写培训岗位，未指定仍写实际岗位。"""
    number, _ = await _make_employee(db_session)
    url = f"/api/v1/hr/employees/{number}/training-record"

    given = await client.post(url, json={"training_items": ITEMS, "training_position": "工艺员"})
    assert given.status_code == 200, given.text
    text = _docx_text(given.content)
    assert "工艺员" in text
    assert "万古纯化" not in text
    assert "{体现岗位}" not in text

    fallback = await client.post(url, json={"training_items": ITEMS})
    assert fallback.status_code == 200, fallback.text
    assert "万古纯化" in _docx_text(fallback.content)


@pytest.mark.asyncio
async def test_prejob_training_plan_post_follows_training_position(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """岗前培训计划：指定培训岗位写培训岗位，未指定仍写实际岗位。"""
    _, employee_id = await _make_employee(db_session)
    url = f"/api/v1/hr/employees/{employee_id}/prejob-training-plan"

    given = await client.post(url, json={"training_items": ITEMS, "training_position": "工艺员"})
    assert given.status_code == 200, given.text
    text = _docx_text(given.content)
    assert "工艺员" in text
    assert "万古纯化" not in text
    assert "{体现岗位}" not in text

    fallback = await client.post(url, json={"training_items": ITEMS})
    assert fallback.status_code == 200, fallback.text
    assert "万古纯化" in _docx_text(fallback.content)
