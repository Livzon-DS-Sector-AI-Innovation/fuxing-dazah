"""员工证件资料库：缺件清单导出（按员工汇总为一行）。"""

from datetime import date as _date
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy import update


@pytest.mark.asyncio
async def test_missing_certificates_export_one_row_per_employee(db_session, client):
    """缺件清单导出：同一员工的多条缺件合并成一行（缺件数 + 明细），供 HR 线下催收。

    service 层按「员工 × 类别」逐行输出；页面上之前也是一人多行（约 2600 行）。
    """
    from app.modules.hr.models import CertificateRequirement, Employee, EmployeeCertificate

    tag = uuid4().hex[:6].upper()
    # 应交配置的唯一索引按 (category, applies_to)：事务内先软删存量，再放两条测试配置
    await db_session.execute(update(CertificateRequirement).values(is_deleted=True))
    db_session.add_all([
        CertificateRequirement(
            category=EmployeeCertificate.CATEGORY_OTHER,
            applies_to=CertificateRequirement.APPLIES_ALL,
        ),
        CertificateRequirement(
            category=EmployeeCertificate.CATEGORY_HEALTH,
            applies_to=CertificateRequirement.APPLIES_ALL,
        ),
        Employee(
            employee_number=f"CE{tag}1", name=f"缺件导出测试{tag}", department="人力资源部",
            position="HR", status="在职", hire_date=_date.today(),
        ),
    ])
    await db_session.flush()

    res = await client.get("/api/v1/hr/certificates/missing/export")
    assert res.status_code == 200, res.text

    ws = load_workbook(BytesIO(res.content)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("姓名", "工号", "部门", "重点岗位", "缺件数", "缺件明细")

    mine = [r for r in rows[1:] if r[1] == f"CE{tag}1"]
    assert len(mine) == 1, "同一员工的多条缺件应合并为一行"
    assert mine[0][4] == 2
    assert set(str(mine[0][5]).split("、")) == {"健康证", "其他"}
