"""劳动合同签订次序推算：录入缺省按入职日期 + 期限规则推算，可人工指定覆盖。

需求规则：第 1 次 3 年、第 2 次 6 年（累计满 9 年）、第 3 次起无固定期限。
锚点 = 本次合同起始日（首份起始日即入职日）。
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.core.exceptions import AppException, DuplicateException
from app.modules.hr.labor_contract import service
from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.models import Employee

API = "/api/v1/hr"


def _number() -> str:
    return str(100000 + uuid4().int % 899999)


async def _employee(db, *, hire_date: date) -> Employee:
    employee = Employee(
        employee_number=_number(), name=f"推{uuid4().hex[:4]}",
        department="人力资源部", position="专员", status="在职", hire_date=hire_date,
    )
    db.add(employee)
    await db.flush()
    return employee


# ─── 纯函数：推算边界 ───


def test_infer_seq_from_hire_boundaries():
    hire = date(2017, 1, 1)
    # 入职日期缺失 / 明显占位年份 / 晚于合同起始日 → 兜底 1
    assert service.infer_seq_from_hire(None, date(2026, 1, 1)) == 1
    assert service.infer_seq_from_hire(date(1900, 1, 1), date(2026, 1, 1)) == 1
    assert service.infer_seq_from_hire(date(2030, 1, 1), date(2026, 1, 1)) == 1
    # 不足 3 年 → 1；满 3 年 → 2；满 3 年不足 9 年 → 2；满 9 年 → 3
    assert service.infer_seq_from_hire(hire, date(2019, 12, 31)) == 1
    assert service.infer_seq_from_hire(hire, date(2020, 1, 1)) == 2
    assert service.infer_seq_from_hire(hire, date(2025, 12, 31)) == 2
    assert service.infer_seq_from_hire(hire, date(2026, 1, 1)) == 3
    assert service.infer_seq_from_hire(hire, date(2040, 1, 1)) == 3


def test_infer_seq_from_hire_leap_day_hire():
    """2/29 入职：满 3/9 年平移到 2/28 判界（与 compute_end_date 同口径）。"""
    hire = date(2020, 2, 29)
    assert service.infer_seq_from_hire(hire, date(2023, 2, 27)) == 1
    assert service.infer_seq_from_hire(hire, date(2023, 2, 28)) == 2
    assert service.infer_seq_from_hire(hire, date(2029, 2, 27)) == 2
    assert service.infer_seq_from_hire(hire, date(2029, 2, 28)) == 3


# ─── 录入缺省推算 ───


@pytest.mark.asyncio
async def test_create_infers_seq_by_hire_date(db_session):
    # 入职满 9 年、无历史合同行：缺省推第 3 份，无固定期限、不设到期日
    hire = date.today() - timedelta(days=365 * 9 + 40)
    employee = await _employee(db_session, hire_date=hire)
    contract = await service.create_contract(
        db_session, employee_number=employee.employee_number,
        start_date=date.today(), sign_date=None, remark=None,
    )
    assert contract.seq_no == 3
    assert contract.term_type == LaborContract.TERM_OPEN
    assert contract.end_date is None
    assert contract.seq_label == "第 3 次（无固定期限）"

    # 入职不足 3 年：第 1 份 · 3 年
    new_hire = date.today() - timedelta(days=365)
    newbie = await _employee(db_session, hire_date=new_hire)
    contract = await service.create_contract(
        db_session, employee_number=newbie.employee_number,
        start_date=date.today(), sign_date=None, remark=None,
    )
    assert contract.seq_no == 1
    assert contract.term_type == LaborContract.TERM_FIXED_3Y
    assert contract.end_date == service.compute_end_date(date.today(), contract.term_type, 3)

    # 入职满 3 年不足 9 年：第 2 份 · 6 年
    mid_hire = date.today() - timedelta(days=365 * 5)
    mid = await _employee(db_session, hire_date=mid_hire)
    contract = await service.create_contract(
        db_session, employee_number=mid.employee_number,
        start_date=date.today(), sign_date=None, remark=None,
    )
    assert contract.seq_no == 2
    assert contract.term_type == LaborContract.TERM_FIXED_6Y


@pytest.mark.asyncio
async def test_create_inference_not_rewound_by_existing_rows(db_session):
    """已有历史合同行时，缺省 = max(已有份数 + 1, 入职推算)——老员工只迁了
    第 1 份、再录现合同不会被错写成第 2 份 6 年。"""
    hire = date.today() - timedelta(days=365 * 10)
    employee = await _employee(db_session, hire_date=hire)
    db_session.add(LaborContract(
        employee_number=employee.employee_number, name=employee.name,
        department=employee.department, position=employee.position,
        seq_no=1, term_type=LaborContract.TERM_FIXED_3Y, term_years=3,
        start_date=hire, end_date=hire.replace(year=hire.year + 3),
        status=LaborContract.STATUS_ACTIVE,
    ))
    await db_session.flush()
    contract = await service.create_contract(
        db_session, employee_number=employee.employee_number,
        start_date=date.today(), sign_date=None, remark=None,
    )
    assert contract.seq_no == 3
    assert contract.term_type == LaborContract.TERM_OPEN

    # 入职不足 3 年且已有第 1 份：按已有份数 + 1 继续（续签语义不被推算回退）
    new_hire = date.today() - timedelta(days=365)
    newbie = await _employee(db_session, hire_date=new_hire)
    db_session.add(LaborContract(
        employee_number=newbie.employee_number, name=newbie.name,
        department=newbie.department, position=newbie.position,
        seq_no=1, term_type=LaborContract.TERM_FIXED_3Y, term_years=3,
        start_date=new_hire, end_date=new_hire.replace(year=new_hire.year + 3),
        status=LaborContract.STATUS_ACTIVE,
    ))
    await db_session.flush()
    contract = await service.create_contract(
        db_session, employee_number=newbie.employee_number,
        start_date=date.today() + timedelta(days=30), sign_date=None, remark=None,
    )
    assert contract.seq_no == 2
    assert contract.term_type == LaborContract.TERM_FIXED_6Y


# ─── 人工指定覆盖 ───


@pytest.mark.asyncio
async def test_create_explicit_seq_overrides_inference(db_session):
    """非标准履历（如转签重签）可人工指定签订次序，指定值优先于推算。"""
    hire = date.today() - timedelta(days=365 * 10)
    employee = await _employee(db_session, hire_date=hire)
    contract = await service.create_contract(
        db_session, employee_number=employee.employee_number,
        start_date=date.today(), sign_date=None, remark=None, seq_no=1,
    )
    assert contract.seq_no == 1
    assert contract.term_type == LaborContract.TERM_FIXED_3Y


@pytest.mark.asyncio
async def test_create_rejects_invalid_and_duplicate_seq(db_session):
    hire = date.today() - timedelta(days=365 * 10)
    employee = await _employee(db_session, hire_date=hire)
    with pytest.raises(AppException, match="签订次序必须为正整数"):
        await service.create_contract(
            db_session, employee_number=employee.employee_number,
            start_date=date.today(), sign_date=None, remark=None, seq_no=0,
        )
    first = await service.create_contract(
        db_session, employee_number=employee.employee_number,
        start_date=date.today(), sign_date=None, remark=None, seq_no=1,
    )
    assert first.seq_no == 1
    # 同一工号同一签订次数的有效合同不可重复录入（缺省推算到 3 不冲突，指定 1 冲突）
    with pytest.raises(DuplicateException):
        await service.create_contract(
            db_session, employee_number=employee.employee_number,
            start_date=date.today() + timedelta(days=10), sign_date=None,
            remark=None, seq_no=1,
        )


# ─── API：预推与录入 ───


@pytest.mark.asyncio
async def test_entry_preview_and_create_api(client, db_session):
    hire = date.today() - timedelta(days=365 * 9 + 40)
    employee = await _employee(db_session, hire_date=hire)
    res = await client.get(
        f"{API}/labor-contracts/entry-preview",
        params={"employee_number": employee.employee_number, "start_date": date.today().isoformat()},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["seq_no"] == 3
    assert data["seq_label"] == "第 3 次 · 无固定期限"
    assert data["term_type"] == LaborContract.TERM_OPEN
    assert data["end_date"] is None
    assert data["years_employed"] is not None and data["years_employed"] >= 9

    # 缺省录入：与预推一致（推算为第 3 份）
    res = await client.post(f"{API}/labor-contracts", json={
        "employee_number": employee.employee_number,
        "start_date": date.today().isoformat(),
    })
    assert res.status_code == 200
    created = res.json()["data"]
    assert created["seq_no"] == 3
    assert created["term_type"] == LaborContract.TERM_OPEN

    # 指定签订次序：覆盖推算
    other = await _employee(db_session, hire_date=hire)
    res = await client.post(f"{API}/labor-contracts", json={
        "employee_number": other.employee_number,
        "start_date": date.today().isoformat(),
        "seq_no": 2,
    })
    assert res.status_code == 200
    assert res.json()["data"]["seq_no"] == 2
    assert res.json()["data"]["term_type"] == LaborContract.TERM_FIXED_6Y

    # 非法次序被 422 拦截
    res = await client.post(f"{API}/labor-contracts", json={
        "employee_number": other.employee_number,
        "start_date": date.today().isoformat(),
        "seq_no": 0,
    })
    assert res.status_code == 422
