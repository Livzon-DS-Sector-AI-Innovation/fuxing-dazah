"""危化品库存每日定时更新。

流程（每天 19:30，scheduler 调度）：
  1. 拉取「危险品日报」群当日 .xls/.xlsx 文件消息；
  2. 逐个下载 → apply_daily_workbook 更新多维表（批量写回，静默）；
  3. sync_from_bitable + run_full_scan（重算风险，写回风险标记/说明）；
  4. 对比昨日快照做每日分析（超量 + 急剧上升/下降 + 主要危化品汇总），
     落今日 daily 快照，把「危化品库存每日分析日报」推送「安全AI创新交流群」。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.safety.chemical_inventory.daily_report import (
    compute_daily_analysis,
    render_daily_report,
)
from app.modules.safety.chemical_inventory.daily_update import apply_daily_workbook
from app.modules.safety.chemical_inventory.snapshots import (
    KIND_DAILY,
    load_prev_daily_snapshot,
    take_snapshot,
)
from app.modules.safety.feishu.business_agent_bot_handler import _download_message_file
from app.modules.safety.feishu.chemical_inventory_bitable_handler import (
    sync_inventory_records_from_bitable,
)
from app.modules.safety.feishu.client import get_safety_tenant_token
from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.models import ChemicalInventoryRecord
from app.modules.safety.service.chemical_inventory import ChemicalInventoryService

logger = logging.getLogger(__name__)

DANGEROUS_GOODS_DAILY_CHAT_ID = "oc_ae9c3a305430cb196e42130f69b052bc"   # 危险品日报（数据源）
INVENTORY_BITABLE_URL = "https://j0eukrlohu.feishu.cn/base/QoUXbLVcQaYAO7sod1CcUH3JnVd?table=tbl78IlFOo3f1fj1"  # 危化品库存总表
SAFETY_AI_CHAT_ID = os.getenv("SAFETY_CHEMICAL_INVENTORY_DAILY_CHAT_ID", "oc_f05532603bd7682fc520929c01aca88d")  # 安全AI创新交流群

_TMP_DIR = "/tmp/chemical_inventory_scheduled"


def _inventory_app_token() -> str:
    """危化品库存总表 app_token（配置中心 store：DB 活行 → registry 默认）。"""
    from app.modules.safety.bitable_config.store import store

    conn = store.get_connection("chemical_inventory", "inventory")
    if conn is None or conn.status == "disabled":
        return ""
    return conn.app_token


def _day_bounds(now: datetime | None = None) -> tuple[int, int]:
    """返回当日 00:00 与当前时刻的毫秒时间戳。"""
    now = now or datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000), int(now.timestamp() * 1000)


async def _list_chat_messages(
    chat_id: str, start_ms: int, end_ms: int
) -> list[dict[str, Any]]:
    """分页拉取群消息（Im API GET /im/v1/messages）。"""
    token = await get_safety_tenant_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "sort_type": "ByCreateTimeAsc",
            "page_size": 50,
            # 飞书 Im 消息列表 API 的 start_time/end_time 为「秒」级 Unix 时间戳
            "start_time": start_ms // 1000,
            "end_time": end_ms // 1000,
        }
        if page_token:
            params["page_token"] = page_token
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                url, headers={"Authorization": f"Bearer {token}"}, params=params
            )
            d = resp.json()
        if d.get("code", 0) != 0:
            logger.error("拉取危险品日报群消息失败: code=%s msg=%s", d.get("code"), d.get("msg"))
            break
        data = d.get("data", {}) or {}
        items.extend(data.get("items", []) or [])
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return items


async def fetch_daily_files(chat_id: str, start_ms: int, end_ms: int) -> list[dict[str, str]]:
    """从群消息中筛选当日的 .xls/.xlsx 文件。"""
    msgs = await _list_chat_messages(chat_id, start_ms, end_ms)
    files: list[dict[str, str]] = []
    for m in msgs:
        if m.get("msg_type") != "file":
            continue
        # 原始 Im 消息结构为 body.content（lark-cli 才转成顶层 content）
        raw = m.get("content")
        if raw is None:
            body = m.get("body") or {}
            raw = body.get("content")
        try:
            content = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        fk = content.get("file_key", "")
        fn = content.get("file_name", "unknown")
        mid = m.get("message_id", "")
        if not fk or not mid:
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext not in (".xls", ".xlsx"):
            continue
        files.append({"message_id": mid, "file_key": fk, "file_name": fn})
    return files


async def _apply_one(path: str, file_name: str | None = None) -> dict[str, Any]:
    """应用单个文件到多维表（apply_daily_workbook 内部自建客户端并批量写回）。"""
    return await apply_daily_workbook(path, _inventory_app_token(), file_name=file_name)


async def run_scheduled_daily_update() -> dict[str, Any]:
    """执行每日定时更新：拉取 → 下载 → 更新 → 同步 → 重算 → 返回结果。"""
    if not _inventory_app_token():
        logger.warning("危化品库存 Bitable 未配置，跳过每日更新")
        return {"skipped": True, "reason": "no_app_token"}

    start_ms, end_ms = _day_bounds()
    files = await fetch_daily_files(DANGEROUS_GOODS_DAILY_CHAT_ID, start_ms, end_ms)
    logger.info("危险品日报群当日文件: %d 个", len(files))
    if not files:
        return {"skipped": True, "reason": "no_files_today", "files": []}

    file_results: list[dict[str, Any]] = []
    os.makedirs(_TMP_DIR, exist_ok=True)
    for f in files:
        ext = os.path.splitext(f["file_name"])[1].lower()
        path = os.path.join(_TMP_DIR, f"{uuid.uuid4().hex}{ext}")
        try:
            file_bytes = await _download_message_file(f["message_id"], f["file_key"])
            with open(path, "wb") as fh:
                fh.write(file_bytes)
            res = await _apply_one(path, f["file_name"])
            file_results.append({"file_name": f["file_name"], **res})
        except Exception:  # noqa: BLE001
            logger.exception("每日更新文件处理失败: %s", f["file_name"])
            file_results.append({"file_name": f["file_name"], "parsed": 0, "updated": 0, "created": 0, "error": True})
        finally:
            if os.path.exists(path):
                os.remove(path)

    async with async_session_factory() as db:
        sync = await sync_inventory_records_from_bitable()
        svc = ChemicalInventoryService(db)
        scan = await svc.run_full_scan()
        records = list((await db.scalars(select(ChemicalInventoryRecord).where(
            ChemicalInventoryRecord.is_deleted == False,  # noqa: E712
        ))).all())
        warnings = [r for r in records if r.risk_flag == "warn"]

        # 每日分析：与昨日 daily 快照环比（超量 + 急剧变化 + 汇总），并落今日快照
        today = (datetime.now(UTC) + timedelta(hours=8)).date()  # 北京时间
        prev_snapshot = await load_prev_daily_snapshot(db, today)
        analysis = compute_daily_analysis(records, prev_snapshot)
        await take_snapshot(db, today, kind=KIND_DAILY)
        await db.commit()

    return {
        "files": file_results,
        "sync": sync,
        "scan": scan,
        "warnings": warnings,
        "analysis": analysis,
        "total_updated": sum(r.get("updated", 0) for r in file_results),
        "total_created": sum(r.get("created", 0) for r in file_results),
        "total_parsed": sum(r.get("parsed", 0) for r in file_results),
    }


def build_daily_summary(result: dict[str, Any]) -> str:
    """生成发送到群聊的日报 Markdown（危化品库存每日分析日报）。"""
    if result.get("skipped"):
        reason = "今日危险品日报群未发现 Excel 文件" if result.get("reason") == "no_files_today" else "未配置/跳过"
        return f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n⚠️ {reason}"
    analysis = result.get("analysis")
    if analysis is None:
        return "📅 无分析结果"
    return render_daily_report(analysis)


async def send_daily_summary(result: dict[str, Any], chat_id: str | None = None) -> str | None:
    """把每日分析日报推送到配置群聊（发送目标唯一来源：调度器配置，不再回退 env）。"""
    effective_chat_id = chat_id
    if not effective_chat_id or effective_chat_id.startswith("#"):
        logger.info("安全AI创新交流群 chat_id 未配置，跳过日报推送")
        return None
    content = build_daily_summary(result)
    analysis = result.get("analysis")
    if analysis is not None and analysis.has_risk():
        header_template = "red" if analysis.over_limit_count else "orange"
    else:
        header_template = "green"
    return await send_group_card(
        chat_id=effective_chat_id,
        title="危化品库存每日分析日报",
        content=content,
        header_template=header_template,
    )
