"""物料容器二维码赋码模型：物料字典、容器台账、进出库流水。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class QualityMaterialRequest(BaseModel):
    """物料请验单：到货 → 请验 → 取样 → 检验任务 → 放行/拒收/让步。

    status: pending_sample 待取样 → sampled 已取样 → in_test 检验中
    → released 已放行 / rejected 已拒收 / conceded 让步接收；void 作废。
    """

    __tablename__ = "quality_material_requests"
    __table_args__ = (
        Index(
            "uq_quality_material_request_no",
            "request_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_material_request_status", "status"),
        Index("ix_quality_material_request_batch", "inbound_batch_no"),
        {"schema": "quality"},
    )

    request_no: Mapped[str] = mapped_column(String(100), comment="请验单号 MR+YYMMDD+序号")
    material_code: Mapped[str] = mapped_column(String(100), comment="物料代码（逻辑引用 quality_materials.code）")
    material_name: Mapped[str] = mapped_column(String(200), comment="物料名称快照")
    vendor_code: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="供应商代码")
    vendor_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="供应商名称快照")
    inbound_batch_no: Mapped[str] = mapped_column(String(100), comment="进厂批号")
    inbound_qty: Mapped[int] = mapped_column(Integer, default=1, comment="到货数量（瓶/桶）")
    inbound_date: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="到货日期 YYYY-MM-DD")
    status: Mapped[str] = mapped_column(
        String(32), default="pending_sample",
        comment="pending_sample/sampled/in_test/released/rejected/conceded/void",
    )
    sampled_at: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="取样日期")
    sampled_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="取样数量")
    sampled_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="取样人")
    verdict: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="放行结论 release/reject/concede"
    )
    verdict_remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="放行备注（拒收/让步原因）")
    released_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="放行人")
    released_at: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="放行日期 YYYY-MM-DD")
    task_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="关联物料检验任务（逻辑引用 quality_test_tasks.id）")


class QualityMaterialStandard(BaseModel):
    """物料质量标准（按物料+供应商；同物料不同供应商可多条）。"""

    __tablename__ = "quality_material_standards"
    __table_args__ = (
        Index(
            "uq_quality_material_std",
            "material_code",
            "vendor_code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    material_code: Mapped[str] = mapped_column(String(100), comment="物料代码")
    material_name: Mapped[str] = mapped_column(String(200), comment="物料名称快照")
    vendor_code: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="供应商代码（空=通用标准）")
    version: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="版本号")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityMaterialStandardItem(BaseModel):
    """物料质量标准检验项目行（与产品标准行同构）。"""

    __tablename__ = "quality_material_standard_items"
    __table_args__ = (
        Index(
            "uq_quality_material_std_item",
            "standard_id",
            "sop_no",
            "item_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    standard_id: Mapped[uuid.UUID] = mapped_column(comment="逻辑引用 quality_material_standards.id（无 FK）")
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="序号")
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="项目大类")
    item_name: Mapped[str] = mapped_column(String(200), comment="项目名称")
    sop_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="方法 SOP 号")
    standard_text: Mapped[str | None] = mapped_column(String(300), nullable=True, comment="合格标准原文")
    operator: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="≤ ≥ < > 范围")
    limit_min: Mapped[float | None] = mapped_column(nullable=True, comment="限度下限")
    limit_max: Mapped[float | None] = mapped_column(nullable=True, comment="限度上限")
    method_source: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="方法来源")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityLabItem(BaseModel):
    """实验室试剂/对照品/滴定液/仪器校验台账（效期到期提醒数据源）。"""

    __tablename__ = "quality_lab_items"
    __table_args__ = (
        Index("ix_quality_lab_item_type", "item_type"),
        Index("ix_quality_lab_item_expiry", "expiry_date"),
        {"schema": "quality"},
    )

    item_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="reagent 试剂 / reference_standard 对照品 / titrant 滴定液 / instrument 仪器校验",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="名称/仪器名称")
    batch_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="批号（试剂类）")
    spec: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="规格")
    opened_at: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="开封日期 YYYY-MM-DD（试剂开启后效期从开封算）"
    )
    expiry_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="效期/下次校验日期 YYYY-MM-DD（到期提醒依据）"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityInspectionPlan(BaseModel):
    """车间中控及成品请检计划（统一台账，请检时间到点提醒）。"""

    __tablename__ = "quality_inspection_plans"
    __table_args__ = (
        Index("ix_quality_plan_department", "department"),
        Index("ix_quality_plan_plan_time", "plan_time"),
        {"schema": "quality"},
    )

    department: Mapped[str] = mapped_column(String(128), nullable=False, comment="车间/部门")
    product_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="品种/产品名称")
    batch_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="批号")
    plan_time: Mapped[str] = mapped_column(String(32), nullable=False, comment="计划请检时间 YYYY-MM-DD HH:mm")
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending",
        comment="pending 待请检 / inspected 已请检",
    )
    assignments: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True, comment="排班 [{\"sop_no\": ..., \"assignee_id\": ...}]"
    )
    notified_at: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="排班通知最近下发时间 YYYY-MM-DD HH:mm（排班变更后清空）"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityMicroRecord(BaseModel):
    """微生物限度/平板菌落计数登记（AI 计数插件预留：ai_count 供未来视觉模型填入）。"""

    __tablename__ = "quality_micro_records"
    __table_args__ = (
        Index("ix_quality_micro_batch", "batch_number"),
        Index("ix_quality_micro_sample_date", "sample_date"),
        {"schema": "quality"},
    )

    sample_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="样品名称/品名")
    batch_number: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="样品批号")
    sample_date: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="检测日期 YYYY-MM-DD")
    colony_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="菌落计数（人工确认数，判定依据）")
    ai_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="AI 预计数（视觉模型插件预留，不作判定依据）")
    alert_limit: Mapped[float | None] = mapped_column(nullable=True, comment="警戒线")
    action_limit: Mapped[float | None] = mapped_column(nullable=True, comment="标准限（行动限）")
    judge: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="pass 合格 / alert 超警戒 / action 超标准（按人工确认数判定）"
    )
    photo_keys: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="平皿照片对象键列表（MinIO/本地兜底）"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityRetainedSample(BaseModel):
    """留样台账：物料/成品批留样登记、贮存位置、销毁到期提醒。"""

    __tablename__ = "quality_retained_samples"
    __table_args__ = (
        Index("ix_quality_retained_batch", "batch_no"),
        Index("ix_quality_retained_destroy_due", "destroy_due_date"),
        {"schema": "quality"},
    )

    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="product 成品 / material 物料"
    )
    batch_no: Mapped[str] = mapped_column(String(100), nullable=False, comment="批号")
    sample_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="名称/品名")
    qty: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="留样量（如 2 瓶）")
    location: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="贮存位置（柜号）")
    retained_at: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="留样日期 YYYY-MM-DD")
    destroy_due_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="销毁到期日 YYYY-MM-DD（到期提醒依据）"
    )
    destroyed_at: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="实际销毁日期")
    destroyed_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="销毁登记人")
    destroy_confirm_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="销毁双人确认第二人")
    status: Mapped[str] = mapped_column(
        String(32), default="active", server_default="active", comment="active 在留 / destroyed 已销毁"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityStocktakeSheet(BaseModel):
    """库存盘点单：扫码盘点在库容器，结束自动对比系统库存出差异清单。"""

    __tablename__ = "quality_stocktake_sheets"
    __table_args__ = (
        Index(
            "uq_quality_stocktake_sheet_no",
            "sheet_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_stocktake_sheet_status", "status"),
        {"schema": "quality"},
    )

    sheet_no: Mapped[str] = mapped_column(String(100), comment="盘点单号 ST+YYMMDD+序号")
    scope_material_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="盘点范围物料代码，空=全部物料"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="in_progress", comment="in_progress/completed/void"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")
    expected_count: Mapped[int] = mapped_column(Integer, default=0, comment="系统在库容器数")
    scanned_count: Mapped[int] = mapped_column(Integer, default=0, comment="实扫容器数")
    missing_count: Mapped[int] = mapped_column(Integer, default=0, comment="盘亏（系统在库未扫到）")
    extra_count: Mapped[int] = mapped_column(Integer, default=0, comment="盘盈（系统有但不在库，实物多出）")
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0, comment="异常（扫到系统不存在的容器号，疑似贴错/外购未赋码）")


class QualityStocktakeItem(BaseModel):
    """盘点扫码明细（按容器号去重）。"""

    __tablename__ = "quality_stocktake_items"
    __table_args__ = (
        Index("ix_quality_stocktake_item_sheet", "sheet_id"),
        Index(
            "uq_quality_stocktake_item_container",
            "sheet_id",
            "container_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "quality"},
    )

    sheet_id: Mapped[uuid.UUID] = mapped_column(comment="逻辑引用 quality_stocktake_sheets.id（无 FK）")
    container_no: Mapped[str] = mapped_column(String(100), comment="扫到的容器号")
    result: Mapped[str] = mapped_column(
        String(32), comment="matched 在库匹配 / out_of_scope 系统有但不在库 / not_found 系统不存在"
    )
    status_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="扫描时容器状态快照")
    material_code: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="物料代码快照（系统有容器时）")
    material_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="物料名称快照")
    scanned_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="扫码人")


class QualitySupplier(BaseModel):
    """供应商主数据：资质效期到期提醒与赋码/采购建议的供应商维度。"""

    __tablename__ = "quality_suppliers"
    __table_args__ = (
        Index(
            "uq_quality_supplier_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_supplier_name", "name"),
        {"schema": "quality"},
    )

    code: Mapped[str] = mapped_column(String(100), comment="供应商代码")
    name: Mapped[str] = mapped_column(String(200), comment="供应商名称")
    contact: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="联系人")
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="联系电话")
    qual_expiry_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="资质效期 YYYY-MM-DD（到期提醒）"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityMaterial(BaseModel):
    """物料主数据字典（轻量版）：赋码下拉与采购清单的基础。

    后续 01 方案物料标准库落地后，标准按「物料+供应商」挂在本表之下。
    """

    __tablename__ = "quality_materials"
    __table_args__ = (
        Index(
            "uq_quality_material_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_material_name", "name"),
        {"schema": "quality"},
    )

    code: Mapped[str] = mapped_column(String(100), comment="物料代码（容器号中段）")
    name: Mapped[str] = mapped_column(String(200), comment="物料名称")
    category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="类别：原料/辅料/包材/溶剂"
    )
    vendor_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="默认供应商名称")
    vendor_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="供应商代码（逻辑引用 quality.quality_suppliers.code）"
    )
    pack_spec: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="包装规格，如 5kg/听")
    min_stock: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="安全库存阈值（瓶/桶数），采购建议依据"
    )
    valid_months: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="效期月数（赋码时自动计算复验期=入库日期+N月，可手改）"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityMaterialContainer(BaseModel):
    """物料容器（每瓶/桶一个唯一容器号，二维码赋码）。

    status 流转：labeled 已赋码 → in_warehouse 在库待验 → qualified 合格
    → issued 已领出 / returned 退库；void 作废。阶段1为人工流转，
    后续接入请验/放行链路后自动联动（见质量设计文档 06）。
    """

    __tablename__ = "quality_material_containers"
    __table_args__ = (
        Index(
            "uq_quality_container_no",
            "container_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_container_batch", "inbound_batch_no"),
        Index("ix_quality_container_status", "status"),
        {"schema": "quality"},
    )

    container_no: Mapped[str] = mapped_column(String(100), comment="容器号，如 MC-VAN-20261010-0001")
    material_code: Mapped[str] = mapped_column(String(100), comment="物料代码")
    material_name: Mapped[str] = mapped_column(String(200), comment="物料名称")
    vendor_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="供应商代码"
    )
    inbound_batch_no: Mapped[str] = mapped_column(String(100), comment="进厂批号")
    material_request_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="所属请验单（逻辑引用 quality.quality_material_requests.id，放行联动用）"
    )
    inbound_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="入库登记日期 YYYY-MM-DD（入库动作自动记录）"
    )
    location: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="库位（货架编号，如 A-01-03）"
    )
    expiry_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="复验期 YYYY-MM-DD（过期拦截用，阶段3）"
    )
    seq: Mapped[int] = mapped_column(comment="该批第几瓶（容器号末段流水）")
    status: Mapped[str] = mapped_column(
        String(32), default="labeled", comment="labeled/in_warehouse/qualified/issued/returned/void"
    )
    qr_issued_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="赋码人")


class QualityContainerMovement(BaseModel):
    """容器进出库流水（操作日志，供台账审计）。"""

    __tablename__ = "quality_container_movements"
    __table_args__ = (
        Index("ix_quality_container_mv_container", "container_id"),
        {"schema": "quality"},
    )

    container_id: Mapped[uuid.UUID] = mapped_column(
        comment="逻辑引用 quality.quality_material_containers.id（无 FK）"
    )
    container_no: Mapped[str] = mapped_column(String(100), comment="操作时容器号快照")
    op_type: Mapped[str] = mapped_column(String(16), comment="in 入库登记 / out 领料出库 / status 人工流转")
    from_status: Mapped[str] = mapped_column(String(32), comment="操作前状态")
    to_status: Mapped[str] = mapped_column(String(32), comment="操作后状态")
    operator: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="操作人")
    op_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now, comment="操作时间")
    related_doc: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="关联单据号（领料单等）"
    )
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")
