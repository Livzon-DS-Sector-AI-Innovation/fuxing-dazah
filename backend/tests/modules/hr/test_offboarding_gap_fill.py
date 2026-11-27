"""离职管理缺口补齐 — 业务规则测试（对照《员工离职管理需求说明》）。

覆盖：清退默认清单与可配置、清退交接发起时点（离职日前 2 天）、M5 及以上审批轨、
短信闭环（文案模板 / 登记发送，不带链接）、交接人与部门办事员、从台账行带出建单与
「以飞书表为准」、证明版式对齐公司现行样式、当面手写签名与签名图调取、办结联动终止劳动合同。
走 service 层 + API（真实 DB 回滚）；飞书 / 邮件 / 对象存储一律打桩。
"""

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.hr.employee_sync import service as sync_service
from app.modules.hr.models import DepartureRecord, OnboardingRecord
from app.modules.hr.offboarding import approval, clearance, service
from app.modules.hr.offboarding import certificate as cert_gen
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding import settings as offboarding_settings
from app.modules.hr.offboarding.ledger import query as ledger_query
from app.modules.hr.offboarding.models import OffboardingCase
from tests.modules.hr.conftest import _ALL_HR_PERMS, _rand
from tests.modules.hr.test_offboarding_case import (  # noqa: F401 — 夹具随导入在本模块生效
    FEISHU_DEFINITION,
    PNG_SIGNATURE,
    _create_case,
    _make_employee,
    _no_real_feishu_approval,
    _set_settings,
    _to_cert_issuing,
    _to_clearing,
    no_mail,
    object_store,
)


async def _to_signed(db: AsyncSession, case: OffboardingCase) -> OffboardingCase:
    """停在「已签字确认」：开电子证明 → 员工到人事办公室在公司电脑上手写签名。"""
    case = await _to_cert_issuing(db, case)
    case, _note = await service.issue_certificate(db, case)
    return await service.register_signature(db, case, signature=PNG_SIGNATURE)


# ═══════════════════════════════════════════════════════════════
# 清退清单（需求「多部门会签」列明的 20 项，可配置）
# ═══════════════════════════════════════════════════════════════

REQUIREMENT_ITEMS = {
    "admin": ["宿舍钥匙", "寝室个人物品", "饭卡余额", "通信补贴", "车辆通行证", "办公室钥匙", "工本费"],
    "finance": ["电脑等电子设备", "U盘", "个人欠款"],
    "hr": ["社保医保公积金", "厂牌考勤卡", "培训费", "违约金", "工资结算至"],
    "work": ["业务往来", "考勤统计", "劳保用品", "工作服", "岗位技术资料"],
}


def test_default_clearance_items_cover_every_item_in_requirement():
    """默认清退清单 = 需求列明的四部门 20 项，顺序与需求一致。"""
    assert {key: list(value) for key, value in clearance.DEFAULT_ITEMS.items()} == REQUIREMENT_ITEMS


def test_clearance_items_setting_overrides_default_and_falls_back_on_bad_value():
    key = "hr_offboarding.clearance_items"
    configured = {"finance": ["电脑"], "admin": ["门禁卡"]}
    assert offboarding_settings.clearance_items(
        {key: json.dumps(configured, ensure_ascii=False)},
    ) == configured
    # 未配置 / 不是 JSON / 空清单 → 回落默认，不让一条坏配置把清退单清空
    for bad in ({}, {key: "{坏 JSON"}, {key: json.dumps({"admin": []})}, {key: "  "}):
        assert offboarding_settings.clearance_items(bad) == REQUIREMENT_ITEMS


async def test_seeded_clearance_list_follows_system_setting(db_session: AsyncSession):
    """系统配置里改了清退清单：进入清退阶段落的默认清单跟着变。"""
    configured = {"finance": ["电脑等电子设备", "U盘"], "hr": ["工资结算至"]}
    await _set_settings(db_session, **{
        "hr_offboarding.clearance_items": json.dumps(configured, ensure_ascii=False),
    })
    case = await _to_clearing(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ))
    items = await repo.list_clearance_items(db_session, case.id)
    assert sorted((i.category, i.item_name) for i in items) == sorted(
        (category, name) for category, names in configured.items() for name in names
    )


# ═══════════════════════════════════════════════════════════════
# 清退交接发起时点（离职日前 2 天）
# ═══════════════════════════════════════════════════════════════

def test_clearance_is_due_two_days_before_departure():
    case = OffboardingCase(offboarding_date=date(2026, 12, 10))
    assert clearance.clearance_due_date(case) == date(2026, 12, 8)
    assert clearance.should_defer_clearance(case, today=date(2026, 12, 6)) is True
    assert clearance.should_defer_clearance(case, today=date(2026, 12, 8)) is False
    assert clearance.should_defer_clearance(case, today=date(2026, 12, 9)) is False


def _stub_feishu_clearance(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """清退交接接上飞书（定义可用、负责人可解析），返回被创建的实例 uuid 列表。"""
    created: list[str] = []

    async def fake_create(approval_code, *, initiator_open_id, form, node_approver_open_id_list,
                          uuid, app_id, app_secret):
        created.append(uuid)
        return f"INST-{len(created)}"

    monkeypatch.setattr(approval, "load_definition", AsyncMock(return_value=FEISHU_DEFINITION))
    monkeypatch.setattr(approval, "create_instance", fake_create)
    monkeypatch.setattr(approval, "resolve_approver_open_id", AsyncMock(return_value="ou_manager"))
    return created


async def test_clearance_waits_for_due_date_when_resignation_approved_early(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """离职审批办结时还没到「离职日前 2 天」：不立即发起清退交接，挂起到期由轮询自动发起。"""
    created = _stub_feishu_clearance(monkeypatch)
    await _set_settings(db_session, **{"hr_offboarding.clearance_approval_code_staff": "CODE-C"})
    case = await _to_clearing(db_session, await _create_case(
        db_session, await _make_employee(db_session), days_ahead=30,
    ))

    assert case.status == OffboardingCase.STATUS_CLEARING
    assert case.clearance_pending is True and case.clearance_instance_code is None
    assert created == []

    due = case.offboarding_date - timedelta(days=2)
    launched = await approval.initiate_deferred_clearance(db_session, today=due - timedelta(days=1))
    assert launched == 0 and created == []  # 还没到建议发起日
    launched = await approval.initiate_deferred_clearance(db_session, today=due)
    await db_session.flush()
    assert launched == 1 and created == [f"ob-clearance-{case.id}-1"]
    case = await repo.get_case(db_session, case.id)
    assert case.clearance_instance_code == "INST-1" and case.clearance_pending is False


async def test_clearance_starts_immediately_once_due_date_reached(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """到了建议发起日（距离职日 ≤ 2 天）：登记审批办结时直接发起清退交接，不挂起。"""
    created = _stub_feishu_clearance(monkeypatch)
    await _set_settings(db_session, **{"hr_offboarding.clearance_approval_code_staff": "CODE-C"})
    case = await _to_clearing(db_session, await _create_case(
        db_session, await _make_employee(db_session), days_ahead=2,
    ))

    assert created == [f"ob-clearance-{case.id}-1"]
    assert case.clearance_instance_code == "INST-1" and case.clearance_pending is False


async def test_hr_can_start_clearance_early_by_hand(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """没到建议发起日但情况需要提前办：HR 可手动发起清退交接，挂起标记随之清除。"""
    created = _stub_feishu_clearance(monkeypatch)
    await _set_settings(db_session, **{"hr_offboarding.clearance_approval_code_staff": "CODE-C"})
    case = await _to_clearing(db_session, await _create_case(
        db_session, await _make_employee(db_session), days_ahead=30,
    ))
    assert case.clearance_pending is True

    case = await service.submit_clearance(db_session, case)
    assert created == [f"ob-clearance-{case.id}-1"]
    assert case.clearance_instance_code == "INST-1" and case.clearance_pending is False


async def test_submit_clearance_without_feishu_definition_tells_hr_to_register(
    db_session: AsyncSession,
):
    """没接飞书清退审批：没有可发起的实例，提示直接登记各部门清退情况。"""
    case = await _to_clearing(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ))
    with pytest.raises(AppException) as exc:
        await service.submit_clearance(db_session, case)
    assert "未配置" in str(exc.value)


# ═══════════════════════════════════════════════════════════════
# 审批轨：M5 及以上走总监级
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize(("level", "track"), [
    ("M4", "staff"), ("M5", "director"), ("M9", "director"), ("M12", "director"),
    ("S9", "staff"), ("P3", "staff"), ("", "staff"), (None, "staff"),
])
def test_director_track_means_m5_and_above(level: str | None, track: str):
    assert offboarding_settings.resolve_track({}, level) == track


# ═══════════════════════════════════════════════════════════════
# 短信闭环（通道未真接：文案可复制、登记发送；系统仅内网可达，短信不带链接）
# ═══════════════════════════════════════════════════════════════

def test_sms_text_follows_company_sample_without_link():
    """短信文案对齐现行样式的口吻（人力资源部联系人）；员工在手机上打不开本系统的链接，
    所以只通知「已开具、到人力资源部签收」，不带任何链接。"""
    text = offboarding_settings.render_sms_text(
        offboarding_settings.DEFAULT_SMS_TEMPLATE, contact="王琳",
    )
    assert text == (
        "你好，我是丽珠福兴人力资源部王琳，您的离职证明已经开具，"
        "请您到人力资源部签收。"
    )
    assert "链接" not in text and "http" not in text
    # 自定义模板缺占位符也不报错，原样输出
    assert offboarding_settings.render_sms_text("请联系{联系人}", contact="王琳") == "请联系王琳"


async def test_resend_with_sms_phone_registers_send(db_session: AsyncSession):
    """补发时只登记手机号：记下接收号码与发送时间，证明状态不变。"""
    case = await _to_cert_issuing(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ))
    case, _note = await service.issue_certificate(db_session, case)

    case, note = await service.resend_delivery(db_session, case, sms_phone="13800000000")
    assert note == ""
    assert case.sms_phone == "13800000000" and case.sms_status == "manual" and case.sms_sent_at
    assert case.status == OffboardingCase.STATUS_DELIVERING


async def test_register_sms_rejects_blank_phone(db_session: AsyncSession):
    case = await _create_case(db_session, await _make_employee(db_session))
    with pytest.raises(AppException):
        await service.register_sms_sent(db_session, case, phone="   ")


# ═══════════════════════════════════════════════════════════════
# 交接人 / 部门办事员
# ═══════════════════════════════════════════════════════════════

async def test_record_handover_keeps_names_on_case(db_session: AsyncSession):
    """部门审批后转办交接人与部门办事员：清退阶段登记，取消后不可再改。"""
    case = await _to_clearing(db_session, await _create_case(
        db_session, await _make_employee(db_session),
    ))
    case = await service.record_handover(
        db_session, case, handover_to="张三", dept_clerk="李四",
    )
    assert (case.handover_to, case.dept_clerk) == ("张三", "李四")

    case = await service.cancel_case(db_session, case)
    with pytest.raises(AppException):
        await service.record_handover(db_session, case, handover_to="王五")


# ═══════════════════════════════════════════════════════════════
# 从台账行发起办理 + 离职台账以飞书表为准
# ═══════════════════════════════════════════════════════════════

def _ledger_row(employee, *, days_ahead: int, synced: bool = True) -> DepartureRecord:
    return DepartureRecord(
        name=employee.name, employee_number=employee.employee_number,
        department=employee.department, position="操作工",
        offboarding_date=date.today() + timedelta(days=days_ahead), offboarding_type="合同到期",
        employee_category="转正员工",
        feishu_record_id="recGapFill" if synced else None,
    )


async def test_create_case_from_ledger_row_takes_date_and_type_from_feishu(
    db_session: AsyncSession,
):
    """从台账行发起：离职日期与类型取台账（飞书表）的值，不取弹窗里手填的值。"""
    employee = await _make_employee(db_session)
    record = _ledger_row(employee, days_ahead=25)
    db_session.add(record)
    await db_session.flush()

    case = await service.create_case(
        db_session, employee_id=employee.id,
        offboarding_date=date.today() + timedelta(days=1), offboarding_type="辞职",
        departure_record_id=record.id,
    )
    assert case.departure_record_id == record.id
    assert case.offboarding_date == record.offboarding_date
    assert case.offboarding_type == "合同到期"


async def test_feishu_synced_ledger_rows_cannot_be_edited_in_platform(
    db_session: AsyncSession,
):
    """台账行来自飞书同步：离职日期 / 类型以飞书表为准，平台不改（改了也会被整点同步改回）。"""
    employee = await _make_employee(db_session)
    record = _ledger_row(employee, days_ahead=25)
    db_session.add(record)
    await db_session.flush()
    case = await service.create_case(
        db_session, employee_id=employee.id,
        offboarding_date=record.offboarding_date, departure_record_id=record.id,
    )

    with pytest.raises(AppException) as exc:
        await service.update_case(db_session, case, offboarding_date=date.today() + timedelta(days=60))
    assert "飞书" in str(exc.value)
    with pytest.raises(AppException):
        await service.update_case(db_session, case, offboarding_type="辞职")
    # 离职原因等平台自己的字段仍可改
    case = await service.update_case(db_session, case, reason="家庭原因")
    assert case.reason == "家庭原因"


async def test_platform_owned_ledger_rows_stay_editable(db_session: AsyncSession):
    """不是飞书同步来的台账行（平台自己建的）：离职日期照常可改。"""
    employee = await _make_employee(db_session)
    record = _ledger_row(employee, days_ahead=25, synced=False)
    db_session.add(record)
    await db_session.flush()
    case = await service.create_case(
        db_session, employee_id=employee.id,
        offboarding_date=record.offboarding_date, departure_record_id=record.id,
    )
    later = record.offboarding_date + timedelta(days=3)
    case = await service.update_case(db_session, case, offboarding_date=later)
    assert case.offboarding_date == later


async def test_open_case_follows_ledger_change_after_feishu_sync(db_session: AsyncSession):
    """飞书表里改了离职日期：同步后，还在「待发起审批 / 审批中」的办理单跟着改。"""
    employee = await _make_employee(db_session)
    record = _ledger_row(employee, days_ahead=25)
    db_session.add(record)
    await db_session.flush()
    case = await service.create_case(
        db_session, employee_id=employee.id,
        offboarding_date=record.offboarding_date, departure_record_id=record.id,
    )

    new_date = record.offboarding_date + timedelta(days=10)
    stats = await sync_service.EmployeeSyncService(db_session)._reconcile_departures(
        [{"record_id": "recGapFill", "fields": {
            "工号": employee.employee_number, "姓名": employee.name,
            "离职日期": new_date.isoformat(), "离职原因": "个人原因",
        }}],
        [],
    )
    assert stats["cases_followed"] == 1
    case = await repo.get_case(db_session, case.id)
    # 飞书表的「离职原因」原话进离职原因（会写进证明正文），办结单类型归到五类里的「辞职」
    assert case.offboarding_date == new_date
    assert (case.offboarding_type, case.reason) == ("辞职", "个人原因")


async def test_ledger_rows_say_whether_a_case_can_be_started(
    db_session: AsyncSession,
):
    """台账行告诉前端：这个人能不能直接发起办理、不能的话为什么。"""
    leaving = await _make_employee(db_session)
    departed = await _make_employee(db_session, status="离职")
    db_session.add_all([
        _ledger_row(leaving, days_ahead=25), _ledger_row(departed, days_ahead=5),
        DepartureRecord(
            name="查无此人", employee_number=_rand("NO"), department="未分类",
            position="-", offboarding_date=date.today() + timedelta(days=5), offboarding_type="辞职",
        ),
    ])
    await db_session.flush()

    rows, _total = await ledger_query.query(db_session, {}, scoped=None, page_size=200)
    by_number = {row["employee_number"]: row for row in rows}

    ready = by_number[leaving.employee_number]
    assert ready["employee_id"] == str(leaving.id)
    assert ready["startable"] is True and ready["start_block_reason"] is None
    gone = by_number[departed.employee_number]
    assert gone["startable"] is False and "离职" in gone["start_block_reason"]
    missing = next(row for row in rows if row["name"] == "查无此人")
    assert missing["startable"] is False and "档案" in missing["start_block_reason"]

    # 发起后：已有进行中的办理单，台账行不再允许重复发起，并带出办理单编号
    case = await service.create_case(
        db_session, employee_id=leaving.id, offboarding_date=date.today() + timedelta(days=25),
    )
    rows, _total = await ledger_query.query(db_session, {}, scoped=None, page_size=200)
    started = next(row for row in rows if row["employee_number"] == leaving.employee_number)
    assert started["case_id"] == str(case.id)
    assert started["startable"] is False and "进行中" in started["start_block_reason"]


async def test_ledger_row_can_start_when_employee_was_soft_deleted_by_sync(db_session: AsyncSession):
    """人一进飞书离职表就从员工表移走，档案被员工同步软删——只要离职日期还没到，
    仍然可以从台账行发起办理（用软删档案的 id 建单，员工信息取台账行）。"""
    employee = await _make_employee(db_session)
    employee.is_deleted = True
    record = _ledger_row(employee, days_ahead=10)
    db_session.add(record)
    await db_session.flush()

    rows, _total = await ledger_query.query(db_session, {}, scoped=None, page_size=200)
    row = next(r for r in rows if r["employee_number"] == employee.employee_number)
    assert row["startable"] is True and row["start_block_reason"] is None
    assert row["employee_id"] == str(employee.id)

    case = await service.create_case(
        db_session, employee_id=employee.id,
        offboarding_date=record.offboarding_date, departure_record_id=record.id,
    )
    assert case.status == OffboardingCase.STATUS_DRAFT and case.employee_id == employee.id


async def test_ledger_row_past_departure_date_cannot_start(db_session: AsyncSession):
    """已经过了离职日期的台账行不能再发起办理；档案已软删的也一样。"""
    alive = await _make_employee(db_session)
    gone = await _make_employee(db_session)
    gone.is_deleted = True
    db_session.add_all([_ledger_row(alive, days_ahead=-5), _ledger_row(gone, days_ahead=-5)])
    await db_session.flush()

    rows, _total = await ledger_query.query(db_session, {}, scoped=None, page_size=200)
    by_number = {r["employee_number"]: r for r in rows}
    for number in (alive.employee_number, gone.employee_number):
        assert by_number[number]["startable"] is False
        assert "已过离职日期" in by_number[number]["start_block_reason"]

    with pytest.raises(AppException) as exc:
        await service.create_case(
            db_session, employee_id=gone.id,
            offboarding_date=date.today() - timedelta(days=5),
            departure_record_id=by_number[gone.employee_number]["id"],
        )
    assert "已过离职日期" in str(exc.value)


# ═══════════════════════════════════════════════════════════════
# 证明版式（与公司现行样式一致）
# ═══════════════════════════════════════════════════════════════

CERT_FIELDS = dict(
    name="曾志某", id_number="350823200002031615", department="提炼技术精进中心",
    position="检测员", entry_date=date(2024, 6, 5), leave_date=date(2026, 7, 1),
    leave_reason="个人原因", issued_on=date(2026, 7, 15),
)


def test_electronic_certificate_matches_company_layout():
    """电子单张版：Logo+公司名页眉、加粗编号、正文措辞、说明、落款含人力资源部。"""
    html = cert_gen.generate_electronic_html(**CERT_FIELDS)
    assert "丽珠集团福州福兴医药有限公司" in html and "HR-RE-013" in html
    assert "company_logo" in html or "data:image/png;base64," in html
    assert (
        "兹有我司原职工曾志某，身份证号 350823200002031615，2024年6月5日到我公司工作，"
        "担任提炼技术精进中心/检测员。现因个人原因，于2026年7月1日正式解除劳动关系。"
    ) in html
    assert "特此证明。" in html and "说明：" in html
    assert "员工离职后仍需履行保密义务" in html and "本证明仅开具一次" in html
    assert "2026年7月15日" in html and "人力资源部" in html


def test_paper_certificate_has_two_copies_with_receipt_block():
    """纸质两联版：同一版式两联，各带员工签收栏。"""
    html = cert_gen.generate_paper_html(**CERT_FIELDS)
    assert html.count("解除劳动关系证明") == 2
    assert "第一联" in html and "第二联" in html
    assert html.count("员工签收栏") == 2
    assert "担任提炼技术精进中心/检测员" in html


def test_certificate_escapes_field_values():
    """字段值进 HTML 前转义（预览窗与免登签字页都直接进 DOM）。"""
    html = cert_gen.generate_electronic_html(**{**CERT_FIELDS, "name": "<script>x</script>"})
    assert "<script>x</script>" not in html and "&lt;script&gt;x&lt;/script&gt;" in html


def test_certificate_pdfs_are_generated_by_both_renderers():
    assert cert_gen.generate_electronic_pdf(**CERT_FIELDS).read()[:4] == b"%PDF"
    assert cert_gen.generate_paper_pdf(**CERT_FIELDS).read()[:4] == b"%PDF"


# ═══════════════════════════════════════════════════════════════
# 接口层：详情带出联系方式 / 短信模板 / 发起时点；签名图调取；按员工取办理单
# ═══════════════════════════════════════════════════════════════

async def test_api_detail_brings_contact_prefill_and_stage_hints(client, db_session: AsyncSession):
    """详情带出档案手机号与入职台账邮箱（送达不用手填）、短信文案模板、清退建议发起日。"""
    employee = await _make_employee(db_session)
    employee.phone = "13800001234"
    db_session.add(OnboardingRecord(
        employee_number=employee.employee_number, name=employee.name, department=employee.department,
        position="操作工", hire_date=date(2020, 3, 1), email="someone@example.com",
    ))
    await db_session.flush()
    leave_date = date.today() + timedelta(days=45)
    created = await client.post("/api/v1/hr/offboarding-cases", json={
        "employee_id": str(employee.id), "offboarding_date": str(leave_date),
    })
    assert created.status_code == 200, created.text
    case_id = created.json()["data"]["id"]

    detail = (await client.get(f"/api/v1/hr/offboarding-cases/{case_id}")).json()["data"]
    assert detail["employee_phone"] == "13800001234"
    assert detail["employee_email"] == "someone@example.com"
    assert "{联系人}" in detail["sms_template"] and "{链接}" not in detail["sms_template"]
    assert detail["contact"] == "人力资源部"
    assert detail["clearance_due_date"] == (leave_date - timedelta(days=2)).isoformat()
    assert detail["ledger_synced"] is False

    listed = await client.get(f"/api/v1/hr/offboarding-cases/by-employee/{employee.employee_number}")
    assert listed.json()["data"]["case"]["id"] == case_id
    absent = await client.get("/api/v1/hr/offboarding-cases/by-employee/NO-SUCH-NUMBER-0000")
    assert absent.status_code == 200 and absent.json()["data"]["case"] is None


async def test_api_signature_image_is_masked_without_sensitive_permission(
    client, db_session: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch,
):
    """签名图可随档案调取；没有敏感信息权限时只告知已签，不给图。"""
    case = await _to_signed(db_session, await _create_case(db_session, await _make_employee(db_session)))

    masked = (await client.get(f"/api/v1/hr/offboarding-cases/{case.id}/signature-image")).json()["data"]
    assert masked["masked"] is True and masked["image"] is None
    assert masked["signed_at"] and masked["signed_name"]

    # 敏感信息权限是路由里直接调函数取的（不走依赖注入），要从取用户、取权限两处底层一起放行
    async def _current_user(request, db=None, settings=None):
        return test_user

    monkeypatch.setattr("app.platform.identity.deps.get_current_user", _current_user)
    monkeypatch.setattr(
        "app.platform.permission.deps.get_user_permissions",
        AsyncMock(return_value={*_ALL_HR_PERMS, "hr:profile:sensitive"}),
    )
    shown = (await client.get(f"/api/v1/hr/offboarding-cases/{case.id}/signature-image")).json()["data"]
    assert shown["masked"] is False and shown["image"] == PNG_SIGNATURE


# ═══════════════════════════════════════════════════════════════
# 办结联动：劳动合同随之终止
# ═══════════════════════════════════════════════════════════════

async def test_close_terminates_labor_contracts_right_away(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """办结即终止该员工的劳动合同（不等次日的合同扫描，避免继续发出续签提醒）。"""
    calls: list[tuple[str, date]] = []

    async def fake_terminate(db, *, employee_number: str, departed_on: date) -> int:
        calls.append((employee_number, departed_on))
        return 0

    monkeypatch.setattr(
        "app.modules.hr.labor_contract.departure_service.terminate_for_employee", fake_terminate,
    )
    case = await _to_signed(db_session, await _create_case(db_session, await _make_employee(db_session)))
    closed = await service.close_case(db_session, case)
    assert closed.status == OffboardingCase.STATUS_CLOSED
    assert calls == [(case.employee_number, case.offboarding_date)]
