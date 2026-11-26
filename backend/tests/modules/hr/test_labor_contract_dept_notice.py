"""部门负责人续签审批提醒：卡片正文 / 按负责人分组发送 / 公告期扫描接线 / 飞书审批撤销退回站内。

本地后端连的是真实飞书：本文件所有用例一律打桩发送层，并在模块级把
notify.send_user_card 换成一被调用就报错的桩——任何漏打桩的发送路径都会让用例失败，
而不是把卡片发给真人。
"""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract import (
    dept_notice,
    notify,
    renewal_approval,
    scheduled,
)
from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.models import Employee, HrDepartment


@pytest.fixture(autouse=True)
def _no_real_send(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _must_not_send(*args, **kwargs):
        raise AssertionError("用例触达了真实飞书发送层：请打桩 notify._send / dept_notice._send")

    monkeypatch.setattr(notify, "send_user_card", _must_not_send)


class _Capture:
    """记录卡片发送调用；open_id 在 fail_for 里的返回失败（模拟飞书发送失败）。"""

    def __init__(self, *fail_for: str) -> None:
        self.calls: list[tuple[str, str, str, object]] = []
        self._fail_for = set(fail_for)

    async def __call__(self, open_id, title, markdown, elements=None) -> bool:
        self.calls.append((open_id, title, markdown, elements))
        return open_id not in self._fail_for


def _resolver(mapping: dict[str, tuple[str | None, str | None]]):
    """按部门名返回 (负责人姓名, open_id)；不在映射里的部门一律解析不到（含库里其它真实合同）。"""
    async def resolve(db: AsyncSession, contract: LaborContract):
        return mapping.get(contract.department, (None, None))
    return resolve


def _number() -> str:
    return str(9000000 + uuid4().int % 999999)


async def _employee(db: AsyncSession, *, department: str, name: str) -> Employee:
    employee = Employee(
        employee_number=_number(), name=name, department=department,
        position="操作工", status="在职", hire_date=date.today(),
    )
    db.add(employee)
    await db.flush()
    return employee


async def _contract(
    db: AsyncSession, employee: Employee, *, days_to_expire: int, **overrides,
) -> LaborContract:
    values: dict = {
        "employee_number": employee.employee_number, "name": employee.name,
        "department": employee.department, "position": employee.position,
        "seq_no": 1, "term_type": LaborContract.TERM_FIXED_3Y, "term_years": 3,
        "start_date": date.today() - timedelta(days=400),
    }
    values.update(overrides)
    values.setdefault("end_date", date.today() + timedelta(days=days_to_expire))
    contract = LaborContract(**values)
    db.add(contract)
    await db.flush()
    return contract


def _use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """让 scheduled 里自开会话的任务改用测试事务（提交已被 HR conftest 换成 flush）。"""
    class _Scope:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(scheduled, "async_session_factory", lambda: _Scope())


# 固定的任务上下文：不读库里的真实配置，用例不受本地开关影响
_CTX = {"kv": {}, "enabled": True, "days": 50, "copy_entries": [], "dept_notice": True}


# ─── 卡片正文 ───


def test_reminder_markdown_lists_contracts_with_next_term():
    """清单列姓名/工号/部门/岗位、现合同到期与剩余天数、续签后的签订次数与期限。"""
    today = date(2027, 1, 1)
    first = LaborContract(
        name="张三", department="提炼工程一部", position="操作工", seq_no=1,
        term_type=LaborContract.TERM_FIXED_3Y, start_date=date(2024, 1, 1),
        end_date=today + timedelta(days=50),
    )
    first.employee_number = "111003118"
    second = LaborContract(
        name="李四", department="提炼工程一部", position="操作工", seq_no=2,
        term_type=LaborContract.TERM_FIXED_6Y, start_date=date(2021, 1, 1), end_date=today,
    )
    second.employee_number = "111003255"
    expired = LaborContract(
        name="王五", department="提炼工程一部", position="操作工", seq_no=2,
        term_type=LaborContract.TERM_FIXED_6Y, start_date=date(2020, 12, 30),
        end_date=today - timedelta(days=3),
    )
    expired.employee_number = "111003462"

    text = dept_notice.approval_reminder_markdown(
        [first, second, expired], today=today, note="此前的飞书审批已撤销。",
    )

    lines = text.splitlines()
    assert lines[0] == "您部门有 **3** 名员工的劳动合同已进入公告期，请审批是否续签："
    assert lines[1] == (
        "- 张三，工号 111003118，提炼工程一部，操作工；"
        "现合同 2027-02-20 到期（剩 50 天），续签为「第二次续签 · 6 年」"
    )
    assert "李四，工号 111003255" in lines[2] and "2027-01-01 到期（今天）" in lines[2]
    assert "续签为「第 3 次 · 无固定期限」" in lines[2]
    assert "王五" in lines[3] and "2026-12-29 已到期 3 天" in lines[3]
    assert "此前的飞书审批已撤销。" in lines
    assert "**同意续签**或**不同意续签**" in lines[-1]


def test_reminder_markdown_caps_long_lists():
    """卡片正文有长度上限：超过 20 人只列 20 条，其余合并成一行。"""
    contracts = []
    for i in range(25):
        contract = LaborContract(name=f"员工{i}", department="一部", seq_no=1)
        contract.employee_number = str(9000000 + i)
        contracts.append(contract)
    lines = dept_notice.approval_reminder_markdown(contracts).splitlines()
    listed = [line for line in lines if line.startswith("- 员工")]
    assert len(listed) == 20 and "员工24" not in "\n".join(listed)
    assert "- 其余 5 人请在合同台账中查看" in lines


# ─── 按负责人分组发送 ───


@pytest.mark.asyncio
async def test_notify_dept_heads_groups_by_manager(monkeypatch: pytest.MonkeyPatch):
    """同一负责人的合同合并成一张卡片；发送失败的归到 failed 交调用方处理；带台账按钮。"""
    contracts = []
    for i in range(4):
        contract = LaborContract(name=f"员工{i}", department="一部", seq_no=1)
        contract.employee_number = str(9000000 + i)
        contracts.append(contract)
    c1, c2, c3, c4 = contracts
    capture = _Capture("ou_broken")
    monkeypatch.setattr(dept_notice, "_send", capture)

    result = await dept_notice.notify_dept_heads([
        (c1, "张管理", "ou_a"), (c2, "张管理", "ou_a"),
        (c3, "李管理", "ou_b"), (c4, "王管理", "ou_broken"),
    ])

    assert [call[0] for call in capture.calls] == ["ou_a", "ou_b", "ou_broken"]
    assert all(call[1] == dept_notice.TITLE for call in capture.calls)
    assert capture.calls[0][2].startswith("您部门有 **2** 名员工")
    assert "员工0" in capture.calls[0][2] and "员工1" in capture.calls[0][2]
    assert capture.calls[1][2].startswith("您部门有 **1** 名员工")
    assert capture.calls[0][3][0]["actions"][0]["url"] == dept_notice.ledger_url()
    assert result == {
        "notified": [(c1, "张管理"), (c2, "张管理"), (c3, "李管理")],
        "failed": [(c4, "王管理")],
    }


def test_ledger_button_needs_frontend_url(monkeypatch: pytest.MonkeyPatch):
    """没配 FRONTEND_URL 就不带按钮，只留文字指引（与其它模块卡片的惯例一致）。"""
    monkeypatch.setattr(
        dept_notice, "get_settings", lambda: SimpleNamespace(FRONTEND_URL=" https://hr.example.com/ "),
    )
    assert dept_notice.ledger_url() == "https://hr.example.com/hr/labor-contracts"
    monkeypatch.setattr(dept_notice, "get_settings", lambda: SimpleNamespace(FRONTEND_URL=""))
    assert dept_notice.ledger_url() == ""


# ─── 公告期扫描接线 ───


@pytest.mark.asyncio
async def test_scan_notifies_dept_heads_and_reports_gaps_to_hr(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """合同进入公告期（站内审批）：同负责人的合同合成一张卡片；通知不到的列原因进 HR 摘要。"""
    dept_a, dept_b, dept_c = (f"负责人提醒{uuid4().hex[:6]}" for _ in range(3))
    a1 = await _contract(
        db_session, await _employee(db_session, department=dept_a, name="警甲一"), days_to_expire=10,
    )
    a2 = await _contract(
        db_session, await _employee(db_session, department=dept_a, name="警甲二"), days_to_expire=20,
    )
    b1 = await _contract(
        db_session, await _employee(db_session, department=dept_b, name="警乙"), days_to_expire=30,
    )
    c1 = await _contract(
        db_session, await _employee(db_session, department=dept_c, name="警丙"), days_to_expire=40,
    )
    monkeypatch.setattr(
        renewal_approval, "initiate", AsyncMock(return_value=(False, "未配置审批定义编码")),
    )
    monkeypatch.setattr(renewal_approval, "resolve_approver", _resolver({
        dept_a: ("张管理", "ou_test_a"),
        dept_c: ("赵管理", None),  # 有负责人但匹配不到飞书账号
    }))
    dept_cards, hr_cards = _Capture(), _Capture()
    monkeypatch.setattr(dept_notice, "_send", dept_cards)
    monkeypatch.setattr(notify, "_send", hr_cards)
    monkeypatch.setattr(scheduled, "resolve_receivers", AsyncMock(return_value=["ou_test_hr"]))

    await scheduled._run_announcement(
        db_session, days_ahead=50, copy_entries=[], dept_notice=True,
    )

    for contract in (a1, a2, b1, c1):
        assert contract.status == LaborContract.STATUS_PENDING_RENEWAL
        assert contract.approval_mode == LaborContract.APPROVAL_MANUAL

    # 负责人卡片：张管理一张（两份合同合并）；其余部门解析不到负责人，没有卡片
    assert [call[0] for call in dept_cards.calls] == ["ou_test_a"]
    _, title, markdown, elements = dept_cards.calls[0]
    assert title == dept_notice.TITLE
    assert markdown.startswith("您部门有 **2** 名员工的劳动合同已进入公告期")
    assert "警甲一" in markdown and "警甲二" in markdown and "警乙" not in markdown
    assert "剩 10 天" in markdown and "剩 20 天" in markdown
    assert elements[0]["actions"][0]["url"] == dept_notice.ledger_url()

    # HR 摘要：已通知的写明负责人，没通知到的写明原因
    assert [call[0] for call in hr_cards.calls] == ["ou_test_hr"]
    summary = hr_cards.calls[0][2]
    assert "站内待审批 · 已通知部门负责人（2 人）" in summary
    assert f"{dept_a} 警甲一（{a1.employee_number}） 到期 {a1.end_date} → 负责人 张管理" in summary
    assert "负责人未通知到" in summary
    assert f"{dept_b} 警乙（{b1.employee_number}） 到期 {b1.end_date}：部门表与员工档案均无负责人" in summary
    assert f"{dept_c} 警丙（{c1.employee_number}） 到期 {c1.end_date}：负责人「赵管理」匹配不到飞书账号" in summary


@pytest.mark.asyncio
async def test_scan_with_notice_off_keeps_hr_informed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """关掉负责人提醒：不发卡片，但 HR 摘要照常列出站内待审批的合同。"""
    contract = await _contract(
        db_session, await _employee(db_session, department=f"负责人提醒{uuid4().hex[:6]}", name="警丁"),
        days_to_expire=10,
    )
    monkeypatch.setattr(
        renewal_approval, "initiate", AsyncMock(return_value=(False, "未配置审批定义编码")),
    )
    monkeypatch.setattr(renewal_approval, "resolve_approver", _resolver({}))
    dept_cards, hr_cards = _Capture(), _Capture()
    monkeypatch.setattr(dept_notice, "_send", dept_cards)
    monkeypatch.setattr(notify, "_send", hr_cards)
    monkeypatch.setattr(scheduled, "resolve_receivers", AsyncMock(return_value=["ou_test_hr"]))

    await scheduled._run_announcement(
        db_session, days_ahead=50, copy_entries=[], dept_notice=False,
    )

    assert contract.status == LaborContract.STATUS_PENDING_RENEWAL
    assert dept_cards.calls == []
    assert "负责人提醒已关闭，请 HR 通知负责人" in hr_cards.calls[0][2]


# ─── 飞书审批撤销 → 退回站内待审批 ───


async def _feishu_pending_contract(db: AsyncSession) -> LaborContract:
    """处于「公告期 · 飞书审批中」的合同。"""
    employee = await _employee(
        db, department=f"负责人撤销{uuid4().hex[:6]}", name="警戊",
    )
    return await _contract(
        db, employee, days_to_expire=25,
        status=LaborContract.STATUS_PENDING_RENEWAL,
        approval_mode=LaborContract.APPROVAL_FEISHU,
        approval_instance_code=f"inst-{uuid4().hex[:8]}",
    )


def _wire_canceled_flow(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, mapping, dept_cards):
    monkeypatch.setattr(renewal_approval, "get_instance", AsyncMock(return_value={"status": "CANCELED"}))
    monkeypatch.setattr(renewal_approval, "resolve_approver", _resolver(mapping))
    hr_cards = _Capture()
    monkeypatch.setattr(dept_notice, "_send", dept_cards)
    monkeypatch.setattr(notify, "_send", hr_cards)
    monkeypatch.setattr(scheduled, "resolve_receivers", AsyncMock(return_value=["ou_test_hr"]))
    monkeypatch.setattr(scheduled, "_load_context", AsyncMock(return_value=dict(_CTX)))
    _use_test_session(monkeypatch, db_session)
    return hr_cards


@pytest.mark.asyncio
async def test_canceled_feishu_approval_sends_in_system_reminder(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """飞书审批被撤销：负责人的审批待办没了，补发带撤销说明的站内提醒；通知到了就不打扰 HR。"""
    contract = await _feishu_pending_contract(db_session)
    dept_cards = _Capture()
    _wire_canceled_flow(
        monkeypatch, db_session, {contract.department: ("张管理", "ou_test_a")}, dept_cards,
    )

    await scheduled.run_approval_sync()

    assert contract.status == LaborContract.STATUS_PENDING_RENEWAL  # 仍待审批，只是换到站内
    assert contract.approval_mode == LaborContract.APPROVAL_MANUAL
    assert contract.approval_instance_code is None
    assert [call[0] for call in dept_cards.calls] == ["ou_test_a"]
    assert scheduled._CANCELED_NOTE in dept_cards.calls[0][2]
    assert "剩 25 天" in dept_cards.calls[0][2]


@pytest.mark.asyncio
async def test_canceled_flow_hands_unreachable_manager_to_hr(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """退回站内但解析不到负责人：没有负责人卡片，原因写进 HR 摘要。"""
    contract = await _feishu_pending_contract(db_session)
    dept_cards = _Capture()
    hr_cards = _wire_canceled_flow(monkeypatch, db_session, {}, dept_cards)

    await scheduled.run_approval_sync()

    assert contract.approval_mode == LaborContract.APPROVAL_MANUAL
    assert dept_cards.calls == []
    assert "负责人未通知到" in hr_cards.calls[0][2]
    assert f"到期 {contract.end_date}：部门表与员工档案均无负责人" in hr_cards.calls[0][2]


@pytest.mark.asyncio
async def test_failed_push_is_handed_to_hr(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """负责人卡片发送失败：不算「已通知」，带上负责人姓名进 HR 摘要。"""
    contract = await _contract(
        db_session, await _employee(db_session, department=f"负责人提醒{uuid4().hex[:6]}", name="警壬"),
        days_to_expire=15,
    )
    monkeypatch.setattr(
        renewal_approval, "initiate", AsyncMock(return_value=(False, "未配置审批定义编码")),
    )
    monkeypatch.setattr(renewal_approval, "resolve_approver", _resolver({contract.department: ("张管理", "ou_test_a")}))
    dept_cards = _Capture("ou_test_a")
    hr_cards = _Capture()
    monkeypatch.setattr(dept_notice, "_send", dept_cards)
    monkeypatch.setattr(notify, "_send", hr_cards)
    monkeypatch.setattr(scheduled, "resolve_receivers", AsyncMock(return_value=["ou_test_hr"]))

    await scheduled._run_announcement(
        db_session, days_ahead=50, copy_entries=[], dept_notice=True,
    )

    assert [call[0] for call in dept_cards.calls] == ["ou_test_a"]  # 尝试发过
    summary = hr_cards.calls[0][2]
    assert "已通知部门负责人" not in summary
    assert f"到期 {contract.end_date}：负责人「张管理」推送失败" in summary


# ─── 找负责人 ───


@pytest.mark.asyncio
async def test_resolve_approver_department_manager_then_fallback(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
):
    """负责人取部门表 → 兜底员工档案直属经理 → 都没有；有姓名但匹配不到飞书账号时 open_id 为空。"""
    dept = f"负责人解析{uuid4().hex[:6]}"
    db_session.add(HrDepartment(name=dept, code=f"DP{uuid4().hex[:8].upper()}", department_manager_name="部门经理"))
    with_dept = await _employee(db_session, department=dept, name="警己")
    no_dept_row = await _employee(
        db_session, department=f"无此部门{uuid4().hex[:6]}", name="警庚",
    )
    no_dept_row.direct_manager_name = "直属经理"
    orphan = await _employee(
        db_session, department=f"无此部门{uuid4().hex[:6]}", name="警辛",
    )
    await db_session.flush()
    known = {"部门经理", "直属经理"}
    monkeypatch.setattr(
        renewal_approval, "_lookup_open_id",
        AsyncMock(side_effect=lambda name: f"ou_{name}" if name in known else None),
    )

    def transient(employee: Employee) -> LaborContract:
        return LaborContract(employee_number=employee.employee_number, department=employee.department)

    assert await renewal_approval.resolve_approver(db_session, transient(with_dept)) == ("部门经理", "ou_部门经理")
    assert await renewal_approval.resolve_approver(db_session, transient(no_dept_row)) == ("直属经理", "ou_直属经理")
    assert await renewal_approval.resolve_approver(db_session, transient(orphan)) == (None, None)
    no_dept_row.direct_manager_name = "查无此人"
    assert await renewal_approval.resolve_approver(db_session, transient(no_dept_row)) == ("查无此人", None)
