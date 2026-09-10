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
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.core.redis import redis_client
from app.modules.safety.bitable_config.store import ConnectionView, store
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


# 总表 Bitable 中文字段 → DB 列
INVENTORY_BITABLE_TO_MODEL: dict[str, str] = {
    "部门": "department",
    "存放部位": "storage_location",
    "物料名称": "material_name",
    "包装规格": "package_spec",
    "库存数量": "quantity",
    "单位": "unit",
    "现场物料总量(T)": "total_quantity_t",
    "库存上限": "max_limit",
    "上限单位": "max_limit_unit",
    "危险性": "hazard_classes",
    "品类": "category",
    "最后更新时间": "last_updated_at",
    "备注": "remark",
    "风险标记": "risk_flag",
    "风险说明": "risk_note",
}


# ── 中文标签 ↔ 枚举值 双向映射 ──

_DEPT_LABEL_TO_ENUM: dict[str, str] = {
    "仓储部": "warehouse",
    "提炼一部": "extraction_1",
    "提炼二期": "extraction_2",
    "提炼二部": "extraction_2b",
    "发酵一部": "fermentation_1",
    "发酵二部": "fermentation_2",
    "菌种中心": "strain",
    "QC": "qc",
    "环保": "env",
    "精制": "purification",
    "提炼半合成工程中心": "semi_synth",
    "提炼技术精进中心": "tech_refine",
    "其他": "other",
}
_DEPT_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _DEPT_LABEL_TO_ENUM.items()}

_UNIT_LABEL_TO_ENUM: dict[str, str] = {
    "kg": "kg", "g": "g", "T": "T", "L": "L", "ml": "ml", "瓶": "bottle",
}
_UNIT_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _UNIT_LABEL_TO_ENUM.items()}

_HAZARD_LABEL_TO_ENUM: dict[str, str] = {
    "易燃": "flammable",
    "易爆": "explosive",
    "易制毒": "precursor_drug",
    "易制爆": "precursor_explosive",
    "腐蚀": "corrosive",
    "毒性": "toxic",
    "氧化剂": "oxidizer",
    "刺激性": "irritant",
}
_HAZARD_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _HAZARD_LABEL_TO_ENUM.items()}

_RISK_FLAG_LABEL_TO_ENUM: dict[str, str] = {"正常": "normal", "预警": "warn"}
_RISK_FLAG_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _RISK_FLAG_LABEL_TO_ENUM.items()}

# 风险说明：正常 + 预警类型
_ALERT_TYPE_LABEL_TO_ENUM: dict[str, str] = {
    "正常": "normal",
    "超量": "over_limit",
    "临限": "near_limit",
    "高占比": "high_ratio",
    "未分类": "unclassified",
    "单位异常": "unit_anomaly",
    "专库违规": "special_storage",
}
_ALERT_TYPE_ENUM_TO_LABEL: dict[str, str] = {v: k for k, v in _ALERT_TYPE_LABEL_TO_ENUM.items()}


# ── 值提取 ──


def _text(raw: Any) -> str | None:
    if raw is None:
        return None
    # 飞书文本字段读回为富文本数组 [{"text": "...", "type": "text"}]
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        s = "".join(parts).strip()
        return s or None
    if isinstance(raw, dict):
        return _text(raw.get("text"))
    s = str(raw).strip()
    return s or None


def _num(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except Exception:  # noqa: BLE001
        return None


def _datetime_from_raw(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000, tz=UTC)
        except (OSError, ValueError):
            return None
    return None


def _multi_select(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = []
        for item in raw:
            if isinstance(item, dict):
                if item.get("text"):
                    values.append(str(item["text"]))
            else:
                values.append(str(item))
    elif isinstance(raw, dict):
        values = [str(raw.get("text", ""))]
    else:
        return None
    values = [v.strip() for v in values if str(v).strip()]
    return values or None


def _map_inventory_fields(values: dict) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for bitable_field, model_col in INVENTORY_BITABLE_TO_MODEL.items():
        raw = values.get(bitable_field)
        if model_col == "last_updated_at":
            mapped[model_col] = _datetime_from_raw(raw)
        elif model_col in ("quantity", "total_quantity_t", "max_limit"):
            mapped[model_col] = _num(raw)
        elif model_col == "hazard_classes":
            labels = _multi_select(raw)
            if labels:
                mapped[model_col] = [_HAZARD_LABEL_TO_ENUM.get(v, v) for v in labels]
        elif model_col == "risk_note":
            labels = _multi_select(raw)
            if labels:
                mapped[model_col] = [_ALERT_TYPE_LABEL_TO_ENUM.get(v, v) for v in labels]
        elif model_col == "department":
            value = _text(raw)
            if value:
                mapped[model_col] = _DEPT_LABEL_TO_ENUM.get(value, value)
        elif model_col in ("unit", "max_limit_unit"):
            value = _text(raw)
            if value:
                mapped[model_col] = _UNIT_LABEL_TO_ENUM.get(value, value)
        elif model_col == "risk_flag":
            value = _text(raw)
            if value:
                mapped[model_col] = _RISK_FLAG_LABEL_TO_ENUM.get(value, value)
        else:
            mapped[model_col] = _text(raw)
    return {k: v for k, v in mapped.items() if v is not None}


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

    action_list 每项仅含 record_id/action，_handle_* 内部回源 get_record，
    此处只构造最小 event_data；created/changed 语义不同（changed 带回声抑制），
    按 action 保持原分派。
    """
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


async def sync_record_flags_to_bitable(records: list[ChemicalInventoryRecord]) -> int:
    """把规则回填的 风险标记/风险说明 批量写回飞书「总表」。返回成功条数。"""
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
