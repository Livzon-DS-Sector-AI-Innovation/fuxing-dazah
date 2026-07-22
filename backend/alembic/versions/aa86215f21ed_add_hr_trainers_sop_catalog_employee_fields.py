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


def upgrade() -> None:
    # ── hr.employees: add concurrent_departments ──
    op.add_column('employees', sa.Column('concurrent_departments', sa.String(256), nullable=True, comment='兼任部门'), schema='hr')
    # ── hr.employees: add sort_order ──
    op.add_column('employees', sa.Column('sort_order', sa.Integer(), nullable=True, comment='Excel行序号'), schema='hr')

    # ── hr.sop_catalog: add created_by / updated_by ──
    op.add_column('sop_catalog', sa.Column('created_by', sa.Uuid(), nullable=True), schema='hr')
    op.add_column('sop_catalog', sa.Column('updated_by', sa.Uuid(), nullable=True), schema='hr')

    # ── hr.trainers: add new columns ──
    op.add_column('trainers', sa.Column('certification_date', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('confirmation_date', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('confirmation_reminder', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('is_primary_trainer', sa.Boolean(), server_default='false', nullable=False), schema='hr')
    op.add_column('trainers', sa.Column('created_by', sa.Uuid(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('updated_by', sa.Uuid(), nullable=True), schema='hr')

    # ── hr.trainers: drop old columns ──
    op.drop_column('trainers', 'is_level1', schema='hr')
    op.drop_column('trainers', 'cert_date', schema='hr')
    op.drop_column('trainers', 'remind_date', schema='hr')
    op.drop_column('trainers', 'confirm_date', schema='hr')


def downgrade() -> None:
    # trainers: restore old columns
    op.add_column('trainers', sa.Column('confirm_date', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('remind_date', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('cert_date', sa.Date(), nullable=True), schema='hr')
    op.add_column('trainers', sa.Column('is_level1', sa.Boolean(), server_default='false', nullable=True), schema='hr')

    # trainers: drop new columns
    op.drop_column('trainers', 'updated_by', schema='hr')
    op.drop_column('trainers', 'created_by', schema='hr')
    op.drop_column('trainers', 'is_primary_trainer', schema='hr')
    op.drop_column('trainers', 'confirmation_reminder', schema='hr')
    op.drop_column('trainers', 'confirmation_date', schema='hr')
    op.drop_column('trainers', 'certification_date', schema='hr')

    # sop_catalog: drop
    op.drop_column('sop_catalog', 'updated_by', schema='hr')
    op.drop_column('sop_catalog', 'created_by', schema='hr')

    # employees: drop
    op.drop_column('employees', 'sort_order', schema='hr')
    op.drop_column('employees', 'concurrent_departments', schema='hr')
