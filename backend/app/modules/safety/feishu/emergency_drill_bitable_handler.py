"""应急演练 Bitable 事件处理器（单向同步：Bitable → 平台）。

单表模型，一行记录 = 一次演练的完整生命周期：计划 → 实施 → 复核。
"""

import asyncio
import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.modules.safety import attachment_store
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.bitable_handler import _is_sync_ignored
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import EmergencyDrillRecord

logger = logging.getLogger(__name__)


def _drill_conn() -> ConnectionView | None:
    """演练统计表（main）连接视图（store：DB 活行 → registry 默认）。"""
    return store.get_connection("emergency_drill", "main")


def _get_app_token() -> str:
    conn = _drill_conn()
    return conn.app_token if conn and conn.status != "disabled" else ""


def _get_table_id() -> str:
    conn = _drill_conn()
    return conn.table_id if conn and conn.status != "disabled" else ""


# ── 字段映射（中文 → ORM 列名）──

BITABLE_TO_MODEL: dict[str, str] = {
    # 计划阶段
    "计划时间": "plan_time",
    "演练类型": "drill_type",
    "演练内容": "drill_content",
    "组织人": "organizer",
    "演练部门": "department",
    "组织人 (人员 )": "organizer_person",
    "参演人员": "participants",
    "配合部门": "coop_department",
    "课时": "duration",
    "备  注": "notes",
    "提醒人员": "alert_person",
    # 实施阶段
    "实施时间": "execution_time",
    # 复核阶段
    "演练问题": "issues",
    "整改时间": "rectification_time",
    "整改责任人": "rectification_person",
    "确认人": "confirmer",
    "状态": "status",
}

# 人员字段 → 存储 open_id/name 的 JSON 列
PERSON_FIELDS: dict[str, str] = {
    "提醒人员 (人员 )": "alert_person_data",
    "整改责任人": "rectification_person_data",
    "确认人": "confirmer_data",
}

# 附件字段 → ORM JSON 列
ATTACHMENT_FIELDS: dict[str, str] = {
    "演练方案（AI）": "drill_plan_file",
    "演练方案（定稿）": "plan_final_file",
    "签到表": "signin_file",
    "演练评估表": "eval_form_file",
    "演练记录表": "drill_record_file",
    "演练评估表（AI）": "eval_ai_file",
}


# ── 值提取工具 ──


def _text(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        v = raw.strip()
        return None if v in ("-", "--", "", "无") else v
    if isinstance(raw, list):
        parts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in raw]
        result = ", ".join(filter(None, parts))
        return result or None
    if isinstance(raw, (int, float)):
        return str(raw)
    return str(raw)


def _date(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip()[:10])
        except (ValueError, TypeError):
            return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000, tz=UTC).date()
        except (OSError, ValueError):
            return None
    return None


def _parse_date_text(raw: str) -> date | None:
    """解析日期文本（宽松格式）— 已迁移至 service.drill_eval.parse_date_text。"""
    from app.modules.safety.service.drill_eval import parse_date_text

    return parse_date_text(raw)


def _person(raw: Any) -> dict | None:
    """提取人员字段：优先取数组第一个元素的 id 和 name。"""
    if not raw or not isinstance(raw, list):
        return None
    first = raw[0]
    if isinstance(first, dict):
        return {
            "open_id": first.get("id", ""),
            "name": first.get("name", ""),
            "email": first.get("email", ""),
        }
    return None


def _attachments(raw: Any) -> list[str] | None:
    """提取附件元数据 — 暂存为 JSON（仅 name/file_token，不落 url/tmp_url）。"""
    if not raw or not isinstance(raw, list):
        return None
    paths = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name", "")
            token = item.get("file_token", "")
            if name or token:
                paths.append(
                    json.dumps(
                        {"name": name, "file_token": token},
                        ensure_ascii=False,
                    )
                )
    return [p for p in paths if p] or None


async def _download_and_replace_attachments(
    raw_record: dict,
    app_token: str,
    table_id: str,
    record_id: str,
) -> dict[str, list[str]]:
    """下载附件到统一存储，返回 {en_field: [store_bytes 返回值, ...]} 用于更新 DB。

    策略：① 已存在（MinIO object / 本地文件）→ 复用；② 预签名 URL → ③ file_token + Drive API → ④ 跳过
    """
    result: dict[str, list[str]] = {}
    client = SafetyBitableClient(app_token=app_token, table_id=table_id)

    for cn_field, en_field in ATTACHMENT_FIELDS.items():
        raw = raw_record.get(cn_field)
        if not raw or not isinstance(raw, list):
            continue

        file_paths: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            token = item.get("file_token", "")
            url = item.get("url", "") or item.get("tmp_url", "")

            if not name and not token:
                continue

            # 统一存储文件名（两种存储形态：MinIO key / 本地相对路径）
            safe_record = record_id.replace("/", "_").replace("\\", "_")
            filename = f"drill_{safe_record}_{token}_{name}" if token else f"drill_{safe_record}_{name}"

            # 已存在则复用（与 store_bytes 返回形式保持一致；MinIO 未启用时本地相对路径命中）
            # 探测 key 同样先过 safe_filename：原始 name 含 /、\、中文时与 store_bytes 落盘文件名一致，
            # 否则 exists 恒 miss 导致每次事件重复下载
            stored_filename = attachment_store.safe_filename(filename)
            stored_forms = (
                f"drill/{stored_filename}",
                f"safety/drill/{stored_filename}",
            )
            existing = next((f for f in stored_forms if attachment_store.exists(f)), None)
            if existing:
                file_paths.append(existing)
                logger.info("附件已存在，复用: %s", existing)
                continue

            data: bytes | None = None
            # 策略1: 预签名 URL 下载
            if url:
                try:
                    data = await client.download_attachment_from_url(url)
                except Exception:
                    logger.warning("URL download failed: name=%s", name)
            # 策略2: file_token + Drive API
            if not data and token:
                try:
                    data = await client.download_attachment(token)
                except Exception:
                    logger.warning("Drive API download failed: token=%s name=%s", token, name)

            if data:
                try:
                    stored = attachment_store.store_bytes(
                        "drill", filename, data, item.get("type") or "application/octet-stream",
                    )
                    file_paths.append(stored)
                    logger.info("附件已下载: %s (%d bytes)", stored, len(data))
                except Exception:
                    logger.exception("保存附件失败: %s", filename)
            else:
                logger.warning("附件下载失败(已跳过): name=%s token=%s", name, token)

        if file_paths:
            result[en_field] = file_paths

    return result


def _extract_name(raw: Any) -> str | None:
    """从人员字段提取姓名文本。"""
    if not raw or not isinstance(raw, list):
        return None
    names = [item.get("name", "") for item in raw if isinstance(item, dict)]
    return ", ".join(filter(None, names)) or None


def _map_fields(values: dict) -> dict[str, Any]:
    """将 Bitable 字段值映射为 ORM 列值。"""
    result: dict[str, Any] = {}

    for cn_field, en_field in BITABLE_TO_MODEL.items():
        raw = values.get(cn_field)
        if raw is None:
            continue
        if en_field in ("execution_time", "rectification_time") or cn_field == "计划时间参考":
            val = _date(raw)
        else:
            val = _text(raw)
        if val is not None:
            result[en_field] = val

    # 人员字段
    for cn_field, en_field in PERSON_FIELDS.items():
        raw = values.get(cn_field)
        if raw is not None:
            result[en_field] = _person(raw)
            # 同时提取姓名文本（如整改责任人姓名）
            name = _extract_name(raw)
            if name:
                base = en_field.replace("_data", "")
                if base not in result:
                    result[base] = name

    # 附件字段
    for cn_field, en_field in ATTACHMENT_FIELDS.items():
        raw = values.get(cn_field)
        if raw is not None:
            result[en_field] = _attachments(raw)

    # 计划时间参考（日期字段）
    plan_ref = values.get("计划时间参考")
    if plan_ref is not None:
        d = _date(plan_ref)
        if d is not None:
            result["plan_time_ref"] = d

    return result


# ── 事件处理 ──


async def _handle_created(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id:
        return

    logger.info("Bitable drill record created: record_id=%s", record_id)

    try:
        async with async_session_factory() as session:
            existing = await session.scalar(
                select(EmergencyDrillRecord).where(
                    EmergencyDrillRecord.feishu_record_id == record_id,
                    EmergencyDrillRecord.is_deleted == False,  # noqa: E712
                )
            )
            if existing:
                logger.info("已存在，跳过: record_id=%s", record_id)
                return

        app_token = _get_app_token()
        table_id = _get_table_id()
        if not app_token or not table_id:
            logger.warning("Emergency drill env vars not configured, skipping sync")
            return

        client = SafetyBitableClient(app_token=app_token, table_id=table_id)
        record = await client.get_record(record_id=record_id)
        # get_record() already returns the flat fields dict, no .get("values") needed
        mapped = _map_fields(record if isinstance(record, dict) else {})
        mapped["feishu_record_id"] = record_id

        async with async_session_factory() as session:
            from app.modules.safety.feishu.bitable_handler import acquire_record_lock

            # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
            async with session.begin():
                await acquire_record_lock(session, record_id)
                # 锁后复查：并发创建已被另一事件完成时跳过
                existing = await session.scalar(
                    select(EmergencyDrillRecord).where(
                        EmergencyDrillRecord.feishu_record_id == record_id,
                        EmergencyDrillRecord.is_deleted == False,  # noqa: E712
                    )
                )
                if existing:
                    obj = existing
                else:
                    obj = EmergencyDrillRecord(**mapped)
                    session.add(obj)
                    await session.flush()
            logger.info("已同步: record_id=%s db_id=%s", record_id, obj.id)

        # 下载附件并更新文件路径
        try:
            file_paths = await _download_and_replace_attachments(
                record, app_token, table_id, record_id,
            )
            if file_paths:
                async with async_session_factory() as session:
                    stmt = (
                        update(EmergencyDrillRecord)
                        .where(EmergencyDrillRecord.feishu_record_id == record_id)
                        .values(**file_paths)
                    )
                    await session.execute(stmt)
                    await session.commit()
                    logger.info("附件下载完成: record_id=%s fields=%s", record_id, list(file_paths.keys()))
        except Exception:
            logger.exception("附件下载失败: record_id=%s", record_id)

    except Exception:
        logger.exception("同步创建失败: record_id=%s", record_id)


async def _handle_changed(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id:
        return

    logger.info("Bitable drill record changed: record_id=%s", record_id)

    try:
        app_token = _get_app_token()
        table_id = _get_table_id()
        if not app_token or not table_id:
            return

        client = SafetyBitableClient(app_token=app_token, table_id=table_id)
        record = await client.get_record(record_id=record_id)
        mapped = _map_fields(record if isinstance(record, dict) else {})

        if not mapped:
            return

        async with async_session_factory() as session:
            from app.modules.safety.feishu.bitable_handler import acquire_record_lock

            # DB 级并发互斥：锁只包 update 判定（附件下载是网络 IO，留在事务外，
            # 避免长期占用连接与锁）——2026-09-08 补齐，见 acquire_record_lock
            async with session.begin():
                await acquire_record_lock(session, record_id)
                stmt = (
                    update(EmergencyDrillRecord)
                    .where(
                        EmergencyDrillRecord.feishu_record_id == record_id,
                        EmergencyDrillRecord.is_deleted == False,  # noqa: E712
                    )
                    .values(**mapped)
                )
                result = await session.execute(stmt)
            if result.rowcount:
                logger.info("已更新: record_id=%s", record_id)
                # 下载附件（变更后可能有新附件）
                try:
                    file_paths = await _download_and_replace_attachments(
                        record, app_token, table_id, record_id,
                    )
                    if file_paths:
                        stmt2 = (
                            update(EmergencyDrillRecord)
                            .where(EmergencyDrillRecord.feishu_record_id == record_id)
                            .values(**file_paths)
                        )
                        await session.execute(stmt2)
                        await session.commit()
                        logger.info("附件更新完成: record_id=%s", record_id)
                        # ★ 演练评估表（AI）：上传演练记录表后自动生成（记录表变化才重生成）
                        record_paths = file_paths.get("drill_record_file", [])
                        if record_paths:
                            file_token = _extract_record_file_token(record)
                            if not await _is_sync_ignored(record_id):
                                asyncio.create_task(
                                    _maybe_generate_eval(
                                        record_id, file_token, app_token, table_id,
                                    )
                                )
                except Exception:
                    logger.exception("附件更新失败: record_id=%s", record_id)
            else:
                logger.info("不存在，转为创建: record_id=%s", record_id)
                # 创建：create 事件可能被漏过，在 changed 中兜底
                mapped["feishu_record_id"] = record_id
                obj = EmergencyDrillRecord(**mapped)
                async with async_session_factory() as create_session:
                    from app.modules.safety.feishu.bitable_handler import (
                        acquire_record_lock,
                    )

                    async with create_session.begin():
                        await acquire_record_lock(create_session, record_id)
                        # 锁后复查：并发兜底创建已被另一事件完成时跳过
                        exists_now = await create_session.scalar(
                            select(EmergencyDrillRecord).where(
                                EmergencyDrillRecord.feishu_record_id == record_id,
                                EmergencyDrillRecord.is_deleted == False,  # noqa: E712
                            )
                        )
                        if not exists_now:
                            create_session.add(obj)
                            await create_session.flush()
                        else:
                            obj = exists_now
                    logger.info("已兜底创建: record_id=%s db_id=%s", record_id, obj.id)

    except Exception:
        logger.exception("同步更新失败: record_id=%s", record_id)


# ── 演练评估表（AI）生成触发 ──


def _extract_record_file_token(record: Any) -> str | None:
    """从 changed 事件记录中提取「演练记录表」附件的 file_token。"""
    if not isinstance(record, dict):
        return None
    attachments = record.get("演练记录表")
    if isinstance(attachments, list) and attachments and isinstance(attachments[0], dict):
        return attachments[0].get("file_token")
    return None


async def _maybe_generate_eval(
    record_id: str,
    file_token: str | None,
    app_token: str,
    table_id: str,
) -> None:
    """按需触发演练评估表（AI）生成（后台 task，失败不阻塞同步）。

    去重规则：无法取到事件 file_token，或 PG 已记录相同 record_file_token
    （记录表未变化）→ 跳过，避免重复生成覆盖。
    """
    from app.modules.safety.service.drill_eval import generate_eval_form

    try:
        if not file_token:
            logger.info("Eval generation skipped, no record file token in event: record_id=%s", record_id)
            return
        async with async_session_factory() as session:
            record = (
                await session.execute(
                    select(EmergencyDrillRecord).where(
                        EmergencyDrillRecord.feishu_record_id == record_id,
                        EmergencyDrillRecord.is_deleted == False,  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
            if record is None:
                logger.info("Eval generation skipped, record not found: %s", record_id)
                return
            if record.eval_source_record_file_token == file_token:
                logger.info("Eval generation skipped, record form unchanged: record_id=%s", record_id)
                return

            doc = await generate_eval_form(
                session,
                record.id,
                source="bitable",
                record_file_token=file_token,
            )
            await session.commit()
            if doc is None:
                logger.info("Eval generation produced no doc: record_id=%s", record_id)
    except Exception:
        logger.exception("Eval generation task failed: record_id=%s", record_id)


async def _handle_deleted(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id:
        return

    logger.info("Bitable drill record deleted: record_id=%s", record_id)

    try:
        async with async_session_factory() as session:
            stmt = (
                update(EmergencyDrillRecord)
                .where(
                    EmergencyDrillRecord.feishu_record_id == record_id,
                    EmergencyDrillRecord.is_deleted == False,  # noqa: E712
                )
                .values(is_deleted=True)
            )
            await session.execute(stmt)
            await session.commit()
            logger.info("已软删除: record_id=%s", record_id)
    except Exception:
        logger.exception("同步删除失败: record_id=%s", record_id)


# ── 事件注册 ──


@on_event("drive.file.bitable_record_changed_v1")
async def _on_drill_drive_changed(event: dict) -> None:
    """文档级记录变更事件：按 app_token + table_id 过滤后逐条分派。

    bitable.record.*_v1 飞书从不推送（3000+ 条真实事件实测 0 次），
    2026-09-08 自该事件类型迁移（文档订阅见 ensure_emergency_drill_bitable_subscribed）。
    action_list 每项仅含 record_id/action，_handle_* 内部回源 get_record，
    此处只构造最小 event_data。
    """
    if event.get("file_token", "") != _get_app_token():
        return
    table_id = event.get("table_id", "")
    if table_id != _get_table_id():
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
        except Exception:
            logger.exception(
                "应急演练 drive 事件处理失败: record_id=%s action=%s", record_id, action
            )


async def ensure_emergency_drill_bitable_subscribed() -> bool:
    """订阅应急演练 Base 文档事件（drive.file.bitable_record_changed_v1 前置）。

    飞书要求：接收文档级 Bitable 事件前，须先调用 /drive/v1/files/:file_token/subscribe。
    订阅持久存在于飞书侧，每次启动重试无害。单 base 订阅同时覆盖统计表与收录表。
    订阅成功与否不影响 handler 注册；失败时由重启/配置变更重试兜底。
    """
    import os

    import httpx

    file_token = _get_app_token()
    if not file_token:
        logger.info("应急演练 Bitable app_token 未配置，跳过文档事件订阅")
        return False

    app_id = os.getenv("SAFETY_FEISHU_APP_ID", "")
    app_secret = os.getenv("SAFETY_FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        logger.warning("飞书应用凭证未配置，跳过应急演练文档事件订阅")
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
                logger.info("应急演练 Bitable 文档事件订阅成功: file_token=%s", file_token)
                return True
            logger.error(
                "应急演练 Bitable 文档事件订阅失败: code=%s msg=%s file_token=%s",
                data.get("code"), data.get("msg"), file_token,
            )
            return False
    except Exception:
        logger.exception("应急演练 Bitable 文档事件订阅异常: file_token=%s", file_token)
        return False
