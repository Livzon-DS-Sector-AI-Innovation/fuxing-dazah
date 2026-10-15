"""regulation.updated 事件信封（对齐后台监控化 §3.1 接入 B）。

事件总线尚未建成（app/core/events.py 骨架零消费方）——当前落地方式：
结构化日志 + 收录留痕 event_envelope jsonb；publish 接口与总线同构，
总线建成后内部实现替换为 event_bus.publish 即接入规则引擎。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

EVENT_TYPE_REGULATION_UPDATED = "regulation.updated"


def build_regulation_updated_envelope(
    *,
    record_id: str,
    title: str,
    op: str,
    changed_fields: list[str],
    trace_id: str | None = None,
    is_revision: bool = False,
) -> dict[str, Any]:
    """构造事件信封（字段口径=后台监控化 §3.1：接入 B 平台域事件）。"""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": EVENT_TYPE_REGULATION_UPDATED,
        "source": "platform",
        "domain": "regulation",
        "table_id": "bitable:regulation",
        "record_id": record_id,
        "op": op,  # created | updated
        "changed_fields": changed_fields,
        "actor": "platform",
        "occurred_at": datetime.now(UTC).isoformat(),
        "trace_id": trace_id,
        "payload": {"title": title, "is_revision": is_revision},
    }


def publish_regulation_updated(envelope: dict[str, Any]) -> None:
    """发布事件（总线未建：先结构化日志留观测；接口与总线同构预留）。"""
    logger.info(
        "event:%s %s",
        EVENT_TYPE_REGULATION_UPDATED,
        json.dumps(envelope, ensure_ascii=False, default=str),
    )
