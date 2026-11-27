"""劳动合同流程增强：审批独立权限 / 续签守卫 / 转入离职办理 / 通知留痕与重发 /
状态驱动的进度步骤 / 办理中不进预警 / 「待我处理」口径 / 归档换传原因与学历 /
协商解除 / 线上签字链路下线。

系统只部署在公司内网，员工在手机上打不开指向本系统的链接：劳动合同没有「线上签字」这一环，
员工到人事办公室领取合同原件即完成签收（HR 登记领取）。签发 token、免登签字接口、签字提醒
等已删除的能力，本文件按「该行为已不存在」断言（服务函数 / 模型列不存在、旧接口 404）。

测试跑在共享本地库的事务里（HR conftest 把 commit 换成 flush，结束统一回滚）。
本地后端连的是真实飞书：本文件一律打桩发送层，autouse 夹具把 notify.send_user_card
换成一被调用就报错的桩——任何漏打桩的发送路径都会让用例失败，而不是把卡片发给真人。
扫描件落到本地对象存储的文件不随事务回滚，相关用例在 finally 里物理清理。
"""

import io
import re
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.core.exceptions import AppException
from app.core.file_storage import store_object
from app.modules.hr.labor_contract import (
    archive_batch_import,
    archive_service,
    departure_ledger,
    departure_service,
    dept_notice,
    notify,
    renewal_approval,
    scheduled,
    service,
)
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract import settings as contract_settings
from app.modules.hr.labor_contract.models import ContractNoticeLog, LaborContract
from app.modules.hr.models import DepartureRecord, Employee, SystemSetting
from app.modules.hr.offboarding.models import OffboardingCase
from tests.modules.hr.test_labor_contract_archive import _cleanup

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
API = "/api/v1/hr"
TODAY = date.today()

DECIDED = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
STAMPED = datetime(2027, 1, 5, 8, 0, tzinfo=UTC)
DELIVERED = datetime(2027, 1, 6, 9, 30, tzinfo=UTC)
ARCHIVED = datetime(2027, 1, 7, 11, 0, tzinfo=UTC)

OPERATOR = "HR测试员"  # HR conftest 的 test_user.name


@pytest.fixture(autouse=True)
def _no_real_send(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _must_not_send(*args, **kwargs):
        raise AssertionError("用例触达了真实飞书发送层：请打桩 notify._send / dept_notice._send")

    monkeypatch.setattr(notify, "send_user_card", _must_not_send)


# ─── 夹具 ───


def _number() -> str:
    return str(200000 + uuid4().int % 699999)


async def _employee(
    db, *, department: str | None = None, education: str | None = None,
    open_id: str | None = None, status: str = "在职",
) -> Employee:
    employee = Employee(
        employee_number=_number(), name=f"流{uuid4().hex[:4]}",
        department=department or f"合同流程{uuid4().hex[:6]}", position="专员",
        status=status, hire_date=TODAY, education=education, feishu_open_id=open_id,
    )
    db.add(employee)
    await db.flush()
    return employee


async def _contract(
    db, employee: Employee, *, seq_no: int = 1, status: str = "active",
    end_date: date | None = None, origin: str | None = "manual",
    signed: bool = True, **overrides,
) -> LaborContract:
    """起始日 400 天前、3 年期的合同（signed=True 时签订日 = 起始日，同录入缺省）。"""
    start = TODAY - timedelta(days=400)
    values: dict = {
        "employee_number": employee.employee_number, "name": employee.name,
        "department": employee.department, "position": employee.position,
        "seq_no": seq_no, "term_type": LaborContract.TERM_FIXED_3Y, "term_years": 3,
        "start_date": start, "end_date": end_date or (start + timedelta(days=365 * 3)),
        "sign_date": start if signed else None, "status": status, "origin": origin,
    }
    values.update(overrides)
    contract = LaborContract(**values)
    db.add(contract)
    await db.flush()
    return contract


async def _departure(db, *, department: str, offboarding_type: str) -> DepartureRecord:
    departure = DepartureRecord(
        name=f"离{uuid4().hex[:4]}", employee_number=_number(), department=department,
        position="专员", offboarding_type=offboarding_type, offboarding_date=TODAY,
        contract_start_date=date(2026, 1, 1), contract_end_date=date(2029, 1, 1),
    )
    db.add(departure)
    await db.flush()
    return departure


class _Capture:
    """记录卡片发送调用；open_id 在 fail_for 里的返回失败（模拟飞书发送失败）。"""

    def __init__(self, *fail_for: str) -> None:
        self.calls: list[tuple[str, str, str, object]] = []
        self._fail_for = set(fail_for)

    async def __call__(self, open_id, title, markdown, elements=None) -> bool:
        self.calls.append((open_id, title, markdown, elements))
        return open_id not in self._fail_for


def _resolver(mapping: dict[str, tuple[str | None, str | None]]):
    """按部门名返回 (负责人姓名, open_id)；不在映射里的部门一律解析不到。"""
    async def resolve(db, contract: LaborContract):
        return mapping.get(contract.department, (None, None))
    return resolve


def _only_perms(monkeypatch: pytest.MonkeyPatch, *codes: str) -> None:
    """收窄成指定权限码（覆盖 HR conftest 的「全权限」放行）。"""
    async def _perms(user_id: str, db) -> set[str]:
        return set(codes)

    monkeypatch.setattr("app.platform.permission.deps.get_user_permissions", _perms)


async def _set_settings(db, **kv: str) -> None:
    """在测试事务内写系统配置（回滚后不影响库里的真实配置）。"""
    for key, value in kv.items():
        row = (await db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )).scalars().first()
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    await db.flush()


async def _notices(db, contract_id: UUID) -> list[tuple[str, str, str | None, str | None]]:
    """某合同的通知留痕 (kind, status, 收件人姓名, 原因)，新→旧。"""
    return [
        (n.kind, n.status, n.recipient_name, n.error_message)
        for n in await repo.list_notices(db, contract_id)
    ]


def _pure_contract(**overrides) -> LaborContract:
    """不落库的合同行（纯函数用）：第 2 份、2024-01-01 ~ 2027-01-01、签订日 = 起始日。"""
    values: dict = {
        "employee_number": "200001", "name": "张三", "department": "甲部门", "position": "专员",
        "seq_no": 2, "term_type": LaborContract.TERM_FIXED_3Y, "term_years": 3,
        "start_date": date(2024, 1, 1), "end_date": date(2027, 1, 1),
        "sign_date": date(2024, 1, 1), "status": "active",
        "archive_status": LaborContract.ARCHIVE_UNARCHIVED,
    }
    values.update(overrides)
    return LaborContract(**values)


def _notice(kind: str, status: str, at: datetime, error: str | None = None) -> ContractNoticeLog:
    return ContractNoticeLog(
        contract_id=uuid4(), kind=kind, status=status, created_at=at,
        recipient_name="张三", error_message=error,
    )


def _states(contract: LaborContract, notices=()) -> list[str]:
    return [step["state"] for step in service.build_progress(contract, notices)]


async def _numbers(client, params: dict) -> tuple[set[str], int]:
    res = await client.get(f"{API}/labor-contracts", params={**params, "page_size": 100})
    assert res.status_code == 200, res.text
    body = res.json()
    return {row["employee_number"] for row in body["data"]}, body["meta"]["total"]


# ═══════════════════════════════════════════════════════════════
# 1. 部门续签审批独立权限
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_approve_permission_covers_dept_decision_only(
    db_session, client, monkeypatch,
):
    """只拿 approve + read 的部门负责人：能登记同意/不同意并留下姓名；
    续签、盖章、终止、转入离职办理、重发通知等办理动作仍 403；只有 read 时连登记也 403。"""
    employee = await _employee(db_session)
    contract = await _contract(db_session, employee, status="pending_renewal")
    base = f"{API}/labor-contracts/{contract.id}"

    _only_perms(monkeypatch, "hr:contract:read")
    res = await client.post(f"{base}/dept-decision", json={"decision": "agree"})
    assert res.status_code == 403, res.text

    _only_perms(monkeypatch, "hr:contract:read", "hr:contract:approve")
    res = await client.post(f"{base}/dept-decision", json={"decision": "agree"})
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert (body["status"], body["dept_decision"]) == ("renewing", "agree")
    assert body["dept_decision_by"] == OPERATOR and body["dept_decision_at"] is not None
    assert (await client.get(base)).status_code == 200  # read 仍可看详情

    res = await client.post(f"{base}/dept-decision", json={"decision": "disagree"})
    assert res.status_code == 200, res.text  # 不同意也可登记
    next_start = (date.fromisoformat(body["end_date"]) + timedelta(days=1)).isoformat()
    for path, payload in (
        ("renew", {"start_date": next_start}),
        ("terminate", {"reason": "办理权限校验"}),
        ("transfer-offboarding", {}),
        ("resend-notice", {"kind": "renew"}),
    ):
        res = await client.post(f"{base}/{path}", json=payload)
        assert res.status_code == 403, (path, res.text)
    assert (await client.post(f"{base}/stamp")).status_code == 403
    assert (await client.post(f"{API}/labor-contracts", json={
        "employee_number": employee.employee_number, "start_date": TODAY.isoformat(),
    })).status_code == 403


# ═══════════════════════════════════════════════════════════════
# 2. 续签前必须有部门意见 / 各状态下登记意见 / 续签快照取现值
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_renew_requires_dept_agreement(db_session):
    """没登记部门意见、或登记的是不同意：都不能办理续签，合同保持原状。"""
    employee = await _employee(db_session)
    contract = await _contract(db_session, employee)
    assert contract.end_date is not None
    next_start = contract.end_date + timedelta(days=1)

    with pytest.raises(AppException, match="尚未登记部门续签意见"):
        await service.renew_contract(db_session, contract, start_date=next_start, sign_date=None)
    contract.dept_decision = LaborContract.DECISION_DISAGREE
    await db_session.flush()
    with pytest.raises(AppException, match="尚未登记部门续签意见"):
        await service.renew_contract(db_session, contract, start_date=next_start, sign_date=None)
    assert contract.status == LaborContract.STATUS_ACTIVE

    contract.dept_decision = LaborContract.DECISION_AGREE
    await db_session.flush()
    renewed = await service.renew_contract(db_session, contract, start_date=next_start, sign_date=None)
    assert renewed.seq_no == 2 and contract.status == LaborContract.STATUS_SUPERSEDED


@pytest.mark.asyncio
async def test_renew_snapshots_current_employee_profile(db_session):
    """员工异动后，续签生成的新合同取档案现值；取不到档案时回退沿用旧快照。"""
    employee = await _employee(db_session)
    stale = await _contract(db_session, employee)
    stale.name, stale.department, stale.position = "旧名", "旧部门", "旧岗位"
    stale.dept_decision = LaborContract.DECISION_AGREE
    await db_session.flush()
    assert stale.end_date is not None

    renewed = await service.renew_contract(
        db_session, stale, start_date=stale.end_date + timedelta(days=1), sign_date=None,
    )
    assert (renewed.name, renewed.department, renewed.position) == (
        employee.name, employee.department, employee.position,
    )
    assert renewed.origin == LaborContract.ORIGIN_RENEWAL

    orphan = LaborContract(
        employee_number=_number(), name="无档名", department="无档部门", position="无档岗位",
        seq_no=1, term_type=LaborContract.TERM_FIXED_3Y, term_years=3,
        start_date=date(2024, 1, 1), end_date=date(2027, 1, 1), sign_date=date(2024, 1, 1),
        dept_decision=LaborContract.DECISION_AGREE,
    )
    db_session.add(orphan)
    await db_session.flush()
    renewed = await service.renew_contract(
        db_session, orphan, start_date=date(2027, 1, 2), sign_date=None,
    )
    assert (renewed.name, renewed.department, renewed.position) == ("无档名", "无档部门", "无档岗位")


@pytest.mark.asyncio
async def test_origin_marks_how_the_row_was_created(db_session):
    """录入端点 = manual、续签 = renewal；Excel 导入路径未声明来源的行落 import。"""
    employee = await _employee(db_session)
    created = await service.create_contract(
        db_session, employee_number=employee.employee_number,
        start_date=TODAY, sign_date=None, remark=None,
    )
    assert created.origin == LaborContract.ORIGIN_MANUAL
    imported = LaborContract(
        employee_number=_number(), name="导入", department="导入部门", seq_no=1,
        term_type=LaborContract.TERM_FIXED_3Y, term_years=3,
        start_date=TODAY, end_date=TODAY + timedelta(days=365 * 3), sign_date=TODAY,
    )
    db_session.add(imported)
    await db_session.flush()
    assert imported.origin == LaborContract.ORIGIN_IMPORT
    assert LaborContract.ORIGIN_LABELS[LaborContract.ORIGIN_MIGRATION] == "存量迁移"


@pytest.mark.asyncio
async def test_dept_decision_allowed_on_every_open_status(db_session):
    """生效中 / 到期未续签 / 续签办理中 / 公告期 都能登记意见：同意 → 续签办理中；
    不同意 → 已终止（原因「部门不同意续签」，流程到此为止）。取代/已终止的不可再登记。"""
    agreeing: dict[str, LaborContract] = {}
    for status in ("active", "pending_renewal", "renewing", "expired_unrenewed"):
        contract = await _contract(db_session, await _employee(db_session), status=status)
        agreeing[status] = contract
        updated = await service.apply_dept_decision(
            db_session, contract, decision=LaborContract.DECISION_AGREE, decided_by="张管理",
        )
        assert updated.status == LaborContract.STATUS_RENEWING
        assert (updated.dept_decision, updated.dept_decision_by) == ("agree", "张管理")
    # 同意后尝试通知员工：员工没有飞书账号 → 跳过并留痕
    first = agreeing["active"]
    assert await _notices(db_session, first.id) == [
        ("renew", "skipped", first.name, "员工无飞书账号"),
    ]

    for status in ("active", "pending_renewal", "renewing", "expired_unrenewed"):
        contract = await _contract(db_session, await _employee(db_session), status=status)
        updated = await service.apply_dept_decision(
            db_session, contract, decision=LaborContract.DECISION_DISAGREE, decided_by="张管理",
        )
        assert updated.status == LaborContract.STATUS_TERMINATED
        assert updated.terminated_reason == "部门不同意续签" and updated.terminated_at is not None
        # 已终止的合同流程到此为止：通知续签 / 盖章 / 领取 / 归档都不再推进
        assert _states(updated) == ["done", "done"] + ["skipped"] * 4

    for status in ("superseded", "terminated"):
        contract = await _contract(db_session, await _employee(db_session), status=status)
        with pytest.raises(AppException):
            await service.apply_dept_decision(
                db_session, contract, decision=LaborContract.DECISION_AGREE, decided_by="张管理",
            )


# ═══════════════════════════════════════════════════════════════
# 3. 转入离职办理
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_transfer_offboarding_creates_case_and_terminates_contract(db_session, client):
    """按合同对应员工建离职办理单（类型「合同到期」）；合同置已终止并关联该办理单的离职记录。"""
    employee = await _employee(db_session)
    contract = await _contract(
        db_session, employee, status="expired_unrenewed", end_date=TODAY - timedelta(days=5),
    )

    res = await client.post(
        f"{API}/labor-contracts/{contract.id}/transfer-offboarding",
        json={"offboarding_date": "2027-01-15", "reason": "合同到期不续签"},
    )
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert set(data) == {"id", "case_no", "status", "status_label", "offboarding_date", "offboarding_type"}
    assert re.fullmatch(r"LB-\d{8}-\d{4}", data["case_no"])
    assert (data["status"], data["offboarding_date"], data["offboarding_type"]) == (
        "draft", "2027-01-15", "合同到期",
    )

    case = await db_session.get(OffboardingCase, UUID(data["id"]))
    assert case is not None
    assert case.employee_id == employee.id and case.employee_number == employee.employee_number
    assert case.reason == "合同到期不续签" and case.initiator_name == OPERATOR
    assert case.remark is not None and case.remark.startswith("由劳动合同管理转入")
    assert str(contract.start_date) in case.remark and str(contract.end_date) in case.remark

    contract = await repo.get(db_session, contract.id)
    assert contract is not None
    assert contract.status == LaborContract.STATUS_TERMINATED
    assert contract.terminated_reason == "合同到期未续签，转入离职办理" and contract.terminated_at is not None
    assert case.departure_record_id is not None
    assert contract.departure_record_id == case.departure_record_id

    # 离职办理一发起，合同即归入离职台账、退出在职台账
    total, rows = await repo.list_page(db_session, employee_number=employee.employee_number)
    assert (total, rows) == (0, [])


@pytest.mark.asyncio
async def test_transfer_offboarding_defaults_date_and_reason(db_session, client):
    """没给离职日期：到期日未过用到期日，已过期用今天；没给原因按部门意见自动生成。"""
    department = f"转入默认{uuid4().hex[:6]}"

    async def row(**overrides):
        return await _contract(db_session, await _employee(db_session, department=department), **overrides)

    future = await row(end_date=TODAY + timedelta(days=20))
    past = await row(status="expired_unrenewed", end_date=TODAY - timedelta(days=20))
    dated = await row(end_date=TODAY + timedelta(days=20))

    async def transfer(contract: LaborContract, payload: dict):
        res = await client.post(
            f"{API}/labor-contracts/{contract.id}/transfer-offboarding", json=payload,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        case = await db_session.get(OffboardingCase, UUID(data["id"]))
        assert case is not None
        return data["offboarding_date"], case.reason

    assert await transfer(future, {}) == ((TODAY + timedelta(days=20)).isoformat(), "劳动合同到期未续签")
    assert await transfer(past, {}) == (TODAY.isoformat(), "劳动合同到期未续签")
    assert await transfer(dated, {"offboarding_date": "2027-02-01", "reason": None}) == (
        "2027-02-01", "劳动合同到期未续签",
    )


@pytest.mark.asyncio
async def test_transfer_offboarding_keeps_existing_termination(db_session, client):
    """已因「部门不同意续签」终止的合同转入离职办理：只建单并关联，不改写原终止原因；原因按部门意见生成。"""
    employee = await _employee(db_session)
    contract = await _contract(
        db_session, employee, status="terminated", terminated_reason="部门不同意续签",
        dept_decision=LaborContract.DECISION_DISAGREE,
    )

    res = await client.post(f"{API}/labor-contracts/{contract.id}/transfer-offboarding", json={})
    assert res.status_code == 200, res.text
    case = await db_session.get(OffboardingCase, UUID(res.json()["data"]["id"]))
    assert case is not None
    assert case.reason == "劳动合同到期，部门不同意续签"
    assert contract.status == LaborContract.STATUS_TERMINATED
    assert contract.terminated_reason == "部门不同意续签"
    assert contract.departure_record_id == case.departure_record_id and case.departure_record_id is not None


@pytest.mark.asyncio
async def test_transfer_offboarding_passes_through_case_guard(db_session, client):
    """离职办理单自带的校验原样抛出：员工已离职 400；已有进行中办理单 409。"""
    left = await _contract(db_session, await _employee(db_session, status="离职"))
    res = await client.post(f"{API}/labor-contracts/{left.id}/transfer-offboarding", json={})
    assert res.status_code == 400 and "离职" in res.json()["message"]

    employee = await _employee(db_session)
    contract = await _contract(db_session, employee)
    payload = {"offboarding_date": (TODAY + timedelta(days=3)).isoformat()}
    res = await client.post(f"{API}/labor-contracts/{contract.id}/transfer-offboarding", json=payload)
    assert res.status_code == 200, res.text
    res = await client.post(f"{API}/labor-contracts/{contract.id}/transfer-offboarding", json=payload)
    assert res.status_code == 409, res.text


# ═══════════════════════════════════════════════════════════════
# 4. 通知留痕 + 重发 + 文案配置
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_employee_notices_are_logged_and_returned(db_session, client, test_user, monkeypatch):
    """每次发送写一行留痕；盖章响应带本次通知结果；领取只登记时间（不发通知、不带签字链接）；
    详情按时间倒序返回 notices 与 progress。员工只有续签 / 领取两张卡，都不带按钮、不含链接。"""
    employee = await _employee(db_session, open_id="ou_employee")
    contract = await _contract(db_session, employee, status="pending_renewal")
    # 打在飞书发送层（而不是 notify._send）：连「有没有传按钮」一起看
    sent: list[tuple[str, str, str, object]] = []

    async def _capture_card(open_id, *, title, content, elements=None, **_) -> bool:
        sent.append((open_id, title, content, elements))
        return True

    monkeypatch.setattr(notify, "send_user_card", _capture_card)
    base = f"{API}/labor-contracts/{contract.id}"

    assert (await client.post(f"{base}/dept-decision", json={"decision": "agree"})).status_code == 200
    res = await client.post(f"{base}/stamp")
    assert res.status_code == 200, res.text
    assert res.json()["data"]["notice"] == {"status": "sent", "error": None, "recipient_name": employee.name}
    res = await client.post(f"{base}/deliver")
    assert res.status_code == 200, res.text
    delivered = res.json()
    assert delivered["message"] == "已登记领取" and delivered["data"]["delivered_at"] is not None
    # 领取即签收：不再签发签字链接，也不发通知，响应里没有这两样
    assert "sign_url" not in delivered["data"] and "notice" not in delivered["data"]

    assert [(open_id, title, elements) for open_id, title, _, elements in sent] == [
        ("ou_employee", "劳动合同续签通知", None),
        ("ou_employee", "领取劳动合同原件通知", None),
    ]
    assert all("http" not in content for _, _, content, _ in sent)  # 正文里也没有链接

    rows = await repo.list_notices(db_session, contract.id)
    assert [(n.kind, n.status, n.recipient_open_id) for n in rows] == [
        ("collect", "sent", "ou_employee"),
        ("renew", "sent", "ou_employee"),
    ]
    assert all(n.created_by == test_user.id and n.created_by_name == OPERATOR for n in rows)

    res = await client.get(base)
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert (body["origin"], body["origin_label"]) == ("manual", "手工录入")
    assert "sign_confirmed_at" not in body
    assert body["notices"] == [
        {"kind": "collect", "recipient_name": employee.name, "status": "sent",
         "error_message": None, "created_at": rows[0].created_at.isoformat()},
        {"kind": "renew", "recipient_name": employee.name, "status": "sent",
         "error_message": None, "created_at": rows[1].created_at.isoformat()},
    ]
    stored = await repo.get(db_session, contract.id)
    assert stored is not None
    progress = body["progress"]
    # 已领取、未归档：归档是当前步（领取之后没有签字环节）
    assert [step["state"] for step in progress] == [
        "done", "done", "done", "done", "done", "current",
    ]
    assert progress[2]["at"] == rows[1].created_at.isoformat()  # 通知续签：以续签通知送达时间为准
    assert progress[4]["at"] == stored.delivered_at.isoformat()


@pytest.mark.asyncio
async def test_detail_notices_capped_at_latest_twenty(db_session, client):
    contract = await _contract(db_session, await _employee(db_session))
    for minute in range(25):
        db_session.add(ContractNoticeLog(
            contract_id=contract.id, kind="renew", status="sent",
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute),
        ))
    await db_session.flush()

    body = (await client.get(f"{API}/labor-contracts/{contract.id}")).json()["data"]
    assert len(body["notices"]) == 20
    newest = datetime.fromisoformat(body["notices"][0]["created_at"])
    oldest = datetime.fromisoformat(body["notices"][-1]["created_at"])
    assert newest == datetime(2026, 1, 1, 0, 24, tzinfo=UTC)
    assert oldest == datetime(2026, 1, 1, 0, 5, tzinfo=UTC)


@pytest.mark.asyncio
async def test_notice_skipped_without_feishu_and_failed_on_push_error(db_session, client, monkeypatch):
    """员工没有飞书账号 → 跳过（写明原因）；飞书返回失败 → failed；两种结果都留痕并回给前端。"""
    cards = _Capture("ou_broken")
    monkeypatch.setattr(notify, "_send", cards)
    offline = await _contract(db_session, await _employee(db_session))
    res = await client.post(f"{API}/labor-contracts/{offline.id}/stamp")
    assert res.status_code == 200, res.text
    assert res.json()["data"]["notice"] == {
        "status": "skipped", "error": "员工无飞书账号", "recipient_name": offline.name,
    }
    assert cards.calls == []  # 没有 open_id 就不尝试发送
    assert await _notices(db_session, offline.id) == [("collect", "skipped", offline.name, "员工无飞书账号")]

    broken = await _contract(db_session, await _employee(db_session, open_id="ou_broken"))
    res = await client.post(f"{API}/labor-contracts/{broken.id}/stamp")
    assert res.status_code == 200, res.text
    assert res.json()["data"]["notice"] == {
        "status": "failed", "error": "飞书卡片发送失败", "recipient_name": broken.name,
    }
    assert await _notices(db_session, broken.id) == [("collect", "failed", broken.name, "飞书卡片发送失败")]
    # 盖章本身不因通知失败而回滚
    assert res.json()["data"]["stamped_at"] is not None


@pytest.mark.asyncio
async def test_resend_notice_supports_renew_and_collect_only(db_session, client, monkeypatch):
    """重发按类型校验前置条件；只有续签通知 / 领取通知两类可重发，结果里没有 sign_url。
    签字提醒已随线上签字一起下线：kind=sign 在接口层 422、服务层直接拒绝，不发也不留痕。"""
    employee = await _employee(db_session, open_id="ou_employee")
    cards = _Capture()
    monkeypatch.setattr(notify, "_send", cards)
    contract = await _contract(db_session, employee, status="pending_renewal")
    base = f"{API}/labor-contracts/{contract.id}"

    async def resend(kind: str):
        res = await client.post(f"{base}/resend-notice", json={"kind": kind})
        assert res.status_code in (200, 400, 422), res.text
        return res

    res = await resend("renew")
    assert res.status_code == 400 and "同意续签" in res.json()["message"]
    assert (await resend("collect")).status_code == 400  # 未盖章
    assert (await resend("sign")).status_code == 422  # 签字提醒已下线：不是合法的类型
    with pytest.raises(AppException, match="kind 只能是 renew / collect"):
        await service.resend_notice(db_session, contract, kind="sign")
    res = await client.post(f"{base}/resend-notice", json={"kind": "nope"})
    assert res.status_code == 422
    assert cards.calls == []  # 被拒的重发一次都没发出去
    assert await _notices(db_session, contract.id) == []  # 也不留痕

    assert (await client.post(f"{base}/dept-decision", json={"decision": "agree"})).status_code == 200
    res = await resend("renew")
    assert res.status_code == 200, res.text
    assert res.json()["data"] == {"status": "sent", "error": None, "recipient_name": employee.name}
    assert (await client.post(f"{base}/stamp")).status_code == 200
    res = await resend("collect")
    assert res.status_code == 200 and res.json()["data"]["status"] == "sent"

    # 领取之后同样只有这两类可重发：没有「签字提醒」可发
    assert (await client.post(f"{base}/deliver")).status_code == 200
    assert (await resend("sign")).status_code == 422
    # 到这里共发出 4 张：登记同意 + 重发各 1 张续签通知，盖章 + 重发各 1 张领取通知；都不带按钮
    assert [(c[1], c[3]) for c in cards.calls] == [
        ("劳动合同续签通知", None), ("劳动合同续签通知", None),
        ("领取劳动合同原件通知", None), ("领取劳动合同原件通知", None),
    ]

    await service.terminate_contract(db_session, contract, reason="人工终止")
    for kind in ("renew", "collect"):
        assert (await resend(kind)).status_code == 400
    assert (await resend("sign")).status_code == 422
    assert len(cards.calls) == 4  # 终止之后一张都没再发出去


def test_renew_notice_text_with_contact_name_and_materials():
    """配了联系人姓名和材料：按新文案写；姓名为空回退原写法；材料为空不带那一句。"""
    contract = _pure_contract(seq_no=1, end_date=date(2027, 3, 1))
    first = "张三您好，您的劳动合同（第 1 份，期限 3 年，至 2027-03-01）已通过部门审批。\n\n"
    assert notify.renew_notice_markdown(contract, notify.Contact(
        info="人力资源部", name="王琳", materials="身份证、学历证书原件",
    )) == first + (
        "您的劳动合同即将到期，部门已同意续签，请尽快到 **人力资源部** 找 **王琳** 办理续签手续。"
        "需携带材料：身份证、学历证书原件。如有疑问请联系 **人力资源部** 王琳。"
    )
    assert notify.renew_notice_markdown(contract, notify.Contact(info="人力资源部", name="王琳")) == (
        first
        + "您的劳动合同即将到期，部门已同意续签，请尽快到 **人力资源部** 找 **王琳** 办理续签手续。"
        "如有疑问请联系 **人力资源部** 王琳。"
    )
    assert notify.renew_notice_markdown(contract, notify.Contact(info="人力资源部", materials="身份证")) == (
        first + "请尽快到 **人力资源部** 办理续签手续。需携带材料：身份证。"
    )
    assert notify.renew_notice_markdown(contract, notify.Contact(info="人力资源部")) == (
        first + "请尽快到 **人力资源部** 办理续签手续。"
    )


def test_collect_notice_text_carries_contact_name():
    """领取通知带上联系人姓名；姓名为空时与原文案逐字一致；不用列表语法。
    签字提醒文案已随线上签字删除；两张员工卡的正文里都不出现「签字」，也不带链接。"""
    contract = _pure_contract()
    opening = "张三您好，您的劳动合同（第 2 份）已完成签订盖章。\n\n"
    assert notify.stamp_notice_markdown(contract, notify.Contact(info="人力资源部", name="王琳")) == (
        opening + "请到 **人力资源部** 找 **王琳** 领取劳动合同原件。"
    )
    assert notify.stamp_notice_markdown(contract, notify.Contact(info="人力资源部")) == (
        opening + "请到 **人力资源部** 领取劳动合同原件。"
    )
    contact = notify.Contact(info="人力资源部", name="王琳", materials="身份证")
    for text in (
        notify.stamp_notice_markdown(contract, contact),
        notify.renew_notice_markdown(contract, contact),
    ):
        assert "签字" not in text and "http" not in text and "- " not in text

    # 签字提醒的文案与发送函数都已删除，sign 不再是通知类型
    assert not hasattr(notify, "sign_reminder_markdown")
    assert not hasattr(notify, "send_sign_reminder")
    assert not hasattr(ContractNoticeLog, "KIND_SIGN")
    assert ContractNoticeLog.RESENDABLE_KINDS == (ContractNoticeLog.KIND_RENEW, ContractNoticeLog.KIND_COLLECT)


@pytest.mark.asyncio
async def test_contact_settings_round_trip(db_session):
    """两个新键走已有的加载/保存；未配置时姓名为空、材料为空。"""
    assert contract_settings.contact_name({}) == ""
    assert contract_settings.required_materials({}) == ""
    await contract_settings.save_contract_settings(db_session, {
        contract_settings.KEY_CONTACT_NAME: " 王琳 ",
        contract_settings.KEY_REQUIRED_MATERIALS: "身份证、学历证书原件",
    })
    kv = await contract_settings.load_contract_settings(db_session)
    assert contract_settings.contact_name(kv) == "王琳"
    assert contract_settings.required_materials(kv) == "身份证、学历证书原件"


@pytest.mark.asyncio
async def test_scan_logs_every_dept_notice_outcome(db_session, monkeypatch):
    """公告期扫描给部门负责人发卡：送达 / 推送失败 / 匹配不到负责人，逐合同各留一行。"""
    dept_ok, dept_fail, dept_none, dept_blank = (f"留痕{uuid4().hex[:6]}" for _ in range(4))
    delivered = await _contract(
        db_session, await _employee(db_session, department=dept_ok), end_date=TODAY + timedelta(days=10),
    )
    failed = await _contract(
        db_session, await _employee(db_session, department=dept_fail), end_date=TODAY + timedelta(days=20),
    )
    unresolved = await _contract(
        db_session, await _employee(db_session, department=dept_none), end_date=TODAY + timedelta(days=30),
    )
    nameless = await _contract(
        db_session, await _employee(db_session, department=dept_blank), end_date=TODAY + timedelta(days=40),
    )
    monkeypatch.setattr(renewal_approval, "initiate", AsyncMock(return_value=(False, "未配置审批定义编码")))
    monkeypatch.setattr(renewal_approval, "resolve_approver", _resolver({
        dept_ok: ("张管理", "ou_test_ok"),
        dept_fail: ("李管理", "ou_test_fail"),
        dept_none: ("赵管理", None),  # 有负责人但匹配不到飞书账号
    }))
    monkeypatch.setattr(dept_notice, "_send", _Capture("ou_test_fail"))
    monkeypatch.setattr(notify, "_send", _Capture())
    monkeypatch.setattr(scheduled, "resolve_receivers", AsyncMock(return_value=["ou_test_hr"]))

    await scheduled._run_announcement(db_session, days_ahead=50, copy_entries=[], dept_notice=True)

    assert await _notices(db_session, delivered.id) == [("dept_approval", "sent", "张管理", None)]
    assert await _notices(db_session, failed.id) == [
        ("dept_approval", "failed", "李管理", "负责人「李管理」推送失败"),
    ]
    assert await _notices(db_session, unresolved.id) == [
        ("dept_approval", "skipped", "赵管理", "负责人「赵管理」匹配不到飞书账号"),
    ]
    assert await _notices(db_session, nameless.id) == [
        ("dept_approval", "skipped", None, "部门表与员工档案均无负责人"),
    ]


@pytest.mark.asyncio
async def test_dept_head_card_goes_through_real_send_chain(db_session, monkeypatch):
    """部门负责人审批提醒走真实的 dept_notice._send → notify._send → send_user_card。

    这两层一旦被打桩，参数对不上也发现不了：notify._send 收窄签名后负责人发卡即崩、用例却全绿。
    这里只打桩最底层的飞书发送；按钮（去合同台账审批）只在配了前台地址时才有，不写死。
    """
    sent: list[dict] = []

    async def _capture(open_id, *, title, content, elements=None):
        sent.append({"open_id": open_id, "title": title, "elements": elements})
        return True

    monkeypatch.setattr(notify, "send_user_card", _capture)
    contract = await _contract(
        db_session, await _employee(db_session, department=f"真实链路{uuid4().hex[:6]}"),
        end_date=TODAY + timedelta(days=15),
    )

    result = await dept_notice.notify_dept_heads([(contract, "张管理", "ou_test_manager")])

    assert result == {"notified": [(contract, "张管理")], "failed": []}
    assert len(sent) == 1 and sent[0]["open_id"] == "ou_test_manager"
    assert sent[0]["title"] == dept_notice.TITLE
    buttons = (sent[0]["elements"] or [{}])[0].get("actions", [{}])[0].get("text", {}).get("content")
    assert buttons in (None, "去合同台账审批")


@pytest.mark.asyncio
async def test_scan_logs_skipped_when_dept_notice_disabled(db_session, monkeypatch):
    """负责人提醒关闭：不发卡片，但留一行「已跳过」；飞书审批撤销后退回站内的补发同样留痕。"""
    department = f"留痕关闭{uuid4().hex[:6]}"
    contract = await _contract(
        db_session, await _employee(db_session, department=department), end_date=TODAY + timedelta(days=15),
    )
    monkeypatch.setattr(renewal_approval, "initiate", AsyncMock(return_value=(False, "未配置审批定义编码")))
    monkeypatch.setattr(renewal_approval, "resolve_approver", _resolver({department: ("张管理", "ou_test_a")}))
    dept_cards, hr_cards = _Capture(), _Capture()
    monkeypatch.setattr(dept_notice, "_send", dept_cards)
    monkeypatch.setattr(notify, "_send", hr_cards)
    monkeypatch.setattr(scheduled, "resolve_receivers", AsyncMock(return_value=["ou_test_hr"]))

    await scheduled._run_announcement(db_session, days_ahead=50, copy_entries=[], dept_notice=False)

    assert contract.status == LaborContract.STATUS_PENDING_RENEWAL
    assert dept_cards.calls == []
    assert await _notices(db_session, contract.id) == [
        ("dept_approval", "skipped", None, "负责人提醒已关闭，请 HR 通知负责人"),
    ]

    await scheduled._notify_back_to_manual(
        db_session, [contract], days_ahead=50, copy_entries=[], dept_notice=True,
    )

    assert [call[0] for call in dept_cards.calls] == ["ou_test_a"]
    assert scheduled._CANCELED_NOTE in dept_cards.calls[0][2]
    assert await _notices(db_session, contract.id) == [
        ("dept_approval", "sent", "张管理", None),
        ("dept_approval", "skipped", None, "负责人提醒已关闭，请 HR 通知负责人"),
    ]


# ═══════════════════════════════════════════════════════════════
# 5. 状态驱动的进度步骤（纯函数）
# ═══════════════════════════════════════════════════════════════


def test_progress_has_six_fixed_steps():
    """固定六步：领取之后直接归档，没有「线上签字」这一步。"""
    steps = service.build_progress(_pure_contract())
    assert [step["key"] for step in steps] == [
        "expiry_alert", "dept_approval", "renew_notice", "stamp", "deliver", "archive",
    ]
    assert [step["title"] for step in steps] == [
        "到期预警", "部门审批", "通知续签", "签订盖章", "领取合同", "电子归档",
    ]
    assert [key for key, _ in service.STEP_TITLES] == [step["key"] for step in steps]
    assert not hasattr(service, "STEP_SIGN")
    assert not hasattr(service, "NOTE_ARCHIVED_BEFORE_SIGN")
    assert all(set(step) == {"key", "title", "state", "at", "note"} for step in steps)


def test_progress_active_contract_counts_as_signed():
    """履约中的存量合同：签订日已有、没有盖章/领取时间 → 签订两步按「已签订生效」完成，待归档为当前步。"""
    steps = service.build_progress(_pure_contract())
    assert [step["state"] for step in steps] == [
        "pending", "pending", "pending", "done", "done", "current",
    ]
    assert [steps[i]["note"] for i in (3, 4)] == ["已签订生效"] * 2
    assert steps[0]["at"] is None and steps[5]["note"] is None


def test_progress_pending_renewal_awaits_dept_decision():
    steps = service.build_progress(_pure_contract(status="pending_renewal"))
    assert [step["state"] for step in steps] == [
        "done", "current", "pending", "done", "done", "current",
    ]
    assert steps[1]["note"] is None


def test_progress_records_who_registered_agreement():
    steps = service.build_progress(_pure_contract(
        status="pending_renewal", dept_decision="agree", dept_decision_by="张管理", dept_decision_at=DECIDED,
    ))
    assert [step["state"] for step in steps] == [
        "done", "done", "pending", "done", "done", "current",
    ]
    assert (steps[1]["at"], steps[1]["note"]) == (DECIDED, "张管理 登记同意")


def test_progress_expired_unrenewed_asks_for_decision_or_transfer():
    steps = service.build_progress(_pure_contract(status="expired_unrenewed"))
    assert [step["state"] for step in steps] == [
        "done", "current", "pending", "done", "done", "current",
    ]
    assert steps[1]["note"] == "到期未续签，待处理"
    # 已登记同意：部门审批完成，不再是当前步
    assert _states(_pure_contract(
        status="expired_unrenewed", dept_decision="agree", dept_decision_by="张管理", dept_decision_at=DECIDED,
    )) == ["done", "done", "pending", "done", "done", "current"]


def test_progress_renewing_follows_renew_notice_log():
    contract = _pure_contract(
        status="renewing", dept_decision="agree", dept_decision_by="张管理", dept_decision_at=DECIDED,
    )
    first, second = datetime(2026, 11, 12, 9, 0, tzinfo=UTC), datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    prompt = {"key": "renew_notice", "title": "通知续签"}

    assert _states(contract)[:3] == ["done", "done", "current"]  # 还没发过通知
    assert service.build_progress(contract)[2] == prompt | {"state": "current", "at": None, "note": None}
    assert service.build_progress(contract, [_notice("renew", "failed", first)])[2] == prompt | {
        "state": "current", "at": None, "note": "通知发送失败，可重发",
    }
    assert service.build_progress(contract, [_notice("renew", "skipped", first, "员工无飞书账号")])[2] == (
        prompt | {"state": "current", "at": None, "note": "员工无飞书账号"}
    )
    # 失败后重发成功：以送达时间为准
    assert service.build_progress(contract, [
        _notice("renew", "sent", second), _notice("renew", "failed", first),
    ])[2] == prompt | {"state": "done", "at": second, "note": None}
    # 公告期（还没同意）即使有通知记录也不算通知续签完成
    assert service.build_progress(_pure_contract(status="pending_renewal"), [_notice("renew", "sent", second)])[2][
        "state"
    ] == "pending"


def test_progress_legacy_contract_with_milestones():
    """已有盖章/领取时间的存量合同按时间戳逐个判断；领取之后下一步就是归档。"""
    steps = service.build_progress(_pure_contract(stamped_at=STAMPED))
    assert [step["state"] for step in steps] == [
        "pending", "pending", "pending", "done", "current", "pending",
    ]
    assert (steps[3]["at"], steps[3]["note"]) == (STAMPED, None)
    # 没有签订日：从签订盖章开始，不按「已签订生效」
    assert _states(_pure_contract(sign_date=None)) == [
        "pending", "pending", "pending", "current", "pending", "pending",
    ]
    # 已领取、未归档：归档是当前步（领取即签收，中间没有签字环节）
    steps = service.build_progress(_pure_contract(stamped_at=STAMPED, delivered_at=DELIVERED))
    assert [step["state"] for step in steps] == [
        "pending", "pending", "pending", "done", "done", "current",
    ]
    assert (steps[4]["at"], steps[4]["note"], steps[5]["note"]) == (DELIVERED, None, None)
    # 归档完成：全部走完，不再有「签字前已归档」之类的备注
    steps = service.build_progress(_pure_contract(
        stamped_at=STAMPED, delivered_at=DELIVERED,
        archive_status=LaborContract.ARCHIVE_ARCHIVED, archive_uploaded_at=ARCHIVED,
    ))
    assert [step["state"] for step in steps] == [
        "pending", "pending", "pending", "done", "done", "done",
    ]
    assert (steps[5]["at"], steps[5]["note"]) == (ARCHIVED, None)
    # 先归档、后领取的存量行：归档步按归档状态算完成，领取仍是当前步
    assert _states(_pure_contract(
        stamped_at=STAMPED,
        archive_status=LaborContract.ARCHIVE_ARCHIVED, archive_uploaded_at=ARCHIVED,
    )) == ["pending", "pending", "pending", "done", "current", "done"]


def test_progress_renewal_origin_contract():
    """续签生成的新合同：前三步续签时已完成，之后按盖章 / 领取 / 归档依次推进。"""
    fresh = service.build_progress(_pure_contract(origin="renewal"))
    assert [step["state"] for step in fresh] == [
        "done", "done", "done", "current", "pending", "pending",
    ]
    assert [step["note"] for step in fresh[:3]] == ["续签时已完成"] * 3
    assert all(step["at"] is None for step in fresh[:3])

    # 只盖章未领取：领取是当前步
    assert _states(_pure_contract(origin="renewal", stamped_at=STAMPED)) == [
        "done", "done", "done", "done", "current", "pending",
    ]
    # 已领取未归档：归档是当前步
    steps = service.build_progress(_pure_contract(
        origin="renewal", stamped_at=STAMPED, delivered_at=DELIVERED,
    ))
    assert [step["state"] for step in steps] == [
        "done", "done", "done", "done", "done", "current",
    ]
    assert (steps[4]["at"], steps[4]["note"]) == (DELIVERED, None)
    steps = service.build_progress(_pure_contract(
        origin="renewal", stamped_at=STAMPED, delivered_at=DELIVERED,
        archive_status=LaborContract.ARCHIVE_ARCHIVED, archive_uploaded_at=ARCHIVED,
    ))
    assert [step["state"] for step in steps] == ["done"] * 6
    assert (steps[5]["at"], steps[5]["note"]) == (ARCHIVED, None)

    # 续签生成的无固定期限合同走续签分支，不套用「无固定期限」整段完成
    assert _states(_pure_contract(
        origin="renewal", term_type=LaborContract.TERM_OPEN, term_years=None, end_date=None,
    )) == ["done", "done", "done", "current", "pending", "pending"]


def test_progress_open_term_contract():
    open_term = {"term_type": LaborContract.TERM_OPEN, "term_years": None, "end_date": None}
    steps = service.build_progress(_pure_contract(**open_term))
    assert [step["state"] for step in steps] == ["done"] * 5 + ["current"]
    assert [step["note"] for step in steps[:5]] == ["无固定期限，不设到期日"] * 5
    steps = service.build_progress(_pure_contract(
        **open_term, archive_status=LaborContract.ARCHIVE_ARCHIVED, archive_uploaded_at=ARCHIVED,
    ))
    assert [step["state"] for step in steps] == ["done"] * 6
    assert steps[5]["at"] == ARCHIVED


def test_progress_superseded_contract():
    steps = service.build_progress(_pure_contract(status="superseded"))
    assert [step["state"] for step in steps] == ["done"] * 5 + ["skipped"]
    assert [step["note"] for step in steps[:5]] == ["已续签为新合同"] * 5
    assert steps[5]["note"] is None
    assert _states(_pure_contract(
        status="superseded", archive_status=LaborContract.ARCHIVE_ARCHIVED,
    )) == ["done"] * 6


def test_progress_terminated_contract():
    ended = ["done", "done"] + ["skipped"] * 4
    steps = service.build_progress(_pure_contract(
        status="terminated", terminated_reason="部门不同意续签",
        dept_decision="disagree", dept_decision_by="张管理", dept_decision_at=DECIDED,
    ))
    assert [step["state"] for step in steps] == ended
    assert [step["note"] for step in steps[:2]] == ["部门不同意续签"] * 2
    assert steps[1]["at"] == DECIDED
    # 即使留有盖章 / 归档记录，终止之后也不再推进
    assert _states(_pure_contract(
        status="terminated", stamped_at=STAMPED, archive_status=LaborContract.ARCHIVE_ARCHIVED,
    )) == ended


# ═══════════════════════════════════════════════════════════════
# 6. 离职办理中的人不进入到期预警 / 单员工终止
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scan_skips_employees_with_pending_offboarding(db_session, monkeypatch):
    """台账里登记了将要离职（离职日期 ≥ 今天）的人：合同不进公告期、不发部门卡片；已软删的离职记录不算。"""
    department = f"办理中{uuid4().hex[:6]}"
    leaving = await _employee(db_session, department=department)
    leaving_contract = await _contract(db_session, leaving, end_date=TODAY + timedelta(days=10))
    staying = await _employee(db_session, department=department)
    staying_contract = await _contract(db_session, staying, end_date=TODAY + timedelta(days=10))
    for employee, deleted in ((leaving, False), (staying, True)):
        db_session.add(DepartureRecord(
            name=employee.name, employee_number=employee.employee_number, department=department,
            position="专员", offboarding_type="合同到期",
            offboarding_date=TODAY + timedelta(days=30), is_deleted=deleted,
        ))
    await db_session.flush()

    scanned = {c.id for c in await service.find_expiring_active(db_session, days_ahead=50)}
    assert leaving_contract.id not in scanned and staying_contract.id in scanned

    monkeypatch.setattr(renewal_approval, "initiate", AsyncMock(return_value=(False, "未配置审批定义编码")))
    monkeypatch.setattr(renewal_approval, "resolve_approver", _resolver({department: ("张管理", "ou_test_a")}))
    dept_cards, hr_cards = _Capture(), _Capture()
    monkeypatch.setattr(dept_notice, "_send", dept_cards)
    monkeypatch.setattr(notify, "_send", hr_cards)
    monkeypatch.setattr(scheduled, "resolve_receivers", AsyncMock(return_value=["ou_test_hr"]))

    await scheduled._run_announcement(db_session, days_ahead=50, copy_entries=[], dept_notice=True)

    assert leaving_contract.status == LaborContract.STATUS_ACTIVE
    assert staying_contract.status == LaborContract.STATUS_PENDING_RENEWAL
    assert len(dept_cards.calls) == 1
    markdown = dept_cards.calls[0][2]
    assert staying.name in markdown and leaving.name not in markdown
    assert await _notices(db_session, leaving_contract.id) == []


@pytest.mark.asyncio
async def test_terminate_for_employee_matches_daily_reconcile(db_session):
    """离职办结时按单个员工终止未完结合同：判定与写法同每日 reconcile，只 flush 不 commit。"""
    employee = await _employee(db_session)
    superseded = await _contract(db_session, employee, seq_no=1, status="superseded")
    current = await _contract(db_session, employee, seq_no=2)
    announced = await _contract(db_session, employee, seq_no=3, status="pending_renewal")
    leave_on = TODAY + timedelta(days=10)
    departure = DepartureRecord(
        name=employee.name, employee_number=employee.employee_number, department=employee.department,
        position="专员", offboarding_type="合同到期", offboarding_date=leave_on,
    )
    db_session.add(departure)
    await db_session.flush()
    number = employee.employee_number

    assert await departure_service.terminate_for_employee(
        db_session, employee_number=number, departed_on=TODAY,
    ) == 0  # 离职日期未到、档案仍在职
    assert current.status == LaborContract.STATUS_ACTIVE

    assert await departure_service.terminate_for_employee(
        db_session, employee_number=number, departed_on=leave_on,
    ) == 2
    for contract in (current, announced):
        assert contract.status == LaborContract.STATUS_TERMINATED
        assert contract.terminated_reason == "合同到期终止" and contract.terminated_at is not None
        assert contract.departure_record_id == departure.id
    assert superseded.status == LaborContract.STATUS_SUPERSEDED  # 已完结的历史行不动
    assert await departure_service.terminate_for_employee(
        db_session, employee_number=number, departed_on=leave_on,
    ) == 0  # 幂等
    assert db_session.commit.call_count == 0  # 由调用方统一提交

    # 档案已是离职状态：没有离职记录也终止，终止原因与 reconcile 的推导一致
    left = await _employee(db_session, status="离职")
    left_contract = await _contract(db_session, left)
    assert await departure_service.terminate_for_employee(
        db_session, employee_number=left.employee_number, departed_on=TODAY,
    ) == 1
    assert left_contract.status == LaborContract.STATUS_TERMINATED
    assert left_contract.terminated_reason == "其他"


@pytest.mark.asyncio
async def test_terminate_for_employee_agrees_with_daily_reconcile(db_session):
    """同一天离职的两个员工：单员工终止与每日扫描写出的结果一致。

    先跑单员工终止再跑每日扫描——扫描是全量的，会把两个员工都处理掉。"""
    twins = []
    for _ in range(2):
        employee = await _employee(db_session)
        contract = await _contract(db_session, employee)
        db_session.add(DepartureRecord(
            name=employee.name, employee_number=employee.employee_number,
            department=employee.department, position="专员",
            offboarding_type="个人原因", offboarding_date=TODAY,
        ))
        twins.append((employee, contract))
    await db_session.flush()
    (scanned_employee, scanned), (direct_employee, direct) = twins

    assert await departure_service.terminate_for_employee(
        db_session, employee_number=direct_employee.employee_number, departed_on=TODAY,
    ) == 1
    reconciled = await departure_service.reconcile_departed_contracts(db_session)
    assert [c.id for c in reconciled if c.employee_number == scanned_employee.employee_number] == [scanned.id]

    def outcome(contract: LaborContract) -> tuple:
        return (
            contract.status, contract.terminated_reason, contract.departure_record_id is not None,
            contract.terminated_at is not None,
        )

    assert outcome(direct) == outcome(scanned) == (
        LaborContract.STATUS_TERMINATED, "员工辞职解除", True, True,
    )


# ═══════════════════════════════════════════════════════════════
# 7. 「待我处理」口径（统计与筛选共用）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_stats_and_todo_filters_share_one_definition(db_session, client):
    """每个「待我处理」口径各准备一份合同：统计计数与列表筛选必须指向同一批行；
    attention_total = 前五项之和，「全部待办」筛选与它同一批行。"""
    department = f"待办口径{uuid4().hex[:6]}"

    async def row(**overrides) -> LaborContract:
        return await _contract(db_session, await _employee(db_session, department=department), **overrides)

    await_approval = await row(status="pending_renewal")
    approved = await row(status="pending_renewal", dept_decision="agree")
    to_renew = await row(status="renewing", dept_decision="agree")
    to_stamp = await row(origin="renewal")
    to_deliver = await row(origin="renewal", stamped_at=STAMPED)
    # 领取即签收：领取之后的下一步就是归档，中间没有「待签字」；不看来源，存量合同领了没归档同样算
    to_archive = await row(stamped_at=STAMPED, delivered_at=DELIVERED)
    archived = await row(
        stamped_at=STAMPED, delivered_at=DELIVERED,
        archive_status=LaborContract.ARCHIVE_ARCHIVED, archive_uploaded_at=ARCHIVED,
    )
    expired = await row(status="expired_unrenewed")
    replaced = await row(status="superseded")
    finished = await row(status="terminated", terminated_reason="人工终止")

    res = await client.get(f"{API}/labor-contracts/stats", params={"department": department})
    assert res.status_code == 200, res.text
    stats = res.json()["data"]
    assert stats == {
        "pending_dept_approval": 1, "to_renew": 1, "to_stamp": 1, "to_deliver": 1,
        "to_archive": 1, "pending_renewal": 2, "expired_unrenewed": 1,
        "attention_total": 5,
    }
    # 返回键 = 七个口径 + 合计（attention_total = 前五项之和）；「待签字」口径已随线上签字删除
    assert set(stats) == {*repo.TODO_KEYS, "attention_total"}
    assert set(repo.ATTENTION_KEYS) == {
        "pending_dept_approval", "to_renew", "to_stamp", "to_deliver", "to_archive",
    }
    assert repo.LIST_TODO_KEYS == (*repo.TODO_KEYS, "attention")
    assert not hasattr(repo, "TODO_TO_SIGN")

    expected = {
        "pending_dept_approval": {await_approval},
        "to_renew": {to_renew},
        "to_stamp": {to_stamp},
        "to_deliver": {to_deliver},
        "to_archive": {to_archive},
        "pending_renewal": {await_approval, approved},
        "expired_unrenewed": {expired},
    }
    assert set(expected) == set(repo.TODO_KEYS)
    for todo, wanted_contracts in expected.items():
        wanted = {c.employee_number for c in wanted_contracts}
        numbers, total = await _numbers(client, {"todo": todo, "department": department})
        assert (numbers, total) == (wanted, len(wanted)), todo
    # 「全部待办」= 前五项（HR 手上要办的事）的并集，与 attention_total 是同一批行
    attention = {await_approval, to_renew, to_stamp, to_deliver, to_archive}
    numbers, total = await _numbers(client, {"todo": "attention", "department": department})
    assert (numbers, total) == ({c.employee_number for c in attention}, stats["attention_total"])
    # 旧的「待签字」口径不再可筛
    res = await client.get(f"{API}/labor-contracts", params={"todo": "to_sign"})
    assert res.status_code == 422

    open_contracts = (
        await_approval, approved, to_renew, to_stamp, to_deliver, to_archive, archived, expired,
    )
    open_numbers = {c.employee_number for c in open_contracts}
    # 缺省不再返回已续签取代 / 已终止的历史行；显式要历史、或按状态筛时照旧
    numbers, total = await _numbers(client, {"department": department})
    assert (numbers, total) == (open_numbers, 8)
    numbers, total = await _numbers(client, {"department": department, "include_history": "true"})
    history = {replaced.employee_number, finished.employee_number}
    assert (numbers, total) == (open_numbers | history, 10)
    numbers, _ = await _numbers(client, {"department": department, "status": "superseded,terminated"})
    assert numbers == history
    numbers, _ = await _numbers(client, {"department": department, "status": "terminated"})
    assert numbers == {finished.employee_number}


@pytest.mark.asyncio
async def test_stats_follow_department_scope(db_session, client, test_user, monkeypatch):
    """部门数据范围：统计与筛选只算授权部门内的合同。"""
    mine, theirs = f"待办范围{uuid4().hex[:6]}", f"待办范围{uuid4().hex[:6]}"
    own = await _contract(
        db_session, await _employee(db_session, department=mine), status="pending_renewal",
    )
    await _contract(
        db_session, await _employee(db_session, department=theirs), status="pending_renewal",
    )
    await _contract(db_session, await _employee(db_session, department=mine), status="expired_unrenewed")
    test_user.department = mine
    monkeypatch.setattr(
        "app.platform.permission.repository.PermissionRepository.get_effective_data_scope",
        AsyncMock(return_value="department"),
    )

    res = await client.get(f"{API}/labor-contracts/stats")
    assert res.status_code == 200, res.text
    stats = res.json()["data"]
    assert (stats["pending_dept_approval"], stats["pending_renewal"], stats["expired_unrenewed"]) == (1, 1, 1)
    numbers, _ = await _numbers(client, {"todo": "pending_dept_approval"})
    assert numbers == {own.employee_number}


# ═══════════════════════════════════════════════════════════════
# 8. 归档：换传原因 / 学历列与筛选 / 筛选项字典
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_replacing_archive_version_requires_reason(db_session, client, monkeypatch):
    """首次上传可不填原因；已有当前版本再上传必须写明原因并存到新版本行；被拒的换传不落文件。"""
    contract = await _contract(db_session, await _employee(db_session))
    base = f"{API}/labor-contracts/{contract.id}/archive"
    stored: list[str] = []
    real_store = archive_service.store_object

    def spy_store(module, key, data, content_type):
        stored.append(key)
        return real_store(module, key, data, content_type)

    monkeypatch.setattr(archive_service, "store_object", spy_store)
    try:
        res = await client.post(base, files={"file": ("扫描件.png", PNG, "image/png")})
        assert res.status_code == 200, res.text
        assert res.json()["data"]["versions"][0]["reason"] is None

        for form in (None, {"reason": "   "}):
            res = await client.post(
                base, files={"file": ("第二版.pdf", PDF, "application/pdf")}, data=form,
            )
            assert res.status_code == 422, res.text
            assert "原因" in res.json()["message"]
        versions = await repo.list_versions(db_session, contract.id)
        assert [(v.version_no, v.is_current) for v in versions] == [(1, True)]

        res = await client.post(
            base, files={"file": ("第二版.pdf", PDF, "application/pdf")},
            data={"reason": "重扫：补骑缝页"},
        )
        assert res.status_code == 200, res.text
        assert [
            (v["version_no"], v["is_current"], v["reason"]) for v in res.json()["data"]["versions"]
        ] == [(2, True, "重扫：补骑缝页"), (1, False, None)]
        assert len(stored) == 2
    finally:
        await _cleanup(db_session, [contract.id], keys=stored)


@pytest.mark.asyncio
async def test_batch_commit_requires_reason_when_replacing(db_session, client, test_user):
    """批量挂接走同一条规则：替换已有版本的行必须带原因，失败原因逐行返回；补上原因后可重新提交。"""
    contract = await _contract(db_session, await _employee(db_session))
    await archive_service.create_archive_version(
        db_session, contract=contract, file_bytes=PNG, filename="v1.png", user=test_user,
    )
    staged = f"{archive_batch_import.STAGING_PREFIX}test/{uuid4().hex}.pdf"
    store_object(archive_service.MODULE, staged, PDF, "application/pdf")

    async def commit(row: dict) -> dict:
        res = await client.post(f"{API}/labor-contracts-archive/batch-import/commit", json={
            "rows": [{"storage_key": staged, "contract_id": str(contract.id), **row}],
        })
        assert res.status_code == 200, res.text
        return res.json()["data"]

    try:
        result = await commit({"filename": "无原因.pdf"})
        assert result["summary"] == {"imported": 0, "failed": 1}
        assert "换传原因" in result["results"][0]["error"] and result["results"][0]["ok"] is False
        assert [(v.version_no, v.reason) for v in await repo.list_versions(db_session, contract.id)] == [
            (1, None),
        ]

        result = await commit({"filename": "有原因.pdf", "reason": "重扫"})
        assert result["summary"] == {"imported": 1, "failed": 0}
        assert [(v.version_no, v.reason) for v in await repo.list_versions(db_session, contract.id)] == [
            (2, "重扫"), (1, None),
        ]
    finally:
        await _cleanup(db_session, [contract.id], keys=[staged])


@pytest.mark.asyncio
async def test_education_shown_and_filterable(db_session, client):
    """在职台账、档案库列表带学历；列表与补扫清单的 education 筛选都是逗号分隔多值 IN 匹配。"""
    department = f"学历{uuid4().hex[:6]}"
    bachelor = await _contract(db_session, await _employee(db_session, department=department, education="本科"))
    master = await _contract(db_session, await _employee(db_session, department=department, education="硕士"))
    college = await _contract(db_session, await _employee(db_session, department=department, education="大专"))

    async def library(education: str | None = None) -> dict[str, str]:
        params: dict = {"department": department, "page_size": 100}
        if education is not None:
            params["education"] = education
        res = await client.get(f"{API}/labor-contracts-archive", params=params)
        assert res.status_code == 200, res.text
        return {row["employee_number"]: row["education"] for row in res.json()["data"]}

    everything = {
        bachelor.employee_number: "本科", master.employee_number: "硕士", college.employee_number: "大专",
    }
    assert await library() == everything
    assert await library("本科,硕士") == {
        bachelor.employee_number: "本科", master.employee_number: "硕士",
    }
    assert await library(" 大专 ") == {college.employee_number: "大专"}
    assert await library("博士") == {}

    numbers, _ = await _numbers(client, {"department": department, "education": "大专"})
    assert numbers == {college.employee_number}
    res = await client.get(f"{API}/labor-contracts", params={"keyword": master.employee_number})
    # 关键字是模糊匹配，共享库里可能有别的工号包含同样数字：只看工号完全相等的那一行
    own = [row for row in res.json()["data"] if row["employee_number"] == master.employee_number]
    assert [row["education"] for row in own] == ["硕士"]

    # 领取即签收：补扫清单不再有「签字确认时间」列，领取时间之后直接是人员状态 / 合同状态
    headers = [
        "部门", "工号", "姓名", "岗位", "学历", "签订次数", "合同期限", "起始日", "到期日",
        "签订日", "领取时间", "人员状态", "合同状态",
    ]
    assert headers == archive_service.UNARCHIVED_EXPORT_HEADERS

    async def export(education: str | None = None) -> list[list]:
        params = {"department": department} if education is None else {
            "department": department, "education": education,
        }
        res = await client.get(f"{API}/labor-contracts-archive/export-unarchived", params=params)
        assert res.status_code == 200
        ws = load_workbook(io.BytesIO(res.content)).active
        assert [c.value for c in ws[1]] == headers
        rows = [[c.value for c in row] for row in ws.iter_rows(min_row=2)]
        assert all(len(row) == len(headers) for row in rows)
        return rows

    rows = await export()
    assert {(r[1], r[4]) for r in rows} == set(everything.items())
    # 这三份都还没领取：领取时间是空格子，后面直接是人员状态 / 合同状态
    assert {(r[1], r[10], r[11], r[12]) for r in rows} == {
        (number, None, "在职", "生效中") for number in everything
    }
    assert {(r[1], r[4]) for r in await export("本科,大专")} == {
        (bachelor.employee_number, "本科"), (college.employee_number, "大专"),
    }


@pytest.mark.asyncio
async def test_filter_options_follow_scope_and_drop_dirty_education(db_session, client, test_user, monkeypatch):
    """筛选项字典：部门与学历只取数据范围内有合同的取值；学历按由高到低排列并剔除脏值。"""
    mine = f"筛选项{uuid4().hex[:6]}"
    for education in ("大专", "本科", "硕士", "本科-全日制", "成人教育本科毕业（自学考试）"):
        await _contract(db_session, await _employee(db_session, department=mine, education=education))
    await _contract(
        db_session, await _employee(db_session, department=f"筛选项{uuid4().hex[:6]}", education="博士"),
    )
    test_user.department = mine
    monkeypatch.setattr(
        "app.platform.permission.repository.PermissionRepository.get_effective_data_scope",
        AsyncMock(return_value="department"),
    )

    res = await client.get(f"{API}/labor-contracts-archive/filter-options")
    assert res.status_code == 200, res.text
    assert res.json()["data"] == {"departments": [mine], "education": ["硕士", "本科", "大专"]}


# ═══════════════════════════════════════════════════════════════
# 9. 协商解除 / 线上签字链路已下线
# ═══════════════════════════════════════════════════════════════


def test_negotiated_termination_type():
    """新增「协商解除」：离职类型写明协商解除即判为协商解除；合同期满后才离开仍按到期终止。"""
    assert departure_service.TERMINATION_LABELS["negotiated"] == "协商解除"
    assert "negotiated" in departure_service.TERMINATION_CHOICES
    assert departure_service.derive_termination_type(
        "协商解除", date(2026, 6, 1), date(2028, 7, 1),
    ) == "negotiated"
    assert departure_service.derive_termination_type(
        "协商解除", date(2026, 7, 1), date(2026, 7, 1),
    ) == "expiry"
    assert departure_service.derive_termination_type(
        "协商解除", date(2026, 6, 1), None, has_contract=False,
    ) == "none"


@pytest.mark.asyncio
async def test_negotiated_termination_filterable_and_correctable(db_session, client):
    """离职合同台账可按「协商解除」筛选、导出；人工更正可选该方式。"""
    department = f"协商{uuid4().hex[:6]}"
    negotiated = await _departure(db_session, department=department, offboarding_type="协商解除")
    resigned = await _departure(db_session, department=department, offboarding_type="个人原因")

    res = await client.get(f"{API}/departure-contracts", params={
        "department": department, "termination_type": "negotiated",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["total"] == 1
    assert (body["data"][0]["id"], body["data"][0]["termination_type_label"]) == (
        str(negotiated.id), "协商解除",
    )

    res = await client.get(f"{API}/departure-contracts/export", params={
        "department": department, "termination_type": "negotiated",
    })
    assert res.status_code == 200
    ws = load_workbook(io.BytesIO(res.content)).active
    assert "终止方式：协商解除" in ws["A2"].value
    assert ws.cell(row=5, column=11).value == "协商解除" and ws.cell(row=6, column=2).value is None

    res = await client.get(f"{API}/departure-contracts/filter-options")
    assert {"value": "negotiated", "label": "协商解除"} in res.json()["data"]["termination_types"]

    res = await client.put(f"{API}/departure-records/{resigned.id}/contract-procedure", json={
        "termination_type": "negotiated", "approval_ref": None,
        "separation_process_no": None, "contract_original_status": "unrecovered",
    })
    assert res.status_code == 200, res.text
    _, rows = await departure_ledger.page_rows(
        db_session, department=department, keyword=resigned.employee_number,
    )
    assert rows[0]["termination_type"] == "negotiated" and rows[0]["termination_type_overridden"] is True


@pytest.mark.asyncio
async def test_sign_link_service_and_endpoints_are_gone(db_session, client):
    """线上签字整条链路已下线：签发 token / 凭 token 签字的服务函数、模型列、签字页地址配置项都不存在；
    旧的免登签字接口（查看 / 确认）一律 404，不再能凭 token 改动合同。"""
    for gone in (
        "sign_page_url", "issue_sign_token", "find_by_sign_token", "confirm_sign_by_token",
        "SIGNABLE_STATUSES",
    ):
        assert not hasattr(service, gone), gone
    for column in ("sign_token_hash", "sign_confirmed_at"):
        assert not hasattr(LaborContract, column), column
    assert not hasattr(contract_settings, "KEY_SIGN_BASE_URL")

    contract = await _contract(db_session, await _employee(db_session))
    token = uuid4().hex
    assert (await client.get(f"{API}/contract-sign/{token}")).status_code == 404
    res = await client.post(f"{API}/contract-sign/{token}/confirm", json={})
    assert res.status_code == 404
    stored = await repo.get(db_session, contract.id)
    assert stored is not None
    assert stored.status == LaborContract.STATUS_ACTIVE and stored.delivered_at is None


@pytest.mark.asyncio
async def test_legacy_sign_notice_rows_are_listed_but_ignored_by_progress(db_session, client):
    """存量库里可能留有 kind=sign（早期「签字提醒」）的留痕：详情照常返回这一行，展示标签兜底为「历史通知」；
    进度里已没有签字这一步，这类留痕也不参与判断。"""
    assert ContractNoticeLog.KIND_LABELS.get("sign", ContractNoticeLog.LEGACY_KIND_LABEL) == "历史通知"
    contract = await _contract(
        db_session, await _employee(db_session), status="renewing", dept_decision="agree",
        stamped_at=STAMPED, delivered_at=DELIVERED,
    )
    db_session.add(ContractNoticeLog(
        contract_id=contract.id, kind="sign", status="sent", recipient_name="张三",
        created_at=datetime(2027, 1, 6, 10, 0, tzinfo=UTC),
    ))
    await db_session.flush()

    body = (await client.get(f"{API}/labor-contracts/{contract.id}")).json()["data"]
    assert [(n["kind"], n["status"]) for n in body["notices"]] == [("sign", "sent")]
    progress = body["progress"]
    assert [step["key"] for step in progress] == [
        "expiry_alert", "dept_approval", "renew_notice", "stamp", "deliver", "archive",
    ]
    # 续签通知没发过：仍是当前步（不会被早期的签字留痕顶掉）；已领取未归档：归档也是当前步
    assert [step["state"] for step in progress] == ["done", "done", "current", "done", "done", "current"]


@pytest.mark.asyncio
async def test_notice_skipped_when_employee_profile_is_missing(db_session, client, monkeypatch):
    """合同对应的员工已不在档案里：不发送、不报错，留痕为跳过并写明原因。"""
    monkeypatch.setattr(notify, "_send", _Capture())
    orphan = LaborContract(
        employee_number=_number(), name="无档员工", department=f"无档{uuid4().hex[:6]}", seq_no=1,
        term_type=LaborContract.TERM_FIXED_3Y, term_years=3,
        start_date=TODAY - timedelta(days=100), end_date=TODAY + timedelta(days=900),
        sign_date=TODAY - timedelta(days=100),
    )
    db_session.add(orphan)
    await db_session.flush()

    res = await client.post(f"{API}/labor-contracts/{orphan.id}/stamp")

    assert res.status_code == 200, res.text
    assert res.json()["data"]["notice"] == {
        "status": "skipped", "error": "员工档案不存在", "recipient_name": None,
    }
    assert await _notices(db_session, orphan.id) == [("collect", "skipped", None, "员工档案不存在")]


@pytest.mark.asyncio
async def test_no_authorized_department_means_empty_stats_and_list(db_session, client, test_user, monkeypatch):
    """部门范围但解析不到任何授权部门：统计全为 0、列表为空（空范围不等于全量）。"""
    await _contract(db_session, await _employee(db_session), status="pending_renewal")
    test_user.department = None
    monkeypatch.setattr(
        "app.platform.permission.repository.PermissionRepository.get_effective_data_scope",
        AsyncMock(return_value="department"),
    )

    res = await client.get(f"{API}/labor-contracts/stats")
    assert res.status_code == 200, res.text
    assert set(res.json()["data"].values()) == {0}
    numbers, total = await _numbers(client, {})
    assert (numbers, total) == (set(), 0)


@pytest.mark.asyncio
async def test_todo_attention_lists_everything_that_needs_action(db_session, client):
    """todo=attention = 五项待办（待部门审批 / 待续签 / 待盖章 / 待领取 / 待归档）的并集：
    合同页默认的「需要处理」视图用它，不再先看到一屏历史合同；正常履约的、「到期未续签」这类
    存量提示、以及已经归档（流程走完）的都不在里面。"""
    department = f"待办合计{uuid4().hex[:6]}"

    async def row(**overrides) -> LaborContract:
        return await _contract(db_session, await _employee(db_session, department=department), **overrides)

    inside = {
        (await row(status="pending_renewal")).employee_number,  # 待部门审批
        (await row(status="renewing", dept_decision="agree")).employee_number,  # 待续签
        (await row(origin="renewal")).employee_number,  # 待盖章
        (await row(origin="renewal", stamped_at=STAMPED)).employee_number,  # 待领取
        # 待归档：不看来源，存量合同领了没归档同样算
        (await row(stamped_at=STAMPED, delivered_at=DELIVERED)).employee_number,
    }
    await row(status="active")  # 正常履约
    await row(status="expired_unrenewed")  # 存量提示，不算待办
    await row(  # 已领取并归档：流程走完
        stamped_at=STAMPED, delivered_at=DELIVERED,
        archive_status=LaborContract.ARCHIVE_ARCHIVED, archive_uploaded_at=ARCHIVED,
    )

    numbers, total = await _numbers(client, {"todo": "attention", "department": department})

    assert (numbers, total) == (inside, 5)
