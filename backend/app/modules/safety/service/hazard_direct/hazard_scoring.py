"""⑤ 隐患AI评分轮询 — 直读多维表格，不落库。

链路：
    search(分类（AI）已填 ∧ 评分结果为空 ∧ 检查日期∈回填窗口) → per-record 锁
      → 纯文本 AI 调用（无图，输入=描述 + ①轮识别结论；不含上报人身份）
      → rules 校验/总分计算 → 写回 Bitable（评分结果 + 评分说明 2 列）→ 释放锁

失败语义（与①轮一致）：**不写任何列** → 下一轮仍命中同一判据 → 自动重试。
重评运营语义：清空表内「评分结果」列即可触发重打。

评分模型：制度 SOPAQ01015-03 §10.3 D=L×E×C×X；AI 只选档位，
总分/一致性提示由代码计算（ai_hazard_scoring.rules）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.modules.safety.service.hazard_direct import bitable_repo, config
from app.modules.safety.service.hazard_direct.alert import notify_failures
from app.modules.safety.service.hazard_direct.round_result import RoundResult

if TYPE_CHECKING:
    from app.modules.safety.ai_hazard_scoring import HazardScoringOutput

logger = logging.getLogger(__name__)


async def _score_one(client: Any, view: bitable_repo.HazardView):
    """调用 AI 评分插件，返回强类型 HazardScoringOutput（不做任何写回）。"""
    from app.modules.safety.ai_hazard_scoring import (
        AIHazardScorer,
        HazardScoringInput,
    )
    from app.modules.safety.service.config import create_ai_service

    input_data = HazardScoringInput(
        hazard_no=view.hazard_no or view.record_id[:8],
        description=view.description or "无描述",
        key_defect=view.key_defect,
        # 读口径（P0-B B2）：评分输入 = effective_*（人工优先、AI fallback），
        # 不再直读 AI 列；口径来源在评分说明末尾标注。
        hazard_type=view.effective_type,
        hazard_category=view.effective_category,
        hazard_level=view.effective_level,
        major_hazard_basis=view.major_hazard_basis or None,
        department=view.department,
        inspection_category=view.inspection_category,
    )

    ai_service = create_ai_service("text")
    try:
        from app.modules.safety.ai_audit import ai_audit_scope

        with ai_audit_scope(
            scenario="hazard_scoring",
            resource_type="hazard",
            channel="system",
            extra={"bitable_record_id": view.record_id, "source": "bitable_direct"},
        ):
            plugin = AIHazardScorer(ai_service)
            return await plugin.score(input_data)
    finally:
        await ai_service.close()


def _build_note(
    out: "HazardScoringOutput", total: float, level_source: str | None = None
) -> str:
    """评分说明固定格式（前端按「｜」切分取首段做 H/M/L 色点）。

    模板：{band}｜{L档}{L值}×{E档}{E值}×{C档}{C值}×{X档}{X值}={D}｜{评语}｜依据:{条目}
          [｜重大判定:{条款;条款}] [｜⚠分值与风险等级不一致…]
          [｜基于人工等级 | ｜基于AI等级（人工等级缺失）]

    等级口径段追加在**末尾**（首段=band 的前端契约不变）：输入等级取自
    ``effective_level``，human 来源标注「基于人工等级」；AI fallback 标注
    「基于AI等级（人工等级缺失）」，避免把 AI 候选当人工结论。
    """
    from app.modules.safety.ai_hazard_scoring import rules

    def _dim(dim: str, member: Any) -> str:
        label = rules.tier_label(dim, member.value)
        value = member.value.rstrip("0").rstrip(".") if "." in member.value else member.value
        return f"{label}{value}"

    parts = [
        out.band.value,
        "×".join(
            [
                _dim("likelihood", out.likelihood),
                _dim("exposure", out.exposure),
                _dim("consequence", out.consequence),
                _dim("difficulty", out.difficulty),
            ]
        )
        + f"={total}",
        out.summary,
        f"依据:{out.band_basis}",
    ]
    if out.major_hazard.hit and out.major_hazard.clauses:
        parts.append("重大判定:" + ";".join(out.major_hazard.clauses))
    warning = rules.band_consistency(out, total)
    if warning:
        parts.append(warning)
    # 等级口径标注（末尾追加，不破坏「首段=band」前端契约）
    if level_source == "human":
        parts.append("基于人工等级")
    elif level_source == "ai":
        parts.append("基于AI等级（人工等级缺失）")
    return "｜".join(parts)


async def run_scoring_round(
    *, limit: int | None = None, notify: bool = True
) -> RoundResult:
    """执行一轮 ⑤ 隐患AI评分。"""
    from app.modules.safety.ai_hazard_scoring import compute_total
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    result = RoundResult(job_label="隐患AI评分轮询")
    client = SafetyBitableClient()
    records = await bitable_repo.search_pending_scoring(client, limit=limit)
    result.total = len(records)
    if not records:
        logger.info("⑤ 无待评分记录")
        return result

    logger.info("⑤ 待评分 %d 条（判据: 分类（AI）已填 ∧ 评分结果为空）", len(records))
    write_lock = bitable_repo.WRITE_LOCK
    semaphore = asyncio.Semaphore(config.write_concurrency())

    async def _worker(record: dict[str, Any]) -> None:
        record_id = record.get("record_id", "")
        if not record_id:
            return
        async with bitable_repo.record_lock(record_id) as acquired:
            if not acquired:
                result.skipped += 1
                logger.info("⑤ 跳过（记录锁被占用）: record_id=%s", record_id)
                return
            try:
                async with semaphore:
                    view = bitable_repo.to_view(record)
                    output = await _score_one(client, view)
                    total = compute_total(output)
                    note = _build_note(output, total, view.effective_level_source)

                async with write_lock:
                    ok = await bitable_repo.write_scoring(
                        client, record_id, total=total, note=note
                    )
                    if not ok:
                        raise RuntimeError("写回 Bitable 返回 False")

                result.succeeded += 1
                logger.info(
                    "⑤ 完成: record_id=%s score=%s band=%s hit=%s",
                    record_id, total, output.band.value, output.major_hazard.hit,
                )
            except Exception as exc:
                result.failed += 1
                result.failures.append(
                    {"record_id": record_id, "reason": f"{type(exc).__name__}: {exc}"[:200]}
                )
                logger.exception("⑤ 评分失败（不写列，下轮自动重试）: record_id=%s", record_id)

    await asyncio.gather(*(_worker(rec) for rec in records))

    logger.info(
        "⑤ 本轮结束: 总数=%d 成功=%d 失败=%d 跳过=%d",
        result.total, result.succeeded, result.failed, result.skipped,
    )
    if notify and len(result.failures) >= config.alert_min_failures():
        await notify_failures(
            result.job_label,
            failures=result.failures,
            total=result.total,
        )
    return result
