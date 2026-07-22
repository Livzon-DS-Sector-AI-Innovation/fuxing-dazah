"""产品 API 契约。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    product_code: str | None = Field(default=None, max_length=50)
    product_name: str = Field(max_length=200)
    unit: str = Field(default="kg", max_length=20)
    remark: str | None = None


class ProductUpdate(BaseModel):
    product_name: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=20)
    remark: str | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_code: str | None
    product_name: str
    unit: str
    remark: str | None
    created_at: datetime
    updated_at: datetime
