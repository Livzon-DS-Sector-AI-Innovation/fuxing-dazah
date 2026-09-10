"""中控报警 Bitable 事件处理器。

监听「中控报警统计」Base 下 15 张同构表的记录变更事件，实时同步到 CentralAlarmRecord。
仅同步数据（upsert/软删），不触发 AI 分析（分析由生成入口负责）。

- 事件格式：drive.file.bitable_record_changed_v1（v2 action_list 格式，兼容 flat 兜底）
- 表过滤：file_token == 中控 Base AND table_id ∈ 白名单（主表+extra_table_ids，store），否则忽略
- workshop/line 从 Bitable 表名推导（拉取表名并缓存）
- 防循环/去重：复用 bitable_handler 的 _is_sync_ignored + _is_duplicate（suffix="central"）
- upsert 保留 ai_* 分析字段；软删清空 feishu_record_id（软删除铁律）
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.modules.safety.feishu import bitable_handler as bh
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import CentralAlarmRecord
from app.modules.safety.service.central_alarm.bitable_mapper import (
    derive_workshop_line,
    map_bitable_fields,
)
from app.modules.safety.service.central_alarm.service import (
    central_alarm_app_token,
    central_alarm_table_ids,
)

logger = logging.getLogger(__name__)

# 表名缓存（table_id → (workshop, line)），避免每个事件都拉取表名
_TABLE_META_CACHE: dict[str, tuple[str, str | None]] = {}


@on_event("drive.file.bitable_record_changed_v1")
async def handle_central_alarm_record_changed(event: dict) -> None:
    """处理中控报警 Bitable 记录变更事件（v2 action_list 格式，兼容 flat 兜底）。

    file_token/table_id 在顶层；action_list 项含 record_id + action。
    仅处理中控报警白名单表，其他表事件直接忽略。
    """
    file_token = event.get("file_token", "")
    table_id = event.get("table_id", "")
    if (
        file_token != central_alarm_app_token()
        or table_id not in central_alarm_table_ids()
    ):
        logger.debug(
            "中控报警 Bitable 事件过滤跳过: file_token=%s table_id=%s",
            file_token, table_id,
        )
        return

    action_list = event.get("action_list") or []
    if action_list:
        for item in action_list:
            record_id = item.get("record_id", "")
            action = item.get("action", "")
            if not record_id:
                continue
            try:
                if action == "record_deleted":
                    await _handle_delete(record_id, table_id)
                elif action in ("record_added", "record_edited"):
                    await _handle_upsert(record_id, table_id)
            except Exception:
                logger.exception(
                    "处理中控报警 Bitable 事件失败: action=%s record_id=%s",
                    action, record_id,
                )
        return
    # flat 兜底（旧格式）
    record_id = event.get("record_id", "")
    if record_id:
        try:
            await _handle_upsert(record_id, table_id)
        except Exception:
            logger.exception("处理中控报警 Bitable 事件失败: record_id=%s", record_id)


async def _handle_upsert(record_id: str, table_id: str) -> None:
    """从 Bitable 读取记录并 upsert 到 CentralAlarmRecord。

    事件只同步数据，不触发 AI 分析。
    """
    # 1. 平台回写防循环（本期无回写，仍按惯例处理；Redis 不可用降级）
    try:
        if await bh._is_sync_ignored(record_id):
            logger.debug("中控报警 Bitable 同步忽略（平台回写）: record_id=%s", record_id)
            return
    except Exception:
        pass
    # 2. Redis 60s 去重（suffix=central 避免跨表 record_id 碰撞）
    try:
        if await bh._is_duplicate("central_upsert", record_id, ttl=60, suffix="central"):
            logger.info("中控报警 Bitable 重复事件已忽略: record_id=%s", record_id)
            return
    except Exception:
        pass
    # 3. 回源拉全量 + 表名推导车间/产线
    workshop, line = await _get_workshop_line(table_id)
    client = SafetyBitableClient(app_token=central_alarm_app_token(), table_id=table_id)
    fields = await client.get_record(record_id)
    if not fields:
        logger.warning("中控报警 Bitable 记录读取为空: record_id=%s", record_id)
        return
    mapped = map_bitable_fields(fields)
    mapped["feishu_record_id"] = record_id
    mapped["source"] = "bitable"
    mapped["workshop"] = workshop
    mapped["line"] = line
    mapped["synced_at"] = datetime.now(UTC)

    # 4. 活行 upsert（WHERE is_deleted=false）；UPDATE 保留 ai_* 分析字段
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(CentralAlarmRecord).where(
                CentralAlarmRecord.feishu_record_id == record_id,
                CentralAlarmRecord.is_deleted == False,  # noqa: E712
            )
        )
        if existing:
            for k, v in mapped.items():
                if v is not None and k not in ("feishu_record_id", "source"):
                    setattr(existing, k, v)
        else:
            session.add(CentralAlarmRecord(**mapped))
        await session.commit()
        logger.info("中控报警记录已同步: record_id=%s", record_id)


async def _handle_delete(record_id: str, table_id: str) -> None:
    """软删除对应记录，并清空 feishu_record_id（软删除铁律：不占用唯一键）。"""
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                update(CentralAlarmRecord)
                .where(
                    CentralAlarmRecord.feishu_record_id == record_id,
                    CentralAlarmRecord.source == "bitable",
                    CentralAlarmRecord.is_deleted == False,  # noqa: E712
                )
                .values(is_deleted=True, feishu_record_id=None,
                        synced_at=datetime.now(UTC))
            )
            await session.commit()
            if result.rowcount:
                logger.info("中控报警记录已软删除: record_id=%s", record_id)
    except Exception:
        logger.exception("中控报警软删除失败: record_id=%s", record_id)


async def _get_workshop_line(table_id: str) -> tuple[str, str | None]:
    """从 Bitable 拉取表名并推导车间/产线（模块级缓存）。

    事件只给 table_id；表名从 GET /tables/{table_id} 拉取（失败降级为 (table_id, None)）。
    """
    if table_id in _TABLE_META_CACHE:
        return _TABLE_META_CACHE[table_id]
    table_name = ""
    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                f"https://open.feishu.cn/open-apis/bitable/v1/apps"
                f"/{central_alarm_app_token()}/tables/{table_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            d = resp.json()
            if d.get("code") == 0:
                table_name = d.get("data", {}).get("table", {}).get("name", "")
    except Exception:
        logger.warning("拉取中控报警表名失败: table_id=%s", table_id)
    workshop, line = derive_workshop_line(table_name or table_id)
    _TABLE_META_CACHE[table_id] = (workshop, line)
    return workshop, line


async def ensure_central_alarm_bitable_subscribed() -> bool:
    """订阅中控报警 Bitable 文档事件。

    飞书要求先订阅文档，WebSocket 长连接才会推送
    drive.file.bitable_record_changed_v1 变更事件。
    """
    if not central_alarm_app_token():
        logger.info("中控报警 Bitable app_token 未配置，跳过订阅")
        return False
    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{central_alarm_app_token()}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info(
                    "中控报警 Bitable 订阅成功: %s", central_alarm_app_token()
                )
                return True
            logger.error("中控报警 Bitable 订阅失败: code=%s msg=%s",
                         data.get("code"), data.get("msg"))
            return False
    except Exception:
        logger.exception("中控报警 Bitable 订阅异常")
        return False
