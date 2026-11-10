"""① 定向重跑核心 —— 指定 record_id 走标准识别+写回链（P3-1 T03 下沉）。

诞生于 P2-4 T05-C 脚本（``scripts/hazard_backfill_rerun.py``），P3-1 为使
重跑链可导入、可单测、可被 stale 按需重算复用而下沉为模块函数——语义与
脚本版完全一致（纯下沉，零行为变化）：

复刻轮询主流程单条路径：``record_lock → _identify_one → write_ai_analysis``
（D5 CAS 写前回读）→ ``failure_ledger.record_success``。

- 语义=① 标准重跑：AI 列全部按新输出重写（CAS 保护窗口内人工改动）；
- ``confirm=False`` = dry-run：只跑取数与视图构造，不调 AI 不写回；
- P3-1 起写回成功自动刷新 stale 双指纹基线（``write_ai_analysis`` 挂钩，
  见 ``stale_state``）——重算成功即 stale 自愈。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 运行期延迟 import 防测试收集期触碰配置（模块惯例）
    from app.modules.safety.service.hazard_direct.stale_state import RedisLike

logger = logging.getLogger(__name__)


async def rerun_record(
    client: Any, record_id: str, *, confirm: bool
) -> tuple[str, str]:
    """单条重跑，返回 ``(status, detail)``——status ∈ done/skip/failed/dry-run。"""
    from app.modules.safety.service.hazard_direct import (
        ai_analysis,
        bitable_repo,
        failure_ledger,
    )
    from app.modules.safety.service.hazard_direct.field_authority import F_TYPE_AI

    record = {"record_id": record_id, "fields": await client.get_record(record_id)}
    fields = record.get("fields") or {}
    if not fields:
        return "skip", "记录不存在/读取失败"
    view = bitable_repo.to_view(record)

    async with bitable_repo.record_lock(record_id):
        if not confirm:
            return (
                "dry-run",
                f"可重跑：描述 {len(view.description or '')} 字｜"
                f"现分类（AI）={view.raw.get(F_TYPE_AI)!r}",
            )
        output = await ai_analysis._identify_one(client, view)
        async with bitable_repo.WRITE_LOCK:
            ok = await bitable_repo.write_ai_analysis(
                client,
                record_id,
                hazard_no=None,
                output={
                    **output,
                    "advice_text": ai_analysis._build_advice_text(output),
                },
                supervision_label=ai_analysis._supervision_label(view),
                snapshot_fields=fields,
            )
        if not ok:
            return "failed", "写回返回 False"
        await failure_ledger.record_success(record_id)
        return (
            "done",
            f"级别={output.get('hazard_level')} 类别={output.get('hazard_category')}",
        )


# ── T04：stale 按需重算（input_changed 组专用，ai_edited 永不触碰） ──


@dataclass
class StaleRerunReport:
    """一次 stale 按需重算的报告（脚本打印与证据档数据源）。"""

    done: int = 0
    failed: int = 0
    skipped: int = 0  # 记录不存在/读取失败等 skip（非失败，口径同脚本版）
    dry_run: int = 0
    # ai_edited 保护清单（列出但不触碰，spec US2）
    protected: list[str] = field(default_factory=list)
    # record_id → ai_diff（重算前后差异，重大/跨档变化一目了然）
    diffs: dict[str, dict[str, str]] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)


async def stale_rerun(
    client: Any,
    records: list[dict[str, Any]],
    *,
    limit: int,
    registry_cap: int,
    confirm: bool,
    redis: RedisLike | None = None,
) -> StaleRerunReport:
    """对 stale 扫描的 input_changed 组按需重算（spec §2 / US1·US2·US3）。

    - 候选=``stale_state.scan_records`` 的 input_changed 组（人工改输入）；
      ai_edited 组只进 ``protected`` 清单，永不重算（重跑不覆盖人工）；
    - 限量双重钳制取小：``min(limit, registry_cap)``（registry 0=关）；
    - ``confirm=True`` 时逐条走 ``rerun_record`` 标准链（D5 CAS），重算前后
      AI 值 diff 经 writeback_trace（writer=ai_rerun）挂记录级 Thread 留痕；
      重算成功后双指纹基线自动刷新（stale 自愈）。
    """
    from app.modules.safety.service.hazard_direct import stale_state, writeback_trace

    report = StaleRerunReport()
    scan = await stale_state.scan_records(records, redis=redis)
    report.protected = [c.record_id for c in scan.ai_edited]
    effective = max(0, min(int(limit), int(registry_cap)))
    targets = [c.record_id for c in scan.input_changed][:effective]

    for record_id in targets:
        before: dict[str, Any] = {}
        if confirm:
            before = await client.get_record(record_id)
        try:
            status, detail = await rerun_record(client, record_id, confirm=confirm)
        except Exception as exc:  # noqa: BLE001 — 逐条隔离，失败不中断
            status, detail = "failed", f"{type(exc).__name__}: {str(exc)[:120]}"
        report.details[record_id] = detail
        if status == "done":
            report.done += 1
            after = await client.get_record(record_id)
            diff = stale_state.ai_diff(before, after)
            report.diffs[record_id] = diff
            await writeback_trace.record_writeback(
                writer=writeback_trace.WRITER_AI_RERUN,
                record_id=record_id,
                fields=sorted(diff),
                applied=True,
                note=json.dumps(diff, ensure_ascii=False)[:200],
            )
        elif status == "dry-run":
            report.dry_run += 1
        elif status == "skip":
            report.skipped += 1
        else:
            report.failed += 1
    return report
