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


class MaterialContainerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    container_no: str
    material_code: str
    material_name: str
    vendor_code: str | None
    inbound_batch_no: str
    inbound_date: str | None
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
    expiry_date: str | None
    seq: int
    status: str
    created_at: datetime


class ContainerMoveRequest(BaseModel):
    """进出库操作。in：入库登记（labeled → in_warehouse）；out：领料出库（in_warehouse/qualified → issued）；
    auto：按当前状态自动判定（labeled→入库；in_warehouse/qualified→出库；其余状态报错）。"""

    op_type: Literal["in", "out", "auto"]
    related_doc: str | None = Field(default=None, max_length=100, description="关联单据号（领料单等）")
    remark: str | None = Field(default=None, max_length=500)


class ContainerBatchMoveRequest(BaseModel):
    """批量进出库：逐容器校验流转，单个失败不影响整体，结果逐条返回。"""

    container_nos: list[str] = Field(min_length=1, max_length=200)
    op_type: Literal["in", "out", "auto"]
    related_doc: str | None = Field(default=None, max_length=100, description="关联单据号（领料单等）")
    remark: str | None = Field(default=None, max_length=500)


class ContainerStatusUpdate(BaseModel):
    """阶段1人工状态流转（后续接入请验/放行链路后由系统自动联动）。"""

    status: Literal["in_warehouse", "qualified", "void"]


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
    """按容器号批量出标签 PDF。"""

    container_nos: list[str] = Field(min_length=1, max_length=200)


class MaterialCreate(BaseModel):
    """物料字典新增。"""

    code: str = Field(max_length=100, description="物料代码（容器号中段，不能含空格/斜杠）")
    name: str = Field(max_length=200)
    category: str | None = Field(default=None, max_length=32, description="原料/辅料/包材/溶剂")
    vendor_name: str | None = Field(default=None, max_length=100, description="默认供应商名称")
    pack_spec: str | None = Field(default=None, max_length=50, description="包装规格，如 5kg/听")
    min_stock: int | None = Field(default=None, ge=0, description="安全库存阈值（瓶/桶数）")
    remark: str | None = Field(default=None, max_length=200)


class MaterialUpdate(BaseModel):
    """物料字典更新（全部可选）。"""

    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=32)
    vendor_name: str | None = Field(default=None, max_length=100)
    pack_spec: str | None = Field(default=None, max_length=50)
    min_stock: int | None = Field(default=None, ge=0)
    remark: str | None = Field(default=None, max_length=200)


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    category: str | None
    vendor_name: str | None
    pack_spec: str | None
    min_stock: int | None
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
