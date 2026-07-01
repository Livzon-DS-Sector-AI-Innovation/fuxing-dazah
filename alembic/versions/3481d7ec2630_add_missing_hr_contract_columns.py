"""add missing columns to hr onboarding_records / employees / departure_records

Revision ID: 3481d7ec2630
Revises: ec7e0e3b9953
Create Date: 2026-06-29 19:52:28.730832
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3481d7ec2630'
down_revision: str | None = 'ec7e0e3b9953'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table: str, column: str, schema: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        ),
        {"schema": schema, "table": table, "column": column},
    ).first()
    return row is not None


def _add_column_if_missing(table: str, column: sa.Column, *, schema: str) -> None:
    if not _column_exists(table, column.name, schema):
        op.add_column(table, column, schema=schema)


def upgrade() -> None:
    # ── onboarding_records ──
    _add_column_if_missing('onboarding_records', sa.Column('contract_start_2', sa.Date(), nullable=True, comment='第二次合同起点'), schema='hr')
    _add_column_if_missing('onboarding_records', sa.Column('contract_end_2', sa.Date(), nullable=True, comment='第二次合同终止'), schema='hr')
    _add_column_if_missing('onboarding_records', sa.Column('contract_start_3', sa.Date(), nullable=True, comment='第三次合同起点'), schema='hr')
    _add_column_if_missing('onboarding_records', sa.Column('contract_end_3', sa.Date(), nullable=True, comment='第三次合同终止'), schema='hr')
    _add_column_if_missing('onboarding_records', sa.Column('contract_start_4', sa.Date(), nullable=True, comment='第四次合同起点'), schema='hr')
    _add_column_if_missing('onboarding_records', sa.Column('contract_end_4', sa.Date(), nullable=True, comment='第四次合同终止'), schema='hr')
    _add_column_if_missing('onboarding_records', sa.Column('emergency_contact_relation', sa.String(length=32), nullable=True, comment='紧急联系人|关系'), schema='hr')
    _add_column_if_missing('onboarding_records', sa.Column('bank_account_location', sa.String(length=32), nullable=True, comment='银行卡开户地'), schema='hr')

    # ── employees ──
    _add_column_if_missing('employees', sa.Column('contract_start_2', sa.Date(), nullable=True, comment='第二次合同起点'), schema='hr')
    _add_column_if_missing('employees', sa.Column('contract_end_2', sa.Date(), nullable=True, comment='第二次合同终止'), schema='hr')
    _add_column_if_missing('employees', sa.Column('contract_start_3', sa.Date(), nullable=True, comment='第三次合同起点'), schema='hr')
    _add_column_if_missing('employees', sa.Column('contract_end_3', sa.Date(), nullable=True, comment='第三次合同终止'), schema='hr')
    _add_column_if_missing('employees', sa.Column('contract_start_4', sa.Date(), nullable=True, comment='第四次合同起点'), schema='hr')
    _add_column_if_missing('employees', sa.Column('contract_end_4', sa.Date(), nullable=True, comment='第四次合同终止'), schema='hr')
    _add_column_if_missing('employees', sa.Column('emergency_contact_relation', sa.String(length=32), nullable=True, comment='紧急联系人关系'), schema='hr')

    # ── departure_records ──
    _add_column_if_missing('departure_records', sa.Column('emergency_contact_relation', sa.String(length=64), nullable=True, comment='紧急联系人|关系'), schema='hr')
    _add_column_if_missing('departure_records', sa.Column('offboarding_reason_2', sa.JSON(), nullable=True, comment='离职原因2（多选）'), schema='hr')
    _add_column_if_missing('departure_records', sa.Column('offboarding_remarks', sa.JSON(), nullable=True, comment='离职备注（多选）'), schema='hr')


def downgrade() -> None:
    op.drop_column('departure_records', 'offboarding_remarks', schema='hr')
    op.drop_column('departure_records', 'offboarding_reason_2', schema='hr')
    op.drop_column('departure_records', 'emergency_contact_relation', schema='hr')

    op.drop_column('employees', 'emergency_contact_relation', schema='hr')
    op.drop_column('employees', 'contract_end_4', schema='hr')
    op.drop_column('employees', 'contract_start_4', schema='hr')
    op.drop_column('employees', 'contract_end_3', schema='hr')
    op.drop_column('employees', 'contract_start_3', schema='hr')
    op.drop_column('employees', 'contract_end_2', schema='hr')
    op.drop_column('employees', 'contract_start_2', schema='hr')

    op.drop_column('onboarding_records', 'bank_account_location', schema='hr')
    op.drop_column('onboarding_records', 'emergency_contact_relation', schema='hr')
    op.drop_column('onboarding_records', 'contract_end_4', schema='hr')
    op.drop_column('onboarding_records', 'contract_start_4', schema='hr')
    op.drop_column('onboarding_records', 'contract_end_3', schema='hr')
    op.drop_column('onboarding_records', 'contract_start_3', schema='hr')
    op.drop_column('onboarding_records', 'contract_end_2', schema='hr')
    op.drop_column('onboarding_records', 'contract_start_2', schema='hr')
