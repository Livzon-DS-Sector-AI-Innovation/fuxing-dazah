"""数据管理「测试数据分类」接口测试。"""

import uuid
from datetime import date

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr import models as hr_models


def _rand() -> str:
    return uuid.uuid4().hex[:8].upper()


class TestTestDataCategory:
    async def test_list_and_clear(self, client: AsyncClient, db_session: AsyncSession):
        """测试数据分类：汇总计数 + 一键清空（硬删，清空后归零）。"""
        db_session.add(hr_models.Employee(
            name="员工甲", employee_number=f"SOP{_rand()}", department="甲部门",
            position="测试岗", status="在职", hire_date=date(2026, 1, 1),
        ))
        await db_session.flush()

        r = await client.get("/api/v1/hr/data-management/test-data")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] >= 1
        emp_row = next(t for t in data["tables"] if t["table"] == "employees")
        assert emp_row["count"] >= 1

        r = await client.post("/api/v1/hr/data-management/clear-test-data")
        assert r.status_code == 200

        r = await client.get("/api/v1/hr/data-management/test-data")
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 0
