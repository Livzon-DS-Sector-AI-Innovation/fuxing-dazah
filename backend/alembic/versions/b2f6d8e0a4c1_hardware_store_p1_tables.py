"""五金库系统原生模块一期 —— 7 张核心表建表迁移

第一个本地 DB 权威仓储域（不走 Bitable）：物料主数据/库位/入库单(头+行)/
领用申请(头+行)/出入库流水。设计文档 docs/DESIGN-五金库系统原生模块-20261104.md §二。

- 数量精度 Numeric(18,3)；movement.quantity 恒正 + direction 表方向
- code 可空（清单导入留空，P2 定案待采购编码表回填），非空时唯一
- erp_doc_no 唯一（erp_import 通道去重键，预留）
- 状态机全部 CheckConstraint 固化（receipts: draft/accepted/rejected；
  requisitions: draft/pending/approved/issued/rejected/cancelled/overdue_unpatched）

Revision ID: b2f6d8e0a4c1
Revises: c3e5f7a9b1d4
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "b2f6d8e0a4c1"
down_revision: str | None = "c3e5f7a9b1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"

# 与 app.modules.warehouse.hardware.models 常量保持一致（迁移内固化，防模型漂移）
_COMMON_COLUMNS = [
    sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("created_by", UUID(), nullable=True),
    sa.Column("updated_by", UUID(), nullable=True),
    sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
]


def upgrade() -> None:
    op.create_table(
        "hardware_materials",
        *_COMMON_COLUMNS,
        sa.Column("code", sa.String(50), nullable=True, comment="物料编码（采购 ERP 编码，导入时留空待回填）"),
        sa.Column("name", sa.String(200), nullable=False, comment="物资名称"),
        sa.Column("spec", sa.String(200), nullable=True, comment="规格型号"),
        sa.Column("unit", sa.String(20), nullable=False, comment="计量单位"),
        sa.Column("category", sa.String(20), nullable=False, comment="类别（7 大类+沉淀类）"),
        sa.Column("managed_class", sa.String(10), nullable=False, server_default="stocked",
                  comment="stocked 共用类占库存 / direct 车间单独需求类不占库存"),
        sa.Column("direct_dept", sa.String(100), nullable=True, comment="direct 专属物资所属车间"),
        sa.Column("inspect_class", sa.String(20), nullable=True, comment="验收类别"),
        sa.Column("safety_stock", sa.Numeric(18, 3), nullable=False, server_default="0", comment="安全库存量"),
        sa.Column("max_stock", sa.Numeric(18, 3), nullable=True, comment="最大库存"),
        sa.Column("monthly_demands", JSONB(), nullable=True, comment="月需求 JSON：{部门: 量}"),
        sa.Column("lead_time_days", sa.Integer(), nullable=True, comment="采购周期（天）"),
        sa.Column("shelf_life_months", sa.Integer(), nullable=True, comment="效期（月）"),
        sa.Column("no_expiry", sa.Boolean(), nullable=True, comment="无效期（五金件默认）"),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=True, comment="最近入库单价"),
        sa.Column("secondary_holder", sa.String(100), nullable=True, comment="二级库归属标注"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true", comment="启用"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("managed_class IN ('stocked', 'direct')", name="ck_hardware_materials_managed_class"),
        sa.CheckConstraint("safety_stock >= 0", name="ck_hardware_materials_safety_stock"),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_materials_code", "hardware_materials", ["code"], unique=True,
        postgresql_where=sa.text("code IS NOT NULL AND is_deleted = false"), schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_materials_name_spec", "hardware_materials", ["name", "spec"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )

    op.create_table(
        "hardware_locations",
        *_COMMON_COLUMNS,
        sa.Column("code", sa.String(50), nullable=False, comment="库位编码，如 P-A-03"),
        sa.Column("zone", sa.String(50), nullable=False, comment="区域：平台下/平台上货架"),
        sa.Column("description", sa.String(200), nullable=True, comment="说明"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_locations_code", "hardware_locations", ["code"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )

    op.create_table(
        "hardware_receipts",
        *_COMMON_COLUMNS,
        sa.Column("receipt_no", sa.String(50), nullable=False, comment="入库单号 WJK-RK-YYMMDD-序号"),
        sa.Column("source", sa.String(20), nullable=False, comment="数据源：ocr/manual/erp_import"),
        sa.Column("erp_doc_no", sa.String(100), nullable=True, comment="ERP 单据号（导入去重键）"),
        sa.Column("erp_imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supplier_name", sa.String(200), nullable=True, comment="供应商"),
        sa.Column("delivery_note_no", sa.String(100), nullable=True, comment="厂家送货单号"),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True, comment="到货日期"),
        sa.Column("target_dept", sa.String(100), nullable=True, comment="direct 类直发领用车间"),
        sa.Column("mode", sa.String(10), nullable=False, server_default="stocked",
                  comment="stocked 实际入库 / direct 出入双流水净零"),
        sa.Column("inspected_by_warehouse", sa.String(100), nullable=True, comment="验收·仓管员 open_id"),
        sa.Column("inspected_by_dept", sa.String(100), nullable=True, comment="验收·使用部门经办人 open_id"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft",
                  comment="draft/accepted/rejected"),
        sa.Column("rejected_reason", sa.String(500), nullable=True, comment="拒收原因（留证）"),
        sa.Column("ocr_result", JSONB(), nullable=True, comment="OCR 结构化提取+逐行匹配置信度"),
        sa.Column("inspect_checklist", JSONB(), nullable=True, comment="物理检查勾选"),
        sa.Column("attachments", JSONB(), nullable=True, comment="附件 file tokens"),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=True, comment="整单参考单价"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True, comment="确认入账时间"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("source IN ('ocr', 'manual', 'erp_import')", name="ck_hardware_receipts_source"),
        sa.CheckConstraint("status IN ('draft', 'accepted', 'rejected')", name="ck_hardware_receipts_status"),
        sa.CheckConstraint("mode IN ('stocked', 'direct')", name="ck_hardware_receipts_mode"),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_receipts_no", "hardware_receipts", ["receipt_no"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_receipts_erp_doc", "hardware_receipts", ["erp_doc_no"], unique=True,
        postgresql_where=sa.text("erp_doc_no IS NOT NULL AND is_deleted = false"), schema=SCHEMA,
    )

    op.create_table(
        "hardware_receipt_items",
        *_COMMON_COLUMNS,
        sa.Column("receipt_id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=True, comment="主数据匹配；direct 未匹配 NULL"),
        sa.Column("name", sa.String(200), nullable=False, comment="品名"),
        sa.Column("spec", sa.String(200), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False, comment="入库数量"),
        sa.Column("location_id", UUID(), nullable=True, comment="库位（仅 stocked）"),
        sa.Column("lot_no", sa.String(50), nullable=True, comment="批次号=本行 id（仅 stocked）"),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True, comment="FIFO 排序键"),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("remaining_quantity", sa.Numeric(18, 3), nullable=True, comment="批次余额（FIFO 扣减）"),
        sa.Column("match_confidence", sa.String(20), nullable=True, comment="匹配方式"),
        sa.Column("match_score", sa.Numeric(5, 2), nullable=True, comment="匹配置信度 0-100"),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=True, comment="行单价"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity > 0", name="ck_hardware_receipt_items_qty"),
        sa.CheckConstraint(
            "remaining_quantity IS NULL OR remaining_quantity >= 0",
            name="ck_hardware_receipt_items_remaining",
        ),
        sa.ForeignKeyConstraint(["receipt_id"], ["warehouse.hardware_receipts.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["warehouse.hardware_materials.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["warehouse.hardware_locations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index("ix_hardware_receipt_items_material", "hardware_receipt_items", ["material_id"], schema=SCHEMA)
    op.create_index("ix_hardware_receipt_items_receipt", "hardware_receipt_items", ["receipt_id"], schema=SCHEMA)

    op.create_table(
        "hardware_requisitions",
        *_COMMON_COLUMNS,
        sa.Column("req_no", sa.String(50), nullable=False, comment="领料单号 WJK-LY-YYMMDD-序号"),
        sa.Column("dept_name", sa.String(100), nullable=False, comment="领用部门"),
        sa.Column("applicant", sa.String(100), nullable=False, comment="领用人姓名"),
        sa.Column("applicant_user_id", UUID(), nullable=True, comment="identity 用户"),
        sa.Column("applicant_open_id", sa.String(100), nullable=True, comment="飞书 open_id"),
        sa.Column("purpose", sa.String(500), nullable=True, comment="用途"),
        sa.Column("req_type", sa.String(10), nullable=False, server_default="normal",
                  comment="normal/urgent/excess"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("approval_channel", sa.String(10), nullable=True, comment="feishu/manual"),
        sa.Column("approval_instance_code", sa.String(100), nullable=True),
        sa.Column("approval_status", sa.String(20), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True, comment="审批备注/超额生产总监提示"),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.String(500), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True, comment="提交审批（预扣生效）"),
        sa.Column("issued_by", sa.String(100), nullable=True, comment="发料仓管员"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_by", sa.String(100), nullable=True, comment="领用人点收"),
        sa.Column("urgent_patch_deadline", sa.DateTime(timezone=True), nullable=True, comment="紧急补单截止(+24h)"),
        sa.Column("patched_at", sa.DateTime(timezone=True), nullable=True, comment="补审批完成"),
        sa.Column("monthly_check", JSONB(), nullable=True, comment="当月已领 vs 月需求快照"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("req_type IN ('normal', 'urgent', 'excess')", name="ck_hardware_requisitions_type"),
        sa.CheckConstraint(
            "status IN ('draft', 'pending', 'approved', 'issued', 'rejected', 'cancelled', 'overdue_unpatched')",
            name="ck_hardware_requisitions_status",
        ),
        sa.ForeignKeyConstraint(["applicant_user_id"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_requisitions_no", "hardware_requisitions", ["req_no"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )
    op.create_index("ix_hardware_requisitions_status", "hardware_requisitions", ["status"], schema=SCHEMA)
    op.create_index("ix_hardware_requisitions_dept", "hardware_requisitions", ["dept_name"], schema=SCHEMA)

    op.create_table(
        "hardware_requisition_items",
        *_COMMON_COLUMNS,
        sa.Column("requisition_id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=False, comment="领料必选主数据"),
        sa.Column("need_qty", sa.Numeric(18, 3), nullable=False, comment="需料量（预扣口径）"),
        sa.Column("issued_qty", sa.Numeric(18, 3), nullable=True, comment="实发量"),
        sa.Column("fifo_lot_allocations", JSONB(), nullable=True, comment="批次分配 [{lot_no,location,qty}]"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("need_qty > 0", name="ck_hardware_req_items_need"),
        sa.CheckConstraint("issued_qty IS NULL OR issued_qty >= 0", name="ck_hardware_req_items_issued"),
        sa.ForeignKeyConstraint(["requisition_id"], ["warehouse.hardware_requisitions.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["warehouse.hardware_materials.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index("ix_hardware_req_items_req", "hardware_requisition_items", ["requisition_id"], schema=SCHEMA)
    op.create_index("ix_hardware_req_items_material", "hardware_requisition_items", ["material_id"], schema=SCHEMA)

    op.create_table(
        "hardware_movements",
        *_COMMON_COLUMNS,
        sa.Column("movement_no", sa.String(50), nullable=False, comment="流水号"),
        sa.Column("direction", sa.String(10), nullable=False, comment="inbound/outbound/adjust"),
        sa.Column("business_type", sa.String(20), nullable=False, comment="业务类型"),
        sa.Column("material_id", UUID(), nullable=True, comment="主数据；direct 未匹配 NULL"),
        sa.Column("material_name", sa.String(200), nullable=False, comment="品名快照"),
        sa.Column("spec", sa.String(200), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("lot_id", UUID(), nullable=True, comment="入库批次行"),
        sa.Column("lot_no", sa.String(50), nullable=True, comment="批次号快照"),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False, comment="数量（恒正）"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, comment="发生时间"),
        sa.Column("operator", sa.String(100), nullable=True, comment="经办人"),
        sa.Column("dept_name", sa.String(100), nullable=True, comment="关联部门"),
        sa.Column("ref_table", sa.String(50), nullable=True, comment="来源单据表"),
        sa.Column("ref_id", UUID(), nullable=True, comment="来源单据 id"),
        sa.Column("erp_status", sa.String(10), nullable=False, server_default="pending",
                  comment="ERP 录入标记 pending/entered"),
        sa.Column("erp_entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erp_operator", sa.String(100), nullable=True),
        sa.Column("remark", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity > 0", name="ck_hardware_movements_qty"),
        sa.CheckConstraint("direction IN ('inbound', 'outbound', 'adjust')", name="ck_hardware_movements_direction"),
        sa.CheckConstraint(
            "business_type IN ('receipt', 'pass_in', 'pass_out', 'req_issue', 'urgent_issue',"
            " 'return_in', 'stocktake_adj', 'scrap')",
            name="ck_hardware_movements_biz_type",
        ),
        sa.CheckConstraint("erp_status IN ('pending', 'entered')", name="ck_hardware_movements_erp_status"),
        sa.ForeignKeyConstraint(["material_id"], ["warehouse.hardware_materials.id"]),
        sa.ForeignKeyConstraint(["lot_id"], ["warehouse.hardware_receipt_items.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_movements_no", "hardware_movements", ["movement_no"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )
    op.create_index("ix_hardware_movements_material", "hardware_movements", ["material_id"], schema=SCHEMA)
    op.create_index("ix_hardware_movements_occurred", "hardware_movements", ["occurred_at"], schema=SCHEMA)
    op.create_index("ix_hardware_movements_business", "hardware_movements", ["business_type"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_hardware_movements_business", table_name="hardware_movements", schema=SCHEMA)
    op.drop_index("ix_hardware_movements_occurred", table_name="hardware_movements", schema=SCHEMA)
    op.drop_index("ix_hardware_movements_material", table_name="hardware_movements", schema=SCHEMA)
    op.drop_index(
        "uq_hardware_movements_no", table_name="hardware_movements", schema=SCHEMA
    )
    op.drop_table("hardware_movements")

    op.drop_index("ix_hardware_req_items_material", table_name="hardware_requisition_items", schema=SCHEMA)
    op.drop_index("ix_hardware_req_items_req", table_name="hardware_requisition_items", schema=SCHEMA)
    op.drop_table("hardware_requisition_items")

    op.drop_index("ix_hardware_requisitions_dept", table_name="hardware_requisitions", schema=SCHEMA)
    op.drop_index("ix_hardware_requisitions_status", table_name="hardware_requisitions", schema=SCHEMA)
    op.drop_index(
        "uq_hardware_requisitions_no", table_name="hardware_requisitions", schema=SCHEMA
    )
    op.drop_table("hardware_requisitions")

    op.drop_index("ix_hardware_receipt_items_receipt", table_name="hardware_receipt_items", schema=SCHEMA)
    op.drop_index("ix_hardware_receipt_items_material", table_name="hardware_receipt_items", schema=SCHEMA)
    op.drop_table("hardware_receipt_items")

    op.drop_index("uq_hardware_receipts_erp_doc", table_name="hardware_receipts", schema=SCHEMA)
    op.drop_index("uq_hardware_receipts_no", table_name="hardware_receipts", schema=SCHEMA)
    op.drop_table("hardware_receipts")

    op.drop_index("uq_hardware_locations_code", table_name="hardware_locations", schema=SCHEMA)
    op.drop_table("hardware_locations")

    op.drop_index("uq_hardware_materials_name_spec", table_name="hardware_materials", schema=SCHEMA)
    op.drop_index("uq_hardware_materials_code", table_name="hardware_materials", schema=SCHEMA)
    op.drop_table("hardware_materials")
