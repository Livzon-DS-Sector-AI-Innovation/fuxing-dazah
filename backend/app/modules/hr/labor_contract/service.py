"""劳动合同业务服务：期限规则、状态机流转、审批结论应用、通知与留痕、进度步骤、终止衔接。

职责边界：api.py 只收参；repository 只读写；本层负责业务规则与跨表校验。
SQLAlchemy async 铁律：INSERT flush 返回即可；UPDATE 后 flush 不 re-fetch
（上层按需重查），避免 MissingGreenlet。
"""

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.hr.labor_contract import notify
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.models import ContractNoticeLog, LaborContract

logger = logging.getLogger(__name__)


# ─── 期限规则（需求：第 1 次 3 年、第 2 次 6 年、第 3 次起无固定期限）───

def term_for_seq(seq_no: int) -> tuple[str, int | None]:
    """按签订次数给出期限类型与年数。seq 从 1 起算。"""
    if seq_no <= 1:
        return LaborContract.TERM_FIXED_3Y, 3
    if seq_no == 2:
        return LaborContract.TERM_FIXED_6Y, 6
    return LaborContract.TERM_OPEN, None


def compute_end_date(start_date: date, term_type: str, term_years: int | None) -> date | None:
    """自合同起始日起算到期日；无固定期限返回 None。闰日落到 2/28。"""
    if term_type == LaborContract.TERM_OPEN:
        return None
    years = {
        LaborContract.TERM_FIXED_3Y: 3,
        LaborContract.TERM_FIXED_6Y: 6,
    }.get(term_type, term_years or 0)
    if years <= 0:
        raise AppException(message="固定期限年数必须大于 0")
    try:
        return start_date.replace(year=start_date.year + years)
    except ValueError:  # 2/29 → 平年
        return start_date.replace(year=start_date.year + years, day=28, month=2)


def next_term_preview(seq_no: int) -> str:
    """续签台账展示用：本次签订类型与次数（如「第二次续签 · 6 年」）。"""
    term_type, years = term_for_seq(seq_no)
    label = LaborContract.TERM_LABELS[term_type] if term_type != LaborContract.TERM_FIXED else f"{years} 年"
    order = "第一次签订" if seq_no <= 1 else ("第二次续签" if seq_no == 2 else f"第 {seq_no} 次")
    return f"{order} · {label}"


def _shift_years(d: date, years: int) -> date:
    """按整年平移日期（闰日 2/29 落到 2/28，与 compute_end_date 同口径）。"""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, month=2, day=28)


def infer_seq_from_hire(hire_date: date | None, start_date: date) -> int:
    """按入职日期 + 期限规则推算签订次序（录入缺省值，可人工指定覆盖）。

    需求规则：第 1 次 3 年、第 2 次 6 年（累计满 9 年）、第 3 次起无固定期限。
    锚点取本次合同起始日（规则口径「自每份合同起始日起算」，首份起始日即入职日）：
    距入职不足 3 年 → 1；满 3 年不足 9 年 → 2；满 9 年 → 3。
    入职日期缺失或明显占位（年份早于 1950）时无法推算，返回 1 兜底。
    """
    if hire_date is None or hire_date.year < 1950 or start_date < hire_date:
        return 1
    if start_date >= _shift_years(hire_date, 9):
        return 3
    if start_date >= _shift_years(hire_date, 3):
        return 2
    return 1


def _now() -> datetime:
    return datetime.now(UTC)


async def _refetch(db: AsyncSession, contract_id: UUID) -> LaborContract:
    """UPDATE 后按主键 select re-fetch（MissingGreenlet 铁律：禁 refresh/懒加载序列化）。"""
    contract = await repo.get(db, contract_id)
    assert contract is not None, f"合同 {contract_id} 刚更新后查询不到"
    return contract


# ─── 查询装配 ───

async def get_or_404(db: AsyncSession, contract_id: UUID) -> LaborContract:
    contract = await repo.get(db, contract_id)
    if not contract:
        raise NotFoundException("劳动合同", str(contract_id))
    return contract


async def contract_history(db: AsyncSession, contract: LaborContract) -> list[LaborContract]:
    return await repo.list_by_employee(db, contract.employee_number)


# ─── 通知发送（员工两张卡；留痕见 notify.log_notice）───


async def _notify_employee(
    db: AsyncSession, contract: LaborContract, kind: str, *,
    user_id: UUID | None = None, user_name: str | None = None,
) -> notify.NoticeResult:
    """给合同对应员工发一张卡并留痕；没有员工档案时留痕为跳过（不中断主流程）。

    系统只在公司内网可达，员工在手机上点不开本系统的链接，所以卡片只带文字不带跳转按钮。
    """
    employee = await repo.get_employee(db, contract.employee_number)
    if employee is None:
        return await notify.log_notice(
            db, contract=contract, kind=kind, status=ContractNoticeLog.STATUS_SKIPPED,
            error_message="员工档案不存在", created_by=user_id, created_by_name=user_name,
        )
    if kind == ContractNoticeLog.KIND_RENEW:
        return await notify.send_renewal_notice(
            db, contract, employee, created_by=user_id, created_by_name=user_name,
        )
    if kind == ContractNoticeLog.KIND_COLLECT:
        return await notify.send_stamp_notice(
            db, contract, employee, created_by=user_id, created_by_name=user_name,
        )
    raise ValueError(f"不支持的员工通知类型: {kind}")


# ─── 录入 / 编辑 ───

async def create_contract(
    db: AsyncSession,
    *,
    employee_number: str,
    start_date: date,
    sign_date: date | None,
    remark: str | None,
    seq_no: int | None = None,
    user_id: UUID | None = None,
) -> LaborContract:
    employee = await repo.get_employee(db, employee_number)
    if not employee:
        raise NotFoundException("员工档案", f"工号 {employee_number}")
    if employee.status == "离职":
        raise AppException(message="该员工已离职，合同请在离职台账中维护")

    prior = await repo.list_by_employee(db, employee_number)
    max_prior = max((c.seq_no for c in prior), default=0)
    if seq_no is None:
        # 缺省推算：入职日期 + 期限规则，且不早于已有份数的下一份
        # （老员工录入现合同不会错写成「第一次签订 · 3 年」）
        seq_no = max(max_prior + 1, infer_seq_from_hire(employee.hire_date, start_date))
    elif seq_no < 1:
        raise AppException(message="签订次序必须为正整数")
    if await repo.get_active_with_seq(db, employee_number, seq_no):
        raise DuplicateException("有效合同", f"工号 {employee_number} 第 {seq_no} 份")

    term_type, years = term_for_seq(seq_no)
    contract = LaborContract(
        employee_number=employee.employee_number,
        name=employee.name,
        department=employee.department,
        position=employee.position,
        seq_no=seq_no,
        term_type=term_type,
        term_years=years,
        start_date=start_date,
        end_date=compute_end_date(start_date, term_type, years),
        sign_date=sign_date or start_date,
        status=LaborContract.STATUS_ACTIVE,
        origin=LaborContract.ORIGIN_MANUAL,
        remark=remark,
        created_by=user_id,
    )
    db.add(contract)
    await db.flush()
    logger.info("录入劳动合同: %s 第%d份 %s~%s",
                employee_number, seq_no, start_date, contract.end_date)
    return contract


EDITABLE_STATUSES = (LaborContract.STATUS_ACTIVE, LaborContract.STATUS_RENEWING)


async def update_contract(
    db: AsyncSession, contract: LaborContract,
    *, start_date: date | None, sign_date: date | None,
    position: str | None, remark: str | None, user_id: UUID | None = None,
) -> LaborContract:
    if contract.status not in EDITABLE_STATUSES:
        raise AppException(message="仅「生效中 / 续签办理中」的合同可编辑")
    if start_date is not None and start_date != contract.start_date:
        contract.start_date = start_date
        contract.end_date = compute_end_date(start_date, contract.term_type, contract.term_years)
    if sign_date is not None:
        contract.sign_date = sign_date
    if position is not None:
        contract.position = position
    if remark is not None:
        contract.remark = remark
    contract.updated_by = user_id
    await db.flush()
    return await _refetch(db, contract.id)


# ─── 续签（签订盖章：生成新合同行，旧行被取代）───

RENEWABLE_STATUSES = (
    LaborContract.STATUS_ACTIVE,
    LaborContract.STATUS_PENDING_RENEWAL,
    LaborContract.STATUS_RENEWING,
    LaborContract.STATUS_EXPIRED_UNRENEWED,
)


async def renew_contract(
    db: AsyncSession, contract: LaborContract,
    *, start_date: date, sign_date: date | None, user_id: UUID | None = None,
) -> LaborContract:
    """办理续签：须已登记部门「同意续签」；按签订次数自动带出新合同期限，生成新行并取代旧行。"""
    if contract.status not in RENEWABLE_STATUSES:
        raise AppException(message="该合同当前状态不可办理续签")
    if contract.term_type == LaborContract.TERM_OPEN:
        raise AppException(message="无固定期限合同不再续签")
    if contract.dept_decision != LaborContract.DECISION_AGREE:
        raise AppException(message="尚未登记部门续签意见，请先由部门负责人登记『同意续签』后再办理续签")
    if contract.end_date and start_date <= contract.end_date:
        raise AppException(message="新合同起始日应晚于原合同到期日（期限自新合同起始日起算）")

    next_seq = contract.seq_no + 1
    if await repo.get_active_with_seq(db, contract.employee_number, next_seq):
        raise DuplicateException("有效合同", f"工号 {contract.employee_number} 第 {next_seq} 份")

    # 新合同的姓名 / 部门 / 岗位取员工档案现值（员工异动后下一轮到期提醒才会发给现部门负责人）；
    # 取不到档案时回退沿用旧行快照
    employee = await repo.get_employee(db, contract.employee_number)
    term_type, years = term_for_seq(next_seq)
    new_contract = LaborContract(
        employee_number=contract.employee_number,
        name=employee.name if employee else contract.name,
        department=employee.department if employee else contract.department,
        position=employee.position if employee else contract.position,
        seq_no=next_seq,
        term_type=term_type,
        term_years=years,
        start_date=start_date,
        end_date=compute_end_date(start_date, term_type, years),
        sign_date=sign_date or date.today(),
        status=LaborContract.STATUS_ACTIVE,
        origin=LaborContract.ORIGIN_RENEWAL,
        remark=f"自第 {contract.seq_no} 份合同续签",
        created_by=user_id,
    )
    db.add(new_contract)
    contract.status = LaborContract.STATUS_SUPERSEDED
    contract.updated_by = user_id
    await db.flush()
    logger.info("续签办理: %s 第%d→%d份，旧行 superseded",
                contract.employee_number, contract.seq_no, next_seq)
    return new_contract


# ─── 部门审批结论（站内勾选降级路径；飞书路径见 renewal_approval.apply_result）───

# 可登记续签意见的状态：不必等到公告期——生效中、到期未续签的也可由部门直接表态
DECIDABLE_STATUSES = (
    LaborContract.STATUS_ACTIVE,
    LaborContract.STATUS_PENDING_RENEWAL,
    LaborContract.STATUS_RENEWING,
    LaborContract.STATUS_EXPIRED_UNRENEWED,
)


async def apply_dept_decision(
    db: AsyncSession, contract: LaborContract,
    *, decision: str, decided_by: str, user_id: UUID | None = None,
    send_notice: bool = True,
) -> LaborContract:
    """应用部门审批结论：同意 → 续签办理中并通知员工；不同意 → 终止转离职。

    登记人姓名记入 dept_decision_by；同意时给员工发续签通知并留痕（跳过 / 失败同样留痕）。
    """
    if contract.status not in DECIDABLE_STATUSES:
        raise AppException(message="仅「生效中 / 公告期 / 续签办理中 / 到期未续签」的合同可登记续签意见")
    if decision not in (LaborContract.DECISION_AGREE, LaborContract.DECISION_DISAGREE):
        raise AppException(message="审批结论只能是 agree / disagree")

    contract.dept_decision = decision
    contract.dept_decision_by = decided_by
    contract.dept_decision_at = _now()
    contract.updated_by = user_id

    if decision == LaborContract.DECISION_AGREE:
        contract.status = LaborContract.STATUS_RENEWING
        await db.flush()
        if send_notice:
            await _notify_employee(
                db, contract, ContractNoticeLog.KIND_RENEW,
                user_id=user_id, user_name=decided_by if user_id else None,
            )
    else:
        contract.status = LaborContract.STATUS_TERMINATED
        contract.terminated_reason = "部门不同意续签"
        contract.terminated_at = _now()
        departure_id = await repo.find_departure_record_id(db, contract.employee_number)
        if departure_id:
            contract.departure_record_id = departure_id
        await db.flush()
    return await _refetch(db, contract.id)


# ─── 盖章 / 领取 ───


async def mark_stamped(
    db: AsyncSession, contract: LaborContract, *,
    user_id: UUID | None = None, user_name: str | None = None,
) -> tuple[LaborContract, notify.NoticeResult]:
    """公司盖章完成：触发领取通知。返回 (合同, 本次通知结果)；通知未送达不影响盖章本身。"""
    if contract.status not in (LaborContract.STATUS_ACTIVE, LaborContract.STATUS_RENEWING):
        raise AppException(message="仅生效中的合同可标记盖章")
    if contract.stamped_at:
        raise DuplicateException("盖章记录", f"合同 {contract.id} 已标记盖章完成")
    contract.stamped_at = _now()
    contract.updated_by = user_id
    await db.flush()
    notice = await _notify_employee(
        db, contract, ContractNoticeLog.KIND_COLLECT, user_id=user_id, user_name=user_name,
    )
    return await _refetch(db, contract.id), notice


async def mark_delivered(
    db: AsyncSession, contract: LaborContract, *,
    user_id: UUID | None = None, user_name: str | None = None,
) -> LaborContract:
    """员工领取：到人事办公室领取合同原件，领取即签收（需求「领取时办理签收」）。

    系统只在公司内网可达，员工在手机上打不开本系统的链接，所以没有领取后的线上签字。
    """
    if not contract.stamped_at:
        raise AppException(message="请先标记「盖章完成」再办理领取")
    if contract.delivered_at:
        raise DuplicateException("领取记录", f"合同 {contract.id} 已标记领取")
    contract.delivered_at = _now()
    contract.updated_by = user_id
    await db.flush()
    return await _refetch(db, contract.id)


async def resend_notice(
    db: AsyncSession, contract: LaborContract, *, kind: str,
    user_id: UUID | None = None, user_name: str | None = None,
) -> notify.NoticeResult:
    """HR 重发一张员工通知（续签通知 / 领取通知）。"""
    if kind not in ContractNoticeLog.RESENDABLE_KINDS:
        raise AppException(message="kind 只能是 renew / collect")
    if contract.status in (LaborContract.STATUS_SUPERSEDED, LaborContract.STATUS_TERMINATED):
        raise AppException(message="该合同已终止或已被取代，不能再发送通知")
    if kind == ContractNoticeLog.KIND_RENEW and contract.dept_decision != LaborContract.DECISION_AGREE:
        raise AppException(message="尚未登记部门「同意续签」，不能发送续签通知")
    if kind == ContractNoticeLog.KIND_COLLECT and not contract.stamped_at:
        raise AppException(message="请先标记「盖章完成」，再发送领取通知")
    return await _notify_employee(
        db, contract, kind, user_id=user_id, user_name=user_name,
    )


# ─── 终止 ───


async def terminate_contract(
    db: AsyncSession, contract: LaborContract, *,
    reason: str | None, user_id: UUID | None = None,
) -> LaborContract:
    if contract.status in (LaborContract.STATUS_SUPERSEDED, LaborContract.STATUS_TERMINATED):
        raise AppException(message="该合同已是取代/终止状态")
    contract.status = LaborContract.STATUS_TERMINATED
    contract.terminated_reason = reason or "人工终止"
    contract.terminated_at = _now()
    contract.updated_by = user_id
    departure_id = await repo.find_departure_record_id(db, contract.employee_number)
    if departure_id:
        contract.departure_record_id = departure_id
    await db.flush()
    return await _refetch(db, contract.id)


# ─── 公告期扫描（scheduled 任务调用）───

async def find_expiring_active(db: AsyncSession, *, days_ahead: int) -> list[LaborContract]:
    """窗口内即将到期且仍未进入公告期的生效合同（无固定期限不参与、离职办理中的人不参与）。"""
    today = date.today()
    deadline = today + timedelta(days=days_ahead)
    rows = (await db.execute(
        select(LaborContract).where(
            LaborContract.is_deleted.is_(False),
            LaborContract.status == LaborContract.STATUS_ACTIVE,
            LaborContract.term_type != LaborContract.TERM_OPEN,
            LaborContract.end_date.is_not(None),
            LaborContract.end_date >= today,
            LaborContract.end_date <= deadline,
            # 台账里登记了将要离职的人：已在走离职流程，不再进公告期、不打扰部门负责人
            not_(repo.pending_offboarding_expr()),
        ).order_by(LaborContract.end_date.asc())
    )).scalars().all()
    return list(rows)


async def flip_expired_contracts(db: AsyncSession) -> list[LaborContract]:
    """生效合同到期未续签 → expired_unrenewed（仅在职员工；离职走终止流程）。"""
    today = date.today()
    rows = (await db.execute(
        select(LaborContract).where(
            LaborContract.is_deleted.is_(False),
            LaborContract.status == LaborContract.STATUS_ACTIVE,
            LaborContract.term_type != LaborContract.TERM_OPEN,
            LaborContract.end_date.is_not(None),
            LaborContract.end_date < today,
        )
    )).scalars().all()
    flipped: list[LaborContract] = []
    if not rows:
        return flipped
    active_map = await repo.list_active_employees(db, [c.employee_number for c in rows])
    for contract in rows:
        if contract.employee_number not in active_map:
            continue  # 已离职员工的合同不参与到期预警（离职台账 P3 单独保管）
        contract.status = LaborContract.STATUS_EXPIRED_UNRENEWED
        flipped.append(contract)
    if flipped:
        await db.flush()
        logger.info("到期未续签标注: %d 人", len(flipped))
    return flipped


async def mark_pending_renewal(
    db: AsyncSession,
    contract: LaborContract,
    *,
    mode: str,
    instance_code: str | None = None,
) -> None:
    """进入公告期：标注审批方式（飞书/站内），attempt 递增供幂等键使用。"""
    contract.status = LaborContract.STATUS_PENDING_RENEWAL
    contract.approval_mode = mode
    if instance_code:
        contract.approval_instance_code = instance_code
    contract.approval_attempt = (contract.approval_attempt or 0) + 1
    await db.flush()


# ─── 「待我处理」统计（口径与列表 todo 筛选共用 repository.todo_expr）───


async def contract_stats(
    db: AsyncSession, *, departments: frozenset[str] | None = None,
    employee_number: str | None = None,
) -> dict[str, int]:
    """各待办口径的计数 + attention_total（前五项之和）；人群同在职台账列表（在职人员合同）。"""
    counts = await repo.count_todos(
        db, departments=departments, employee_number=employee_number,
    )
    return {**counts, "attention_total": sum(counts[key] for key in repo.ATTENTION_KEYS)}


# ─── 进度步骤（状态驱动，前端只渲染）───

STEP_EXPIRY_ALERT = "expiry_alert"
STEP_DEPT_APPROVAL = "dept_approval"
STEP_RENEW_NOTICE = "renew_notice"
STEP_STAMP = "stamp"
STEP_DELIVER = "deliver"
STEP_ARCHIVE = "archive"
STEP_TITLES: tuple[tuple[str, str], ...] = (
    (STEP_EXPIRY_ALERT, "到期预警"),
    (STEP_DEPT_APPROVAL, "部门审批"),
    (STEP_RENEW_NOTICE, "通知续签"),
    (STEP_STAMP, "签订盖章"),
    (STEP_DELIVER, "领取合同"),
    (STEP_ARCHIVE, "电子归档"),
)

STATE_DONE = "done"
STATE_CURRENT = "current"
STATE_PENDING = "pending"
STATE_SKIPPED = "skipped"

NOTE_RENEWAL_DONE = "续签时已完成"
NOTE_OPEN_TERM = "无固定期限，不设到期日"
NOTE_SIGNED = "已签订生效"
NOTE_SUPERSEDED = "已续签为新合同"
# 步骤条里每步很窄，说明要短：具体怎么办写在抽屉顶部的「下一步」面板里
NOTE_EXPIRED_UNRENEWED = "到期未续签，待处理"
NOTE_RENEW_NOTICE_FAILED = "通知发送失败，可重发"


def _step(key: str, state: str, *, at: datetime | None = None, note: str | None = None) -> dict[str, Any]:
    return {
        "key": key, "title": dict(STEP_TITLES)[key], "state": state, "at": at, "note": note,
    }


def _first_notice_at(notices: Sequence[ContractNoticeLog], kind: str) -> datetime | None:
    """某类通知留痕最早一次的时间（如首次到期预警）。"""
    return min((n.created_at for n in notices if n.kind == kind), default=None)


def _last_notice_at(notices: Sequence[ContractNoticeLog], kind: str, status: str) -> datetime | None:
    """某类通知留痕里指定结果最近一次的时间。"""
    return max(
        (n.created_at for n in notices if n.kind == kind and n.status == status), default=None,
    )


def _signing_steps(contract: LaborContract, *, note: str | None = None) -> list[dict[str, Any]]:
    """签订盖章 / 领取合同：按时间戳依次判断——已完成 done，第一个未完成 current，其余 pending。"""
    steps: list[dict[str, Any]] = []
    waiting = False
    for key, at in (
        (STEP_STAMP, contract.stamped_at),
        (STEP_DELIVER, contract.delivered_at),
    ):
        if at is not None:
            steps.append(_step(key, STATE_DONE, at=at, note=note))
        elif waiting:
            steps.append(_step(key, STATE_PENDING))
        else:
            waiting = True
            steps.append(_step(key, STATE_CURRENT))
    return steps


def _signing_done_steps(contract: LaborContract, *, note: str) -> list[dict[str, Any]]:
    """签订盖章 / 领取合同两步整体视为已完成（at 取实际时间，没有则留空）。"""
    return [
        _step(STEP_STAMP, STATE_DONE, at=contract.stamped_at, note=note),
        _step(STEP_DELIVER, STATE_DONE, at=contract.delivered_at, note=note),
    ]


def _archive_step(contract: LaborContract, *, current: bool) -> dict[str, Any]:
    """电子归档：已归档 done；未归档按 current 给 current / pending。"""
    if contract.archive_status == LaborContract.ARCHIVE_ARCHIVED:
        return _step(STEP_ARCHIVE, STATE_DONE, at=contract.archive_uploaded_at)
    return _step(STEP_ARCHIVE, STATE_CURRENT if current else STATE_PENDING)


def _renew_notice_step(contract: LaborContract, notices: Sequence[ContractNoticeLog]) -> dict[str, Any]:
    """通知续签：仅续签办理中才看续签通知留痕——送达即 done；否则停在当前步并说明原因。"""
    if contract.status != LaborContract.STATUS_RENEWING:
        return _step(STEP_RENEW_NOTICE, STATE_PENDING)
    sent_at = _last_notice_at(notices, ContractNoticeLog.KIND_RENEW, ContractNoticeLog.STATUS_SENT)
    if sent_at is not None:
        return _step(STEP_RENEW_NOTICE, STATE_DONE, at=sent_at)
    unsent = [n for n in notices if n.kind == ContractNoticeLog.KIND_RENEW]
    note = None
    if unsent:
        latest = max(unsent, key=lambda n: n.created_at)
        note = (
            NOTE_RENEW_NOTICE_FAILED
            if latest.status == ContractNoticeLog.STATUS_FAILED else latest.error_message
        )
    return _step(STEP_RENEW_NOTICE, STATE_CURRENT, note=note)


def _superseded_progress(
    contract: LaborContract, notices: Sequence[ContractNoticeLog],
) -> list[dict[str, Any]]:
    note = NOTE_SUPERSEDED
    if contract.archive_status == LaborContract.ARCHIVE_ARCHIVED:
        archive = _step(STEP_ARCHIVE, STATE_DONE, at=contract.archive_uploaded_at)
    else:
        archive = _step(STEP_ARCHIVE, STATE_SKIPPED)
    return [
        _step(STEP_EXPIRY_ALERT, STATE_DONE, at=_first_notice_at(
            notices, ContractNoticeLog.KIND_DEPT_APPROVAL,
        ), note=note),
        _step(STEP_DEPT_APPROVAL, STATE_DONE, at=contract.dept_decision_at, note=note),
        _step(STEP_RENEW_NOTICE, STATE_DONE, at=_last_notice_at(
            notices, ContractNoticeLog.KIND_RENEW, ContractNoticeLog.STATUS_SENT,
        ), note=note),
        *_signing_done_steps(contract, note=note),
        archive,
    ]


def _terminated_progress(
    contract: LaborContract, notices: Sequence[ContractNoticeLog],
) -> list[dict[str, Any]]:
    note = contract.terminated_reason
    return [
        _step(STEP_EXPIRY_ALERT, STATE_DONE, at=_first_notice_at(
            notices, ContractNoticeLog.KIND_DEPT_APPROVAL,
        ), note=note),
        _step(STEP_DEPT_APPROVAL, STATE_DONE, at=contract.dept_decision_at, note=note),
        *(_step(key, STATE_SKIPPED) for key in (
            STEP_RENEW_NOTICE, STEP_STAMP, STEP_DELIVER, STEP_ARCHIVE,
        )),
    ]


def _open_term_progress(contract: LaborContract) -> list[dict[str, Any]]:
    note = NOTE_OPEN_TERM
    return [
        _step(STEP_EXPIRY_ALERT, STATE_DONE, note=note),
        _step(STEP_DEPT_APPROVAL, STATE_DONE, at=contract.dept_decision_at, note=note),
        _step(STEP_RENEW_NOTICE, STATE_DONE, note=note),
        *_signing_done_steps(contract, note=note),
        _archive_step(contract, current=True),
    ]


def _renewal_progress(contract: LaborContract) -> list[dict[str, Any]]:
    signing = _signing_steps(contract)
    done_before = [
        _step(key, STATE_DONE, note=NOTE_RENEWAL_DONE)
        for key in (STEP_EXPIRY_ALERT, STEP_DEPT_APPROVAL, STEP_RENEW_NOTICE)
    ]
    return [
        *done_before, *signing,
        _archive_step(contract, current=all(step["state"] == STATE_DONE for step in signing)),
    ]


def _fixed_term_progress(
    contract: LaborContract, notices: Sequence[ContractNoticeLog],
) -> list[dict[str, Any]]:
    """存量或在履约的固定期限合同：续签流程走到哪一步，加上签订两步（盖章 / 领取）与归档。"""
    status = contract.status
    in_renewal_flow = status in (
        LaborContract.STATUS_PENDING_RENEWAL, LaborContract.STATUS_RENEWING,
        LaborContract.STATUS_EXPIRED_UNRENEWED,
    )
    steps = [_step(
        STEP_EXPIRY_ALERT, STATE_DONE if in_renewal_flow else STATE_PENDING,
        at=_first_notice_at(notices, ContractNoticeLog.KIND_DEPT_APPROVAL),
    )]
    if status == LaborContract.STATUS_PENDING_RENEWAL and not contract.dept_decision:
        steps.append(_step(STEP_DEPT_APPROVAL, STATE_CURRENT))
    elif contract.dept_decision:
        agreed = contract.dept_decision == LaborContract.DECISION_AGREE
        by = contract.dept_decision_by or ""
        steps.append(_step(
            STEP_DEPT_APPROVAL, STATE_DONE, at=contract.dept_decision_at,
            note=f"{by} 登记{'同意' if agreed else '不同意'}".strip(),
        ))
    elif status == LaborContract.STATUS_EXPIRED_UNRENEWED:
        steps.append(_step(STEP_DEPT_APPROVAL, STATE_CURRENT, note=NOTE_EXPIRED_UNRENEWED))
    else:
        steps.append(_step(STEP_DEPT_APPROVAL, STATE_PENDING))
    steps.append(_renew_notice_step(contract, notices))

    # 签订两步：有签订日却没有任何盖章 / 领取时间的，是线下签好的存量或在履约合同，
    # 整段按「已签订生效」；否则按时间戳逐个判断
    milestones = (contract.stamped_at, contract.delivered_at)
    if contract.sign_date is not None and not any(milestones):
        signing = [_step(key, STATE_DONE, note=NOTE_SIGNED) for key in (
            STEP_STAMP, STEP_DELIVER,
        )]
    else:
        signing = _signing_steps(contract)
    steps.extend(signing)
    steps.append(_archive_step(contract, current=all(step["state"] == STATE_DONE for step in signing)))
    return steps


def build_progress(
    contract: LaborContract, notices: Sequence[ContractNoticeLog] = (),
) -> list[dict[str, Any]]:
    """按合同状态推导 6 个进度步骤，每步 {key, title, state, at, note}（纯函数，不查库）。

    - 已续签取代 / 已终止：终态，到流程结束处为止 done（note 写原因），其余 skipped
    - 无固定期限（非续签生成）：不设到期日，前五步 done，归档按状态
    - 续签生成的新合同（origin=renewal）：前三步续签时已完成，之后按盖章 / 领取 / 归档推进
    - 其它固定期限合同（含 origin 为空的存量）：到期预警 → 部门审批 → 通知续签 → 签订两步 → 归档

    notices 是该合同的通知留痕（时间倒序或正序均可），用于判断「通知续签」与首次预警时间。
    """
    if contract.status == LaborContract.STATUS_SUPERSEDED:
        return _superseded_progress(contract, notices)
    if contract.status == LaborContract.STATUS_TERMINATED:
        return _terminated_progress(contract, notices)
    if contract.term_type == LaborContract.TERM_OPEN and contract.origin != LaborContract.ORIGIN_RENEWAL:
        return _open_term_progress(contract)
    if contract.origin == LaborContract.ORIGIN_RENEWAL:
        return _renewal_progress(contract)
    return _fixed_term_progress(contract, notices)
