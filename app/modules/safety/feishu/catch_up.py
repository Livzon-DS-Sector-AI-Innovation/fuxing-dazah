"""Bitable catch-up recovery — Phase 1 diagnostic.

在服务器重启后，通过飞书 Bitable 系统字段 `last_modified_time` 精准定位
WebSocket 断线期间被遗漏的记录变更（新增/修改），与本地数据库做只读比对。

不修改数据库或 Bitable 中的任何数据。
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.models import HazardReport

logger = logging.getLogger(__name__)

# Bitable 系统字段：最后修改时间（type=1002），需 automatic_fields=true 时返回
_SYSTEM_FIELD_LAST_MODIFIED = "修改时间"


async def _get_local_max_updated_at(db: AsyncSession) -> datetime | None:
    """获取本地隐患记录的最新 updated_at，作为漏单检测的时间下界。"""
    stmt = select(func.max(HazardReport.updated_at))
    result = await db.execute(stmt)
    return result.scalar()


async def _fetch_bitable_since(
    cutoff_ms: int,
) -> list[dict[str, Any]]:
    """从 Bitable 拉取 last_modified_time > cutoff_ms 的全部记录（分页）。

    使用结构化 filter + sort，仅返回停机窗口内被修改的记录。
    """
    client = SafetyBitableClient()
    return await client.list_all_records(
        filter_info={
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": _SYSTEM_FIELD_LAST_MODIFIED,
                    "operator": "isGreater",
                    "value": ["ExactDate", str(cutoff_ms)],
                }
            ],
        },
        sort=[{"field_name": _SYSTEM_FIELD_LAST_MODIFIED, "desc": True}],
        automatic_fields=True,
        page_size=200,
    )


async def _get_local_feishu_ids(db: AsyncSession) -> set[str]:
    """获取本地所有已关联 feishu_record_id 的隐患记录 ID 集合。"""
    stmt = select(HazardReport.feishu_record_id).where(
        HazardReport.feishu_record_id.isnot(None)
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.fetchall() if row[0]}


async def diagnose_missed_records(db: AsyncSession) -> dict[str, Any]:
    """诊断 Bitable 中可能在 WS 断线期间被遗漏的记录。

    策略（精准增量查询，非全量比对）：
      1. 取本地最大 updated_at 作为时间下界
      2. 查询 Bitable 中 last_modified_time > 此值的记录
      3. 按 feishu_record_id 与本地比对，找出本地不存在的记录
      4. 仅报告，不修改

    返回:
      {
        "cutoff_time": "2026-06-29T10:00:00+00:00",  # 时间下界
        "bitable_matched": int,    # 查询窗口内 Bitable 返回的记录数
        "local_total": int,        # 本地已关联 feishu_record_id 的记录数
        "missed": int,             # Bitable 有但本地没有（漏单）
        "existing": int,           # 两边都有的记录
        "missed_records": [...],   # 漏单详情（最多 50 条）
        "diagnostic_ran_at": str,  # ISO 时间戳
      }
    """
    now = datetime.now(UTC)
    local_total = 0
    bitable_matched = 0
    missed = 0
    existing = 0
    missed_records: list[dict[str, Any]] = []
    cutoff_time: datetime | None = None

    # Step 1: 时间锚点
    max_updated = await _get_local_max_updated_at(db)
    if max_updated:
        cutoff_time = max_updated
        cutoff_ms = int(max_updated.timestamp() * 1000)
        logger.info(
            "Bitable 漏单诊断: 时间下界=%s (ms=%d)",
            max_updated.isoformat(), cutoff_ms,
        )
    else:
        # DB 为空（全新部署），使用过去 7 天作为窗口
        cutoff_time = now
        cutoff_ms = int(now.timestamp() * 1000) - 7 * 24 * 3600 * 1000
        logger.info(
            "Bitable 漏单诊断: 本地无记录，使用过去 7 天窗口 (since=%s)",
            datetime.fromtimestamp(cutoff_ms / 1000, tz=UTC).isoformat(),
        )

    # Step 2: 拉取 Bitable 停机窗口内的记录
    try:
        bitable_records = await _fetch_bitable_since(cutoff_ms)
    except Exception:
        logger.exception("Bitable 漏单诊断: API 查询失败")
        return {
            "cutoff_time": cutoff_time.isoformat() if cutoff_time else None,
            "bitable_matched": 0,
            "local_total": 0,
            "missed": -1,
            "existing": 0,
            "missed_records": [],
            "diagnostic_ran_at": now.isoformat(),
            "error": "Bitable API 查询失败，详见日志",
        }

    bitable_matched = len(bitable_records)
    if bitable_matched == 0:
        logger.info("Bitable 漏单诊断: 停机窗口内无记录变更")
        return {
            "cutoff_time": cutoff_time.isoformat() if cutoff_time else None,
            "bitable_matched": 0,
            "local_total": 0,
            "missed": 0,
            "existing": 0,
            "missed_records": [],
            "diagnostic_ran_at": now.isoformat(),
        }

    # Step 3: 本地 feishu_record_id 集合
    try:
        local_ids = await _get_local_feishu_ids(db)
    except Exception:
        logger.exception("Bitable 漏单诊断: 本地 DB 查询失败")
        local_ids = set()
    local_total = len(local_ids)

    # Step 4: 逐条比对
    for rec in bitable_records:
        record_id = rec.get("record_id", "")
        if not record_id:
            continue

        if record_id in local_ids:
            existing += 1
        else:
            missed += 1
            # 提取关键字段用于日志
            fields = rec.get("fields", {})
            preview = {
                "record_id": record_id,
                "检查日期": fields.get("检查日期"),
                "隐患描述": fields.get("隐患描述"),
                "责任部门": fields.get("责任部门"),
                "整改状态": fields.get("整改状态"),
                "last_modified_time": rec.get("last_modified_time"),
            }
            if len(missed_records) < 50:
                missed_records.append(preview)
            logger.warning(
                "Bitable 漏单诊断: 发现漏单 record_id=%s 检查日期=%s 部门=%s 描述=%s",
                record_id,
                fields.get("检查日期"),
                fields.get("责任部门"),
                (fields.get("隐患描述") or "")[:80],
            )

    # Step 5: 汇总
    if missed > 0:
        logger.warning(
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║  Bitable 漏单诊断: 发现 %d 条漏单                            ║\n"
            "║  时间下界: %-50s ║\n"
            "║  Bitable 窗口内: %-5d  本地已关联: %-5d  已存在: %-5d  ║\n"
            "╚══════════════════════════════════════════════════════════════╝",
            missed,
            (cutoff_time.isoformat() if cutoff_time else "N/A"),
            bitable_matched, local_total, existing,
        )
    else:
        logger.info(
            "Bitable 漏单诊断: 全部正常 (窗口内 %d 条, 本地 %d 条, 无漏单)",
            bitable_matched, local_total,
        )

    return {
        "cutoff_time": cutoff_time.isoformat() if cutoff_time else None,
        "bitable_matched": bitable_matched,
        "local_total": local_total,
        "missed": missed,
        "existing": existing,
        "missed_records": missed_records,
        "diagnostic_ran_at": now.isoformat(),
    }
