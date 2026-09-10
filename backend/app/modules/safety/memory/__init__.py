"""Agent 长期记忆模块 —— 跨会话用户记忆的提取、检索与注入。

Phase 1：用户上下文注入 — 让 Agent 知道在和谁说话。
Phase 2（当前）：记忆存储与提取 — 对话事实不再丢失。
Phase 3（规划）：记忆检索与注入 — Agent 能回忆起之前的事。
"""

from __future__ import annotations

from app.modules.safety.memory.extractor import MemoryExtractor
from app.modules.safety.memory.injector import MemoryInjector
from app.modules.safety.memory.models import AgentMemory
from app.modules.safety.memory.retriever import MemoryRetriever
from app.modules.safety.memory.schemas import (
    MemoryExtractionResult,
    MemoryFact,
    MemoryRecord,
)
from app.modules.safety.memory.store import MemoryStore

__all__ = [
    "AgentMemory",
    "MemoryExtractionResult",
    "MemoryExtractor",
    "MemoryFact",
    "MemoryInjector",
    "MemoryRecord",
    "MemoryRetriever",
    "MemoryStore",
]
