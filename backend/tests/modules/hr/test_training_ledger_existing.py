"""「添加到培训台账」事前查重端点（GET /training-ledgers/check-existing）。

前端在批量创建前先调查重接口，把当天已有同主题记录的人排除在外；
本文件锁定查重口径（同工号 + 同培训日期 + 同培训主题，未删除）与数据范围收敛。
"""

import json
import re
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.api import check_existing_training_ledgers
from app.modules.hr.deps import HrAccessContext, _resource_for_path

_TAG = uuid4().hex[:8].upper()


async def _add_ledger(
    db_session: AsyncSession,
    employee_number: str,
    *,
    training_date: date,
    training_subject: str,
    is_deleted: bool = False,
) -> None:
    from app.modules.hr.models import TrainingLedger

    db_session.add(TrainingLedger(
        employee_number=employee_number,
        training_date=training_date,
        training_subject=training_subject,
        source_type="manual",
        is_deleted=is_deleted,
    ))
    await db_session.flush()


@pytest.mark.asyncio
async def test_check_existing_returns_only_employees_with_same_date_and_subject(db_session, client):
    """只返回「同工号 + 同日期 + 同主题」已存在的工号；不存在的、不同日期的都不算。"""
    tag = uuid4().hex[:6].upper()
    existed, other_date, missing = f"CK{tag}A", f"CK{tag}B", f"CK{tag}C"
    day, subject = date(2026, 11, 24), f"查重测试主题{tag}"
    await _add_ledger(db_session, existed, training_date=day, training_subject=subject)
    await _add_ledger(db_session, other_date, training_date=date(2026, 11, 25), training_subject=subject)

    res = await client.get("/api/v1/hr/training-ledgers/check-existing", params={
        "training_date": day.isoformat(),
        "training_subject": subject,
        # 逗号分隔，容忍空白与空段
        "employee_numbers": f" {existed} , {other_date},,{missing} ",
    })
    assert res.status_code == 200, res.text
    assert res.json()["data"]["employee_numbers"] == [existed]


@pytest.mark.asyncio
async def test_check_existing_requires_exact_subject(db_session, client):
    """培训主题不同不算已存在（避免把同一天的另一场培训误判为重复）。"""
    tag = uuid4().hex[:6].upper()
    number = f"CK{tag}D"
    day = date(2026, 11, 24)
    await _add_ledger(db_session, number, training_date=day, training_subject=f"主题{tag}")

    res = await client.get("/api/v1/hr/training-ledgers/check-existing", params={
        "training_date": day.isoformat(),
        "training_subject": f"主题{tag}（复训）",
        "employee_numbers": number,
    })
    assert res.status_code == 200, res.text
    assert res.json()["data"]["employee_numbers"] == []


@pytest.mark.asyncio
async def test_check_existing_ignores_soft_deleted(db_session, client):
    """已软删除的记录不算已存在（删掉重录是允许的）。"""
    tag = uuid4().hex[:6].upper()
    number = f"CK{tag}E"
    day, subject = date(2026, 11, 24), f"查重软删{tag}"
    await _add_ledger(db_session, number, training_date=day, training_subject=subject, is_deleted=True)

    res = await client.get("/api/v1/hr/training-ledgers/check-existing", params={
        "training_date": day.isoformat(),
        "training_subject": subject,
        "employee_numbers": number,
    })
    assert res.status_code == 200, res.text
    assert res.json()["data"]["employee_numbers"] == []


@pytest.mark.asyncio
async def test_check_existing_with_blank_employee_numbers_returns_empty(client):
    """工号列表为空（或只有空白/逗号）时返回空集，不报错。"""
    res = await client.get("/api/v1/hr/training-ledgers/check-existing", params={
        "training_date": date(2026, 11, 24).isoformat(),
        "training_subject": f"查重空入参{_TAG}",
        "employee_numbers": " , ,",
    })
    assert res.status_code == 200, res.text
    assert res.json()["data"]["employee_numbers"] == []


@pytest.mark.asyncio
async def test_check_existing_hidden_for_out_of_scope_employees(db_session):
    """数据范围受限：授权部门之外的工号不返回（与创建接口同口径，不泄露他部门台账）。"""
    from app.modules.hr.models import TrainingRosterProfile

    tag = uuid4().hex[:6].upper()
    inside, outside = f"CK{tag}F", f"CK{tag}G"
    day, subject = date(2026, 11, 24), f"查重范围{tag}"
    db_session.add_all([
        TrainingRosterProfile(
            employee_number=inside, name="范围内", department=f"查重甲部门{tag}",
            position="操作工", status="在职",
        ),
        TrainingRosterProfile(
            employee_number=outside, name="范围外", department=f"查重乙部门{tag}",
            position="操作工", status="在职",
        ),
    ])
    await _add_ledger(db_session, inside, training_date=day, training_subject=subject)
    await _add_ledger(db_session, outside, training_date=day, training_subject=subject)
    await db_session.flush()

    class _User:
        name = "测试员"
        employee_no = "TEST001"

    hr_scope = HrAccessContext(
        user=_User(),  # type: ignore[arg-type]
        data_scope="department",
        department=f"查重甲部门{tag}",
        employee_number="TEST001",
        scoped_departments=frozenset({f"查重甲部门{tag}"}),
    )
    res = await check_existing_training_ledgers(
        training_date=day,
        training_subject=subject,
        employee_numbers=f"{inside},{outside}",
        session=db_session,
        hr_scope=hr_scope,
    )
    assert json.loads(res.body)["data"]["employee_numbers"] == [inside]


def test_check_existing_maps_to_training_read_permission():
    """路径登记：GET 走培训读权限（与台账列表同级），数据范围按 training 资源计算。"""
    from app.modules.hr.deps import _HR_PATH_PERMISSIONS

    path = "/api/v1/hr/training-ledgers/check-existing"
    matched = next(val for pat, val in _HR_PATH_PERMISSIONS if re.search(pat, path))
    assert matched.get("GET") == "hr:training:read"
    assert _resource_for_path(path, "GET") == "training"
