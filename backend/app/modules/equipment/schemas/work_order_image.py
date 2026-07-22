"""Work order image schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class WorkOrderImageResponse(BaseModel):
    """工单图片响应"""

    id: uuid.UUID
    work_order_id: uuid.UUID
    file_name: str
    file_size: int | None
    uploaded_at: datetime

    model_config = {"from_attributes": True}
