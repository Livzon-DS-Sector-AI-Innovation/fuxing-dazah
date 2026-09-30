"""Quality 模块请求/响应 Schema。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ─── 报告单 ───


class GenerateReportRequest(BaseModel):
    """生成报告单请求。"""

    inspection_record_id: uuid.UUID | None = Field(
        default=None, description="关联的检验记录 ID（从数据库加载数据自动填充）"
    )
    template: str = Field(default="万古霉素/3205.docx", description="模板路径")
    data: dict[str, Any] | None = Field(
        default=None, description="手动填写的数据字典（inspection_record_id 为空时使用）"
    )


class ReportRecordOut(BaseModel):
    """报告单记录输出。"""

    id: uuid.UUID
    inspection_record_id: uuid.UUID
    template_path: str
    product_name: str
    batch_number: str
    file_path: str | None = None
    file_size: int | None = None
    created_at: datetime | None = None
