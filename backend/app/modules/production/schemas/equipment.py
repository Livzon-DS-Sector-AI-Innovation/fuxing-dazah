"""生产模块引用的设备摘要 schema（数据来自 equipment.public_api）。"""

import uuid

from pydantic import BaseModel


class EquipmentOptionOut(BaseModel):
    """设备下拉选项：仅返回跨模块引用所需的轻量摘要和来源标记。"""

    id: uuid.UUID
    equipment_no: str
    name: str
    status: str | None = None
    is_active: bool = True
    source: str | None = None
