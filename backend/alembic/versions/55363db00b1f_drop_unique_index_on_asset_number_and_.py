"""drop unique index on asset_number and product_number

Revision ID: 55363db00b1f
Revises: 7bf26efe0801
Create Date: 2026-07-07 14:07:11.528172
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55363db00b1f'
down_revision: Union[str, None] = '7bf26efe0801'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 删除标准计量器具资产编号唯一索引，替换为非唯一索引
    op.drop_index(
        "ix_instrument_records_asset_number_active",
        table_name="instrument_records",
        schema="meter",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_instrument_records_asset_number_active",
        "instrument_records",
        ["asset_number"],
        unique=False,
        schema="meter",
        postgresql_where=sa.text("is_deleted = false"),
    )

    # 删除探测器产品编号唯一索引，替换为非唯一索引
    op.drop_index(
        "ix_gas_detector_product_number_active",
        table_name="gas_detector_records",
        schema="meter",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_gas_detector_product_number_active",
        "gas_detector_records",
        ["product_number"],
        unique=False,
        schema="meter",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    # 恢复唯一索引
    op.drop_index(
        "ix_instrument_records_asset_number_active",
        table_name="instrument_records",
        schema="meter",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_instrument_records_asset_number_active",
        "instrument_records",
        ["asset_number"],
        unique=True,
        schema="meter",
        postgresql_where=sa.text("is_deleted = false"),
    )

    op.drop_index(
        "ix_gas_detector_product_number_active",
        table_name="gas_detector_records",
        schema="meter",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_gas_detector_product_number_active",
        "gas_detector_records",
        ["product_number"],
        unique=True,
        schema="meter",
        postgresql_where=sa.text("is_deleted = false"),
    )
