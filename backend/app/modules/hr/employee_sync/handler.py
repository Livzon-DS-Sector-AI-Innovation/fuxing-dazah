"""员工档案多维表格 WS 事件处理。

注册到平台 bitable 广播注册表（main.py 启动接线）。按绑定的
app_token + 源表 table_id 过滤事件：同一 Base 内脱敏副本表和其他
表的事件一律忽略（系统是唯一写入方，无需防环）。

事件只更新本地 hr.employees；脱敏副本表由 5 分钟对账与手动同步维护，
避免 HR 连续编辑时对飞书 API 的放大调用。Redis 去重失败可重试。
"""

import hashlib
import json
import logging
from typing import Any

from app.core.database import async_session_factory
from app.modules.hr.employee_sync import bitable_client as bitable
from app.modules.hr.employee_sync.config import load_config
from app.modules.hr.employee_sync.mapping import normalize_event_value
from app.modules.hr.employee_sync.service import EmployeeSyncService
from app.platform.integrations.feishu.event_handler import (
    register_bitable_record_handler,
)

logger = logging.getLogger(__name__)

_FIELD_MAP_TTL = 600  # field_id → 列名 缓存 10 分钟
_DEDUP_TTL = 120


async def _redis_set(key: str, value: str, ex: int, nx: bool = True) -> bool:
    """Redis SET（不可用时返回 True：放弃去重，靠对账兜底）。"""
    try:
        from app.core.redis import redis_client

        return bool(await redis_client.set(key, value, ex=ex, nx=nx))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 不可用，跳过缓存操作: key=%s error=%s", key, exc)
        return True


async def _redis_get(key: str) -> str | None:
    try:
        from app.core.redis import redis_client

        value = await redis_client.get(key)
        return value.decode() if isinstance(value, bytes) else value
    except Exception:  # noqa: BLE001
        return None


def _field_map_cache_key(app_token: str, table_id: str) -> str:
    return f"employee_sync:fields:{app_token}:{table_id}"


async def _get_field_map(app_token: str, table_id: str) -> dict[str, str]:
    """field_id → 中文列名（Redis 缓存 10 分钟，失败返回空表按原名透传）。"""
    cache_key = _field_map_cache_key(app_token, table_id)
    cached = await _redis_get(cache_key)
    if cached:
        try:
            return dict(json.loads(cached))
        except (TypeError, ValueError):
            pass
    try:
        fields = await bitable.list_fields(app_token, table_id)
    except bitable.BitableAPIError as exc:
        logger.warning("拉取字段列表失败: %s table=%s error=%s", app_token, table_id, exc)
        return {}
    field_map = {
        str(f.get("field_id")): str(f.get("field_name") or "")
        for f in fields
        if f.get("field_id")
    }
    await _redis_set(cache_key, json.dumps(field_map, ensure_ascii=False), ex=_FIELD_MAP_TTL)
    return field_map


def _dedup_key(record_id: str, action: str, action_data: dict[str, Any]) -> str:
    """内容哈希去重键：同一事件重复投递可去重，合法二次修改不受影响。"""
    content = json.dumps(
        action_data.get("after_value") or {}, ensure_ascii=False, sort_keys=True,
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"employee_sync:event:{record_id}:{action}:{digest}"


async def handle_record_changed(
    file_token: str, table_id: str, action_list: list[dict[str, Any]],
) -> None:
    """多维表格事件入口：按绑定过滤 → field_id 转列名 → 增量落库。"""
    async with async_session_factory() as db:
        cfg = await load_config(db)
        if not cfg.is_ready:
            return
        if file_token != cfg.app_token or table_id != cfg.source_table_id:
            return  # 非源表（脱敏副本表/其他表）事件一律忽略

        field_map = await _get_field_map(file_token, table_id)
        service = EmployeeSyncService(db)
        try:
            for action in action_list:
                await _process_action(service, field_map, action)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _process_action(
    service: EmployeeSyncService,
    field_map: dict[str, str],
    action: dict[str, Any],
) -> None:
    record_id = str(action.get("record_id") or "")
    act = str(action.get("action") or "")
    if not record_id or act not in ("record_added", "record_edited", "record_deleted"):
        return

    # 去重（重复投递）：处理成功保留 120s；异常时缩到 1s 允许快速重试
    if not await _redis_set(_dedup_key(record_id, act, action), "1", ex=_DEDUP_TTL):
        logger.debug("重复事件已忽略: record_id=%s action=%s", record_id, act)
        return
    try:
        raw_fields = action.get("after_value") or {}
        if not raw_fields and act == "record_deleted":
            raw_fields = action.get("before_value") or {}
        fields = {
            field_map.get(str(fid), str(fid)): normalize_event_value(value)
            for fid, value in raw_fields.items()
        }
        async with service.session.begin_nested():
            result = await service.apply_event_record(act, record_id, fields)
        logger.info("员工档案事件已应用: %s %s → %s", act, record_id, result)
    except Exception:
        logger.exception(
            "处理多维表格事件失败: record_id=%s action=%s", record_id, act,
        )
        await _redis_set(_dedup_key(record_id, act, action), "1", ex=1, nx=False)


def register_feishu_callbacks() -> None:
    """应用启动时调用（main.py 接线）：注册到平台事件广播。"""
    register_bitable_record_handler(handle_record_changed)
