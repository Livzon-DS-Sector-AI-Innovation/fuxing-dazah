"""人员持证台账 Bitable 镜像事件处理器。

监听三个飞书 Bitable 表的记录变更事件，实时镜像到平台
safety.person_certificates。模式对照 `oh_bitable_handler.py`：

- 事件按 table_id → kind 分发（cert_tables() 反查，配置中心 store）
- 特种作业证在 wiki 文档（独立 app_token）；监护人 A/B 证在 base 文档（共用 app_token）
- 防循环四件套：_is_sync_ignored（平台回写前必调）/ Redis 60s 去重
- 活行 upsert（WHERE is_deleted=false）；软删清唯一键（feishu_record_id）
- 纯数据对齐：不触发通知 / 不触发 AI / 不修改 Bitable

字段映射见 `cert_bitable.py`（2026-08-21 已用真实字段名补全）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.modules.safety.feishu import bitable_handler as bh
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.cert_bitable import (
    map_guardian_cert_fields,
    map_special_op_cert_fields,
    table_kind_by_id,
)
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import PersonCertificate

logger = logging.getLogger(__name__)

# kind → 映射函数（监护人证映射需要 kind 参数，统一用 lambda 适配签名）
_MAPPERS: dict[str, Any] = {
    "special_op": lambda fields: map_special_op_cert_fields(fields),
    "guardian_a": lambda fields: map_guardian_cert_fields(fields, "guardian_a"),
    "guardian_b": lambda fields: map_guardian_cert_fields(fields, "guardian_b"),
}


def _get_mapper(kind: str):
    return _MAPPERS.get(kind)


async def _upsert(kind: str, record_id: str, *, created: bool = False) -> None:
    """回源拉取记录并 upsert 到平台 person_certificates（活行 WHERE is_deleted=false）。

    流程对照 oh_bitable_handler._upsert：
      1. 平台回写 Bitable 触发的 changed → 跳过（bh._is_sync_ignored）
      2. Redis 60s 去重（bh._is_duplicate，suffix=kind）
      3. SafetyBitableClient.get_record 拉全量（app_token 按 kind 切换）
      4. _MAPPERS[kind] 映射 → mapped；None 跳过（脏数据）
      5. mapped['feishu_record_id'] = record_id; mapped['source'] = 'bitable'
      6. 查 existing → _apply_values + commit；无 existing → INSERT
      7. 纯数据对齐：不触发通知 / AI / 状态流转
    """
    from app.modules.safety.feishu.cert_bitable import cert_tables

    pair = cert_tables().get(kind)
    if not pair:
        return
    _app_token, table_id = pair

    # 1. 平台回写防循环
    try:
        if await bh._is_sync_ignored(record_id):
            logger.debug("持证 Bitable 同步忽略（平台回写）: record_id=%s", record_id)
            return
    except Exception:
        pass  # Redis 不可用 → 不拦截

    # 2. Redis 60s 去重
    try:
        if await bh._is_duplicate("cert_upsert", record_id, ttl=60, suffix=kind):
            logger.info(
                "持证 Bitable 重复事件已忽略: kind=%s record_id=%s", kind, record_id
            )
            return
    except Exception:
        pass

    # 3. 回源拉全量（app_token 按 kind 切换：特种作业证在 wiki，监护人在 base）
    if not _app_token:
        logger.warning("持证 Bitable app_token 未配置: kind=%s", kind)
        return
    client = SafetyBitableClient(app_token=_app_token, table_id=table_id)
    fields = await client.get_record(record_id)
    if not fields:
        logger.warning(
            "持证 Bitable 记录读取为空: kind=%s record_id=%s", kind, record_id
        )
        return

    # 4. 字段映射
    mapper = _get_mapper(kind)
    if mapper is None:
        return
    mapped = mapper(fields)
    if mapped is None:
        logger.info(
            "持证记录映射为空，跳过: kind=%s record_id=%s", kind, record_id
        )
        return

    mapped["feishu_record_id"] = record_id
    mapped["source"] = "bitable"

    # 5. 活行 upsert
    async with async_session_factory() as session:
        from app.modules.safety.feishu.bitable_handler import acquire_record_lock

        # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
        async with session.begin():
            await acquire_record_lock(session, record_id)
            existing = await session.scalar(
                select(PersonCertificate).where(
                    PersonCertificate.feishu_record_id == record_id,
                    PersonCertificate.is_deleted == False,  # noqa: E712
                )
            )
            if existing:
                for key, val in mapped.items():
                    if val is None:
                        continue
                    setattr(existing, key, val)
                await session.flush()
                item = existing
            else:
                obj = PersonCertificate(**mapped)
                session.add(obj)
                await session.flush()
                item = obj

    logger.info(
        "持证 upsert 完成: kind=%s record_id=%s id=%s",
        kind, record_id, getattr(item, "id", None),
    )


async def _soft_delete(kind: str, record_id: str) -> None:
    """软删除 Bitable 来源记录，并清空 feishu_record_id（防软删隐形 bug）。

    清空 feishu_record_id 即可（本表唯一键只有 feishu_record_id），
    避免重复添加→删除→添加时部分唯一索引冲突。
    """
    async with async_session_factory() as session:
        stmt = (
            update(PersonCertificate)
            .where(
                PersonCertificate.feishu_record_id == record_id,
                PersonCertificate.source == "bitable",
                PersonCertificate.is_deleted == False,  # noqa: E712
            )
            .values(is_deleted=True, feishu_record_id=None)
        )
        result = await session.execute(stmt)
        await session.commit()
        rowcount = getattr(result, "rowcount", 0) or 0
        if rowcount > 0:
            logger.info(
                "持证软删完成: kind=%s record_id=%s", kind, record_id
            )


async def _handle_record_event(event_data: dict, *, created: bool) -> None:
    """created/changed 统一入口：table_id → kind 分发 → 回源拉记录 → 映射 → upsert。"""
    record_id = event_data.get("record_id", "")
    table_id = event_data.get("table_id", "")
    kind = table_kind_by_id(table_id)
    if not kind or not record_id:
        return
    logger.info("持证 Bitable 记录事件: kind=%s record_id=%s", kind, record_id)
    try:
        await _upsert(kind, record_id, created=created)
    except Exception:
        logger.exception(
            "持证 upsert 失败: kind=%s record_id=%s", kind, record_id
        )


async def _handle_deleted_event(event_data: dict) -> None:
    """deleted 入口：table_id → kind 分发 → 软删除。"""
    record_id = event_data.get("record_id", "")
    table_id = event_data.get("table_id", "")
    kind = table_kind_by_id(table_id)
    if not kind or not record_id:
        return
    logger.info("持证 Bitable 删除事件: kind=%s record_id=%s", kind, record_id)
    try:
        await _soft_delete(kind, record_id)
    except Exception:
        logger.exception(
            "持证软删除失败: kind=%s record_id=%s", kind, record_id
        )


# ── 事件注册 ──


@on_event("drive.file.bitable_record_changed_v1")
async def _on_cert_record_changed(event_data: dict) -> None:
    """持证台账记录变更（v2 action_list 格式），created/edited/deleted 统一分发。

    v2 payload 顶层含 file_token/table_id，record_id 与 action 在 action_list 项内；
    兼容旧 flat 格式（record_id/action 顶层）兜底。按 table_kind_by_id 二次过滤分发，
    与 oh / hazard 互不干扰。
    """
    table_id = event_data.get("table_id", "")
    if table_kind_by_id(table_id) is None:
        return  # 非本 handler 关心的表
    action_list = event_data.get("action_list") or []
    if action_list:
        for item in action_list:
            record_id = item.get("record_id", "")
            action = item.get("action", "")
            if not record_id:
                continue
            if action == "record_deleted":
                await _handle_deleted_event(
                    {"record_id": record_id, "table_id": table_id}
                )
            elif action in ("record_added", "record_edited"):
                await _handle_record_event(
                    {"record_id": record_id, "table_id": table_id},
                    created=(action == "record_added"),
                )
        return
    # flat 兜底（旧格式）
    await _handle_record_event(event_data, created=False)
