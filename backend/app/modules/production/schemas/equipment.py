"""生产模块引用的设备摘要 schema（数据来自 equipment.public_api）。"""

import uuid

from pydantic import BaseModel


class EquipmentOptionOut(BaseModel):
    """设备下拉选项：编号 + 名称。"""

    id: uuid.UUID
    equipment_no: str
    name: str
