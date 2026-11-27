"""离职合同台账 · 规则与流程衔接（P3）：终止方式判定、离职人员合同归入、人工项维护。

- 终止方式 = 人工更正值 > 自动判定（没有任何合同信息 = 无合同记录；否则离职日期不早于
  合同到期日 = 到期终止，再按离职类型归类），离职类型取值以离职台账真实数据为准
  （个人原因/实习结束/退休/部门劝退/调合成公司…）
- 办结衔接：已离职人员的未完结合同统一置 terminated 并关联离职记录（两本台账不交叉、
  不再参与到期预警）；离职日期未到（办理中）的不动，撤销离职后状态不必回滚
- 没有合同行的历史离职人员，归档扫描件时按离职记录合同信息建一份已终止合同

列表查询与行装配见 departure_ledger.py。SQLAlchemy async 铁律：UPDATE 后不直接
序列化 updated_at（上层按需重查）。
"""

import logging
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.models import DepartureRecord

logger = logging.getLogger(__name__)

# ─── 合同终止方式（需求：终止/解除方式）───
TERMINATION_EXPIRY = "expiry"          # 合同到期终止
TERMINATION_RESIGN = "resign"          # 员工辞职解除
TERMINATION_EMPLOYER = "employer"      # 公司解除
TERMINATION_RETIRE = "retire"          # 退休终止
TERMINATION_TRANSFER = "transfer"      # 调动转签解除
TERMINATION_OTHER = "other"            # 其他
TERMINATION_NONE = "none"              # 无合同记录（自动判定结果，不可人工选）
TERMINATION_LABELS = {
    TERMINATION_EXPIRY: "合同到期终止",
    TERMINATION_RESIGN: "员工辞职解除",
    TERMINATION_EMPLOYER: "公司解除",
    TERMINATION_RETIRE: "退休终止",
    TERMINATION_TRANSFER: "调动转签解除",
    TERMINATION_OTHER: "其他",
    TERMINATION_NONE: "无合同记录",
}
# 人工更正可选值（「无合同记录」不是一种方式，由数据决定）
TERMINATION_CHOICES = tuple(k for k in TERMINATION_LABELS if k != TERMINATION_NONE)

# 离职类型 → 终止方式；未列出的归「其他」（SQL 判定表达式在 departure_ledger 复用）
RETIRE_TYPES = ("退休",)
EXPIRY_TYPES = ("合同到期", "实习结束", "退休返聘到期")
RESIGN_TYPES = ("辞职", "个人原因")
EMPLOYER_TYPES = ("辞退", "部门劝退", "劝退", "裁员")
TRANSFER_TYPES = ("调合成公司", "调动", "转签")

# ─── 离职证明开具/送达状态 ───
CERT_PENDING = "pending"
CERT_ISSUED = "issued"
CERT_DELIVERING = "delivering"
CERT_SIGNED = "signed"
CERT_LABELS = {
    CERT_PENDING: "未开具",
    CERT_ISSUED: "已开具",
    CERT_DELIVERING: "送达中",
    CERT_SIGNED: "已签收",
}

# 离职办结单状态字面量（OffboardingCase.STATUS_*；其模型懒导入，避免模块间硬依赖）
CASE_SIGNED = "signed"
CASE_CLOSED = "closed"
CASE_DELIVERING = "delivering"
CASE_CANCELED = "canceled"

_CHUNK = 500


def chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ═══════════════════════════════════════════════════════════════
# 判定规则（纯函数；SQL 侧的同序表达式见 departure_ledger，一致性由测试保证）
# ═══════════════════════════════════════════════════════════════

def derive_termination_type(
    offboarding_type: str | None, offboarding_date: date | None,
    contract_end: date | None, *, has_contract: bool = True,
) -> str:
    """自动判定合同终止方式。

    没有任何合同信息 → 无合同记录（合同都没有，谈不上怎么终止）；否则
    退休 > 到期类离职类型 > 离职日期不早于合同到期日（合同已期满）> 辞职类 >
    公司解除类 > 调动转签类 > 其他。
    """
    if not has_contract:
        return TERMINATION_NONE
    if offboarding_type in RETIRE_TYPES:
        return TERMINATION_RETIRE
    if offboarding_type in EXPIRY_TYPES:
        return TERMINATION_EXPIRY
    if contract_end is not None and offboarding_date is not None and offboarding_date >= contract_end:
        return TERMINATION_EXPIRY
    if offboarding_type in RESIGN_TYPES:
        return TERMINATION_RESIGN
    if offboarding_type in EMPLOYER_TYPES:
        return TERMINATION_EMPLOYER
    if offboarding_type in TRANSFER_TYPES:
        return TERMINATION_TRANSFER
    return TERMINATION_OTHER


def term_from_dates(start: date, end: date | None) -> tuple[str, int | None]:
    """按起止日期推期限（离职记录建档/兜底展示用）：整 3/6 年按标准期限，其余记实际年数。"""
    if end is None:
        return LaborContract.TERM_OPEN, None
    raw_years = (end - start).days / 365.25
    if raw_years < 1:  # 先判再取整：7 个月四舍五入会变成「1 年」
        return LaborContract.TERM_FIXED, None
    years = round(raw_years)
    if years == 3:
        return LaborContract.TERM_FIXED_3Y, 3
    if years == 6:
        return LaborContract.TERM_FIXED_6Y, 6
    return LaborContract.TERM_FIXED, years


def term_label(term_type: str | None, term_years: int | None) -> str | None:
    if term_type is None:
        return None
    if term_type == LaborContract.TERM_FIXED:
        return "不足 1 年" if not term_years else f"{term_years} 年"
    return LaborContract.TERM_LABELS.get(term_type, term_type)


def derive_certificate_status(departure: DepartureRecord, case=None) -> str:
    """离职证明开具/送达状态：有离职办结单以办结单为准（case 为空即没有办结单），否则看台账签字/开具字段。"""
    case_status = getattr(case, "status", None)
    # 签收优先于开具：电子签收记在台账 cert_sign_status，纸质签收与办结态记在办结单
    if departure.cert_sign_status == "signed" or getattr(case, "paper_signed_at", None):
        return CERT_SIGNED
    if case_status in (CASE_SIGNED, CASE_CLOSED):
        return CERT_SIGNED
    if case_status == CASE_DELIVERING:
        return CERT_DELIVERING
    if getattr(case, "cert_issued_at", None) or departure.cert_issued_at:
        return CERT_ISSUED
    return CERT_PENDING


def can_build_from_departure(departure: DepartureRecord | None) -> bool:
    """离职记录能否按自带合同信息建档：有工号且有可用的合同起始日。"""
    return bool(departure) and bool(departure.employee_number) and bool(
        departure.contract_start_date or departure.livo_entry_date
    )


# ═══════════════════════════════════════════════════════════════
# 流程衔接：终止 → 离职台账
# ═══════════════════════════════════════════════════════════════

async def latest_departures(db: AsyncSession, numbers: list[str]) -> dict[str, DepartureRecord]:
    """按工号批量取最新一条离职记录（离职日期最近者优先，空值排最后）。"""
    result: dict[str, DepartureRecord] = {}
    for chunk in chunks(numbers):
        rows = (await db.execute(
            select(DepartureRecord).where(
                DepartureRecord.employee_number.in_(chunk),
                DepartureRecord.is_deleted.is_(False),
            ).order_by(
                DepartureRecord.offboarding_date.desc().nulls_last(),
                DepartureRecord.created_at.desc(),
            )
        )).scalars().all()
        for row in rows:
            if row.employee_number:
                result.setdefault(row.employee_number, row)
    return result


async def reconcile_departed_contracts(db: AsyncSession) -> list[LaborContract]:
    """已离职人员的未完结合同统一归入离职台账：置 terminated 并关联离职记录。

    「已离职」= 有离职记录且离职日期已到，或员工档案状态为离职。归入后不再参与
    到期预警（扫描按状态过滤）。
    """
    open_rows = await repo.list_open_contracts(db)
    if not open_rows:
        return []
    numbers = sorted({c.employee_number for c in open_rows})
    departure_map = await latest_departures(db, numbers)
    left = await repo.map_left_employees(db, numbers)
    today = date.today()
    reconciled: list[LaborContract] = []
    for contract in open_rows:
        departure = departure_map.get(contract.employee_number)
        left_date = departure.offboarding_date if departure else None
        if not ((left_date is not None and left_date <= today) or contract.employee_number in left):
            continue
        termination_type = derive_termination_type(
            departure.offboarding_type if departure else None, left_date, contract.end_date,
        )
        contract.status = LaborContract.STATUS_TERMINATED
        contract.terminated_reason = (
            TERMINATION_LABELS[termination_type]
            if termination_type != TERMINATION_NONE else "员工离职，合同解除"
        )
        contract.terminated_at = datetime.now(UTC)
        contract.sign_token_hash = None
        if departure is not None and contract.departure_record_id is None:
            contract.departure_record_id = departure.id
        reconciled.append(contract)
    if reconciled:
        await db.flush()
        logger.info("离职人员合同归入离职台账: %d 份", len(reconciled))
    return reconciled


async def ensure_departure_contract(
    db: AsyncSession, departure: DepartureRecord, *, user=None,
) -> LaborContract:
    """没有合同行的离职人员，按离职记录合同信息建一份已终止合同（扫描件挂接用）。

    已有合同行时返回签订次数最高的一份，不重复建档。
    """
    if not departure.employee_number:
        raise AppException(message="该离职记录没有工号，无法关联合同档案")
    existing = await repo.list_by_employee(db, departure.employee_number)
    if existing:
        return existing[-1]
    start = departure.contract_start_date or departure.livo_entry_date
    if start is None:
        raise AppException(message="该离职记录缺少合同起始日期，无法建立合同档案，请先补录")
    end = departure.contract_end_date
    if end is not None and end < start:  # 脏数据：到期日早于起始日按无固定期限处理
        end = None
    term_type, term_years = term_from_dates(start, end)
    termination_type = derive_termination_type(departure.offboarding_type, departure.offboarding_date, end)
    contract = LaborContract(
        employee_number=departure.employee_number,
        name=departure.name,
        department=departure.department,
        position=departure.position,
        seq_no=1,
        term_type=term_type,
        term_years=term_years,
        start_date=start,
        end_date=end,
        sign_date=None,
        status=LaborContract.STATUS_TERMINATED,
        terminated_reason=TERMINATION_LABELS[termination_type],
        terminated_at=datetime.combine(departure.offboarding_date or date.today(), time.min, tzinfo=UTC),
        departure_record_id=departure.id,
        remark="离职合同台账建档（按离职记录合同信息）",
        created_by=user.id if user is not None else None,
    )
    db.add(contract)
    await db.flush()
    logger.info("离职合同台账建档: %s（离职记录 %s）", departure.employee_number, departure.id)
    return contract


async def update_procedure(
    db: AsyncSession, departure: DepartureRecord, *, termination_type: str | None,
    approval_ref: str | None, separation_process_no: str | None,
    original_status: str, user=None,
) -> None:
    """维护离职合同台账的人工项：终止方式更正 / 审批依据 / 流程单号 / 原件回收状态。"""
    if termination_type and termination_type not in TERMINATION_CHOICES:
        raise AppException(message="合同终止方式取值不合法")
    if original_status not in DepartureRecord.ORIGINAL_STATUS_LABELS:
        raise AppException(message="合同原件回收状态取值不合法")
    departure.contract_termination_type = (termination_type or "").strip() or None  # 清空=恢复自动判定
    departure.contract_approval_ref = (approval_ref or "").strip() or None
    departure.separation_process_no = (separation_process_no or "").strip() or None
    departure.contract_original_status = original_status
    departure.updated_by = user.id if user is not None else None
    await db.flush()
