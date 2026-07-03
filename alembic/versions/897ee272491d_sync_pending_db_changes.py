"""sync HR module pending db changes

Revision ID: 897ee272491d
Revises: fe3b3de0002c
Create Date: 2026-07-03 15:18:06.526577
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '897ee272491d'
down_revision: Union[str, None] = 'fe3b3de0002c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== HR schema changes ==========

    # --- 删除废弃表 ---
    op.drop_table('dept_training_personnel', schema='hr')
    op.drop_table('training_evaluations', schema='hr')

    # --- hr.sop_catalog ---
    op.alter_column('sop_catalog', 'department',
                    existing_type=sa.VARCHAR(length=64),
                    type_=sa.String(length=128),
                    existing_nullable=True,
                    schema='hr')
    op.alter_column('sop_catalog', 'id',
                    existing_type=sa.UUID(),
                    server_default=None,
                    existing_nullable=False,
                    schema='hr')
    op.alter_column('sop_catalog', 'created_at',
                    existing_type=postgresql.TIMESTAMP(timezone=True),
                    nullable=False,
                    existing_server_default=sa.text('now()'),
                    schema='hr')
    op.alter_column('sop_catalog', 'updated_at',
                    existing_type=postgresql.TIMESTAMP(timezone=True),
                    nullable=False,
                    existing_server_default=sa.text('now()'),
                    schema='hr')
    op.alter_column('sop_catalog', 'is_deleted',
                    existing_type=sa.BOOLEAN(),
                    nullable=False,
                    existing_server_default=sa.text('false'),
                    schema='hr')
    op.create_index('ix_sop_catalog_category', 'sop_catalog', ['category'], unique=False, schema='hr')
    op.create_index('ix_sop_catalog_department', 'sop_catalog', ['department'], unique=False, schema='hr')
    op.create_foreign_key(None, 'sop_catalog', 'users', ['updated_by'], ['id'], source_schema='hr', referent_schema='identity')
    op.create_foreign_key(None, 'sop_catalog', 'users', ['created_by'], ['id'], source_schema='hr', referent_schema='identity')

    # --- hr.trainers ---
    op.alter_column('trainers', 'trainable_departments',
                    existing_type=sa.VARCHAR(length=256),
                    type_=sa.Text(),
                    comment='可培训部门',
                    existing_nullable=True,
                    schema='hr')
    op.alter_column('trainers', 'qualification_scope',
                    existing_type=sa.VARCHAR(length=256),
                    type_=sa.Text(),
                    comment='资格范围',
                    existing_nullable=True,
                    schema='hr')
    op.alter_column('trainers', 'remarks',
                    existing_type=sa.VARCHAR(length=256),
                    type_=sa.Text(),
                    existing_nullable=True,
                    schema='hr')
    op.alter_column('trainers', 'id',
                    existing_type=sa.UUID(),
                    server_default=None,
                    existing_nullable=False,
                    schema='hr')
    op.alter_column('trainers', 'created_at',
                    existing_type=postgresql.TIMESTAMP(timezone=True),
                    nullable=False,
                    existing_server_default=sa.text('now()'),
                    schema='hr')
    op.alter_column('trainers', 'updated_at',
                    existing_type=postgresql.TIMESTAMP(timezone=True),
                    nullable=False,
                    existing_server_default=sa.text('now()'),
                    schema='hr')
    op.alter_column('trainers', 'is_deleted',
                    existing_type=sa.BOOLEAN(),
                    nullable=False,
                    existing_server_default=sa.text('false'),
                    schema='hr')
    op.create_index('ix_trainers_department', 'trainers', ['department'], unique=False, schema='hr')
    op.create_index('ix_trainers_name', 'trainers', ['name'], unique=False, schema='hr')
    op.create_foreign_key(None, 'trainers', 'users', ['updated_by'], ['id'], source_schema='hr', referent_schema='identity')
    op.create_foreign_key(None, 'trainers', 'users', ['created_by'], ['id'], source_schema='hr', referent_schema='identity')


def downgrade() -> None:
    # --- hr.trainers (reverse) ---
    op.drop_constraint(None, 'trainers', schema='hr', type_='foreignkey')
    op.drop_constraint(None, 'trainers', schema='hr', type_='foreignkey')
    op.drop_index('ix_trainers_name', table_name='trainers', schema='hr')
    op.drop_index('ix_trainers_department', table_name='trainers', schema='hr')
    op.alter_column('trainers', 'is_deleted',
                    existing_type=sa.BOOLEAN(),
                    nullable=True,
                    existing_server_default=sa.text('false'),
                    schema='hr')
    op.alter_column('trainers', 'updated_at',
                    existing_type=postgresql.TIMESTAMP(timezone=True),
                    nullable=True,
                    existing_server_default=sa.text('now()'),
                    schema='hr')
    op.alter_column('trainers', 'created_at',
                    existing_type=postgresql.TIMESTAMP(timezone=True),
                    nullable=True,
                    existing_server_default=sa.text('now()'),
                    schema='hr')
    op.alter_column('trainers', 'id',
                    existing_type=sa.UUID(),
                    server_default=sa.text('gen_random_uuid()'),
                    existing_nullable=False,
                    schema='hr')
    op.alter_column('trainers', 'remarks',
                    existing_type=sa.Text(),
                    type_=sa.VARCHAR(length=256),
                    existing_nullable=True,
                    schema='hr')
    op.alter_column('trainers', 'qualification_scope',
                    existing_type=sa.Text(),
                    type_=sa.VARCHAR(length=256),
                    comment=None,
                    existing_comment='资格范围',
                    existing_nullable=True,
                    schema='hr')
    op.alter_column('trainers', 'trainable_departments',
                    existing_type=sa.Text(),
                    type_=sa.VARCHAR(length=256),
                    comment=None,
                    existing_comment='可培训部门',
                    existing_nullable=True,
                    schema='hr')

    # --- hr.sop_catalog (reverse) ---
    op.drop_constraint(None, 'sop_catalog', schema='hr', type_='foreignkey')
    op.drop_constraint(None, 'sop_catalog', schema='hr', type_='foreignkey')
    op.drop_index('ix_sop_catalog_department', table_name='sop_catalog', schema='hr')
    op.drop_index('ix_sop_catalog_category', table_name='sop_catalog', schema='hr')
    op.alter_column('sop_catalog', 'is_deleted',
                    existing_type=sa.BOOLEAN(),
                    nullable=True,
                    existing_server_default=sa.text('false'),
                    schema='hr')
    op.alter_column('sop_catalog', 'updated_at',
                    existing_type=postgresql.TIMESTAMP(timezone=True),
                    nullable=True,
                    existing_server_default=sa.text('now()'),
                    schema='hr')
    op.alter_column('sop_catalog', 'created_at',
                    existing_type=postgresql.TIMESTAMP(timezone=True),
                    nullable=True,
                    existing_server_default=sa.text('now()'),
                    schema='hr')
    op.alter_column('sop_catalog', 'id',
                    existing_type=sa.UUID(),
                    server_default=sa.text('gen_random_uuid()'),
                    existing_nullable=False,
                    schema='hr')
    op.alter_column('sop_catalog', 'department',
                    existing_type=sa.String(length=128),
                    type_=sa.VARCHAR(length=64),
                    existing_nullable=True,
                    schema='hr')

    # --- 恢复废弃表 ---
    op.create_table('training_evaluations',
                    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
                    sa.Column('training_content', sa.VARCHAR(length=512), autoincrement=False, nullable=True, comment='培训内容'),
                    sa.Column('training_date', sa.DATE(), autoincrement=False, nullable=True, comment='培训日期'),
                    sa.Column('trainer', sa.VARCHAR(length=64), autoincrement=False, nullable=True, comment='培训师'),
                    sa.Column('training_method', sa.VARCHAR(length=32), autoincrement=False, nullable=True, comment='培训方式'),
                    sa.Column('assessment_method', sa.VARCHAR(length=32), autoincrement=False, nullable=True, comment='考核方式'),
                    sa.Column('trainee_names', sa.TEXT(), autoincrement=False, nullable=True, comment='培训对象'),
                    sa.Column('expected_count', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('actual_count', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('exam_count', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('excellent_count', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('qualified_count', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('unqualified_count', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('sick_leave', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('personal_leave', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('maternity_leave', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('absent_count', sa.INTEGER(), autoincrement=False, nullable=True),
                    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
                    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
                    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=True),
                    sa.Column('department', sa.VARCHAR(length=128), autoincrement=False, nullable=True),
                    sa.PrimaryKeyConstraint('id', name=op.f('training_evaluations_pkey')),
                    schema='hr')
    op.create_table('dept_training_personnel',
                    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), autoincrement=False, nullable=False),
                    sa.Column('display_dept', sa.VARCHAR(length=128), autoincrement=False, nullable=True),
                    sa.Column('department', sa.VARCHAR(length=128), autoincrement=False, nullable=True),
                    sa.Column('admins', sa.TEXT(), autoincrement=False, nullable=True),
                    sa.Column('dept_head', sa.TEXT(), autoincrement=False, nullable=True),
                    sa.Column('primary_trainer', sa.TEXT(), autoincrement=False, nullable=True),
                    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
                    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=True),
                    sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=True),
                    sa.PrimaryKeyConstraint('id', name=op.f('dept_training_personnel_pkey')),
                    schema='hr')
