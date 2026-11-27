"""入职培训文档导出 —— 「体现岗位」写培训岗位的规则。

员工的实际岗位名常与培训岗位不同（如「万古纯化」对「工艺员」）。
导出时指定了培训岗位，岗前培训计划和培训记录里的「体现岗位」都写培训岗位；
没指定时仍写员工实际岗位，保证文档不留空。
转岗/晋升员工：异动记录不回写档案，文档按最近一次异动的目标部门/岗位出。
"""

import io
from datetime import date
from uuid import UUID

import pytest
from docx import Document
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import TransferRecord
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


async def _add_transfer(
    db: AsyncSession, emp_id: str,
    *,
    to_department: str = "质量保证部", to_position: str = "质量QA",
) -> None:
    """给员工落一条转岗异动（真实入口 POST /transfers，这里聚焦文档口径走 ORM）。"""
    db.add(TransferRecord(
        employee_id=UUID(emp_id), transfer_type="转岗",
        from_department="岗前测试部", to_department=to_department,
        from_position="万古纯化", to_position=to_position,
        effective_date=date.today(),
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_training_record_follows_transfer_target(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """培训记录：转岗员工的体现部门/岗位写异动目标值，档案还没同步更新也按异动口径。"""
    number, emp_id = await _make_employee(db_session)
    await _add_transfer(db_session, emp_id)

    resp = await client.post(
        f"/api/v1/hr/employees/{number}/training-record", json={"training_items": ITEMS},
    )
    assert resp.status_code == 200, resp.text
    text = _docx_text(resp.content)
    assert "质量保证部" in text
    assert "质量QA" in text
    assert "岗前测试部" not in text
    assert "万古纯化" not in text


@pytest.mark.asyncio
async def test_work_permit_follows_transfer_target(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """上岗证：转岗员工的体现部门写异动目标部门。"""
    number, emp_id = await _make_employee(db_session)
    await _add_transfer(db_session, emp_id)

    resp = await client.post(
        f"/api/v1/hr/employees/{number}/work-permit", json={"training_items": ITEMS},
    )
    assert resp.status_code == 200, resp.text
    text = _docx_text(resp.content)
    assert "质量保证部" in text
    assert "岗前测试部" not in text


@pytest.mark.asyncio
async def test_prejob_plan_follows_transfer_target(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """岗前培训计划：有入职台账的转岗员工同样按异动目标部门/岗位出文档。"""
    number, emp_id = await _make_employee(db_session)
    await _add_transfer(db_session, emp_id)

    resp = await client.post(
        f"/api/v1/hr/employees/{number}/prejob-training-plan", json={"training_items": ITEMS},
    )
    assert resp.status_code == 200, resp.text
    text = _docx_text(resp.content)
    assert "质量保证部" in text
    assert "质量QA" in text
    assert "岗前测试部" not in text
    assert "万古纯化" not in text
    # 类别写异动类型「转岗」（模板标题本身含「新员工」字样，无法断言其不在）
    assert "转岗" in text
