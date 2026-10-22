"""物料容器赋码 Schema。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONTAINER_STATUSES = Literal["labeled", "in_warehouse", "qualified", "issued", "returned", "void"]


class MaterialContainerGenerateRequest(BaseModel):
    """批量赋码：同一进厂批次的 N 瓶/桶物料，连续生成容器号。"""

    material_code: str = Field(max_length=100, description="物料代码（容器号中段）")
    material_name: str = Field(max_length=200, description="物料名称（标签人眼可读）")
    vendor_code: str | None = Field(default=None, max_length=100, description="供应商代码")
    inbound_batch_no: str = Field(max_length=100, description="进厂批号")
    expiry_date: str | None = Field(default=None, max_length=32, description="复验期 YYYY-MM-DD")
    count: int = Field(default=1, ge=1, le=500, description="本批容器数量")
    material_request_id: uuid.UUID | None = Field(
        default=None, description="可选：挂到请验单（放行结论联动本批容器状态）"
    )


class MaterialContainerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    container_no: str
    material_code: str
    material_name: str
    vendor_code: str | None
    inbound_batch_no: str
    inbound_date: str | None
    location: str | None
    expiry_date: str | None
    seq: int
    status: str
    created_at: datetime


class MaterialContainerListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    container_no: str
    material_code: str
    material_name: str
    inbound_batch_no: str
    inbound_date: str | None
    location: str | None
    expiry_date: str | None
    seq: int
    status: str
    created_at: datetime


class ContainerMoveRequest(BaseModel):
    """进出库操作。in：入库登记（labeled/returned → in_warehouse）；out：领料出库（in_warehouse/qualified → issued）；
    return：退库（issued → returned）；auto：按当前状态自动判定（labeled→入库；in_warehouse/qualified→出库；其余状态报错）。"""

    op_type: Literal["in", "out", "auto", "return"]
    related_doc: str | None = Field(default=None, max_length=100, description="关联单据号（领料单等）")
    remark: str | None = Field(default=None, max_length=500)


class ContainerBatchMoveRequest(BaseModel):
    """批量进出库：逐容器校验流转，单个失败不影响整体，结果逐条返回。"""

    container_nos: list[str] = Field(min_length=1, max_length=200)
    op_type: Literal["in", "out", "auto", "return"]
    related_doc: str | None = Field(default=None, max_length=100, description="关联单据号（领料单等）")
    remark: str | None = Field(default=None, max_length=500)


class ContainerLocationUpdate(BaseModel):
    """库位维护（货架编号）。"""

    location: str = Field(max_length=50)


class ContainerStatusUpdate(BaseModel):
    """阶段1人工状态流转（后续接入请验/放行链路后由系统自动联动）。"""

    status: Literal["in_warehouse", "qualified", "void"]
    remark: str | None = Field(default=None, max_length=200, description="流转原因（作废时建议填写）")


class ContainerMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    container_no: str
    op_type: str
    from_status: str
    to_status: str
    related_doc: str | None
    remark: str | None
    op_at: datetime


class ContainerLabelRequest(BaseModel):
    """按容器号批量出标签 PDF。reprint=True 时记为补印流水（防重复贴标留痕）。"""

    container_nos: list[str] = Field(min_length=1, max_length=200)
    reprint: bool = Field(default=False)


class MaterialCreate(BaseModel):
    """物料字典新增。"""

    code: str = Field(max_length=100, description="物料代码（容器号中段，不能含空格/斜杠）")
    name: str = Field(max_length=200)
    category: str | None = Field(default=None, max_length=32, description="原料/辅料/包材/溶剂")
    vendor_name: str | None = Field(default=None, max_length=100, description="默认供应商名称")
    vendor_code: str | None = Field(default=None, max_length=100, description="供应商代码（供应商字典）")
    pack_spec: str | None = Field(default=None, max_length=50, description="包装规格，如 5kg/听")
    min_stock: int | None = Field(default=None, ge=0, description="安全库存阈值（瓶/桶数）")
    valid_months: int | None = Field(default=None, ge=1, le=120, description="效期月数（赋码时自动计算复验期）")
    remark: str | None = Field(default=None, max_length=200)


class MaterialUpdate(BaseModel):
    """物料字典更新（全部可选）。"""

    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=32)
    vendor_name: str | None = Field(default=None, max_length=100)
    vendor_code: str | None = Field(default=None, max_length=100)
    pack_spec: str | None = Field(default=None, max_length=50)
    min_stock: int | None = Field(default=None, ge=0)
    valid_months: int | None = Field(default=None, ge=1, le=120)
    remark: str | None = Field(default=None, max_length=200)


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    category: str | None
    vendor_name: str | None
    vendor_code: str | None
    pack_spec: str | None
    min_stock: int | None
    valid_months: int | None
    remark: str | None
    created_at: datetime


class MaterialSummaryItem(BaseModel):
    """按物料聚合的库存概览（看板/采购建议共用）。"""

    material_code: str
    material_name: str
    labeled: int
    in_warehouse: int
    qualified: int
    issued: int
    returned: int
    total: int
    available: int
    near_expiry: int
    expired: int
    min_stock: int | None
    below_stock: bool


class MaterialMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    container_no: str
    material_code: str | None
    material_name: str | None
    op_type: str
    from_status: str
    to_status: str
    related_doc: str | None
    remark: str | None
    op_at: datetime


class SupplierCreate(BaseModel):
    """供应商主数据新增。"""

    code: str = Field(max_length=100, description="供应商代码（不能含空格/斜杠）")
    name: str = Field(max_length=200)
    contact: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    qual_expiry_date: str | None = Field(default=None, max_length=32, description="资质效期 YYYY-MM-DD")
    remark: str | None = Field(default=None, max_length=200)


class SupplierUpdate(BaseModel):
    """供应商主数据更新（全部可选）。"""

    name: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    qual_expiry_date: str | None = Field(default=None, max_length=32)
    remark: str | None = Field(default=None, max_length=200)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    contact: str | None
    phone: str | None
    qual_expiry_date: str | None
    remark: str | None
    created_at: datetime


class StocktakeCreate(BaseModel):
    """创建盘点单：可选限定物料范围（空=全部物料在库容器）。"""

    scope_material_code: str | None = Field(default=None, max_length=100)
    remark: str | None = Field(default=None, max_length=200)


class StocktakeScanRequest(BaseModel):
    container_no: str = Field(max_length=100)


class StocktakeSheetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sheet_no: str
    scope_material_code: str | None
    status: str
    remark: str | None
    expected_count: int
    scanned_count: int
    missing_count: int
    extra_count: int
    anomaly_count: int
    created_at: datetime


class StocktakeItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    container_no: str
    result: str
    status_snapshot: str | None
    material_code: str | None
    material_name: str | None
    created_at: datetime


class MonthlyReportItem(BaseModel):
    """月度汇总：按物料的当月出入库/退库/状态流转笔数与当前可用。"""

    material_code: str
    material_name: str
    in_count: int
    out_count: int
    return_count: int
    status_count: int
    available: int


class MaterialRequestCreate(BaseModel):
    """创建请验单。"""

    material_code: str = Field(max_length=100)
    vendor_code: str | None = Field(default=None, max_length=100)
    inbound_batch_no: str = Field(max_length=100)
    inbound_qty: int = Field(default=1, ge=1, le=100000)
    inbound_date: str | None = Field(default=None, max_length=32, description="到货日期 YYYY-MM-DD")


class MaterialRequestSample(BaseModel):
    """取样登记。"""

    sampled_at: str | None = Field(default=None, max_length=32, description="取样日期 YYYY-MM-DD")
    sampled_qty: int | None = Field(default=None, ge=1, description="取样数量")


class MaterialRequestRelease(BaseModel):
    """放行结论。"""

    verdict: Literal["release", "reject", "concede"]
    remark: str | None = Field(default=None, max_length=200, description="拒收/让步原因")


class MaterialRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_no: str
    material_code: str
    material_name: str
    vendor_code: str | None
    vendor_name: str | None
    inbound_batch_no: str
    inbound_qty: int
    inbound_date: str | None
    status: str
    sampled_at: str | None
    sampled_qty: int | None
    verdict: str | None
    verdict_remark: str | None
    task_id: uuid.UUID | None
    linked_containers: int = Field(default=0, description="已挂单容器数（列表接口填充）")
    created_at: datetime


class MaterialStandardCreate(BaseModel):
    """物料质量标准（物料+供应商）。"""

    material_code: str = Field(max_length=100)
    vendor_code: str | None = Field(default=None, max_length=100, description="空=该物料通用标准")
    version: str | None = Field(default=None, max_length=32)
    remark: str | None = Field(default=None, max_length=200)


class MaterialStandardItemCreate(BaseModel):
    standard_id: uuid.UUID
    seq: int | None = Field(default=None)
    category: str | None = Field(default=None, max_length=100)
    item_name: str = Field(max_length=200)
    sop_no: str | None = Field(default=None, max_length=100)
    standard_text: str | None = Field(default=None, max_length=300)
    operator: str | None = Field(default=None, max_length=10)
    limit_min: float | None = Field(default=None)
    limit_max: float | None = Field(default=None)
    method_source: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=200)


class MaterialStandardItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    standard_id: uuid.UUID
    seq: int | None
    category: str | None
    item_name: str
    sop_no: str | None
    standard_text: str | None
    operator: str | None
    limit_min: float | None
    limit_max: float | None
    method_source: str | None
    remark: str | None


class MaterialStandardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    material_code: str
    material_name: str
    vendor_code: str | None
    version: str | None
    remark: str | None
    created_at: datetime


class LabItemCreate(BaseModel):
    """试剂/对照品/滴定液/仪器校验台账新增。"""

    item_type: Literal["reagent", "reference_standard", "titrant", "instrument"]
    name: str = Field(max_length=200)
    batch_no: str | None = Field(default=None, max_length=100)
    spec: str | None = Field(default=None, max_length=100)
    opened_at: str | None = Field(default=None, max_length=32, description="开封日期 YYYY-MM-DD")
    expiry_date: str | None = Field(default=None, max_length=32, description="效期/下次校验日 YYYY-MM-DD")
    remark: str | None = Field(default=None, max_length=200)


class LabItemUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    batch_no: str | None = Field(default=None, max_length=100)
    spec: str | None = Field(default=None, max_length=100)
    opened_at: str | None = Field(default=None, max_length=32)
    expiry_date: str | None = Field(default=None, max_length=32)
    remark: str | None = Field(default=None, max_length=200)


class LabItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_type: str
    name: str
    batch_no: str | None
    spec: str | None
    opened_at: str | None
    expiry_date: str | None
    remark: str | None
    created_at: datetime


class InspectionPlanCreate(BaseModel):
    department: str = Field(max_length=128, description="车间/部门")
    product_name: str = Field(max_length=200, description="品种/产品名称")
    batch_no: str | None = Field(default=None, max_length=100)
    plan_time: str = Field(description="计划请检时间 YYYY-MM-DD HH:mm")
    remark: str | None = Field(default=None, max_length=200)


class InspectionPlanUpdate(BaseModel):
    status: Literal["pending", "inspected"]


class InspectionPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    department: str
    product_name: str
    batch_no: str | None
    plan_time: str
    status: str
    remark: str | None
    created_at: datetime


class MicroRecordCreate(BaseModel):
    """微生物限度/菌落计数登记新增（AI 预计数可选，不作判定依据）。"""

    sample_name: str = Field(max_length=200, description="样品名称/品名")
    batch_number: str | None = Field(default=None, max_length=100)
    sample_date: str | None = Field(default=None, max_length=32, description="检测日期 YYYY-MM-DD")
    colony_count: int | None = Field(default=None, ge=0, description="菌落计数（人工确认数，判定依据）")
    ai_count: int | None = Field(default=None, ge=0, description="AI 预计数（预留）")
    alert_limit: float | None = Field(default=None, ge=0, description="警戒线")
    action_limit: float | None = Field(default=None, ge=0, description="标准限（行动限）")
    remark: str | None = Field(default=None, max_length=200)


class MicroRecordUpdate(BaseModel):
    colony_count: int | None = Field(default=None, ge=0)
    ai_count: int | None = Field(default=None, ge=0)
    alert_limit: float | None = Field(default=None, ge=0)
    action_limit: float | None = Field(default=None, ge=0)
    remark: str | None = Field(default=None, max_length=200)


class MicroRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sample_name: str
    batch_number: str | None
    sample_date: str | None
    colony_count: int | None
    ai_count: int | None
    alert_limit: float | None
    action_limit: float | None
    judge: str | None
    photo_keys: list[str] | None
    remark: str | None
    created_at: datetime


class RetainedSampleCreate(BaseModel):
    """留样登记新增（成品/物料批留样台账）。"""

    source_type: Literal["product", "material"] = Field(
        default="product", description="product 成品 / material 物料"
    )
    batch_no: str = Field(max_length=100, description="批号")
    sample_name: str = Field(max_length=200, description="名称/品名")
    qty: str | None = Field(default=None, max_length=50, description="留样量（如 2 瓶）")
    location: str | None = Field(default=None, max_length=50, description="贮存位置（柜号）")
    retained_at: str | None = Field(default=None, max_length=32, description="留样日期 YYYY-MM-DD")
    destroy_due_date: str | None = Field(
        default=None, max_length=32, description="销毁到期日 YYYY-MM-DD（到期提醒依据）"
    )
    remark: str | None = Field(default=None, max_length=200)


class RetainedSampleUpdate(BaseModel):
    """留样登记更新（全部可选，仅更新传入字段）。"""

    source_type: Literal["product", "material"] | None = None
    batch_no: str | None = Field(default=None, max_length=100)
    sample_name: str | None = Field(default=None, max_length=200)
    qty: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=50)
    retained_at: str | None = Field(default=None, max_length=32)
    destroy_due_date: str | None = Field(default=None, max_length=32)
    remark: str | None = Field(default=None, max_length=200)


class RetainedSampleDestroy(BaseModel):
    """销毁登记：登记人自动记录为当前登录用户，需第二人再点一次确认（双人复核模式）。"""

    destroyed_at: str = Field(max_length=32, description="销毁日期 YYYY-MM-DD")
    remark: str | None = Field(default=None, max_length=200, description="销毁备注（覆盖原备注）")


class RetainedSampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: str
    batch_no: str
    sample_name: str
    qty: str | None
    location: str | None
    retained_at: str | None
    destroy_due_date: str | None
    destroyed_at: str | None
    destroyed_by: uuid.UUID | None
    destroyed_by_name: str | None
    destroy_confirm_by: uuid.UUID | None
    destroy_confirm_by_name: str | None
    status: str
    remark: str | None
    created_at: datetime
