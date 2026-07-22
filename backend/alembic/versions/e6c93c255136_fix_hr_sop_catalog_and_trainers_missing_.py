"""fix hr sop_catalog and trainers missing columns

Revision ID: e6c93c255136
Revises: a09acdc0169c
Create Date: 2026-06-29 20:11:40.076320
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'e6c93c255136'
down_revision: str | None = 'a09acdc0169c'
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


def _drop_column_if_exists(table: str, column: str, *, schema: str) -> None:
    if _column_exists(table, column, schema):
        op.drop_column(table, column, schema=schema)


def upgrade() -> None:
    # hr.sop_catalog
    _add_column_if_missing('sop_catalog', sa.Column('created_by', sa.Uuid(), nullable=True), schema='hr')
    _add_column_if_missing('sop_catalog', sa.Column('updated_by', sa.Uuid(), nullable=True), schema='hr')

    # hr.trainers: new columns
    _add_column_if_missing('trainers', sa.Column('certification_date', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('confirmation_date', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('confirmation_reminder', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('is_primary_trainer', sa.Boolean(), server_default='false', nullable=False), schema='hr')
    _add_column_if_missing('trainers', sa.Column('created_by', sa.Uuid(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('updated_by', sa.Uuid(), nullable=True), schema='hr')

    # hr.trainers: drop old columns
    _drop_column_if_exists('trainers', 'is_level1', schema='hr')
    _drop_column_if_exists('trainers', 'cert_date', schema='hr')
    _drop_column_if_exists('trainers', 'remind_date', schema='hr')
    _drop_column_if_exists('trainers', 'confirm_date', schema='hr')


def downgrade() -> None:
    op.add_column('trainers', sa.Column('confirm_date', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('remind_date', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('cert_date', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('is_level1', sa.Boolean(), server_default='false', nullable=True), schema='hr')

    op.drop_column('trainers', 'updated_by', schema='hr')
    op.drop_column('trainers', 'created_by', schema='hr')
    op.drop_column('trainers', 'is_primary_trainer', schema='hr')
    op.drop_column('trainers', 'confirmation_reminder', schema='hr')
    op.drop_column('trainers', 'confirmation_date', schema='hr')
    op.drop_column('trainers', 'certification_date', schema='hr')

    op.drop_column('sop_catalog', 'updated_by', schema='hr')
    op.drop_column('sop_catalog', 'created_by', schema='hr')
