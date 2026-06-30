"""Bitable catch-up recovery — 诊断 + 自动恢复。

在服务器重启后，扫描 Bitable 中「隐患编号」为空的记录（即服务停机期间
通过多维表格表单新增但未被 WebSocket 事件处理的记录），自动执行创建、
AI 识别、回写流程。

同时保留 Phase 1 的诊断功能（只读比对，不修改数据）。
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


# ═══════════════════════════════════════════════════════════════
# Phase 1: 诊断（只读比对）
# ═══════════════════════════════════════════════════════════════


async def _get_local_max_updated_at(db: AsyncSession) -> datetime | None:
    """获取本地隐患记录的最新 updated_at，作为漏单检测的时间下界。"""
    stmt = select(func.max(HazardReport.updated_at))
    result = await db.execute(stmt)
    return result.scalar()


async def _fetch_bitable_since(
    cutoff_ms: int,
) -> list[dict[str, Any]]:
    """从 Bitable 拉取 last_modified_time > cutoff_ms 的全部记录（分页）。"""
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
        "cutoff_time": "2026-06-29T10:00:00+00:00",
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


# ═══════════════════════════════════════════════════════════════
# Phase 2: 自动恢复（服务器启动时调用）
# ═══════════════════════════════════════════════════════════════


async def recover_unprocessed_records() -> dict[str, Any]:
    """扫描 Bitable 中「隐患编号」为空的记录并自动处理。

    适用场景：
    - 服务器停机期间，用户通过多维表格表单新增了隐患记录
    - WebSocket 长连接未建立，事件未被接收
    - 服务器恢复后，这些记录的「隐患编号」字段为空

    处理流程（与 WebSocket 事件处理一致）：
      1. 分页拉取全部 Bitable 记录
      2. 筛选「隐患编号」为空的记录
      3. 对每条记录：查重 → 创建 HazardReport → AI 识别 → 回写 Bitable

    并发安全：
    - 使用 _set_sync_ignore 标记每条正在处理的 record_id，防止同时启动的
      WebSocket 事件重复触发
    - 处理前检查本地 DB 是否已有同 feishu_record_id 的记录（回写失败重试）

    返回:
      {
        "total_bitable": int,       # Bitable 总记录数
        "unprocessed": int,         # 隐患编号为空的记录数
        "recovered": int,           # 成功处理数
        "already_exist": int,       # 本地已存在（仅补回写）
        "failed": int,              # 处理失败数
        "details": [                # 每条记录的处理结果
          {"record_id": "...", "status": "success|already_exist|failed", "error": "..."}
        ],
      }
    """
    from app.core.database import async_session_factory
    from app.modules.safety.feishu.bitable_handler import (
        _create_hazard_from_bitable,
        _extract_rich_text,
        _set_sync_ignore,
    )

    client = SafetyBitableClient()

    # Step 1: 拉取全部 Bitable 记录
    logger.info("🔄 启动时 Bitable 漏单恢复: 开始扫描...")
    try:
        all_records = await client.list_all_records()
    except Exception:
        logger.exception("Bitable 漏单恢复: API 拉取失败")
        return {
            "total_bitable": 0,
            "unprocessed": 0,
            "recovered": 0,
            "already_exist": 0,
            "failed": 0,
            "details": [],
            "error": "Bitable API 拉取失败",
        }

    total = len(all_records)
    logger.info("Bitable 漏单恢复: 共 %d 条记录，开始筛选隐患编号为空的记录...", total)

    # Step 2: 筛选隐患编号为空的记录
    # 注意：Bitable search API 返回的文本字段是富文本格式
    # [{"type":"text","text":"HZ-..."}]，必须用 _extract_rich_text 提取纯文本
    unprocessed: list[dict[str, Any]] = []
    for rec in all_records:
        fields = rec.get("fields", {})
        hazard_no_raw = fields.get("隐患编号")
        hazard_no = _extract_rich_text(hazard_no_raw).strip() if hazard_no_raw else ""
        if not hazard_no:
            unprocessed.append(rec)

    if not unprocessed:
        logger.info("✅ Bitable 漏单恢复: 无未处理记录 (total=%d)", total)
        return {
            "total_bitable": total,
            "unprocessed": 0,
            "recovered": 0,
            "already_exist": 0,
            "failed": 0,
            "details": [],
        }

    logger.info(
        "Bitable 漏单恢复: 发现 %d 条隐患编号为空的记录，开始逐条处理...",
        len(unprocessed),
    )

    # Step 3: 逐条处理
    details: list[dict[str, Any]] = []
    recovered = 0
    already_exist = 0
    failed = 0

    for i, rec in enumerate(unprocessed):
        record_id = rec.get("record_id", "")
        fields = rec.get("fields", {})
        desc_raw = fields.get("隐患描述")
        desc = _extract_rich_text(desc_raw)[:60] if desc_raw else ""

        logger.info(
            "[%d/%d] 处理 record_id=%s 描述=%s...",
            i + 1, len(unprocessed), record_id, desc,
        )

        try:
            # 3a. 防重入标记（30s TTL，足够完成单条处理）
            await _set_sync_ignore(record_id, ttl=60)

            # 3b. 查重：本地是否已有同 feishu_record_id 的记录
            async with async_session_factory() as db:
                stmt = select(HazardReport).where(
                    HazardReport.feishu_record_id == record_id
                )
                result = await db.execute(stmt)
                existing_hazard = result.scalar_one_or_none()

            if existing_hazard and existing_hazard.hazard_no:
                # 本地已存在且有隐患编号 → 只补回写 Bitable
                logger.info(
                    "  本地已存在 hazard_no=%s，仅补回写 Bitable 隐患编号",
                    existing_hazard.hazard_no,
                )
                ok = await client.update_record(
                    record_id,
                    {"隐患编号": existing_hazard.hazard_no},
                )
                if not ok:
                    logger.error(
                        "补回写 Bitable 失败(update_record=False): record_id=%s hazard_no=%s",
                        record_id, existing_hazard.hazard_no,
                    )
                    # 不中断流程，继续处理下一条
                already_exist += 1
                details.append({
                    "record_id": record_id,
                    "status": "already_exist",
                    "hazard_no": existing_hazard.hazard_no,
                })
                continue

            # 3c. 完整处理流程（与 WebSocket 事件处理一致）
            await _create_hazard_from_bitable(record_id, fields)
            recovered += 1
            details.append({"record_id": record_id, "status": "success"})
            logger.info("  ✅ 恢复成功")

        except Exception as exc:
            failed += 1
            logger.exception(
                "  ❌ 恢复失败 [%d/%d] record_id=%s",
                i + 1, len(unprocessed), record_id,
            )
            details.append({
                "record_id": record_id,
                "status": "failed",
                "error": str(exc),
            })

    # Step 4: 汇总
    summary = {
        "total_bitable": total,
        "unprocessed": len(unprocessed),
        "recovered": recovered,
        "already_exist": already_exist,
        "failed": failed,
        "details": details,
    }

    logger.info(
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  Bitable 漏单恢复完成                                          ║\n"
        "║  Bitable 总数: %-5d  未处理: %-5d                               ║\n"
        "║  已恢复: %-5d  已存在: %-5d  失败: %-5d                       ║\n"
        "╚══════════════════════════════════════════════════════════════╝",
        total, len(unprocessed), recovered, already_exist, failed,
    )

    # 输出失败详情
    if failed > 0:
        failed_records = [d for d in details if d["status"] == "failed"]
        logger.warning(
            "以下 %d 条记录恢复失败，请手动检查 Bitable 并重新处理:\n%s",
            failed,
            "\n".join(
                f"  - {d['record_id']}" for d in failed_records
            ),
        )

    return summary
