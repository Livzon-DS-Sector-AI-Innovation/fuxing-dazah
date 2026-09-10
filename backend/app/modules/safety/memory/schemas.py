"""记忆模块 Pydantic schemas。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """单条记忆记录（API 层使用）。"""

    id: UUID
    user_id: str
    memory_type: str = Field(description="fact / preference / episode / workflow")
    content: str = Field(description="人类可读的记忆内容")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    access_count: int = 0
    last_accessed_at: datetime | None = None
    source_session_id: UUID | None = None
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata_")
    expires_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class MemoryExtractionResult(BaseModel):
    """LLM 记忆提取的原始输出。"""

    facts: list[MemoryFact] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class MemoryFact(BaseModel):
    """LLM 提取的单条事实。"""

    memory_type: str = Field(description="fact / preference / episode / workflow")
    content: str = Field(description="人类可读的记忆内容")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要性")
