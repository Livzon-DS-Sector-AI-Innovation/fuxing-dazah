"""相关方准入 Bitable 事件处理器。

监听「相关方准入」表记录变更事件，实时同步到 ContractorAdmission。

事件类型说明（2026-08-31 实测修复）：
- 此前用 bitable.record.created_v1 / changed_v1 / deleted_v1，但飞书实际
  从未推送该类型（uvicorn.log 3000+ 条真实事件中 0 次），导致记录更新
  不触发同步/审核，只能靠补单脚本回填。
- 实际推送的是 drive.file.bitable_record_changed_v1（文档级事件，需先经
  drive/v1/files/:file_token/subscribe 订阅文档），hazard / EHS 等表均
  已验证可推送，本 handler 已迁移至该类型。

- record_added / record_edited → 回源拉记录 → 映射 → upsert（纯数据对齐）
- 触发 AI 审核条件：记录存在「承包商安全管理协议」附件（safety_agreement_files 非空）
  且 ai_review_status 未完成/未审核中 → 后台触发（独立 session，channel="system"）
- record_deleted → 软删除（仅 source='bitable' 记录）
"""

from __future__ import annotations

import asyncio
import logging

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.contractor_admission_bitable import (
    _match_table,
    admission_app_token,
    admission_tables,
    table_kind_by_id,
)
from app.modules.safety.feishu.event_client import on_event

logger = logging.getLogger(__name__)


@on_event("drive.file.bitable_record_changed_v1")
async def _on_drive_record_changed(event: dict) -> None:
    """文档级记录变更事件：按 file_token + table_id 过滤后逐条处理 action_list。"""
    file_token = event.get("file_token", "")
    table_id = event.get("table_id", "")
    if not _match_table(file_token, table_id):
        logger.debug(
            "忽略非相关方准入表格事件: file_token=%s table_id=%s",
            file_token, table_id,
        )
        return

    action_list = event.get("action_list", [])
    if action_list:
        logger.info(
            "相关方准入 Bitable 记录事件(action_list): file_token=%s table_id=%s items=%d",
            file_token, table_id, len(action_list),
        )
        for item in action_list:
            record_id = item.get("record_id", "")
            action_raw = item.get("action", "")
            if not record_id:
                continue
            if action_raw == "record_deleted":
                logger.info(
                    "相关方准入 Bitable 删除事件: table_id=%s record_id=%s",
                    table_id, record_id,
                )
                await _soft_delete(record_id)
            else:  # record_added / record_edited
                await _handle_record_event(table_id, record_id)
        return

    # 兼容 flat 旧格式（无 action_list）
    record_id = event.get("record_id", "")
    action = event.get("action", "")
    if not record_id:
        logger.debug("相关方准入 Bitable 事件缺少 record_id，忽略")
        return
    if action in ("record_deleted", "delete"):
        await _soft_delete(record_id)
    else:
        await _handle_record_event(table_id, record_id)


async def _handle_record_event(table_id: str, record_id: str) -> None:
    """单条记录变更：回源拉记录 → 映射 → upsert。"""
    kind = table_kind_by_id(table_id)
    if not kind or not record_id:
        return
    logger.info("相关方准入 Bitable 记录事件: kind=%s record_id=%s", kind, record_id)
    try:
        await _upsert(kind, record_id)
    except Exception:
        logger.exception("相关方准入 upsert 失败: kind=%s record_id=%s", kind, record_id)


async def _upsert(table_kind: str, record_id: str) -> None:
    """回源拉取记录并 upsert 到 ContractorAdmission。映射返回 None 时软删除。"""
    from app.core.database import async_session_factory
    from app.modules.safety.feishu import bitable_handler as bh
    from app.modules.safety.service.contractor_admission import (
        ContractorAdmissionService,
    )

    # 防回环：平台自身回写 Bitable 触发的 changed 事件 → 跳过
    try:
        if await bh._is_sync_ignored(record_id):
            logger.debug("相关方准入同步忽略（平台回写）: record_id=%s", record_id)
            return
    except Exception:
        pass  # Redis 不可用 → 不拦截

    table_id = admission_tables().get(table_kind)
    if not table_id:
        return

    client = SafetyBitableClient(app_token=admission_app_token(), table_id=table_id)
    fields = await client.get_record(record_id)
    if not fields:
        logger.warning("相关方准入 Bitable 记录读取为空: kind=%s record_id=%s", table_kind, record_id)
        return

    from app.modules.safety.feishu.contractor_admission_bitable import map_fields

    mapped = map_fields(fields)
    if mapped is None:  # 软删除信号（本表暂无，保留扩展）
        await _soft_delete(record_id)
        return

    async with async_session_factory() as session:
        service = ContractorAdmissionService(session)
        item = await service.upsert_from_bitable(mapped, record_id, table_kind)
        logger.info("相关方准入已同步: kind=%s record_id=%s", table_kind, record_id)

        # 触发 AI 审核条件：「承包商安全管理协议」附件有值（safety_agreement_files 非空）
        # 且 ai_review_status 非 completed/processing（未审过或可重审）→ fire-and-forget
        if (
            item is not None
            and item.safety_agreement_files
            and item.ai_review_status not in ("completed", "processing")
        ):
            asyncio.create_task(_trigger_ai_review(item.id))


async def _trigger_ai_review(admission_id) -> None:
    """后台执行平台 AI 审核（独立 session，channel='system'）。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service.contractor_admission import (
        ContractorAdmissionService,
    )

    try:
        async with async_session_factory() as session:
            service = ContractorAdmissionService(session)
            await service.run_admission_review(admission_id, channel="system")
    except Exception:
        logger.exception(
            "相关方准入 AI 审核后台触发失败 admission_id=%s", admission_id
        )


async def _soft_delete(record_id: str) -> None:
    """软删除 Bitable 来源记录。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service.contractor_admission import (
        ContractorAdmissionService,
    )

    async with async_session_factory() as session:
        service = ContractorAdmissionService(session)
        await service.soft_delete_by_feishu_id(record_id)
        logger.info("相关方准入已软删除: record_id=%s", record_id)


async def ensure_contractor_admission_bitable_subscribed() -> bool:
    """订阅相关方准入多维表格文档事件（drive.file.bitable_record_changed_v1 前置）。

    飞书要求：接收文档级 Bitable 事件前，须先调用 /drive/v1/files/:file_token/subscribe。
    订阅持久存在于飞书侧，每次启动重试无害（改表后重订阅天然携带新值）。
    订阅成功与否不影响 handler 注册；失败时由重启/变更重试兜底。
    """
    import httpx

    from app.core.config import get_settings

    file_token = admission_app_token()
    if not file_token:
        logger.warning("相关方准入 app_token 未配置（store 无连接），跳过文档事件订阅")
        return False

    settings = get_settings()
    app_id = settings.SAFETY_FEISHU_APP_ID
    app_secret = settings.SAFETY_FEISHU_APP_SECRET
    if not app_id or not app_secret:
        logger.warning("飞书应用凭证未配置，跳过相关方准入文档事件订阅")
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
                logger.info("相关方准入 Bitable 文档事件订阅成功: file_token=%s", file_token)
                return True
            logger.error(
                "相关方准入 Bitable 文档事件订阅失败: code=%s msg=%s file_token=%s",
                data.get("code"), data.get("msg"), file_token,
            )
            return False
    except Exception:
        logger.exception("相关方准入 Bitable 文档事件订阅异常: file_token=%s", file_token)
        return False
