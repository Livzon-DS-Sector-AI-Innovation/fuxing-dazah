"""AI 自动审核变更检测触发器（Ticket 04，spec §4.1 D1 拍板）。

事件到达即触发审核的直读替代：查询路径（list/stats）顺带检测——

- 候选 = 协议挂载 AND 派生态非 completed AND（无平台行（新记录）OR 映射字段 diff（编辑））
- diff 用 mapped_diff_key 稳定键（附件只比 file_token——预签名 url 每拉必变），
  且只比「upsert 可收敛键集」：upsert_from_bitable 更新分支只写非 None 值，
  视图侧 None 而平台行残留旧值的键 upsert 改不动、diff 永不归零（审查 M-1），
  排除后 WRITEBACK_AI 关（派生态恒 none）时也不会每查询周期重复触发审核
- fire-and-forget：独立 session 从视图 upsert 平台行 → 复用既有
  ``run_admission_review(channel="system")``（内部 Redis 防重 + processing 防重入）
- 进程内 in-flight set 并发上限 3，超限跳过（下次查询再触发）；异常吞掉记日志

历史积压行（平台行与直读一致且未审核）不触发——与现状一致：事件也不补审旧记录。
本模块无定时任务、不碰 scheduler.py（硬约束）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from app.modules.safety.service.contractor_admission_direct.views import (
    AI_REVIEW_STATUS_COMPLETED,
    ContractorAdmissionView,
    mapped_diff_key,
    mapped_field_keys,
)

__all__ = ["detect_candidates", "fire_and_forget", "inflight_count"]

logger = logging.getLogger(__name__)

_MAX_INFLIGHT = 3
_inflight: set[str] = set()
# 持强引用防任务被 GC 中途丢弃（CPython 文档口径），完成即弃
_background_tasks: set[asyncio.Task[None]] = set()


def detect_candidates(
    views: list[ContractorAdmissionView],
    rows_by_record_id: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """纯函数：返回待触发审核的 (record_id, mapped values) 列表。

    rows_by_record_id 为平台库按 feishu_record_id 索引的未删除行（可为空——
    本地/新表全当新记录触发，与「无平台行=新记录」口径一致）。
    """
    keys = mapped_field_keys()
    out: list[tuple[str, dict[str, Any]]] = []
    for view in views:
        if not view.safety_agreement_files:
            continue
        if view.ai_review_status == AI_REVIEW_STATUS_COMPLETED:
            continue
        values = {k: getattr(view, k) for k in keys}
        row = rows_by_record_id.get(view.id)
        if row is not None:
            row_values = {k: getattr(row, k) for k in keys}
            # 只比 upsert 改得动的键（视图 None / 行非 None 的键 upsert 不清空）
            comparable = [
                k for k in keys
                if not (values[k] is None and row_values[k] is not None)
            ]
            if mapped_diff_key({k: row_values[k] for k in comparable}) == \
                    mapped_diff_key({k: values[k] for k in comparable}):
                continue
        out.append((view.id, values))
    return out


def fire_and_forget(candidates: list[tuple[str, dict[str, Any]]]) -> int:
    """并发上限内逐个后台触发；返回实际启动数。"""
    launched = 0
    for record_id, values in candidates:
        if record_id in _inflight:
            continue
        if len(_inflight) >= _MAX_INFLIGHT:
            logger.info(
                "相关方准入直读触发并发已满(%d)，跳过 record_id=%s（下次查询再触发）",
                _MAX_INFLIGHT, record_id,
            )
            continue
        _inflight.add(record_id)
        task = asyncio.create_task(_run_review(record_id, values))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        launched += 1
    return launched


def inflight_count() -> int:
    """当前在途审核数（测试/观测用）。"""
    return len(_inflight)


async def _run_review(record_id: str, values: dict[str, Any]) -> None:
    """后台执行：upsert 平台行（触发时快照）→ 复用既有 AI 审核流程。

    Redis 防重命中时 run_admission_review 提前返回（未实际审核），本层无法区分，
    统一记「流程结束」。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.service.contractor_admission import (
        ContractorAdmissionService,
    )

    try:
        async with async_session_factory() as session:
            service = ContractorAdmissionService(session)
            row = await service.upsert_from_bitable(values, record_id, "admission")
            if row is None:
                return
            await service.run_admission_review(row.id, channel="system")
            logger.info("相关方准入直读自动审核流程结束 record_id=%s", record_id)
    except Exception:
        logger.exception("相关方准入直读自动审核失败 record_id=%s", record_id)
    finally:
        _inflight.discard(record_id)
