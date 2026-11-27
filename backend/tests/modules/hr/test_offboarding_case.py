"""离职管理（OffboardingCase 状态机）— 业务规则测试。

覆盖：建单快照与台账关联、体检门禁、站内降级全链路到办结、当面手写签名 / 纸质签收两种签收、
取消时撤下台账行、飞书审批轮询回写（mock）、清退表单回读、节点提醒扫描规则。
走 service 层 + API（真实 DB 回滚）；飞书 / 邮件 / 对象存储一律打桩，不外连不落盘。
"""

import base64
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException
from app.modules.hr.models import (
    DepartureRecord,
    EmployeeCertificate,
    OnboardingRecord,
    SystemSetting,
    TrainingRosterProfile,
)
from app.modules.hr.offboarding import approval, clearance, reminders, service
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding.models import OffboardingCase
from app.modules.hr.schemas import EmployeeCreate
from app.modules.hr.service import EmployeeService
from tests.modules.hr.conftest import _rand

# 合法签名：PNG 文件头的 base64 dataURL
PNG_SIGNATURE = "data:image/png;base64," + base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + bytes(16)
).decode()
FEISHU_FORM = [{"id": "w1", "type": "input", "name": "姓名"}]
FEISHU_DEFINITION = {
    "approval_name": "离职审批", "status": "ACTIVE", "form": FEISHU_FORM,
    "node_list": [{"node_id": "node_1", "need_approver": True}],
}


# ── 夹具与辅助 ──

@pytest.fixture(autouse=True)
def _no_real_feishu_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """本文件一律不访问真实飞书审批接口（本地后端接的是真实凭证）。

    定义加载默认按「不可用」处理（发起环节走降级分支）；创建实例 / 拉取实例
    默认直接报错，需要它们的用例自行打桩覆盖。
    """

    async def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("测试中禁止访问真实飞书审批接口，请打桩 create_instance / get_instance")

    monkeypatch.setattr(approval, "load_definition", AsyncMock(return_value=None))
    monkeypatch.setattr(approval, "create_instance", _forbidden)
    monkeypatch.setattr(approval, "get_instance", _forbidden)
    monkeypatch.setattr(approval, "list_instance_codes", _forbidden)


@pytest.fixture(autouse=True)  # 自动生效：本文件与引用了本夹具的台账测试都不会往 uploads/ 落文件
def object_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[bytes, str]]:
    """对象存储打桩：进程内字典，测试不往 uploads/ 或 MinIO 落文件。

    autouse 是必须的：pytest.mark.usefixtures 对「夹具函数」不生效，只对测试函数生效——
    曾把它挂在台账测试的 seeded 夹具上，结果每跑一轮就往 uploads/ 写 20 多个真实 PDF。
    """
    store: dict[str, tuple[bytes, str]] = {}

    def put(module: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        store[f"{module}/{key}"] = (data, content_type)
        return key

    def get(module: str, key: str) -> tuple[bytes, str] | None:
        return store.get(f"{module}/{key}")

    for module in ("case", "certify"):
        monkeypatch.setattr(f"app.modules.hr.offboarding.service.{module}.store_object", put)
        monkeypatch.setattr(f"app.modules.hr.offboarding.service.{module}.read_object", get)
    return store


@pytest.fixture(autouse=True)  # 自动生效：任何用例都不可能发出真实邮件
def no_mail(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """邮件发送打桩（本地后端接的是真实 SMTP 配置，测试一律不发）。"""
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr("app.modules.hr.offboarding.delivery.send_email", sender)
    return sender


async def _set_settings(db: AsyncSession, **kv: str) -> None:
    """在测试事务内写系统配置（回滚后不影响库里的真实配置）。"""
    for key, value in kv.items():
        row = (await db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )).scalars().first()
        if row:
            row.value, row.is_deleted = value, False
        else:
            db.add(SystemSetting(key=key, value=value))
    await db.flush()


async def _make_employee(
    db: AsyncSession, *, status: str = "在职", level: str = "S5",
    key_position: bool = False, name: str | None = None,
):
    employee = await EmployeeService(db).create_employee(EmployeeCreate(
        employee_number=_rand("OB"),
        name=name or f"离职测试{_rand()}",
        department=_rand("离职部"),
        position="操作工",
        hire_date=date(2020, 3, 1),
        level=level,
    ))
    employee.status = status
    employee.is_key_position = key_position
    await db.flush()
    return employee


async def _create_case(db: AsyncSession, employee, *, days_ahead: int = 40) -> OffboardingCase:
    return await service.create_case(
        db, employee_id=employee.id,
        offboarding_date=date.today() + timedelta(days=days_ahead),
        initiator_name="HR甲", remark="建单备注",
    )


async def _to_clearing(db: AsyncSession, case: OffboardingCase) -> OffboardingCase:
    """未配置飞书审批：建单 → 发起 → 站内登记审批办结，停在清退阶段。"""
    case, _warning = await service.submit_approval(db, case)
    return await service.manual_stage_done(db, case, stage="approving")


async def _to_cert_issuing(db: AsyncSession, case: OffboardingCase) -> OffboardingCase:
    case = await _to_clearing(db, case)
    return await service.manual_stage_done(db, case, stage="clearing")


# ═══════════════════════════════════════════════════════════════
# 建单
# ═══════════════════════════════════════════════════════════════

async def test_create_case_snapshots_employee_and_links_ledger(db_session: AsyncSession):
    """建单：档案快照落单、按职级定审批轨、同时落一行离职台账并关联（发起人与备注留存）。"""
    employee = await _make_employee(db_session)
    case = await _create_case(db_session, employee)

    assert case.status == OffboardingCase.STATUS_DRAFT
    assert case.approval_track == "staff"
    assert case.employee_category == "转正员工"
    assert case.initiator_name == "HR甲" and case.remark == "建单备注"
    assert case.health_check_required is False
    assert re.fullmatch(r"LB-\d{8}-\d{4}", case.case_no)

    record = await repo.get_departure_record(db_session, case.departure_record_id)
    assert record is not None
    assert record.employee_number == employee.employee_number
    assert record.offboarding_date == case.offboarding_date
    assert record.feishu_record_id is None  # 平台建的行，尚未被飞书同步认领


async def test_create_case_routes_director_track_and_derives_category(db_session: AsyncSession):
    """M5+ 走总监轨；用工类型：台账「员工性质」优先，没有则按档案状态推导。"""
    director = await _make_employee(db_session, level="M6")
    case = await _create_case(db_session, director)
    assert case.approval_track == "director" and case.employee_category == "转正员工"

    probation = await _make_employee(db_session, status="试用期")
    db_session.add(DepartureRecord(
        name=probation.name, employee_number=probation.employee_number,
        department=probation.department, position=probation.position,
        employee_category="实习转试用",
    ))
    await db_session.flush()
    case2 = await _create_case(db_session, probation)
    assert case2.employee_category == "实习转试用"


async def test_create_case_rejects_departed_and_duplicate(db_session: AsyncSession):
    departed = await _make_employee(db_session, status="离职")
    with pytest.raises(AppException):
        await _create_case(db_session, departed)

    active = await _make_employee(db_session)
    await _create_case(db_session, active)
    with pytest.raises(DuplicateException):
        await _create_case(db_session, active)


async def test_cancel_withdraws_platform_ledger_row(db_session: AsyncSession):
    """取消：平台建的台账行撤下（在职员工不能挂在离职台账里），员工档案不变，可重新发起。"""
    employee = await _make_employee(db_session)
    case = await _create_case(db_session, employee)
    record_id = case.departure_record_id

    case = await service.cancel_case(db_session, case)
    assert case.status == OffboardingCase.STATUS_CANCELED
    assert await repo.get_departure_record(db_session, record_id) is None
    assert employee.status == "在职"

    with pytest.raises(AppException):
        await service.cancel_case(db_session, case)  # 重复取消
    again = await _create_case(db_session, employee)
    assert again.status == OffboardingCase.STATUS_DRAFT


async def test_cancel_keeps_feishu_synced_ledger_row(db_session: AsyncSession):
    """台账行已被飞书同步认领（有 feishu_record_id）：是源表数据，取消时不动。"""
    employee = await _make_employee(db_session)
    case = await _create_case(db_session, employee)
    record = await repo.get_departure_record(db_session, case.departure_record_id)
    record.feishu_record_id = "rec123"
    await db_session.flush()

    await service.cancel_case(db_session, case)
    assert await repo.get_departure_record(db_session, record.id) is not None


# ═══════════════════════════════════════════════════════════════
# 体检门禁 / 提前天数
# ═══════════════════════════════════════════════════════════════

async def test_health_check_gate(db_session: AsyncSession):
    """重点岗位：未登记离岗体检不能发起审批；登记后放行；发起后不能撤销登记。"""
    employee = await _make_employee(db_session, key_position=True)
    case = await _create_case(db_session, employee)
    assert case.health_check_required is True

    with pytest.raises(AppException, match="离岗体检"):
        await service.submit_approval(db_session, case)

    case = await service.register_health_check(db_session, case, done=True, check_date=date.today())
    assert case.health_check_done is True and case.health_check_date == date.today()
    case, _ = await service.submit_approval(db_session, case)
    assert case.status == OffboardingCase.STATUS_APPROVING

    with pytest.raises(AppException, match="不能撤销"):
        await service.register_health_check(db_session, case, done=False)


async def test_health_check_rejects_future_date_and_fake_file(db_session: AsyncSession):
    employee = await _make_employee(db_session, key_position=True)
    case = await _create_case(db_session, employee)
    with pytest.raises(AppException, match="不能晚于今天"):
        await service.register_health_check(db_session, case, done=True, check_date=date.today() + timedelta(days=1))
    with pytest.raises(AppException):  # 扩展名是 pdf 但内容不是 PDF
        await service.register_health_check(
            db_session, case, done=True, file_name="报告.pdf", file_bytes=b"not a pdf",
        )


async def test_lead_time_warning_without_blocking(db_session: AsyncSession):
    """提前天数不足只提示不拦截（存在协商离职）；试用期 3 天、转正 30 天。"""
    employee = await _make_employee(db_session)
    case = await _create_case(db_session, employee, days_ahead=10)
    case, warning = await service.submit_approval(db_session, case)
    assert case.status == OffboardingCase.STATUS_APPROVING
    assert warning is not None and "转正员工" in warning and "30" in warning

    probation = await _make_employee(db_session, status="试用期")
    case2 = await _create_case(db_session, probation, days_ahead=4)
    _case2, warning2 = await service.submit_approval(db_session, case2)
    assert warning2 is None


# ═══════════════════════════════════════════════════════════════
# 全链路（站内降级）
# ═══════════════════════════════════════════════════════════════

async def test_manual_flow_office_signature_to_closed(
    db_session: AsyncSession, object_store: dict, no_mail: AsyncMock,
):
    """站内降级全链路：建单 → 发起 → 审批 → 清退（默认清单）→ 开证（邮件送达，不带链接）
    → 员工到人事办公室在公司电脑上手写签名 → 办结五联动。"""
    employee = await _make_employee(db_session)
    db_session.add(EmployeeCertificate(
        employee_id=employee.id, category="身份证", storage_key="k", filename="a.jpg",
        content_type="image/jpeg", size=10, is_current=True,
    ))
    await db_session.flush()

    case = await _create_case(db_session, employee)
    case, warning = await service.submit_approval(db_session, case)
    assert case.status == OffboardingCase.STATUS_APPROVING
    assert case.resignation_instance_code is None  # 未配置飞书审批 → 等站内登记
    assert warning is None

    case = await service.manual_stage_done(db_session, case, stage="approving", note="部门已批")
    assert case.status == OffboardingCase.STATUS_CLEARING and case.resignation_finished_at is not None
    assert case.remark == "建单备注；站内登记（部门审批中）：部门已批"  # 追加不覆盖
    items = await repo.list_clearance_items(db_session, case.id)
    assert len(items) == 20  # 四部门默认清单 7+3+5+5（需求列明的清退事项）
    assert {i.category for i in items} == {"admin", "finance", "hr", "work"}
    assert all(i.source == "seed" and i.status == "pending" for i in items)

    saved = await service.replace_clearance_items(db_session, case, [
        {"category": "admin", "item_name": "宿舍钥匙", "status": "confirmed", "confirmed_by": "后勤乙"},
        {"category": "finance", "item_name": "借款", "status": "deducted",
         "deduction_amount": "200.50", "supplement_amount": 0, "remark": "工资抵扣"},
    ])
    assert [(i.category, i.status, i.source) for i in saved] == [
        ("admin", "confirmed", "manual"), ("finance", "deducted", "manual"),
    ]
    assert saved[1].deduction_amount == Decimal("200.50") and saved[0].confirmed_by == "后勤乙"
    assert len(await repo.list_clearance_items(db_session, case.id)) == 2  # 旧默认行已软删

    case = await service.manual_stage_done(db_session, case, stage="clearing")
    assert case.status == OffboardingCase.STATUS_CERT_ISSUING

    case, note = await service.issue_certificate(
        db_session, case, mail_recipient="a@b.com", issued_by="HR甲",
    )
    assert case.status == OffboardingCase.STATUS_DELIVERING
    assert case.cert_template == "electronic" and case.cert_issued_by == "HR甲"
    assert case.mail_status == "sent" and no_mail.await_count == 1
    assert note == ""  # 邮件发出去了，没有需要提醒的事
    assert f"hr/offboarding/{case.id}/termination_certificate_electronic.pdf" in object_store

    record = await repo.get_departure_record(db_session, case.departure_record_id)
    assert record.cert_issued_at is not None
    assert record.cert_sign_status is None and record.cert_signed_at is None  # 开证不等于签收

    case = await service.register_signature(
        db_session, case, signature=PNG_SIGNATURE, signed_name=employee.name,
    )
    assert case.status == OffboardingCase.STATUS_SIGNED
    assert case.delivery_channel == "handwriting"
    signed_record = await repo.get_departure_record(db_session, case.departure_record_id)
    assert signed_record.cert_sign_status == "signed"
    assert signed_record.cert_signed_at is not None and signed_record.cert_sign_name == employee.name
    assert signed_record.cert_sign_image == PNG_SIGNATURE
    with pytest.raises(AppException):  # 已签收，不能再签
        await service.register_signature(db_session, case, signature=PNG_SIGNATURE)

    case = await service.close_case(db_session, case, account_deactivated=True)
    assert case.status == OffboardingCase.STATUS_CLOSED and case.closed_at is not None
    assert case.account_deactivated is True

    # 五联动：档案 / 证件 / 花名册 / 入职台账 / 离职台账
    assert employee.status == "离职" and employee.departure_date == case.offboarding_date
    certificate = (await db_session.execute(
        select(EmployeeCertificate).where(EmployeeCertificate.employee_id == employee.id)
    )).scalars().one()
    assert certificate.is_current is False
    roster = (await db_session.execute(
        select(TrainingRosterProfile).where(TrainingRosterProfile.employee_number == employee.employee_number)
    )).scalars().one()
    assert roster.status == "离职"
    onboarding = (await db_session.execute(
        select(OnboardingRecord).where(OnboardingRecord.employee_number == employee.employee_number)
    )).scalars().all()
    assert onboarding and all(row.is_employed == "否" for row in onboarding)
    final = await repo.get_departure_record(db_session, case.departure_record_id)
    assert final.offboarding_date == case.offboarding_date
    assert final.offboarding_type == case.offboarding_type

    with pytest.raises(AppException):  # 重复办结
        await service.close_case(db_session, case)


async def test_paper_template_signs_in_person(
    db_session: AsyncSession, object_store: dict,
):
    """纸质两联版：员工在纸质件上签字，HR 登记签收（时间 / 签收人 / 方式留存）。"""
    case = await _to_cert_issuing(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ))
    case, note = await service.issue_certificate(db_session, case, cert_template="paper")
    assert case.status == OffboardingCase.STATUS_DELIVERING and note == "未填写送达邮箱，证明未自动发送"
    assert f"hr/offboarding/{case.id}/termination_certificate_paper.pdf" in object_store
    record = await repo.get_departure_record(db_session, case.departure_record_id)
    assert record.cert_sign_status is None  # 开证不等于签收

    case = await service.register_paper_sign(db_session, case, signed_by="  员工亲笔  ")
    assert case.status == OffboardingCase.STATUS_SIGNED
    assert case.paper_signed_by == "员工亲笔" and case.paper_signed_at is not None
    assert case.delivery_channel == "paper"
    record = await repo.get_departure_record(db_session, case.departure_record_id)
    assert record.cert_sign_status == "signed" and record.cert_signed_at == case.paper_signed_at
    assert record.cert_sign_image is None  # 纸质签字不留签名图


async def test_register_sms_records_send_and_resend_mail(
    db_session: AsyncSession, object_store: dict, no_mail: AsyncMock,
):
    """短信闭环（通道未真接）：登记短信 = 记下号码与发送时间；补发邮件只带证明附件、
    邮件失败时把原因带回（面板顶部逐条提醒）。"""
    case = await _to_cert_issuing(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ))
    case, _note = await service.issue_certificate(db_session, case)

    case = await service.register_sms_sent(db_session, case, phone="13800000000")
    assert case.sms_phone == "13800000000" and case.sms_status == "manual"
    assert case.sms_sent_at is not None

    case, note = await service.resend_delivery(db_session, case, mail_recipient="a@b.com")
    assert note == "" and case.mail_status == "sent" and no_mail.await_count == 1
    # 打桩的邮件函数只收 to / subject / html_body / attachments / session：正文里没有签署链接可带
    kwargs = no_mail.await_args.kwargs
    assert "sign_url" not in kwargs and "签署链接" not in kwargs["html_body"]

    no_mail.side_effect = RuntimeError("SMTP 未配置")
    case, note = await service.resend_delivery(db_session, case, mail_recipient="a@b.com")
    assert case.mail_status == "failed" and note.startswith("邮件发送失败：SMTP 未配置")


async def test_register_signature_validates_payload_and_stage(db_session: AsyncSession, object_store: dict):
    """当面手写签名：只认 PNG/JPEG dataURL，且只在「证明送达中」可登记。"""
    case = await _to_cert_issuing(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ))
    with pytest.raises(AppException, match="证明送达中"):
        await service.register_signature(db_session, case, signature=PNG_SIGNATURE)
    case, _note = await service.issue_certificate(db_session, case)
    with pytest.raises(AppException, match="签名数据格式"):
        await service.register_signature(
            db_session, case, signature="data:text/html;base64,PHNjcmlwdD4=",
        )
    with pytest.raises(AppException, match="签名数据格式"):
        await service.register_signature(db_session, case, signature=PNG_SIGNATURE[:-4] + "!!!!")
    assert case.status == OffboardingCase.STATUS_DELIVERING  # 被拒的签名不落任何东西
    record = await repo.get_departure_record(db_session, case.departure_record_id)
    assert record.cert_sign_status is None

    # 签署人姓名留空取员工姓名
    case = await service.register_signature(db_session, case, signature=PNG_SIGNATURE, signed_name="  ")
    record = await repo.get_departure_record(db_session, case.departure_record_id)
    assert record.cert_sign_name == case.name


async def test_clearance_validation_saves_nothing_on_error(db_session: AsyncSession):
    case = await _to_clearing(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ))
    before = await repo.list_clearance_items(db_session, case.id)
    with pytest.raises(AppException):
        await service.replace_clearance_items(db_session, case, [
            {"category": "admin", "item_name": "宿舍钥匙", "status": "confirmed"},
            {"category": "legal", "item_name": "法务", "status": "confirmed"},
        ])
    with pytest.raises(AppException):
        await service.replace_clearance_items(db_session, case, [
            {"category": "admin", "item_name": "借款", "status": "deducted", "deduction_amount": "-5"},
        ])
    with pytest.raises(AppException):
        await service.replace_clearance_items(db_session, case, [{"category": "admin", "item_name": "  "}])
    assert await repo.list_clearance_items(db_session, case.id) == before


async def test_state_guards(db_session: AsyncSession):
    """状态机守卫：越级推进、错误阶段登记一律拒绝。"""
    case = await _create_case(db_session, await _make_employee(db_session))
    with pytest.raises(AppException):
        await service.manual_stage_done(db_session, case, stage="clearing")
    with pytest.raises(AppException):
        await service.close_case(db_session, case)
    with pytest.raises(AppException):
        await service.issue_certificate(db_session, case)
    with pytest.raises(AppException):
        await service.manual_stage_done(db_session, case, stage="whatever")
    case = (await service.submit_approval(db_session, case))[0]
    with pytest.raises(AppException):  # 不能重复发起
        await service.submit_approval(db_session, case)


# ═══════════════════════════════════════════════════════════════
# 飞书审批编排（mock）
# ═══════════════════════════════════════════════════════════════

async def _submit_with_instance(db: AsyncSession, case: OffboardingCase, stage: str) -> OffboardingCase:
    """把单据直接摆到「已发起飞书实例」的状态。"""
    await _set_settings(db, **{
        "hr_offboarding.resignation_approval_code_staff": "CODE-R",
        "hr_offboarding.clearance_approval_code_staff": "CODE-C",
    })
    case = (await service.submit_approval(db, case))[0]
    if stage == "clearance":
        case = await service.manual_stage_done(db, case, stage="approving")
    if stage == "resignation":
        case.resignation_instance_code = "INST-R"
    else:
        case.clearance_instance_code = "INST-C"
    await db.flush()
    return case


async def test_sync_resignation_approved_advances_to_clearing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """轮询：离职审批通过 → 清退阶段 + 默认清单；清退未接飞书则留站内登记。"""
    monkeypatch.setattr(approval, "get_instance", AsyncMock(return_value={"status": "APPROVED", "form": []}))
    monkeypatch.setattr(approval, "create_instance", AsyncMock(return_value="INST-C"))
    case = await _submit_with_instance(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ), "resignation")

    counts = await approval.sync_pending_results(db_session)
    assert counts == {"resignation_approved": 1}
    case = await repo.get_case(db_session, case.id)
    assert case.status == OffboardingCase.STATUS_CLEARING and case.resignation_finished_at is not None
    assert case.clearance_instance_code is None  # 清退交接未配置定义编码
    assert len(await repo.list_clearance_items(db_session, case.id)) == 20


async def test_sync_resignation_rejection_cancels_case(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(approval, "get_instance", AsyncMock(return_value={"status": "REJECTED", "form": []}))
    case = await _submit_with_instance(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ), "resignation")

    assert await approval.sync_pending_results(db_session) == {"resignation_rejected": 1}
    case = await repo.get_case(db_session, case.id)
    assert case.status == OffboardingCase.STATUS_CANCELED
    assert "飞书审批不同意" in case.remark


async def test_sync_resignation_withdrawn_returns_to_draft(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """审批在飞书被撤销：清实例退回待发起，可重新发起。"""
    monkeypatch.setattr(approval, "get_instance", AsyncMock(return_value={"status": "CANCELED", "form": []}))
    case = await _submit_with_instance(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ), "resignation")

    assert await approval.sync_pending_results(db_session) == {"resignation_canceled": 1}
    case = await repo.get_case(db_session, case.id)
    assert case.status == OffboardingCase.STATUS_DRAFT and case.resignation_instance_code is None
    assert await approval.sync_pending_results(db_session) == {}  # 不再被轮询


async def test_sync_clearance_approved_reads_form_into_items(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """清退会签办结：按控件名回读明细；该部门未动过的默认行撤掉，其它部门默认行保留。"""
    monkeypatch.setattr(approval, "get_instance", AsyncMock(return_value={
        "status": "APPROVED",
        "form": [
            {"id": "w1", "type": "input", "name": "姓名", "value": "张三"},
            {"id": "w2", "type": "textarea", "name": "行政后勤清退事项",
             "value": "宿舍钥匙｜已清退\n餐卡｜有扣补｜50｜｜卡内余额扣款\n个人物品"},
            {"id": "w3", "type": "number", "name": "财务扣款金额", "value": "120"},
        ],
    }))
    case = await _submit_with_instance(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ), "clearance")

    assert await approval.sync_pending_results(db_session) == {"clearance_approved": 1}
    case = await repo.get_case(db_session, case.id)
    assert case.status == OffboardingCase.STATUS_CERT_ISSUING and case.clearance_finished_at is not None
    rows = await repo.list_clearance_items(db_session, case.id)
    by_category: dict[str, list] = {}
    for row in rows:
        by_category.setdefault(row.category, []).append(row)
    assert [(r.item_name, r.status, r.deduction_amount) for r in by_category["admin"]] == [
        ("宿舍钥匙", "confirmed", None), ("餐卡", "deducted", Decimal("50.00")), ("个人物品", "confirmed", None),
    ]
    # 金额列 numeric(12,2)，读回固定两位小数
    assert [(r.item_name, r.deduction_amount) for r in by_category["finance"]] == [("扣补结算", Decimal("120.00"))]
    # 人力资源 / 工作部门没有回读明细：默认清单留着等 HR 确认
    assert [r.item_name for r in by_category["hr"]] == [
        "社保医保公积金", "厂牌考勤卡", "培训费", "违约金", "工资结算至",
    ]
    assert {r.source for r in by_category["admin"] + by_category["finance"]} == {"feishu_form"}


async def test_sync_clearance_rejection_keeps_case_in_clearing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """清退会签被退回：离职审批早已通过，不能作废整单——留在清退阶段等 HR 处理。"""
    monkeypatch.setattr(approval, "get_instance", AsyncMock(return_value={"status": "REJECTED", "form": []}))
    case = await _submit_with_instance(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ), "clearance")

    assert await approval.sync_pending_results(db_session) == {"clearance_rejected": 1}
    case = await repo.get_case(db_session, case.id)
    assert case.status == OffboardingCase.STATUS_CLEARING
    assert case.clearance_instance_code is None and "被退回" in case.remark
    # 之后由 HR 站内登记办结
    case = await service.manual_stage_done(db_session, case, stage="clearing")
    assert case.status == OffboardingCase.STATUS_CERT_ISSUING


async def test_sync_skips_pending_and_isolates_failures(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """未办结的实例不动；某张单回写抛异常只回滚该条，后面的单照常处理。"""
    first = await _submit_with_instance(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ), "resignation")
    second = await _submit_with_instance(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ), "resignation")
    second.resignation_instance_code = "INST-R2"
    await db_session.flush()

    monkeypatch.setattr(approval, "get_instance", AsyncMock(return_value={"status": "PENDING", "form": []}))
    assert await approval.sync_pending_results(db_session) == {}
    assert (await repo.get_case(db_session, first.id)).status == OffboardingCase.STATUS_APPROVING

    async def _by_code(instance_code: str, **kwargs) -> dict:
        if instance_code == "INST-R":
            raise RuntimeError("boom")
        return {"status": "APPROVED", "form": []}

    monkeypatch.setattr(approval, "get_instance", _by_code)
    monkeypatch.setattr(approval, "create_instance", AsyncMock(return_value="INST-C2"))
    assert await approval.sync_pending_results(db_session) == {"resignation_approved": 1}
    # 抛异常的那条原样留在审批中（下一轮重试），另一条正常推进
    assert (await repo.get_case(db_session, first.id)).status == OffboardingCase.STATUS_APPROVING
    assert (await repo.get_case(db_session, second.id)).status == OffboardingCase.STATUS_CLEARING


async def test_initiate_uses_operator_as_initiator_when_employee_has_no_feishu(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """员工没有飞书身份时，审批实例发起人取点「发起」的 HR，而不是审批人自己
    （发起人 = 审批人会被飞书判为同人自动通过）。"""
    await _set_settings(db_session, **{"hr_offboarding.resignation_approval_code_staff": "CODE-R"})
    monkeypatch.setattr(approval, "load_definition", AsyncMock(return_value=FEISHU_DEFINITION))
    monkeypatch.setattr(approval, "resolve_approver_open_id", AsyncMock(return_value="ou_approver"))
    create = AsyncMock(return_value="INST-9")
    monkeypatch.setattr(approval, "create_instance", create)

    case = await _create_case(db_session, await _make_employee(db_session))
    result = await approval.initiate_resignation(db_session, case, operator_open_id="ou_hr")

    assert result.ok and result.unconfigured is False
    assert create.await_args.kwargs["initiator_open_id"] == "ou_hr"
    assert create.await_args.kwargs["node_approver_open_id_list"] == [
        {"key": "node_1", "value": ["ou_approver"]},
    ]
    assert create.await_args.kwargs["uuid"] == f"ob-resignation-{case.id}-1"
    form = create.await_args.kwargs["form"]
    # 定义里只有「姓名」控件：按定义控件填值，没有的控件跳过
    assert json.loads(form) == [{"id": "w1", "type": "input", "value": case.name}]


async def test_initiate_unconfigured_is_not_a_failure(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    """未配置定义编码 = 设计内的降级路径：不调飞书、不按失败报警。"""
    create = AsyncMock(return_value="INST")
    monkeypatch.setattr(approval, "create_instance", create)
    case = await _create_case(db_session, await _make_employee(db_session))
    result = await approval.initiate_resignation(db_session, case)
    assert result.ok is False and result.unconfigured is True
    create.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════
# 清退表单解析（纯函数）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize(("raw", "expected"), [
    ("宿舍钥匙｜已清退", [("宿舍钥匙", "confirmed", None, None, None)]),
    ("餐卡|有扣补|50|12.5|余额", [("餐卡", "deducted", Decimal("50"), Decimal("12.5"), "余额")]),
    ("电脑\n- U盘｜待确认", [("电脑", "confirmed", None, None, None), ("U盘", "pending", None, None, None)]),
    ("工号牌｜已清退，无扣款", [("工号牌", "confirmed", None, None, None)]),  # 「无扣款」不算扣补
    ("工号牌｜无扣款", [("工号牌", "confirmed", None, None, "无扣款")]),  # 整段不是状态写法 → 备注
    ("借款｜￥1,200.50 元", [("借款", "deducted", Decimal("1200.50"), None, None)]),
    ("", []),
    (None, []),
    ([{"text": "钥匙", "type": "text"}, {"text": "｜已清退", "type": "text"}], [("钥匙", "confirmed", None, None, None)]),
])
def test_parse_items(raw, expected):
    rows = clearance.parse_items(raw, "admin")
    assert [
        (r["item_name"], r["status"], r["deduction_amount"], r["supplement_amount"], r["remark"])
        for r in rows
    ] == expected


def test_parse_items_handles_unexpected_status_word():
    """状态段不是约定写法时整段当备注，不丢数据。"""
    rows = clearance.parse_items("业务往来｜已和主管当面交接清楚", "work")
    assert rows[0]["status"] == "confirmed" and rows[0]["remark"] == "已和主管当面交接清楚"


# ═══════════════════════════════════════════════════════════════
# 节点提醒扫描规则（纯函数）
# ═══════════════════════════════════════════════════════════════

def _employee(number: str, status: str, departure_date: date | None):
    from types import SimpleNamespace

    return SimpleNamespace(
        employee_number=number, name=f"员工{number}", department="一车间",
        status=status, departure_date=departure_date,
    )


def test_pick_lead_overdue_follows_lead_time_rules():
    today = date(2026, 11, 25)
    employees = [
        _employee("A", "在职", today + timedelta(days=36)),  # 转正：36 < 30+7 → 提醒（未超期）
        _employee("B", "在职", today + timedelta(days=37)),  # 还早，不提醒
        _employee("C", "在职", today + timedelta(days=25)),  # 已超期 5 天
        _employee("D", "试用期", today + timedelta(days=8)),  # 试用期：8 < 3+7 → 提醒
        _employee("E", "试用期", today + timedelta(days=10)),  # 不提醒
        _employee("F", "在职", None),  # 未定离职日
        _employee("G", "离职", today + timedelta(days=1)),  # 已离职
        _employee("H", "在职", today + timedelta(days=1)),  # 已有进行中办理
    ]
    due = reminders.pick_lead_overdue(
        employees, {"H"}, today=today, lead_probation=3, lead_resigned=30, buffer_days=7,
    )
    assert [item.employee_number for item in due] == ["D", "C", "A"]  # 按离职日升序
    by_number = {item.employee_number: item for item in due}
    assert by_number["C"].overdue_days == 5 and by_number["A"].overdue_days == 0
    assert by_number["A"].deadline == today + timedelta(days=6)
    assert by_number["D"].lead_days == 3 and by_number["D"].probation is True


def test_pick_clearance_overdue_within_two_days():
    today = date(2026, 11, 25)

    def _case(no: str, days_left: int, label: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            case_no=no, name=no, employee_number=no, department="一车间",
            status_label=label, offboarding_date=today + timedelta(days=days_left),
        )

    due = reminders.pick_clearance_overdue(
        [_case("LB-2", 2, "清退会签中"), _case("LB-3", 3, "清退会签中"),
         _case("LB-0", 0, "离职审批中"), _case("LB-N", -1, "清退会签中")],
        today=today,
    )
    assert [item.case_no for item in due] == ["LB-N", "LB-0", "LB-2"]
    card = reminders.clearance_card(due)
    text = card["body"]["elements"][0]["content"]
    assert "今天就是离职日" in text and "已过离职日 1 天" in text and "还剩 2 天" in text


def test_lead_card_uses_configured_lead_days():
    today = date(2026, 11, 25)
    due = reminders.pick_lead_overdue(
        [_employee("A", "在职", today + timedelta(days=10))], set(),
        today=today, lead_probation=3, lead_resigned=45, buffer_days=7,
    )
    text = reminders.lead_card(due, lead_probation=3, lead_resigned=45)["body"]["elements"][0]["content"]
    assert "转正 45 天" in text and "**已超期 35 天**" in text


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

async def test_api_case_lifecycle_and_detail_flags(client, db_session: AsyncSession):
    """接口层：建单 → 详情（飞书未接的标志）→ 发起（降级提示）→ 登记 → 列表。"""
    employee = await _make_employee(db_session)
    created = await client.post("/api/v1/hr/offboarding-cases", json={
        "employee_id": str(employee.id),
        "offboarding_date": str(date.today() + timedelta(days=45)),
        "offboarding_type": "辞职",
        "reason": "个人发展",
    })
    assert created.status_code == 200, created.text
    case_id = created.json()["data"]["id"]
    assert created.json()["data"]["initiator_name"] == "HR测试员"

    detail = await client.get(f"/api/v1/hr/offboarding-cases/{case_id}")
    data = detail.json()["data"]
    assert data["status"] == "draft"
    assert data["resignation_feishu"] is False and data["clearance_feishu"] is False
    assert data["sign_state"]["cert_sign_status"] is None

    submitted = await client.post(f"/api/v1/hr/offboarding-cases/{case_id}/submit-approval")
    assert submitted.status_code == 200, submitted.text
    assert "未配置" in submitted.json()["message"]
    assert submitted.json()["data"]["status"] == "approving"

    done = await client.post(f"/api/v1/hr/offboarding-cases/{case_id}/manual-stage-done", json={
        "stage": "approving", "note": "线下已批",
    })
    assert done.json()["data"]["status"] == "clearing"
    detail = (await client.get(f"/api/v1/hr/offboarding-cases/{case_id}")).json()["data"]
    assert detail["status"] == "clearing" and len(detail["clearance_items"]) == 20

    listed = await client.get("/api/v1/hr/offboarding-cases", params={"status": "clearing"})
    assert case_id in [row["id"] for row in listed.json()["data"]]

    bad = await client.post(f"/api/v1/hr/offboarding-cases/{case_id}/manual-stage-done", json={"stage": "closing"})
    assert bad.status_code == 422


async def test_api_health_check_upload(client, db_session: AsyncSession, object_store: dict):
    employee = await _make_employee(db_session, key_position=True)
    case_id = (await client.post("/api/v1/hr/offboarding-cases", json={
        "employee_id": str(employee.id), "offboarding_date": str(date.today() + timedelta(days=30)),
    })).json()["data"]["id"]

    blocked = await client.post(f"/api/v1/hr/offboarding-cases/{case_id}/submit-approval")
    assert blocked.status_code == 400

    pdf = b"%PDF-1.4\n%%EOF"
    res = await client.post(
        f"/api/v1/hr/offboarding-cases/{case_id}/health-check",
        data={"health_check_done": "true", "health_check_date": str(date.today())},
        files={"file": ("体检报告.pdf", pdf, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["health_check_done"] is True
    assert res.json()["data"]["health_check_file_name"] == "体检报告.pdf"

    downloaded = await client.get(f"/api/v1/hr/offboarding-cases/{case_id}/health-check-file")
    assert downloaded.status_code == 200 and downloaded.content == pdf
    assert "attachment" in downloaded.headers["content-disposition"]

    assert (await client.post(f"/api/v1/hr/offboarding-cases/{case_id}/submit-approval")).status_code == 200


async def test_api_office_signature_and_no_public_sign_routes(
    client, db_session: AsyncSession, object_store: dict, no_mail: AsyncMock,
):
    """当面手写签名走登录态接口（公司电脑上由 HR 提交）；签名图随档案可查；
    免登的公开签字路由已随链接一起下线。"""
    employee = await _make_employee(db_session, name="张三")
    case = await _to_cert_issuing(db_session, await _create_case(db_session, employee))
    case, _note = await service.issue_certificate(db_session, case)

    # 旧的外部链接入口不复存在：拿着任何 token 都打不开
    assert (await client.get("/api/v1/hr/departure-cert-sign/anything")).status_code == 404
    assert (await client.post(
        "/api/v1/hr/departure-cert-sign/anything/confirm", json={"signature": PNG_SIGNATURE},
    )).status_code == 404

    bad = await client.post(
        f"/api/v1/hr/offboarding-cases/{case.id}/signature", json={"signature": "not-an-image"},
    )
    assert bad.status_code == 400

    signed = await client.post(
        f"/api/v1/hr/offboarding-cases/{case.id}/signature",
        json={"signature": PNG_SIGNATURE, "signed_name": "张三"},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["data"]["status"] == "signed"
    assert signed.json()["data"]["delivery_channel"] == "handwriting"
    assert "sign_url" not in signed.json()["data"]

    # 默认测试账号没有敏感信息权限：只告知已签，不给图（有权限给图的路径见 test_offboarding_gap_fill）
    image = await client.get(f"/api/v1/hr/offboarding-cases/{case.id}/signature-image")
    assert image.status_code == 200, image.text
    assert image.json()["data"]["masked"] is True
    assert image.json()["data"]["signed_name"] == "张三"

    detail = (await client.get(f"/api/v1/hr/offboarding-cases/{case.id}")).json()["data"]
    assert detail["sign_state"]["cert_sign_status"] == "signed"
    assert detail["sign_state"]["has_sign_image"] is True
    assert "{联系人}" in detail["sms_template"] and "{链接}" not in detail["sms_template"]


async def test_api_certificate_preview_escapes_fields(client, db_session: AsyncSession):
    employee = await _make_employee(db_session, name="李&四")
    case = await _to_cert_issuing(db_session, await _create_case(db_session, employee))
    for template in ("electronic", "paper"):
        res = await client.get(
            f"/api/v1/hr/offboarding-cases/{case.id}/certificate-preview", params={"template": template},
        )
        assert res.status_code == 200, res.text
        assert "李&四部门" not in res.text and "李&amp;四" in res.text
