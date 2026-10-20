"""三台账 record 变更事件 → 实时闭环通道（facilities-p1 票 04）。

照 key_risk_op_bitable_handler 范式：注册 drive.file.bitable_record_changed_v1
（与既有 20+ handler 并存），按 file_token+table_id 匹配 facilities 域三 kind
已登记连接（未登记直接 return——一期连接位空，事件天然不会来）；命中行
变更 → strict 现读该行 → closure.process_row_change（锚点前移闭环 /
行删停用取消，closed_trigger=event）。

at-least-once 去重复用 event_client `_should_dispatch`（event_id TTL）；
事件丢失由每日派发任务的对账兜底（closed_trigger=poll），事件只做加速。
handler 模块需被 import 才会注册：经 app.modules.safety.facilities 包
__init__ 或启动接线挂载（见 closure 测试的 import 路径注释）。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.bitable_config.store import store
from app.modules.safety.facilities.ledger import BIZ_TO_KIND, DOMAIN
from app.modules.safety.feishu.event_client import on_event

logger = logging.getLogger(__name__)


def match_facilities_biz(file_token: str, table_id: str) -> str | None:
    """事件 (file_token, table_id) → facilities 域 biz_type（未登记返回 None）。"""
    if not file_token or not table_id:
        return None
    for biz_type, kind in BIZ_TO_KIND.items():
        conn = store.get_connection(DOMAIN, kind)
        if conn is None or not conn.enabled:
            continue
        if conn.app_token == file_token and conn.table_id == table_id:
            return biz_type
    return None


async def _process_batch(
    biz_type: str, actions: list[tuple[str, bool]]
) -> dict[str, int]:
    """同表一批行变更：一次全量现读 + 单 session 处理（批量编辑不放大拉取）。

    deleted 行不读表；未删行从本轮全量里定位（不在 = 事件滞后 → 按删除）。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.facilities.closure import process_row_change
    from app.modules.safety.facilities.notify import FacilitiesNotifier
    from app.modules.safety.facilities.reader import FacilitiesLedgerReader

    views_by_id: dict[str, Any] = {}
    if any(not deleted for _rid, deleted in actions):
        reader = FacilitiesLedgerReader()  # 事件通道现读，绕过页面缓存
        for v in await reader.fetch_ledger(biz_type, strict=True):
            views_by_id[v.record_id] = v

    total = {"closed": 0, "cancelled": 0}
    async with async_session_factory() as session:
        for record_id, deleted in actions:
            view = None if deleted else views_by_id.get(record_id)
            row_deleted = deleted or view is None
            stats = await process_row_change(
                session, biz_type, record_id, deleted=row_deleted, view=view,
                notifier=FacilitiesNotifier(),
            )
            total["closed"] += stats["closed"]
            total["cancelled"] += stats["cancelled"]
        await session.commit()
    return total


@on_event("drive.file.bitable_record_changed_v1")
async def handle_facilities_record_changed(event: dict) -> None:
    """三台账行变更 → 实时闭环检测（异常只告警，对账兜底保最终一致）。"""
    try:
        file_token = event.get("file_token", "")
        table_id = event.get("table_id", "")
        biz_type = match_facilities_biz(file_token, table_id)
        if biz_type is None:
            return

        # v2 action_list 格式（照 bitable_handler 既有解析），兼容旧 flat 格式；
        # action 只消费「是否删除」一个语义（added/edited 都走锚点前移判定）
        action_list = event.get("action_list") or []
        if action_list:
            items = [
                (str(item.get("record_id") or ""), str(item.get("action") or ""))
                for item in action_list
            ]
        else:
            record_id = str(event.get("record_id") or "")
            action = str(event.get("action") or "")
            items = [(record_id, action)] if record_id else []

        actions = [
            (record_id, "delete" in action)
            for record_id, action in items
            if record_id
        ]
        if actions:
            stats = await _process_batch(biz_type, actions)
            if stats["closed"] or stats["cancelled"]:
                logger.info(
                    "设施台账事件闭环处理: biz=%s rows=%d %s",
                    biz_type, len(actions), stats,
                )
    except Exception:
        logger.exception(
            "设施台账事件处理失败（对账兜底将补齐）: file=%s table=%s",
            event.get("file_token"), event.get("table_id"),
        )
