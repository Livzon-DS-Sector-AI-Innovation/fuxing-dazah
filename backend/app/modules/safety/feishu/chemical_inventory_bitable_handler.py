"""危化品库存管理 Bitable 镜像（单表：危化品库存总表）。

精简版：
- 总表为固定行台账，每天原地更新；事件变更镜像到 chemical_inventory_records 后
  触发该化学品（含同部位混存）的规则分析；
- 风险标记(正常/预警) + 风险说明(预警类型多选) 系统回填到总表，带防环。
token 未配置时所有操作优雅降级。

事件类型（2026-09-08 修正）：bitable.record.*_v1 飞书从不推送（3000+ 条真实
事件实测 0 次），实际推送文档级 drive.file.bitable_record_changed_v1
（文档订阅由 ensure_chemical_inventory_bitable_subscribed 完成）。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.core.redis import redis_client
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.chemical_inventory.enum_maps import (
    _ALERT_TYPE_ENUM_TO_LABEL as _ALERT_TYPE_ENUM_TO_LABEL,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _ALERT_TYPE_LABEL_TO_ENUM as _ALERT_TYPE_LABEL_TO_ENUM,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _DEPT_ENUM_TO_LABEL as _DEPT_ENUM_TO_LABEL,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _DEPT_LABEL_TO_ENUM as _DEPT_LABEL_TO_ENUM,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _HAZARD_ENUM_TO_LABEL as _HAZARD_ENUM_TO_LABEL,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _HAZARD_LABEL_TO_ENUM as _HAZARD_LABEL_TO_ENUM,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _RISK_FLAG_ENUM_TO_LABEL as _RISK_FLAG_ENUM_TO_LABEL,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _RISK_FLAG_LABEL_TO_ENUM as _RISK_FLAG_LABEL_TO_ENUM,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _UNIT_ENUM_TO_LABEL as _UNIT_ENUM_TO_LABEL,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _UNIT_LABEL_TO_ENUM as _UNIT_LABEL_TO_ENUM,
)

# 总表 Bitable 中文字段 → DB 列 + 标签↔枚举映射 + 值解析：
# 已抽到 chemical_inventory/enum_maps.py（feishu handler 与直读 reader 共用单一来源），
# 此处显式 re-export（`as` 同名形式，mypy 认可）保持既有引用方零改动。
from app.modules.safety.chemical_inventory.enum_maps import (  # noqa: F401
    INVENTORY_BITABLE_TO_MODEL as INVENTORY_BITABLE_TO_MODEL,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _datetime_from_raw as _datetime_from_raw,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _map_inventory_fields as _map_inventory_fields,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _multi_select as _multi_select,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _num as _num,
)
from app.modules.safety.chemical_inventory.enum_maps import (
    _text as _text,
)
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import ChemicalInventoryRecord

logger = logging.getLogger(__name__)


def _inventory_conn() -> ConnectionView | None:
    """危化品库存总表连接视图（store：DB 活行 → registry 默认）。"""
    return store.get_connection("chemical_inventory", "inventory")


def _get_inventory_table_id() -> str:
    conn = _inventory_conn()
    return conn.table_id if conn and conn.status != "disabled" else ""


def _get_inventory_app_token() -> str:
    conn = _inventory_conn()
    return conn.app_token if conn and conn.status != "disabled" else ""


def _enabled() -> bool:
    return store.is_enabled("chemical_inventory", "inventory")


# ── 防环 ──


async def _is_duplicate(event_type: str, record_id: str, ttl: int = 60) -> bool:
    key = f"chem_inv:event:{record_id}:{event_type}"
    try:
        return not await redis_client.set(key, "1", ex=ttl, nx=True)
    except Exception:  # noqa: BLE001
        return False


async def _set_sync_ignore(record_id: str, ttl: int = 60) -> None:
    key = f"chem_inv:ignore:{record_id}"
    try:
        await redis_client.set(key, "1", ex=ttl, nx=False)
    except Exception:  # noqa: BLE001
        pass


async def _is_sync_ignored(record_id: str) -> bool:
    key = f"chem_inv:ignore:{record_id}"
    try:
        return await redis_client.exists(key) > 0
    except Exception:  # noqa: BLE001
        return False


# ── 事件处理（总表）──


async def _analyze_after_change(record_id: str) -> None:
    """镜像完成后，触发该化学品（含同部位混存）的规则分析。"""
    try:
        from app.modules.safety.service.chemical_inventory import (
            ChemicalInventoryService,
        )

        async with async_session_factory() as session:
            svc = ChemicalInventoryService(session)
            await svc.analyze_changed_record(record_id)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("危化品库存变化风险分析失败: %s", record_id)


async def _handle_created(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id or await _is_duplicate("created", record_id):
        return
    conn = _inventory_conn()
    if conn is None or conn.status == "disabled":
        return
    try:
        client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
        fields = await client.get_record(record_id=record_id)
        mapped = _map_inventory_fields(fields)
        if not mapped.get("material_name"):
            return
        mapped["feishu_record_id"] = record_id

        async with async_session_factory() as session:
            from app.modules.safety.feishu.bitable_handler import acquire_record_lock

            # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
            async with session.begin():
                await acquire_record_lock(session, record_id)
                existing = await session.scalar(
                    select(ChemicalInventoryRecord).where(
                        ChemicalInventoryRecord.feishu_record_id == record_id,
                        ChemicalInventoryRecord.is_deleted == False,  # noqa: E712
                    )
                )
                if existing is None:
                    session.add(ChemicalInventoryRecord(**mapped))
    except Exception:  # noqa: BLE001
        logger.exception("危化品库存总表镜像创建失败: %s", record_id)
        return

    await _analyze_after_change(record_id)


async def _handle_changed(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id or await _is_duplicate("changed", record_id):
        return
    if await _is_sync_ignored(record_id):
        logger.debug("平台回写触发变更，跳过: %s", record_id)
        return
    conn = _inventory_conn()
    if conn is None or conn.status == "disabled":
        return
    try:
        client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
        fields = await client.get_record(record_id=record_id)
        mapped = _map_inventory_fields(fields)
        if not mapped:
            return

        async with async_session_factory() as session:
            from app.modules.safety.feishu.bitable_handler import acquire_record_lock

            # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
            async with session.begin():
                await acquire_record_lock(session, record_id)
                existing = await session.scalar(
                    select(ChemicalInventoryRecord).where(
                        ChemicalInventoryRecord.feishu_record_id == record_id,
                        ChemicalInventoryRecord.is_deleted == False,  # noqa: E712
                    )
                )
                if existing:
                    for col, val in mapped.items():
                        setattr(existing, col, val)
                else:
                    mapped["feishu_record_id"] = record_id
                    session.add(ChemicalInventoryRecord(**mapped))
    except Exception:  # noqa: BLE001
        logger.exception("危化品库存总表镜像变更失败: %s", record_id)
        return

    await _analyze_after_change(record_id)


async def _handle_deleted(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id or await _is_duplicate("deleted", record_id):
        return
    try:
        async with async_session_factory() as session:
            await session.execute(
                update(ChemicalInventoryRecord)
                .where(
                    ChemicalInventoryRecord.feishu_record_id == record_id,
                    ChemicalInventoryRecord.is_deleted == False,  # noqa: E712
                )
                .values(is_deleted=True)
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("危化品库存总表镜像软删除失败: %s", record_id)


@on_event("drive.file.bitable_record_changed_v1")
async def _on_inventory_drive_changed(event: dict) -> None:
    """文档级记录变更事件：按 app_token + table_id 过滤后逐条分派。

    直读闸门：事件镜像停用（DIRECT 开 + EVENT_SYNC 关）时整体短路，不落镜像
    也不触发逐条风险分析（cert/central 同口径）。
    action_list 每项仅含 record_id/action，_handle_* 内部回源 get_record，
    此处只构造最小 event_data；created/changed 语义不同（changed 带回声抑制），
    按 action 保持原分派。
    """
    from app.modules.safety.service.chemical_inventory_direct import config

    if not config.legacy_event_sync_active():
        return
    if event.get("file_token", "") != _get_inventory_app_token():
        return
    table_id = event.get("table_id", "")
    if table_id != _get_inventory_table_id():
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
        event_data = {"record_id": record_id, "table_id": table_id}
        try:
            if action == "record_deleted":
                await _handle_deleted(event_data)
            elif action == "record_added":
                await _handle_created(event_data)
            else:  # record_edited 及未知动作
                await _handle_changed(event_data)
        except Exception:  # noqa: BLE001
            logger.exception(
                "危化品库存 drive 事件处理失败: record_id=%s action=%s", record_id, action
            )


# ── 全量同步 ──


async def sync_inventory_records_from_bitable() -> dict[str, Any]:
    """总表全量同步 → DB（幂等 upsert，固定行，单会话批量提交）。"""
    # 直读闸门：直读模式下镜像停更，全量同步无意义（防手工调用打破停更语义）
    from app.modules.safety.service.chemical_inventory_direct import config

    if not config.legacy_event_sync_active():
        logger.info("危化品库存直读模式：跳过镜像全量同步")
        return {"skipped": True, "reason": "direct_mode"}
    if not _enabled():
        logger.info("危化品库存 Bitable 未配置，跳过多维表同步")
        return {"skipped": True, "created": 0, "updated": 0, "total": 0}

    client = SafetyBitableClient(app_token=_get_inventory_app_token(), table_id=_get_inventory_table_id())
    items = await client.list_all_records()
    created = 0
    updated = 0

    async with async_session_factory() as session:
        for item in items:
            record_id = item.get("record_id", "")
            fields = item.get("fields", {}) or {}
            mapped = _map_inventory_fields(fields)
            if not mapped.get("material_name") or not record_id:
                continue
            mapped["feishu_record_id"] = record_id

            existing = await session.scalar(
                select(ChemicalInventoryRecord).where(
                    ChemicalInventoryRecord.feishu_record_id == record_id,
                    ChemicalInventoryRecord.is_deleted == False,  # noqa: E712
                )
            )
            if existing:
                for col, val in mapped.items():
                    setattr(existing, col, val)
                updated += 1
            else:
                session.add(ChemicalInventoryRecord(**mapped))
                created += 1
        await session.commit()

    return {"skipped": False, "created": created, "updated": updated, "total": len(items)}


# ── 系统回填（风险标记/风险说明 → 总表，带防环）──


async def sync_record_flags_to_bitable(records: list[Any]) -> int:
    """把规则回填的 风险标记/风险说明 批量写回飞书「总表」。返回成功条数。

    duck-typing：接受 ORM 行或直读视图（feishu_record_id/risk_flag/risk_note 同名）。
    """
    table_id = _get_inventory_table_id()
    app_token = _get_inventory_app_token()
    if not app_token or not table_id:
        return 0
    client = SafetyBitableClient(app_token=app_token, table_id=table_id)

    payload_records: list[dict[str, Any]] = []
    for record in records:
        if not record.feishu_record_id:
            continue
        fields: dict[str, Any] = {}
        if record.risk_flag:
            fields["风险标记"] = _RISK_FLAG_ENUM_TO_LABEL.get(record.risk_flag, record.risk_flag)
        if record.risk_note:
            fields["风险说明"] = [
                _ALERT_TYPE_ENUM_TO_LABEL.get(v, v) for v in record.risk_note
            ]
        if not fields:
            continue
        await _set_sync_ignore(record.feishu_record_id)
        payload_records.append({"record_id": record.feishu_record_id, "fields": fields})

    if not payload_records:
        return 0

    # 批量更新（500/批）
    import httpx

    token = await client._token()
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{client.app_token}"
        f"/tables/{table_id}/records/batch_update"
    )
    written = 0
    async with httpx.AsyncClient(timeout=120) as http:
        for i in range(0, len(payload_records), 500):
            chunk = payload_records[i : i + 500]
            resp = await http.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"records": chunk},
            )
            data = resp.json()
            if data.get("code") == 0:
                written += len(data.get("data", {}).get("records", []))
            else:
                logger.error("batch_update 失败: code=%s msg=%s", data.get("code"), data.get("msg"))
    return written


# ── 文档事件订阅 ──


async def ensure_chemical_inventory_bitable_subscribed() -> bool:
    """订阅危化品库存 Base 云文档事件（drive/v1/files/{token}/subscribe）。

    app_token 从配置中心 store 读取（``store.get_connection("chemical_inventory", "inventory")``）。
    """
    # 直读闸门：事件镜像停用时不订阅（cert/central 同口径；退订由收尾票统一执行）
    from app.modules.safety.service.chemical_inventory_direct import config

    if not config.legacy_event_sync_active():
        logger.info("危化品库存直读模式：跳过文档事件订阅")
        return False
    conn = _inventory_conn()
    if conn is None or conn.status == "disabled" or not conn.app_token:
        logger.info("危化品库存 Bitable app_token 未配置，跳过文档事件订阅")
        return False
    file_token = conn.app_token
    app_id = os.getenv("SAFETY_FEISHU_APP_ID", "")
    app_secret = os.getenv("SAFETY_FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as http:
            auth_resp = await http.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            auth_data = auth_resp.json()
            if auth_data.get("code") != 0:
                return False
            token = auth_data["tenant_access_token"]
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info("危化品库存 Bitable 文档事件订阅成功: %s", file_token)
                return True
            logger.warning("危化品库存 Bitable 订阅失败: %s", data.get("msg"))
            return False
    except Exception:  # noqa: BLE001
        logger.exception("危化品库存 Bitable 订阅异常")
        return False
