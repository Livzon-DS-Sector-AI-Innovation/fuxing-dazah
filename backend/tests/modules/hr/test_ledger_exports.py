"""台账导出端点测试：入职/离职/事故/编制对账。

口径约定：导出与各列表端点同口径（筛选参数/数据范围），本文件只验证
导出本身的 200/xlsx/文件名/内容行；筛选与数据范围逻辑由列表端点测试覆盖。
"""

from datetime import date
from io import BytesIO
from urllib.parse import unquote
from uuid import uuid4

from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import (
    DepartureRecord,
    Employee,
    HeadcountPlan,
    HrIncidentRecord,
)
from tests.modules.hr.conftest import _rand


def _read_xlsx(content: bytes):
    wb = load_workbook(BytesIO(content))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    return header, [dict(zip(header, r)) for r in rows[1:]]


# ─── 入职台账 ───


async def test_export_onboarding_records(db_session: AsyncSession, client: AsyncClient):
    dept = _rand("导出入职部")
    emp = Employee(
        id=uuid4(), name=_rand("入职导出"), employee_number=f"EXP{uuid4().hex[:6]}",
        department=dept, position="操作工", education="本科", school="某大学", major="药学",
        phone="13800000000", hire_date=date(2026, 3, 15), status="在职",
    )
    db_session.add(emp)
    await db_session.flush()

    res = await client.get("/api/v1/hr/onboarding-records/export", params={"department": dept, "year": 2026})
    assert res.status_code == 200, res.text
    assert "spreadsheetml" in res.headers["content-type"]
    assert "入职台账" in unquote(res.headers.get("content-disposition", ""))

    header, body = _read_xlsx(res.content)
    assert "入职日期" in header and "来源" in header
    hit = [r for r in body if r["姓名"] == emp.name]
    assert len(hit) == 1 and hit[0]["入职日期"] == "2026-03-15"


# ─── 离职台账 ───


async def test_export_departure_records(db_session: AsyncSession, client: AsyncClient):
    dept = _rand("导出离职部")
    rec = DepartureRecord(
        id=uuid4(), name=_rand("离职导出"), employee_number=f"DP{uuid4().hex[:6]}",
        department=dept, position="操作工",
        offboarding_date=date(2026, 5, 20), offboarding_type="辞职",
        id_card="350102199001011234",
    )
    db_session.add(rec)
    await db_session.flush()

    res = await client.get("/api/v1/hr/departure-records/export", params={"department": dept})
    assert res.status_code == 200, res.text
    assert "离职台账" in unquote(res.headers.get("content-disposition", ""))

    header, body = _read_xlsx(res.content)
    hit = [r for r in body if r["姓名"] == rec.name]
    assert len(hit) == 1
    # 身份证全脱敏（与员工档案导出一致）
    assert hit[0]["身份证号"] == "*" * 18
    assert hit[0]["离职类型"] == "辞职"


# ─── 事故台账 ───


async def test_export_incidents(db_session: AsyncSession, client: AsyncClient):
    dept = _rand("导出事故事")
    rec = HrIncidentRecord(
        id=uuid4(), incident_type="work_injury", employee_name=_rand("事故事"),
        department=dept, occurred_date="2026-07-01", description="测试工伤记录", status="processing",
    )
    db_session.add(rec)
    await db_session.flush()

    res = await client.get("/api/v1/hr/incidents/export", params={"incident_type": "work_injury"})
    assert res.status_code == 200, res.text
    assert "事故台账" in unquote(res.headers.get("content-disposition", ""))

    header, body = _read_xlsx(res.content)
    hit = [r for r in body if r["当事人"] == rec.employee_name]
    assert len(hit) == 1
    # 枚举值导出为中文
    assert hit[0]["类型"] == "工伤" and hit[0]["状态"] == "处理中"


# ─── 编制对账 ───


async def test_export_headcount_plans(db_session: AsyncSession, client: AsyncClient):
    dept = _rand("导出编制部")
    plan = HeadcountPlan(
        id=uuid4(), department=dept, department_quota=10,
        position_detail="操作工×8; 班长×2",
    )
    emp = Employee(
        id=uuid4(), name=_rand("编制导出"), employee_number=f"HC{uuid4().hex[:6]}",
        department=dept, position="操作工", status="在职", hire_date=date(2026, 1, 1),
    )
    db_session.add_all([plan, emp])
    await db_session.flush()

    res = await client.get("/api/v1/hr/headcount/plans/export", params={"keyword": dept})
    assert res.status_code == 200, res.text
    assert "编制对账" in unquote(res.headers.get("content-disposition", ""))

    header, body = _read_xlsx(res.content)
    assert "定编人数" in header and "缺口" in header
    assert len(body) == 2  # 数据行 + 合计行
    assert body[0]["部门"] == dept and body[0]["实际在编"] == "1"
    assert body[1]["部门"] == "合计"
    assert body[1]["定编人数"] == "10" and body[1]["实际在编"] == "1" and body[1]["缺口"] == "9"
