"""培训台账 — 业务规则测试。

覆盖培训台账的 CRUD、去重逻辑、通知来源创建等核心规则。
走 service 层（真实 DB 回滚）。
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.hr.schemas import TrainingLedgerCreate, TrainingLedgerUpdate
from app.modules.hr.service import TrainingLedgerService

from tests.modules.hr.conftest import _rand


# ── 辅助函数 ──

async def _make_training_ledger(
    db: AsyncSession,
    *,
    employee_number: str | None = None,
    training_date: date | None = None,
    training_subject: str = "安全生产培训",
) -> object:
    """经 service 创建一个培训台账记录并返回。"""
    svc = TrainingLedgerService(db)
    data = TrainingLedgerCreate(
        employee_number=employee_number or _rand("TL"),
        training_date=training_date or date.today(),
        training_subject=training_subject,
    )
    return await svc.create_record(data)


# ═══════════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_training_ledger(db_session: AsyncSession):
    """正常创建培训台账记录，默认来源为 manual。"""
    record = await _make_training_ledger(db_session, training_subject="GMP培训")
    assert record.id is not None
    assert record.training_subject == "GMP培训"
    assert record.source_type == "manual"


@pytest.mark.asyncio
async def test_create_training_ledger_deduplication(db_session: AsyncSession):
    """同员工+同日期+同主题重复创建应返回已有记录（去重）。"""
    emp_no = _rand("DEDUP")
    train_date = date.today()
    subject = "重复培训主题"

    first = await _make_training_ledger(
        db_session, employee_number=emp_no, training_date=train_date, training_subject=subject
    )
    second = await _make_training_ledger(
        db_session, employee_number=emp_no, training_date=train_date, training_subject=subject
    )
    # 去重：第二次创建应返回同一条记录
    assert second.id == first.id


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_training_ledger(db_session: AsyncSession):
    """按 ID 查询培训台账记录。"""
    record = await _make_training_ledger(db_session)
    svc = TrainingLedgerService(db_session)
    found = await svc.get_record(record.id)
    assert found.id == record.id
    assert found.training_subject == record.training_subject


@pytest.mark.asyncio
async def test_get_training_ledger_not_found_raises(db_session: AsyncSession):
    """查询不存在的培训台账记录应抛 NotFoundException。"""
    svc = TrainingLedgerService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_record(uuid.uuid4())


@pytest.mark.asyncio
async def test_list_training_ledgers_by_employee(db_session: AsyncSession):
    """按工号过滤培训台账列表。"""
    emp_no = _rand("FILTER")
    svc = TrainingLedgerService(db_session)
    record = await _make_training_ledger(db_session, employee_number=emp_no)

    records, total = await svc.list_records(employee_number=emp_no)
    assert total >= 1
    ids = [r.id for r in records]
    assert record.id in ids


@pytest.mark.asyncio
async def test_list_training_ledgers_by_date_range(db_session: AsyncSession):
    """按日期范围过滤培训台账，返回结果数应大于0。"""
    svc = TrainingLedgerService(db_session)
    today = date.today()
    await _make_training_ledger(db_session, training_date=today)

    records, total = await svc.list_records(date_from=today, date_to=today)
    assert total >= 1


# ═══════════════════════════════════════════════════════════════
# 更新
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_training_ledger(db_session: AsyncSession):
    """正常更新培训台账的考核结果。"""
    record = await _make_training_ledger(db_session)
    svc = TrainingLedgerService(db_session)
    data = TrainingLedgerUpdate(assessment_result="合格")
    updated = await svc.update_record(record.id, data)
    assert updated.assessment_result == "合格"


@pytest.mark.asyncio
async def test_update_nonexistent_training_ledger_raises(db_session: AsyncSession):
    """更新不存在的培训台账应抛 NotFoundException。"""
    svc = TrainingLedgerService(db_session)
    with pytest.raises(NotFoundException):
        await svc.update_record(uuid.uuid4(), TrainingLedgerUpdate(assessment_result="不存在"))


# ═══════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_training_ledger(db_session: AsyncSession):
    """删除后查询应抛 NotFoundException。"""
    record = await _make_training_ledger(db_session)
    svc = TrainingLedgerService(db_session)
    await svc.delete_record(record.id)
    with pytest.raises(NotFoundException):
        await svc.get_record(record.id)


# ═══════════════════════════════════════════════════════════════
# 通知来源创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_from_notification(db_session: AsyncSession):
    """通过培训通知来源创建台账记录。"""
    svc = TrainingLedgerService(db_session)
    emp_no = _rand("NOTIFY")
    today = date.today()

    record = await svc.create_from_notification(
        employee_number=emp_no,
        training_date=today,
        training_subject="通知培训",
        training_method="线上",
        trainer="张讲师",
    )
    assert record is not None
    assert record.employee_number == emp_no
    assert record.source_type == "notification"


@pytest.mark.asyncio
async def test_create_from_notification_deduplication(db_session: AsyncSession):
    """同 source_id 的通知重复创建应返回已有记录。"""
    svc = TrainingLedgerService(db_session)
    emp_no = _rand("NDEDUP")
    today = date.today()
    source_id = _rand("SRC")

    first = await svc.create_from_notification(
        employee_number=emp_no,
        training_date=today,
        training_subject="通知培训2",
        training_method="线下",
        trainer="李讲师",
        source_id=source_id,
    )
    second = await svc.create_from_notification(
        employee_number=emp_no,
        training_date=today,
        training_subject="通知培训2",
        training_method="线下",
        trainer="李讲师",
        source_id=source_id,
    )
    assert second is not None
    assert second.id == first.id


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_training_ledgers(client):
    """GET /api/v1/hr/training-ledgers 返回 200。"""
    resp = await client.get("/api/v1/hr/training-ledgers")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_create_and_get_training_ledger(client):
    """POST 创建培训台账→GET 详情验证。"""
    emp_no = _rand("API")
    resp = await client.post("/api/v1/hr/training-ledgers", json={
        "employee_number": emp_no,
        "training_date": str(date.today()),
        "training_subject": "API培训主题",
    })
    assert resp.status_code == 201
    record_id = resp.json()["data"]["id"]

    resp2 = await client.get(f"/api/v1/hr/training-ledgers/{record_id}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["training_subject"] == "API培训主题"


@pytest.mark.asyncio
async def test_api_delete_training_ledger(client):
    """DELETE 培训台账后 GET 返回 404。"""
    emp_no = _rand("DEL")
    resp = await client.post("/api/v1/hr/training-ledgers", json={
        "employee_number": emp_no,
        "training_date": str(date.today()),
        "training_subject": "待删培训",
    })
    record_id = resp.json()["data"]["id"]

    await client.delete(f"/api/v1/hr/training-ledgers/{record_id}")
    resp2 = await client.get(f"/api/v1/hr/training-ledgers/{record_id}")
    assert resp2.status_code == 404
