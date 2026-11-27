"""劳动合同业务服务：期限规则、状态机流转、审批结论应用、终止衔接。

职责边界：api.py 只收参；repository 只读写；本层负责业务规则与跨表校验。
SQLAlchemy async 铁律：INSERT flush 返回即可；UPDATE 后 flush 不 re-fetch
（上层按需重查），避免 MissingGreenlet。
"""

import hashlib
import logging
import secrets
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.hr.labor_contract import notify
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract import settings as contract_settings
from app.modules.hr.labor_contract.models import LaborContract

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


async def sign_page_url(db: AsyncSession, token: str) -> str:
    """签字 H5 页地址（基地址配置在 hr_contract.sign_page_base_url）。

    页面为静态段 + ?token= 形式：前端 /api/* rewrite（afterFiles）先于动态
    路由段生效，token 走路径会被代理到后端 404，必须走查询参数。
    """
    kv = await contract_settings.load_contract_settings(db)
    base = kv.get(contract_settings.KEY_SIGN_BASE_URL, "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}?token={token}"


async def contact_of(db: AsyncSession) -> str:
    kv = await contract_settings.load_contract_settings(db)
    return contract_settings.contact_info(kv)


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
    """办理续签：按签订次数自动带出新合同期限，生成新行并取代旧行。"""
    if contract.status not in RENEWABLE_STATUSES:
        raise AppException(message="该合同当前状态不可办理续签")
    if contract.term_type == LaborContract.TERM_OPEN:
        raise AppException(message="无固定期限合同不再续签")
    if contract.end_date and start_date <= contract.end_date:
        raise AppException(message="新合同起始日应晚于原合同到期日（期限自新合同起始日起算）")

    next_seq = contract.seq_no + 1
    if await repo.get_active_with_seq(db, contract.employee_number, next_seq):
        raise DuplicateException("有效合同", f"工号 {contract.employee_number} 第 {next_seq} 份")

    term_type, years = term_for_seq(next_seq)
    new_contract = LaborContract(
        employee_number=contract.employee_number,
        name=contract.name,
        department=contract.department,
        position=contract.position,
        seq_no=next_seq,
        term_type=term_type,
        term_years=years,
        start_date=start_date,
        end_date=compute_end_date(start_date, term_type, years),
        sign_date=sign_date or date.today(),
        status=LaborContract.STATUS_ACTIVE,
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

async def apply_dept_decision(
    db: AsyncSession, contract: LaborContract,
    *, decision: str, decided_by: str, user_id: UUID | None = None,
    send_notice: bool = True,
) -> LaborContract:
    """应用部门审批结论：同意 → 续签办理中并通知员工；不同意 → 终止转离职。"""
    if contract.status != LaborContract.STATUS_PENDING_RENEWAL:
        raise AppException(message="仅「公告期」的合同可审批")
    if decision not in (LaborContract.DECISION_AGREE, LaborContract.DECISION_DISAGREE):
        raise AppException(message="审批结论只能是 agree / disagree")

    contract.dept_decision = decision
    contract.dept_decision_by = decided_by
    contract.dept_decision_at = _now()
    contract.updated_by = user_id

    contact = await contact_of(db)
    if decision == LaborContract.DECISION_AGREE:
        contract.status = LaborContract.STATUS_RENEWING
        await db.flush()
        if send_notice:
            employee = await repo.get_employee(db, contract.employee_number)
            if employee:
                await notify.send_renewal_notice(db, contract, employee, contact)
    else:
        contract.status = LaborContract.STATUS_TERMINATED
        contract.terminated_reason = "部门不同意续签"
        contract.terminated_at = _now()
        departure_id = await repo.find_departure_record_id(db, contract.employee_number)
        if departure_id:
            contract.departure_record_id = departure_id
        await db.flush()
    return await _refetch(db, contract.id)


# ─── 盖章 / 领取 / 线上签字 ───

async def mark_stamped(
    db: AsyncSession, contract: LaborContract, user_id: UUID | None = None,
) -> LaborContract:
    """公司盖章完成：触发领取通知。"""
    if contract.status not in (LaborContract.STATUS_ACTIVE, LaborContract.STATUS_RENEWING):
        raise AppException(message="仅生效中的合同可标记盖章")
    if contract.stamped_at:
        raise DuplicateException("盖章记录", f"合同 {contract.id} 已标记盖章完成")
    contract.stamped_at = _now()
    contract.updated_by = user_id
    await db.flush()
    employee = await repo.get_employee(db, contract.employee_number)
    if employee:
        await notify.send_stamp_notice(db, contract, employee, await contact_of(db))
    return await _refetch(db, contract.id)


async def mark_delivered(
    db: AsyncSession, contract: LaborContract, user_id: UUID | None = None,
) -> tuple[LaborContract, str]:
    """员工领取：签发一次性签字 token 并推送签字提醒。返回 (合同, 签字链接)。"""
    if not contract.stamped_at:
        raise AppException(message="请先标记「盖章完成」再办理领取")
    if contract.delivered_at:
        raise DuplicateException("领取记录", f"合同 {contract.id} 已标记领取")
    contract.delivered_at = _now()
    contract.updated_by = user_id
    token = await issue_sign_token(db, contract)
    await db.flush()
    sign_url = await sign_page_url(db, token)
    employee = await repo.get_employee(db, contract.employee_number)
    if employee:
        await notify.send_sign_reminder(db, contract, employee, await contact_of(db), sign_url)
    return await _refetch(db, contract.id), sign_url


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_sign_token(db: AsyncSession, contract: LaborContract) -> str:
    """签发一次性签字 token：库里只存 sha256，确认后即作废；重签发旧链接自动失效。"""
    token = secrets.token_urlsafe(32)
    contract.sign_token_hash = _hash_token(token)
    return token


async def find_by_sign_token(db: AsyncSession, token: str) -> LaborContract | None:
    hashed = _hash_token(token)
    return (await db.execute(
        select(LaborContract).where(
            LaborContract.sign_token_hash == hashed,
            LaborContract.is_deleted.is_(False),
        )
    )).scalars().first()


async def confirm_sign_by_token(db: AsyncSession, token: str) -> LaborContract:
    """员工线上签字确认（免登，token 即凭证）：回写签字时间，作为已领取凭证。"""
    contract = await find_by_sign_token(db, token)
    if not contract:
        raise AppException(message="签字链接无效或已失效", status_code=404)
    if contract.sign_confirmed_at:
        return contract  # 幂等：重复点击直接返回已确认状态
    contract.sign_confirmed_at = _now()
    contract.sign_token_hash = None
    await db.flush()
    logger.info("劳动合同线上签字确认: %s 第%d份", contract.employee_number, contract.seq_no)
    return contract


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
    """窗口内即将到期且仍未进入公告期的生效合同（无固定期限不参与）。"""
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
