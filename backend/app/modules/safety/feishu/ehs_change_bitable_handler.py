"""EHS 变更管理 Bitable 事件处理器。

监听「2026EHS变更申请」「变更验收」两个表变更事件，实时同步到 EhsChange。

事件类型（2026-09-08 修正）：此前误用 bitable.record.*_v1（该类型飞书从不
推送，3000+ 条真实事件实测 0 次），已迁移文档级 drive.file.bitable_record_changed_v1
（文档订阅见本文件 ensure_ehs_change_bitable_subscribed）。

- record_added / record_edited → 回源拉记录 → 映射 → upsert（纯数据对齐）
- record_added（审批表，无 AI 结论）→ 异步触发平台 AI 审核并回填
- record_deleted → 软删除（仅 source='bitable' 记录）
"""

from __future__ import annotations

import asyncio
import logging

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.ehs_change_bitable import (
    ehs_app_token,
    ehs_tables,
    get_mapper,
    table_kind_by_id,
)
from app.modules.safety.feishu.event_client import on_event

logger = logging.getLogger(__name__)


@on_event("drive.file.bitable_record_changed_v1")
async def _on_ehs_drive_changed(event: dict) -> None:
    """文档级记录变更事件：按 app_token + table_id 过滤后逐条分派。

    action_list 每项仅含 record_id/action，_upsert 内部回源 get_record，
    此处只构造最小 event_data。审批表/验收表共用一个 handler，按 table_id
    区分 kind（table_kind_by_id）。
    """
    if event.get("file_token", "") != ehs_app_token():
        return
    table_id = event.get("table_id", "")
    if not table_kind_by_id(table_id):
        return

    action_list = event.get("action_list") or []
    if not action_list:  # 兼容无 action_list 的旧 flat 格式
        record_id = event.get("record_id", "")
        if not record_id:
            return
        action_list = [
            {"record_id": record_id, "action": event.get("action", "record_edited")}
        ]

    for item in action_list:
        record_id = item.get("record_id", "")
        action = item.get("action", "")
        if not record_id:
            continue
        try:
            if action == "record_deleted":
                logger.info(
                    "EHS 变更 Bitable 删除事件: table_id=%s record_id=%s",
                    table_id, record_id,
                )
                await _soft_delete(record_id)
            else:  # record_added / record_edited
                created = action == "record_added"
                logger.info(
                    "EHS 变更 Bitable 记录事件: table_id=%s record_id=%s created=%s",
                    table_id, record_id, created,
                )
                await _upsert(table_kind_by_id(table_id), record_id, created=created)
        except Exception:
            logger.exception(
                "EHS 变更 drive 事件处理失败: table_id=%s record_id=%s action=%s",
                table_id, record_id, action,
            )


async def ensure_ehs_change_bitable_subscribed() -> bool:
    """订阅 EHS 变更 Base 文档事件（drive.file.bitable_record_changed_v1 前置）。

    飞书要求：接收文档级 Bitable 事件前，须先调用 /drive/v1/files/:file_token/subscribe。
    订阅持久存在于飞书侧，每次启动重试无害。单 base 订阅同时覆盖审批表与验收表。
    订阅成功与否不影响 handler 注册；失败时由重启/配置变更重试兜底。
    """
    import httpx

    file_token = ehs_app_token()
    if not file_token:
        logger.info("EHS 变更 Bitable app_token 未配置，跳过文档事件订阅")
        return False

    import os

    app_id = os.getenv("SAFETY_FEISHU_APP_ID", "")
    app_secret = os.getenv("SAFETY_FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        logger.warning("飞书应用凭证未配置，跳过 EHS 变更文档事件订阅")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            auth_resp = await http.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            auth_data = auth_resp.json()
            if auth_data.get("code") != 0:
                logger.error(
                    "获取 tenant_access_token 失败: code=%s msg=%s",
                    auth_data.get("code"), auth_data.get("msg"),
                )
                return False
            token = auth_data["tenant_access_token"]

            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info("EHS 变更 Bitable 文档事件订阅成功: file_token=%s", file_token)
                return True
            logger.error(
                "EHS 变更 Bitable 文档事件订阅失败: code=%s msg=%s file_token=%s",
                data.get("code"), data.get("msg"), file_token,
            )
            return False
    except Exception:
        logger.exception("EHS 变更 Bitable 文档事件订阅异常: file_token=%s", file_token)
        return False


async def _upsert(table_kind: str, record_id: str, *, created: bool = False) -> None:
    """回源拉取记录并 upsert 到 EhsChange。映射返回 None（申请状态已删除）时软删除。"""
    from app.core.database import async_session_factory
    from app.modules.safety.feishu import bitable_handler as bh
    from app.modules.safety.service.ehs_change import EhsChangeService

    # 平台自身回写 Bitable 触发的 changed 事件 → 跳过（防死循环）
    try:
        if await bh._is_sync_ignored(record_id):
            logger.debug("EHS Bitable 同步忽略（平台回写）: record_id=%s", record_id)
            return
    except Exception:
        pass  # Redis 不可用 → 不拦截

    table_id = ehs_tables().get(table_kind)
    if not table_id:
        return

    client = SafetyBitableClient(app_token=ehs_app_token(), table_id=table_id)
    fields = await client.get_record(record_id)
    if not fields:
        logger.warning("EHS Bitable 记录读取为空: kind=%s record_id=%s", table_kind, record_id)
        return

    mapper = get_mapper(table_kind)
    if mapper is None:
        return
    mapped = mapper(fields)
    if mapped is None:
        await _soft_delete(record_id)
        return

    async with async_session_factory() as session:
        from app.modules.safety.feishu.bitable_handler import acquire_record_lock

        # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
        async with session.begin():
            await acquire_record_lock(session, record_id)
            service = EhsChangeService(session)
            item = await service.upsert_from_bitable(mapped, record_id, table_kind)
            logger.info("EHS 变更已同步: kind=%s record_id=%s", table_kind, record_id)

            # 新增审批变更且无 AI 结论 → 后台触发平台 AI 审核（不阻塞事件处理）
            if (
                created
                and table_kind == "approval"
                and item is not None
                and item.ai_review_status != "completed"
            ):
                asyncio.create_task(_trigger_ai_review(item.id))


async def _trigger_ai_review(change_id) -> None:
    """后台执行平台 AI 审核（独立 session）。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service.ehs_change import EhsChangeService

    try:
        async with async_session_factory() as session:
            service = EhsChangeService(session)
            await service.run_ehs_ai_review(change_id, channel="system")
    except Exception:
        logger.exception("EHS AI 审核后台触发失败 change_id=%s", change_id)


async def _soft_delete(record_id: str) -> None:
    """软删除 Bitable 来源记录。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service.ehs_change import EhsChangeService

    async with async_session_factory() as session:
        service = EhsChangeService(session)
        await service.soft_delete_by_feishu_id(record_id)
        logger.info("EHS 变更已软删除: record_id=%s", record_id)
