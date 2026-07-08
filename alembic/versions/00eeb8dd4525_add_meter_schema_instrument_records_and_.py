"""add_meter_schema_instrument_records_and_gas_detector_records

Revision ID: 00eeb8dd4525
Revises: d9e76710a2e4
Create Date: 2026-07-01 08:38:59.481480
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '00eeb8dd4525'
down_revision: Union[str, None] = 'd9e76710a2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS meter")

    # ── 标准计量器具台账 ──
    op.create_table('instrument_records',
        sa.Column('asset_number', sa.String(length=80), nullable=False, comment='资产编号'),
        sa.Column('instrument_name', sa.String(length=200), nullable=False, comment='器具名称'),
        sa.Column('model_spec', sa.String(length=200), nullable=True, comment='型号规格'),
        sa.Column('measurement_range', sa.String(length=100), nullable=True, comment='测量范围'),
        sa.Column('accuracy_grade', sa.String(length=50), nullable=True, comment='精度等级'),
        sa.Column('serial_number', sa.String(length=100), nullable=True, comment='器具出厂编号'),
        sa.Column('calibration_cycle_months', sa.Integer(), nullable=True, comment='检定周期(月)'),
        sa.Column('location', sa.String(length=500), nullable=True, comment='使用地点'),
        sa.Column('manufacturer', sa.String(length=200), nullable=True, comment='器具制造商'),
        sa.Column('status', sa.String(length=20), nullable=True, comment='器具状态：在用/停用'),
        sa.Column('color_marking', sa.String(length=20), nullable=True, comment='彩色标志'),
        sa.Column('calibration_date', sa.Date(), nullable=True, comment='检定日期'),
        sa.Column('calibration_unit', sa.String(length=200), nullable=True, comment='检定单位'),
        sa.Column('calibration_result', sa.String(length=50), nullable=True, comment='检定结论'),
        sa.Column('next_calibration_date', sa.Date(), nullable=True, comment='下次检定日期'),
        sa.Column('department', sa.String(length=200), nullable=True, comment='部门/区域'),
        sa.Column('sheet_name', sa.String(length=200), nullable=True, comment='来源 sheet 名（追溯用）'),
        sa.Column('anomaly_flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True, comment='异常标记'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='meter'
    )
    op.create_index('ix_instrument_records_asset_number_active', 'instrument_records', ['asset_number'],
                    unique=True, schema='meter', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_instrument_records_department', 'instrument_records', ['department'], unique=False, schema='meter')
    op.create_index('ix_instrument_records_instrument_name', 'instrument_records', ['instrument_name'], unique=False, schema='meter')
    op.create_index('ix_instrument_records_next_calibration_date', 'instrument_records', ['next_calibration_date'], unique=False, schema='meter')
    op.create_index('ix_instrument_records_status', 'instrument_records', ['status'], unique=False, schema='meter')

    # ── 有毒有害可燃探测器台账 ──
    op.create_table('gas_detector_records',
        sa.Column('instrument_name', sa.String(length=200), nullable=False, comment='器具名称'),
        sa.Column('detection_model', sa.String(length=200), nullable=True, comment='检测型号'),
        sa.Column('measurement_range', sa.String(length=100), nullable=True, comment='量程'),
        sa.Column('product_number', sa.String(length=100), nullable=True, comment='产品编号'),
        sa.Column('installation_type', sa.String(length=50), nullable=True, comment='安装方式'),
        sa.Column('installation_location', sa.String(length=500), nullable=True, comment='安装位置'),
        sa.Column('medium', sa.String(length=500), nullable=True, comment='使用介质'),
        sa.Column('calibration_factor', sa.String(length=100), nullable=True, comment='标定系数'),
        sa.Column('manufacturer_supplier', sa.String(length=500), nullable=True, comment='制造商/供应商'),
        sa.Column('calibration_date', sa.Date(), nullable=True, comment='检定时间'),
        sa.Column('detection_unit', sa.String(length=200), nullable=True, comment='检测单位'),
        sa.Column('next_calibration_date', sa.Date(), nullable=True, comment='下次检定时间'),
        sa.Column('manufacturer', sa.String(length=200), nullable=True, comment='制造单位'),
        sa.Column('department', sa.String(length=200), nullable=True, comment='部门'),
        sa.Column('sheet_name', sa.String(length=200), nullable=True, comment='来源 sheet 名'),
        sa.Column('anomaly_flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True, comment='异常标记'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='meter'
    )
    op.create_index('ix_gas_detector_product_number_active', 'gas_detector_records', ['product_number'],
                    unique=True, schema='meter', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_gas_detector_department', 'gas_detector_records', ['department'], unique=False, schema='meter')
    op.create_index('ix_gas_detector_instrument_name', 'gas_detector_records', ['instrument_name'], unique=False, schema='meter')
    op.create_index('ix_gas_detector_next_calibration_date', 'gas_detector_records', ['next_calibration_date'], unique=False, schema='meter')
    op.create_index('ix_gas_detector_installation_type', 'gas_detector_records', ['installation_type'], unique=False, schema='meter')

    # ── 检测报告 ──
    op.create_table('calibration_reports',
        sa.Column('instrument_id', sa.UUID(), nullable=True, comment='关联标准计量器具'),
        sa.Column('gas_detector_id', sa.UUID(), nullable=True, comment='关联有毒有害可燃探测器'),
        sa.Column('file_name', sa.String(length=255), nullable=False, comment='原始文件名'),
        sa.Column('file_path', sa.String(length=500), nullable=False, comment='MinIO 对象路径'),
        sa.Column('file_size', sa.BigInteger(), nullable=True, comment='文件字节数'),
        sa.Column('content_type', sa.String(length=100), nullable=True, comment='MIME 类型'),
        sa.Column('report_date', sa.Date(), nullable=True, comment='报告日期'),
        sa.Column('remark', sa.String(length=500), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.CheckConstraint('num_nonnulls(instrument_id, gas_detector_id) = 1',
                           name='ck_calibration_reports_single_parent'),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='meter'
    )
    op.create_index('ix_calibration_reports_gas_detector_id', 'calibration_reports', ['gas_detector_id'], unique=False, schema='meter')
    op.create_index('ix_calibration_reports_instrument_id', 'calibration_reports', ['instrument_id'], unique=False, schema='meter')


def downgrade() -> None:
    op.drop_index('ix_calibration_reports_instrument_id', table_name='calibration_reports', schema='meter')
    op.drop_index('ix_calibration_reports_gas_detector_id', table_name='calibration_reports', schema='meter')
    op.drop_table('calibration_reports', schema='meter')

    op.drop_index('ix_gas_detector_installation_type', table_name='gas_detector_records', schema='meter')
    op.drop_index('ix_gas_detector_next_calibration_date', table_name='gas_detector_records', schema='meter')
    op.drop_index('ix_gas_detector_instrument_name', table_name='gas_detector_records', schema='meter')
    op.drop_index('ix_gas_detector_department', table_name='gas_detector_records', schema='meter')
    op.drop_index('ix_gas_detector_product_number_active', table_name='gas_detector_records', schema='meter',
                  postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('gas_detector_records', schema='meter')

    op.drop_index('ix_instrument_records_status', table_name='instrument_records', schema='meter')
    op.drop_index('ix_instrument_records_next_calibration_date', table_name='instrument_records', schema='meter')
    op.drop_index('ix_instrument_records_instrument_name', table_name='instrument_records', schema='meter')
    op.drop_index('ix_instrument_records_department', table_name='instrument_records', schema='meter')
    op.drop_index('ix_instrument_records_asset_number_active', table_name='instrument_records', schema='meter',
                  postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('instrument_records', schema='meter')
