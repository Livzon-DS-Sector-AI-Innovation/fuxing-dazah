"""消防报警 Bitable 事件处理器。

监听「火灾报警信息」表（消防数据多维表格）变更事件，实时同步到 FireAlarmRecord。
仅同步数据（upsert/软删），不触发 AI 分析（分析由生成入口负责）。

- 事件格式：drive.file.bitable_record_changed_v1（v2 action_list 格式，
  顶层含 file_token/table_id，项内含 record_id + action；兼容 flat 旧格式兜底）
- 防循环/去重：复用 bitable_handler 的 _is_sync_ignored（平台回写忽略）+
  _is_duplicate（Redis 60s 去重，suffix="fire" 避免跨表 record_id 碰撞）；
  Redis 不可用时 try/except 降级不阻塞
- upsert 保留 ai_* 分析字段（只更新 Bitable 字段，与 ticket 02 全量同步语义一致）
- 软删清空 feishu_record_id（CLAUDE.md 软删除铁律：不占用部分唯一索引）
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu import bitable_handler as bh
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import FireAlarmRecord
from app.modules.safety.service.fire_alarm.bitable_mapper import map_bitable_fields

logger = logging.getLogger(__name__)


def _fire_alarm_conn() -> ConnectionView | None:
    """消防报警连接配置（配置中心 store 读取；未启用/缺失返回 None）。"""
    return store.get_connection("fire_alarm", "alarm")


def _fire_alarm_app_token() -> str:
    conn = _fire_alarm_conn()
    return conn.app_token if conn and conn.enabled else ""


def _fire_alarm_table_id() -> str:
    conn = _fire_alarm_conn()
    return conn.table_id if conn and conn.enabled else ""


@on_event("drive.file.bitable_record_changed_v1")
async def handle_fire_alarm_record_changed(event: dict) -> None:
    """处理消防报警 Bitable 记录变更事件（v2 action_list 格式，兼容 flat 兜底）。

    与 oh_bitable_handler._on_oh_record_changed 同模式：入参即 v2 的 event 子对象
    （file_token/table_id 在顶层，action_list 项含 record_id + action），
    不要再包一层 event.get("event")。仅处理消防报警表，其他表事件直接忽略。
    """
    file_token = event.get("file_token", "")
    table_id = event.get("table_id", "")
    if file_token != _fire_alarm_app_token() or table_id != _fire_alarm_table_id():
        logger.debug(
            "消防报警 Bitable 事件过滤跳过: file_token=%s table_id=%s",
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
                    await _handle_delete(record_id)
                elif action in ("record_added", "record_edited"):
                    await _handle_upsert(record_id)
            except Exception:
                logger.exception(
                    "处理消防报警 Bitable 事件失败: action=%s record_id=%s",
                    action, record_id,
                )
        return
    # flat 兜底（旧格式）
    record_id = event.get("record_id", "")
    if record_id:
        try:
            await _handle_upsert(record_id)
        except Exception:
            logger.exception("处理消防报警 Bitable 事件失败: record_id=%s", record_id)


async def _handle_upsert(record_id: str) -> None:
    """从 Bitable 读取记录并 upsert 到 FireAlarmRecord。

    事件只同步数据，不触发 AI 分析（分析由日报/周报生成入口显式触发）。
    """
    # 1. 平台回写防循环（本期无回写，仍按惯例处理；Redis 不可用降级）
    try:
        if await bh._is_sync_ignored(record_id):
            logger.debug("消防报警 Bitable 同步忽略（平台回写）: record_id=%s", record_id)
            return
    except Exception:
        pass
    # 2. Redis 60s 去重（suffix=fire 避免跨表 record_id 碰撞）
    try:
        if await bh._is_duplicate("fire_upsert", record_id, ttl=60, suffix="fire"):
            logger.info("消防报警 Bitable 重复事件已忽略: record_id=%s", record_id)
            return
    except Exception:
        pass
    # 3. 回源拉全量
    client = SafetyBitableClient(
        app_token=_fire_alarm_app_token(), table_id=_fire_alarm_table_id()
    )
    fields = await client.get_record(record_id)
    if not fields:
        logger.warning("消防报警 Bitable 记录读取为空: record_id=%s", record_id)
        return
    mapped = map_bitable_fields(fields)
    mapped["feishu_record_id"] = record_id
    mapped["source"] = "bitable"
    mapped["synced_at"] = datetime.now(UTC)

    # 4. 活行 upsert（WHERE is_deleted=false）；UPDATE 保留 ai_* 分析字段
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(FireAlarmRecord).where(
                FireAlarmRecord.feishu_record_id == record_id,
                FireAlarmRecord.is_deleted == False,  # noqa: E712
            )
        )
        if existing:
            for k, v in mapped.items():
                if v is not None and k not in ("feishu_record_id", "source"):
                    setattr(existing, k, v)
        else:
            session.add(FireAlarmRecord(**mapped))
        await session.commit()
        logger.info("消防报警记录已同步: record_id=%s", record_id)


async def _handle_delete(record_id: str) -> None:
    """软删除对应记录，并清空 feishu_record_id（软删除铁律：不占用唯一键）。"""
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                update(FireAlarmRecord)
                .where(
                    FireAlarmRecord.feishu_record_id == record_id,
                    FireAlarmRecord.source == "bitable",
                    FireAlarmRecord.is_deleted == False,  # noqa: E712
                )
                .values(is_deleted=True, feishu_record_id=None,
                        synced_at=datetime.now(UTC))
            )
            await session.commit()
            if result.rowcount:
                logger.info("消防报警记录已软删除: record_id=%s", record_id)
    except Exception:
        logger.exception("消防报警软删除失败: record_id=%s", record_id)


async def ensure_fire_alarm_bitable_subscribed() -> bool:
    """订阅消防报警 Bitable 文档事件（参照 ensure_special_op_bitable_subscribed）。

    飞书要求先订阅文档，WebSocket 长连接才会推送
    drive.file.bitable_record_changed_v1 变更事件。
    """
    if not _fire_alarm_app_token():
        logger.info("消防报警 Bitable app_token 未配置，跳过订阅")
        return False
    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{_fire_alarm_app_token()}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info("消防报警 Bitable 订阅成功: %s", _fire_alarm_app_token())
                return True
            logger.error("消防报警 Bitable 订阅失败: code=%s msg=%s",
                         data.get("code"), data.get("msg"))
            return False
    except Exception:
        logger.exception("消防报警 Bitable 订阅异常")
        return False
