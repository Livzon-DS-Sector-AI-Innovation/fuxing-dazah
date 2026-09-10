"""③ 督办等级计算（轮询）— 直读多维表格，只回写多维表格。

改造前：每日 07:30 独立任务，读 DB → 算 → 写 DB + 回写 Bitable → 发汇总给管理员。
改造后：并入 hazard_direct 轮询（每 5 分钟），读 **多维表格** → 算 → **只回写多维表格**，
不再写库、不再发汇总 DM（避免每 5 分钟打扰）。

规则复用 ``service.hazard_supervision.calculate_supervision_level``（纯函数）：
    0. 整改状态 = 已关闭 → closed（最高优先级）
    1. 隐患级别（人工）为 较大/重大 → 红色预警
    2. 检查日期距今 > 30 天 → 红色预警
    3. 否则 → 一般预警

只回写「计算结果与当前字段值不同」的记录，避免无意义写（Bitable 单表写不支持并发）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.modules.safety.service.hazard_direct import bitable_repo

logger = logging.getLogger(__name__)

# 不参与督办的测试部门（与旧任务口径一致）
EXCLUDED_DEPARTMENTS: tuple[str, ...] = ("AI创新部",)

# 进程级写回锁（同 ai_analysis：手动触发与定时轮询可能并发，需共享同一把锁）
_WRITE_LOCK = asyncio.Lock()


@dataclass
class SupervisionRoundResult:
    """单轮执行结果。"""

    job_label: str = "督办等级计算"
    total: int = 0
    changed: int = 0
    unchanged: int = 0
    failed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_label": self.job_label,
            "total": self.total,
            "changed": self.changed,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "failures": self.failures,
        }


async def _fetch_targets(client: Any) -> list[dict[str, Any]]:
    """取需要计算督办等级的记录。

    A. 未关闭 / 整改中（``整改状态 isNot 已关闭``）——需要算等级
    B. 当前仍标为督办中（``督办等级 is 红色预警 / 一般预警``）——可能已关闭需置 closed
    A ∪ B，按 record_id 去重。
    """
    def cond(name: str, op: str, value: list[str] | None = None) -> dict[str, Any]:
        return {"field_name": name, "operator": op, "value": value or []}

    a = await client.list_all_records(
        filter_info={
            "conjunction": "and",
            "conditions": [cond(bitable_repo.F_RECTIFY_STATUS, "isNot", ["已关闭"])],
        },
        page_size=500,
        strict=True,
    )
    b = await client.list_all_records(
        filter_info={
            "conjunction": "or",
            "conditions": [
                cond(bitable_repo.F_SUPERVISION, "is", ["红色预警"]),
                cond(bitable_repo.F_SUPERVISION, "is", ["一般预警"]),
            ],
        },
        page_size=500,
        strict=True,
    )
    merged: dict[str, dict[str, Any]] = {}
    for rec in [*a, *b]:
        rid = rec.get("record_id", "")
        if rid:
            merged[rid] = rec
    return list(merged.values())


def _compute_label(view: bitable_repo.HazardView) -> str | None:
    """按现有规则计算督办等级标签。"""
    from app.modules.safety.feishu.bitable_handler import SUPERVISION_LEVEL_REVERSE
    from app.modules.safety.service.hazard_supervision import (
        calculate_supervision_level,
    )

    level = calculate_supervision_level(view)  # type: ignore[arg-type]
    return SUPERVISION_LEVEL_REVERSE.get(level, level) if level else None


async def run_supervision_round(
    *, notify: bool = True, dry_run: bool = False
) -> SupervisionRoundResult:
    """执行一轮督办等级计算（只回写多维表格）。

    Args:
        notify: 失败达阈值时是否推送管理员告警。
        dry_run: True 时只计算不写回（用于验证/预览）。
    """
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    result = SupervisionRoundResult()
    client = SafetyBitableClient()
    records = await _fetch_targets(client)
    result.total = len(records)
    if not records:
        logger.info("③ 无需要计算督办等级的记录")
        return result

    write_lock = _WRITE_LOCK

    async def _worker(record: dict[str, Any]) -> None:
        record_id = record.get("record_id", "")
        view = bitable_repo.to_view(record)
        if (view.department or "") in EXCLUDED_DEPARTMENTS:
            result.unchanged += 1
            return
        if bitable_repo.is_audit_record(view.raw):
            result.unchanged += 1
            logger.debug("③ 跳过外审记录: record_id=%s", record_id)
            return
        try:
            label = _compute_label(view)
            current = (view.supervision_level or "").strip()
            if not label or label == current:
                result.unchanged += 1
                return
            if dry_run:
                result.changed += 1
                logger.info(
                    "③ [dry-run] 督办等级将更新: record_id=%s %s → %s",
                    record_id, current or "(空)", label,
                )
                return
            async with write_lock:
                from app.modules.safety.feishu.bitable_handler import (
                    _format_bitable_select_value,
                )

                ok = await client.update_record(
                    record_id,
                    {
                        bitable_repo.F_SUPERVISION: _format_bitable_select_value(
                            bitable_repo.F_SUPERVISION, label
                        )
                    },
                )
                if not ok:
                    raise RuntimeError("写回 Bitable 返回 False")
                await asyncio.sleep(0.5)  # 单表写串行化，规避 1254291
            result.changed += 1
            logger.info(
                "③ 督办等级更新: record_id=%s %s → %s", record_id, current or "(空)", label
            )
        except Exception as exc:
            result.failed += 1
            result.failures.append(
                {"record_id": record_id, "reason": f"{type(exc).__name__}: {exc}"[:200]}
            )
            logger.exception("③ 督办等级计算失败: record_id=%s", record_id)

    await asyncio.gather(*(_worker(rec) for rec in records))

    logger.info(
        "③ 本轮结束: 总数=%d 变更=%d 未变=%d 失败=%d",
        result.total, result.changed, result.unchanged, result.failed,
    )
    if notify and result.failures:
        from app.modules.safety.service.hazard_direct import config
        from app.modules.safety.service.hazard_direct.alert import notify_failures

        if len(result.failures) >= config.alert_min_failures():
            await notify_failures(
                result.job_label, failures=result.failures, total=result.total
            )
    return result
