"""危险品日报群：接收每日 Excel → 更新总表存量（不回群、不通知）。"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from app.core.database import async_session_factory
from app.modules.safety.bitable_config.store import store
from app.modules.safety.chemical_inventory.daily_update import apply_daily_workbook
from app.modules.safety.feishu.business_agent_bot_handler import _download_message_file
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.service.chemical_inventory import ChemicalInventoryService

logger = logging.getLogger(__name__)

DANGEROUS_GOODS_DAILY_CHAT_ID = "oc_ae9c3a305430cb196e42130f69b052bc"
# 实时驱动已关闭：改为每天 19:30 定时拉取（见 scheduler 危化品库存日报）。默认关闭。
DAILY_REALTIME_ENABLED = os.getenv("SAFETY_CHEMICAL_INVENTORY_DAILY_REALTIME_ENABLED", "") == "1"

_TMP_DIR = "/tmp/chemical_inventory_daily"


@on_event("im.message.receive_v1")  # type: ignore[untyped-decorator]
async def handle_daily_excel_message(event_data: dict[str, Any]) -> None:
    """危险品日报群的文件消息 → 解析并更新存量（静默，不回群）。

    自 2026-08-26 起改为每天 19:30 定时拉取（scheduler 危化品库存日报），实时驱动默认关闭。
    """
    if not DAILY_REALTIME_ENABLED:
        return
    message = event_data.get("message", {})
    if message.get("chat_id", "") != DANGEROUS_GOODS_DAILY_CHAT_ID:
        return
    if message.get("message_type", "") != "file":
        return
    conn = store.get_connection("chemical_inventory", "inventory")
    if conn is None or conn.status == "disabled" or not conn.app_token:
        return
    app_token = conn.app_token

    try:
        content = json.loads(message.get("content", "{}"))
    except json.JSONDecodeError:
        return
    file_key = content.get("file_key", "")
    file_name = content.get("file_name", "unknown.file")
    message_id = message.get("message_id", "")
    if not file_key or not message_id:
        return
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in (".xls", ".xlsx"):
        return

    try:
        file_bytes = await _download_message_file(message_id, file_key)
    except Exception as e:  # noqa: BLE001
        logger.warning("危险品日报 Excel 下载失败: %s err=%s", file_name, e)
        return

    os.makedirs(_TMP_DIR, exist_ok=True)
    path = os.path.join(_TMP_DIR, f"{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as f:
        f.write(file_bytes)

    try:
        result = await apply_daily_workbook(path, app_token)
        logger.info("危险品日报 Excel 已更新: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("危险品日报 Excel 处理失败: %s", file_name)
        return
    finally:
        if os.path.exists(path):
            os.remove(path)

    # 更新后同步 DB + 重算风险（不回群、不通知）
    try:
        async with async_session_factory() as db:
            svc = ChemicalInventoryService(db)
            await svc.sync_from_bitable()
            await svc.run_full_scan()
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("危险品日报更新后重算风险失败")
