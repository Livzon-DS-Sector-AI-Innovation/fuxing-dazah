"""飞书多维表格事件处理（职称评审 v2）。

被 app/platform/integrations/feishu/event_handler.py 注册桥接调用（主事件循环）。
职责：按 file_token 路由活动 → 按 table_id 路由申报表/投票表 → 去重/防环 →
落库/投票判定。Redis 不可用时自动降级（失去去重与防环，靠对账兜底）。
"""

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.database import async_session_factory
from app.modules.hr.title_review import models as m
from app.modules.hr.title_review.service import TitleReviewService

logger = logging.getLogger(__name__)

EVENT_ADDED = "record_added"
EVENT_EDITED = "record_edited"
EVENT_DELETED = "record_deleted"


@dataclass(frozen=True, slots=True)
class _ActivityRef:
    """事件路由所需的活动最小信息（避免跨 session 传 ORM 对象）。"""

    id: UUID
    apply_table_id: str | None
    vote_table_id: str | None


async def _redis_set(key: str, value: str, ex: int, nx: bool = True) -> bool:
    """Redis SET（带降级：Redis 不可用返回 True，即放弃去重/防环/锁）。"""
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 不可用，跳过缓存读取: key=%s error=%s", key, exc)
        return None


def _normalize_value(value: Any) -> Any:
    """复合字段（附件/关联/多选）在事件中为 JSON 字符串，解析为 list/dict。"""
    if isinstance(value, str) and value[:1] in ("[", "{"):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _ignore_key(record_id: str) -> str:
    return f"title:bitable:ignore:{record_id}"


def _dedup_key(record_id: str, action: str, action_data: dict[str, Any]) -> str:
    """去重键包含内容哈希：同一事件重复投递可去重，同一行的合法二次修改不受影响。"""
    import hashlib

    content = json.dumps(
        action_data.get("after_value") or {}, ensure_ascii=False, sort_keys=True
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"title:bitable:event:{record_id}:{action}:{digest}"


async def _find_activity(file_token: str) -> _ActivityRef | None:
    """按 file_token 查找进行中的活动（closed 忽略一切事件）。"""
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(m.TitleReviewActivity).where(
                m.TitleReviewActivity.feishu_app_token == file_token,
                m.TitleReviewActivity.is_deleted == False,  # noqa: E712
                m.TitleReviewActivity.status.in_(
                    [m.ACTIVITY_DRAFT, m.ACTIVITY_OPEN, m.ACTIVITY_REVIEWING]
                ),
            )
        )
        activities = list(result.scalars().all())
        if not activities:
            return None
        if len(activities) > 1:
            logger.warning(
                "同一 Base(%s) 绑定了 %d 个进行中的活动，无法唯一定位，跳过事件",
                file_token, len(activities),
            )
            return None
        activity = activities[0]
        return _ActivityRef(
            id=activity.id,
            apply_table_id=activity.apply_table_id,
            vote_table_id=activity.vote_table_id,
        )


async def _get_field_map(app_token: str, table_id: str) -> dict[str, str]:
    """field_id → 中文列名 映射（Redis 缓存 10 分钟）。"""
    cache_key = f"title:bitable:fields:{app_token}:{table_id}"
    cached = await _redis_get(cache_key)
    if cached:
        try:
            return dict(json.loads(cached))
        except (TypeError, ValueError):
            pass
    from app.modules.hr.title_review import bitable_client as bc

    try:
        fields = await bc.list_fields(app_token, table_id)
    except bc.TitleReviewBitableError as exc:
        logger.warning("拉取字段列表失败: app=%s table=%s error=%s", app_token, table_id, exc)
        return {}
    field_map = {
        str(f.get("field_id")): str(f.get("field_name") or "")
        for f in fields
        if f.get("field_id")
    }
    await _redis_set(cache_key, json.dumps(field_map, ensure_ascii=False), ex=600)
    return field_map


async def handle_record_changed(
    file_token: str, table_id: str, action_list: list[dict[str, Any]]
) -> None:
    """多维表格记录变更事件入口（由 platform event_handler 桥接调用）。

    action_list: [{"action": record_added|record_edited|record_deleted,
                   "record_id": str, "after_value": {field_id: value}, ...}]
    """
    activity = await _find_activity(file_token)
    if not activity:
        return
    field_map = await _get_field_map(file_token, table_id)
    for action in action_list:
        try:
            await _process_action(activity, table_id, field_map, action)
        except Exception:
            logger.exception(
                "处理多维表格事件失败: file_token=%s table_id=%s action=%s",
                file_token, table_id, action.get("action"),
            )


async def _process_action(
    activity: _ActivityRef,
    table_id: str,
    field_map: dict[str, str],
    action: dict[str, Any],
) -> None:
    record_id = str(action.get("record_id") or "")
    act = str(action.get("action") or "")
    if not record_id or act not in (EVENT_ADDED, EVENT_EDITED, EVENT_DELETED):
        return

    # 防环：后端回写（票数/附件4结果/投票状态）触发的事件直接跳过
    if await _redis_get(_ignore_key(record_id)):
        logger.debug("忽略后端回写事件: record_id=%s action=%s", record_id, act)
        return

    # 去重（事件重复投递）：处理成功才保留 120s 去重键；
    # 处理抛异常时把键缩短到 1 秒（nx=False 覆盖原键，否则 SET NX 不生效），
    # 事件可被快速重试而不是被 120s 窗口永久吞掉
    dedup_key = _dedup_key(record_id, act, action)
    if not await _redis_set(dedup_key, "1", ex=120):
        logger.debug("重复事件已忽略: record_id=%s action=%s", record_id, act)
        return
    try:
        await _process_action_body(activity, table_id, field_map, record_id, act, action)
    except Exception:
        logger.exception(
            "处理多维表格事件失败: record_id=%s action=%s", record_id, act,
        )
        await _redis_set(dedup_key, "1", ex=1, nx=False)
        # 失败时也没有发生回写：把 ignore 键同样缩短，避免阻塞下一轮真实事件
        await _redis_set(_ignore_key(record_id), "1", ex=1, nx=False)


async def _process_action_body(
    activity: _ActivityRef,
    table_id: str,
    field_map: dict[str, str],
    record_id: str,
    act: str,
    action: dict[str, Any],
) -> None:
    # 后端稍后可能回写该行列 → 预先设置 ignore（60s 窗口）
    await _redis_set(_ignore_key(record_id), "1", ex=60)

    # field_id → 中文列名
    fields = {
        field_map.get(str(fid), str(fid)): _normalize_value(value)
        for fid, value in (action.get("after_value") or {}).items()
    }
    if not fields and act == EVENT_DELETED:
        fields = {
            field_map.get(str(fid), str(fid)): _normalize_value(value)
            for fid, value in (action.get("before_value") or {}).items()
        }

    if table_id not in (activity.apply_table_id, activity.vote_table_id):
        logger.warning("未知 table_id: %s (activity=%s)", table_id, activity.id)
        return

    async with async_session_factory() as db:
        service = TitleReviewService(db)
        try:
            if table_id == activity.apply_table_id:
                await _handle_apply_action(service, activity.id, act, record_id, fields)
            else:
                await _handle_vote_action(service, activity.id, act, record_id, fields)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _handle_apply_action(
    service: TitleReviewService,
    activity_id: UUID,
    act: str,
    record_id: str,
    fields: dict[str, Any],
) -> None:
    if act == EVENT_ADDED:
        await service.sync_apply_record_added(activity_id, record_id, fields)
    elif act == EVENT_EDITED:
        await service.sync_apply_record_edited(activity_id, record_id, fields)
    elif act == EVENT_DELETED:
        await service.sync_apply_record_deleted(activity_id, record_id)


async def _handle_vote_action(
    service: TitleReviewService,
    activity_id: UUID,
    act: str,
    record_id: str,
    fields: dict[str, Any],
) -> None:
    if act == EVENT_EDITED:
        await service.sync_vote_record(activity_id, record_id, fields)
    # record_added 为后端写行触发（已 ignore）；手工加行暂不支持。
    # record_deleted 视为防御性事件：评审期间评委撤换走内网 API，此处不处理。
