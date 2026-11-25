"""hr 劳动合同台账：labor_contracts 建表 + 宽表存量合同数据迁移

1. 建 hr.labor_contracts（一份合同一行；部分唯一索引 (employee_number, seq_no)
   仅约束非 superseded/terminated 行，规避软删除下重复添加→删除→添加的冲突）
2. 存量迁移：onboarding_records 四组合同起止宽表（兜底 employees 单组字段）
   → 按工号展开为逐份合同行；期限规则按签订次数判定（1→3年 2→6年 3+→无固定），
   存量非标准期限记 term_type='fixed'+term_years；离职人员合同置 terminated
   并关联 departure_records

注意：本迁移不带外键约束（仓库惯例，BaseModel 的 created_by/updated_by FK 不落库）；
宽表迁移后只读不回写。重复执行安全：表内已有数据时跳过迁移。

Revision ID: 31877707aa99
Revises: dada00079c92
Create Date: 2026-11-24 17:00:46.907647
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '31877707aa99'
down_revision: str | None = 'dada00079c92'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = 'hr'
TABLE = 'labor_contracts'


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column('employee_number', sa.String(length=32), nullable=False, comment='工号'),
        sa.Column('name', sa.String(length=64), nullable=False, comment='姓名'),
        sa.Column('department', sa.String(length=64), nullable=False, comment='部门'),
        sa.Column('position', sa.String(length=64), nullable=True, comment='岗位'),
        sa.Column('seq_no', sa.Integer(), nullable=False, comment='签订次数（1 起算）'),
        sa.Column('term_type', sa.String(length=16), nullable=False, comment='期限类型: fixed_3y/fixed_6y/fixed/open'),
        sa.Column('term_years', sa.Integer(), nullable=True, comment='固定期限年数（open 为空；存量非标准期限记实际值）'),
        sa.Column('start_date', sa.Date(), nullable=False, comment='合同起始日'),
        sa.Column('end_date', sa.Date(), nullable=True, comment='合同到期日（无固定期限为空，按期限规则自动计算）'),
        sa.Column('sign_date', sa.Date(), nullable=True, comment='实际签订日'),
        sa.Column('status', sa.String(length=24), server_default='active', nullable=False, comment='状态: active/pending_renewal/renewing/superseded/terminated/expired_unrenewed'),
        sa.Column('remark', sa.String(length=512), nullable=True, comment='备注'),
        sa.Column('dept_decision', sa.String(length=16), nullable=True, comment='审批结论: agree/disagree'),
        sa.Column('dept_decision_by', sa.String(length=64), nullable=True, comment="审批人（站内勾选时为人名，飞书审批固定为'飞书审批'）"),
        sa.Column('dept_decision_at', sa.DateTime(timezone=True), nullable=True, comment='审批时间'),
        sa.Column('approval_mode', sa.String(length=16), nullable=True, comment='本次公告期的审批方式: feishu/manual'),
        sa.Column('approval_instance_code', sa.String(length=64), nullable=True, comment="飞书审批实例 Code（离职台账'审批依据'引用）"),
        sa.Column('approval_attempt', sa.Integer(), server_default='0', nullable=False, comment='审批发起次数（幂等键后缀，撤销后重发递增）'),
        sa.Column('stamped_at', sa.DateTime(timezone=True), nullable=True, comment='公司盖章完成时间（触发领取通知）'),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True, comment='员工领取时间（触发签字提醒）'),
        sa.Column('sign_confirmed_at', sa.DateTime(timezone=True), nullable=True, comment='员工线上签字确认时间（已领取凭证）'),
        sa.Column('sign_token_hash', sa.String(length=128), nullable=True, comment='签字一次性 token 的 sha256（确认后清空，重发即作废旧链接）'),
        sa.Column('terminated_reason', sa.String(length=128), nullable=True, comment='终止原因（部门不同意续签/到期未续签/离职终止等）'),
        sa.Column('terminated_at', sa.DateTime(timezone=True), nullable=True, comment='终止时间'),
        sa.Column('departure_record_id', sa.Uuid(), nullable=True, comment='关联离职台账记录 ID（逻辑关联，无外键）'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index('ix_labor_contracts_department', TABLE, ['department'], unique=False, schema=SCHEMA)
    op.create_index('ix_labor_contracts_employee_number', TABLE, ['employee_number'], unique=False, schema=SCHEMA)
    op.create_index('ix_labor_contracts_end_date', TABLE, ['end_date'], unique=False, schema=SCHEMA)
    op.create_index('ix_labor_contracts_sign_token_hash', TABLE, ['sign_token_hash'], unique=False, schema=SCHEMA)
    op.create_index('ix_labor_contracts_status', TABLE, ['status'], unique=False, schema=SCHEMA)
    op.create_index(
        'uq_labor_contracts_employee_seq', TABLE, ['employee_number', 'seq_no'],
        unique=True, schema=SCHEMA,
        postgresql_where=sa.text("is_deleted = false AND status NOT IN ('superseded', 'terminated')"),
    )
    _migrate_legacy_contracts()


def _migrate_legacy_contracts() -> None:
    """宽表 → 逐份合同行。只处理已软删过滤的在职/离职档案；重复执行安全。"""
    conn = op.get_bind()
    existing = conn.execute(sa.text(
        f"SELECT count(*) FROM {SCHEMA}.{TABLE}"
    )).scalar_one()
    if existing:
        return  # 表内已有数据（重复升级/降级后再升级），不重复迁移

    # ── 员工档案（快照 + 离职判断）──
    employees = conn.execute(sa.text(
        "SELECT employee_number, name, department, position, status, "
        "contract_start_date, contract_end_date "
        "FROM hr.employees WHERE is_deleted = false AND employee_number IS NOT NULL"
    )).mappings().all()
    emp_by_number = {r['employee_number']: r for r in employees}

    # ── 入职台账宽表（四组合同起止为第一数据源）──
    onboarding = conn.execute(sa.text(
        "SELECT employee_number, contract_start_date, contract_end_date, "
        "contract_start_2, contract_end_2, contract_start_3, contract_end_3, "
        "contract_start_4, contract_end_4 "
        "FROM hr.onboarding_records WHERE is_deleted = false AND employee_number IS NOT NULL"
    )).mappings().all()

    # ── 离职台账（终止关联 + 终止时间）──
    departures = conn.execute(sa.text(
        "SELECT DISTINCT ON (employee_number) employee_number, id, offboarding_date "
        "FROM hr.departure_records "
        "WHERE is_deleted = false AND employee_number IS NOT NULL "
        "ORDER BY employee_number, created_at DESC"
    )).mappings().all()
    departure_by_number = {r['employee_number']: r for r in departures}

    today = date.today()

    def _term_for(seq_no: int, years: float | None) -> tuple[str, int | None]:
        """期限规则：1→3 年、2→6 年、3+→无固定；存量非标准年限记 fixed+实际年数。"""
        if years is None:
            return 'open', None
        whole = int(Decimal(str(years)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        if seq_no == 1 and whole == 3:
            return 'fixed_3y', 3
        if seq_no == 2 and whole == 6:
            return 'fixed_6y', 6
        return 'fixed', max(1, whole)

    def _years_of(start, end) -> float | None:
        if start is None or end is None or end <= start:
            return None
        return round((end - start).days / 365.25, 2)

    rows: list[dict] = []
    processed: set[str] = set()

    def _build_for(employee_number: str, pairs: list[tuple]) -> None:
        """pairs: [(start, end)]，按起始日排序去重后逐份建行。"""
        info = emp_by_number.get(employee_number) or {}
        name = info.get('name') or employee_number
        department = info.get('department') or '未知部门'
        position = info.get('position')
        emp_status = info.get('status') or ''
        departure = departure_by_number.get(employee_number)

        cleaned: list[tuple] = []
        seen: set[tuple] = set()
        for start, end in pairs:
            if start is None or (start, end) in seen:
                continue
            seen.add((start, end))
            cleaned.append((start, end))
        if not cleaned:
            return
        cleaned.sort(key=lambda p: p[0])

        is_left = departure is not None or emp_status == '离职'
        last_idx = len(cleaned) - 1
        for idx, (start, end) in enumerate(cleaned):
            years = _years_of(start, end)
            term_type, term_years = _term_for(idx + 1, years)
            if is_left:
                status = 'terminated' if idx == last_idx else 'superseded'
                terminated_at = (
                    datetime.combine(departure['offboarding_date'], datetime.min.time(),
                                     tzinfo=UTC)
                    if status == 'terminated' and departure and departure['offboarding_date']
                    else None
                )
                reason = '离职终止' if status == 'terminated' else None
                dep_id = departure['id'] if (status == 'terminated' and departure) else None
            elif idx == last_idx:
                if end is None or end >= today:
                    status, terminated_at, reason, dep_id = 'active', None, None, None
                else:
                    status, terminated_at, reason, dep_id = 'expired_unrenewed', None, None, None
            else:
                status, terminated_at, reason, dep_id = 'superseded', None, None, None
            rows.append({
                'id': str(uuid.uuid4()),
                'employee_number': employee_number,
                'name': name,
                'department': department,
                'position': position,
                'seq_no': idx + 1,
                'term_type': term_type,
                'term_years': term_years,
                'start_date': start,
                'end_date': end,
                'sign_date': start,
                'status': status,
                'remark': '存量迁移（入职台账/员工档案宽表）',
                'terminated_reason': reason,
                'terminated_at': terminated_at,
                'departure_record_id': dep_id,
            })

    for rec in onboarding:
        number = rec['employee_number']
        if number in processed:
            continue
        pairs = [
            (rec['contract_start_date'], rec['contract_end_date']),
            (rec['contract_start_2'], rec['contract_end_2']),
            (rec['contract_start_3'], rec['contract_end_3']),
            (rec['contract_start_4'], rec['contract_end_4']),
        ]
        if any(s is not None for s, _ in pairs):
            processed.add(number)
            _build_for(number, pairs)

    # 入职台账没有的工号：回退员工档案单组合同字段
    for number, info in emp_by_number.items():
        if number in processed:
            continue
        start, end = info.get('contract_start_date'), info.get('contract_end_date')
        if start is not None:
            _build_for(number, [(start, end)])

    if rows:
        conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.{TABLE} "
                "(employee_number, name, department, position, seq_no, term_type, term_years, "
                "start_date, end_date, sign_date, status, remark, terminated_reason, "
                "terminated_at, departure_record_id, id) "
                "VALUES (:employee_number, :name, :department, :position, :seq_no, :term_type, "
                ":term_years, :start_date, :end_date, :sign_date, :status, :remark, "
                ":terminated_reason, :terminated_at, :departure_record_id, :id)"
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_index('uq_labor_contracts_employee_seq', table_name=TABLE, schema=SCHEMA)
    op.drop_index('ix_labor_contracts_sign_token_hash', table_name=TABLE, schema=SCHEMA)
    op.drop_index('ix_labor_contracts_status', table_name=TABLE, schema=SCHEMA)
    op.drop_index('ix_labor_contracts_end_date', table_name=TABLE, schema=SCHEMA)
    op.drop_index('ix_labor_contracts_employee_number', table_name=TABLE, schema=SCHEMA)
    op.drop_index('ix_labor_contracts_department', table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
