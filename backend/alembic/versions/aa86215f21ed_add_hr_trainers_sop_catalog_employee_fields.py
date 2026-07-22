"""add hr trainers, sop_catalog, employee concurrent_departments & sort_order

Revision ID: aa86215f21ed
Revises: 697ce0ee893f
Create Date: 2026-06-29 16:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa86215f21ed'
down_revision: Union[str, None] = '697ce0ee893f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    # ── hr.sop_catalog: create table if missing (was never in any migration) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr.sop_catalog (
            id UUID DEFAULT gen_random_uuid(),
            file_name VARCHAR(256) NOT NULL,
            sop_number VARCHAR(64),
            category VARCHAR(128),
            department VARCHAR(64),
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            is_deleted BOOLEAN DEFAULT false,
            PRIMARY KEY (id)
        )
    """)

    # ── hr.trainers: create table if missing (was never in any migration) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr.trainers (
            id UUID DEFAULT gen_random_uuid(),
            name VARCHAR(64) NOT NULL,
            department VARCHAR(64),
            trainable_departments VARCHAR(256),
            qualification_scope VARCHAR(256),
            is_level1 VARCHAR(16),
            admin VARCHAR(64),
            remarks VARCHAR(256),
            cert_date DATE,
            remind_date DATE,
            confirm_date DATE,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now(),
            is_deleted BOOLEAN DEFAULT false,
            PRIMARY KEY (id)
        )
    """)

    # ── hr.employees: add concurrent_departments ──
    _add_column_if_missing('employees', sa.Column('concurrent_departments', sa.String(256), nullable=True, comment='兼任部门'), schema='hr')
    # ── hr.employees: add sort_order ──
    _add_column_if_missing('employees', sa.Column('sort_order', sa.Integer(), nullable=True, comment='Excel行序号'), schema='hr')

    # ── hr.sop_catalog: add created_by / updated_by ──
    _add_column_if_missing('sop_catalog', sa.Column('created_by', sa.Uuid(), nullable=True), schema='hr')
    _add_column_if_missing('sop_catalog', sa.Column('updated_by', sa.Uuid(), nullable=True), schema='hr')

    # ── hr.trainers: add new columns ──
    _add_column_if_missing('trainers', sa.Column('certification_date', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('confirmation_date', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('confirmation_reminder', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('is_primary_trainer', sa.Boolean(), server_default='false', nullable=False), schema='hr')
    _add_column_if_missing('trainers', sa.Column('created_by', sa.Uuid(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('updated_by', sa.Uuid(), nullable=True), schema='hr')

    # ── hr.trainers: drop old columns ──
    _drop_column_if_exists('trainers', 'is_level1', schema='hr')
    _drop_column_if_exists('trainers', 'cert_date', schema='hr')
    _drop_column_if_exists('trainers', 'remind_date', schema='hr')
    _drop_column_if_exists('trainers', 'confirm_date', schema='hr')


def downgrade() -> None:
    # trainers: restore old columns (note: old columns may not exist if DROP already ran)
    _add_column_if_missing('trainers', sa.Column('confirm_date', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('remind_date', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('cert_date', sa.Date(), nullable=True), schema='hr')
    _add_column_if_missing('trainers', sa.Column('is_level1', sa.Boolean(), server_default='false', nullable=True), schema='hr')

    # trainers: drop new columns
    _drop_column_if_exists('trainers', 'updated_by', schema='hr')
    _drop_column_if_exists('trainers', 'created_by', schema='hr')
    _drop_column_if_exists('trainers', 'is_primary_trainer', schema='hr')
    _drop_column_if_exists('trainers', 'confirmation_reminder', schema='hr')
    _drop_column_if_exists('trainers', 'confirmation_date', schema='hr')
    _drop_column_if_exists('trainers', 'certification_date', schema='hr')

    # sop_catalog: drop
    _drop_column_if_exists('sop_catalog', 'updated_by', schema='hr')
    _drop_column_if_exists('sop_catalog', 'created_by', schema='hr')

    # employees: drop
    _drop_column_if_exists('employees', 'sort_order', schema='hr')
    _drop_column_if_exists('employees', 'concurrent_departments', schema='hr')
