"""物料容器赋码 Schema。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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
    id: uuid.UUID
    container_no: str
    material_code: str
    material_name: str
    vendor_code: str | None
    inbound_batch_no: str
    expiry_date: str | None
    seq: int
    status: str
    created_at: datetime


class MaterialContainerListItem(BaseModel):
    id: uuid.UUID
    container_no: str
    material_code: str
    material_name: str
    inbound_batch_no: str
    expiry_date: str | None
    seq: int
    status: str
    created_at: datetime


class ContainerMoveRequest(BaseModel):
    """进出库操作。in：入库登记（labeled → in_warehouse）；out：领料出库（in_warehouse/qualified → issued）。"""

    op_type: Literal["in", "out"]
    related_doc: str | None = Field(default=None, max_length=100, description="关联单据号（领料单等）")
    remark: str | None = Field(default=None, max_length=500)


class ContainerStatusUpdate(BaseModel):
    """阶段1人工状态流转（后续接入请验/放行链路后由系统自动联动）。"""

    status: Literal["in_warehouse", "qualified", "void"]


class ContainerMovementOut(BaseModel):
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
