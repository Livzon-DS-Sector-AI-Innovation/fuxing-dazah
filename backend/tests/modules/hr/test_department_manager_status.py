"""部门负责人 / 分管领导的账号就绪状态：部门管理列表上标出谁收不到提醒和审批。

状态判断口径要与发提醒时的姓名解析（title_review.notify._lookup_open_id）一致，
否则列表显示「就绪」却发不出去。人员姓名用随机后缀保证不与共享库里的真人重名。
"""

from datetime import date
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr import department_manager_status as ms
from app.modules.hr.models import DepartureRecord, Employee, HrDepartment
from app.platform.identity.models import User

API = "/api/v1/hr"


def _names(prefixes: tuple[str, ...]) -> tuple[str, ...]:
    """每个前缀拼一段随机十六进制：既唯一又是合法姓名，且同组之间互不相同。"""
    return tuple(f"{prefix}{uuid4().hex[:8]}" for prefix in prefixes)


async def _employee(db: AsyncSession, name: str, *, status: str = "在职") -> Employee:
    employee = Employee(
        employee_number=str(9100000 + uuid4().int % 899999), name=name,
        department="账号就绪测试部", position="专员", status=status, hire_date=date.today(),
    )
    db.add(employee)
    await db.flush()
    return employee


def _user(name: str, open_id: str | None = None) -> User:
    return User(name=name, employee_no=f"T-{uuid4().hex[:12]}", feishu_open_id=open_id)


@pytest.mark.asyncio
async def test_account_statuses_match_lookup_rules(db_session: AsyncSession):
    """就绪 / 未登录 / 同名多账号 / 已离职（不在员工档案、在离职台账）四种状态。"""
    ok, no_account, ambiguous, left = _names(("就绪", "未登", "同名", "离职"))
    db_session.add_all([
        _user(ok, "ou_ok"),
        _user(ambiguous, "ou_dup_1"),
        _user(ambiguous, "ou_dup_2"),
        _user(left, "ou_left"),
    ])
    await _employee(db_session, ok)
    await _employee(db_session, no_account)  # 有档案、没登录过
    await _employee(db_session, ambiguous)
    # 已离职的人通常已被同步移出员工档案，离职事实只在离职台账里
    db_session.add(DepartureRecord(
        name=left, department="账号就绪测试部", position="专员",
        employee_number=str(9500000 + uuid4().int % 499999),
        offboarding_type="个人原因", offboarding_date=date.today(),
    ))
    await db_session.flush()

    statuses = await ms.account_statuses(
        db_session, [ok, no_account, ambiguous, left, "", None],
    )

    assert statuses == {
        ok: ms.STATUS_OK,
        no_account: ms.STATUS_NO_ACCOUNT,
        ambiguous: ms.STATUS_AMBIGUOUS,
        left: ms.STATUS_LEFT,
    }


@pytest.mark.asyncio
async def test_account_statuses_fallback_and_left_on_record(db_session: AsyncSession):
    """员工档案自带的飞书 ID 可兜底解析；档案里是离职状态也算已离职；空入参返回空。"""
    fallback, left_on_record = _names(("兜底", "档离"))
    emp = await _employee(db_session, fallback)
    emp.feishu_open_id = "ou_from_employee"  # 没登录过，但员工档案里有飞书 ID
    await _employee(db_session, left_on_record, status="离职")
    db_session.add(_user(left_on_record, "ou_left_record"))
    await db_session.flush()

    assert await ms.account_statuses(db_session, [fallback]) == {fallback: ms.STATUS_OK}
    assert await ms.account_statuses(db_session, [left_on_record]) == {
        left_on_record: ms.STATUS_LEFT,
    }
    assert await ms.account_statuses(db_session, []) == {}
    assert await ms.account_statuses(db_session, ["", None]) == {}


@pytest.mark.asyncio
async def test_department_list_carries_account_status(
    db_session: AsyncSession, client: AsyncClient,
):
    """列表接口随行下发负责人 / 分管领导的账号状态，没填的为空串。"""
    ready, missing = _names(("就绪", "未登"))
    dept_name = f"账号就绪测试{uuid4().hex[:6]}"
    db_session.add(_user(ready, "ou_ready"))
    await _employee(db_session, missing)
    db_session.add_all([
        HrDepartment(
            name=dept_name, code=f"DP{uuid4().hex[:8].upper()}",
            department_manager_name=missing, supervising_leader_name=ready,
        ),
        HrDepartment(name=f"{dept_name}乙", code=f"DP{uuid4().hex[:8].upper()}"),
    ])
    await db_session.flush()

    res = await client.get(f"{API}/departments", params={"keyword": dept_name})

    assert res.status_code == 200, res.text
    rows = {row["name"]: row for row in res.json()["data"]}
    assert len(rows) == 2
    assert rows[dept_name]["manager_account_status"] == ms.STATUS_NO_ACCOUNT
    assert rows[dept_name]["leader_account_status"] == ms.STATUS_OK
    assert rows[f"{dept_name}乙"]["manager_account_status"] == ""
    assert rows[f"{dept_name}乙"]["leader_account_status"] == ""
