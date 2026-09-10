"""① 隐患AI分析轮询 — 直读多维表格，不落库。

链路：
    search(隐患分类（AI）isEmpty) → per-record 锁 → 下载缺陷图 → 视觉AI + RAG
      → 结构化输出 + 枚举校验 → 写回 Bitable（7 字段 + 督办等级）→ 释放锁

失败语义：**不写任何 AI 字段** → 下一轮仍命中同一判据 → 自动重试。
（对比旧路径：失败时把 ERROR 标记写进「隐患编号」，导致永久不再重试。）

编号：若「隐患编号」为空或以 ERROR: 开头 → 重新分配 HZ-YYYYMMDD-NNN 并覆盖。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.modules.safety.service.hazard_direct import bitable_repo, config
from app.modules.safety.service.hazard_direct.alert import notify_failures

logger = logging.getLogger(__name__)

# 进程级写回锁：Bitable 单表写不支持并发（1254291 / 1254607）。
# 放在模块级（而非每轮新建）——手动触发与定时轮询可能并发，共享同一把锁才真正串行。
_WRITE_LOCK = asyncio.Lock()

VALID_TYPES = {
    "unsafe_action",
    "unsafe_condition",
    "environmental",
    "management_defect",
}
VALID_LEVELS = {"general", "serious", "major"}
VALID_CATEGORIES = {
    "equipment", "hazardous_storage", "emergency_mgmt", "instrument_electrical",
    "lightning_antistatic", "occupational_health", "violation_operation", "six_s",
    "label_signage", "process_mgmt", "contractor_defect", "documentation",
    "special_operation",
}


@dataclass
class RoundResult:
    """单轮执行结果。"""

    job_label: str = "隐患AI分析轮询"
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_label": self.job_label,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "failures": self.failures,
        }


async def _load_knowledge_context(session: Any, description: str) -> str | None:
    """RAG 法规检索（知识库仍在平台数据库，与隐患记录无关）。"""
    try:
        from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever

        retriever = SafetyKnowledgeRetriever(session)
        context = await retriever.retrieve(description=description, target_chunks=8)
        text = retriever.build_injection_context(context)
        logger.info(
            "① RAG 检索完成: chunks=%d degradation=%s len=%d",
            len(context.chunks), context.degradation, len(text),
        )
        return text
    except Exception:
        logger.warning("① RAG 法规检索失败，继续不使用知识增强", exc_info=True)
        return None


def _build_advice_text(output: dict[str, Any]) -> str:
    """整改建议 → 可读中文文本（与既有映射一致）。"""
    suggestion = output.get("rectification_suggestion")
    if not isinstance(suggestion, dict):
        return ""
    parts: list[str] = []
    if suggestion.get("corrective"):
        parts.append(f"【整改措施】{suggestion['corrective']}")
    if suggestion.get("preventive"):
        parts.append(f"【预防措施】{suggestion['preventive']}")
    return "\n\n".join(parts)


async def _identify_one(
    client: Any, view: bitable_repo.HazardView
) -> dict[str, Any]:
    """调用 AI 识别插件，返回结构化输出 dict（不做任何写回）。"""
    from app.modules.safety.ai_hazard_identification import (
        AIHazardIdentifier,
        HazardIdentificationInput,
        PluginConfig,
    )
    from app.modules.safety.service.config import create_ai_service

    photos = await bitable_repo.download_photos(
        client, view.raw, record_id=view.record_id
    )
    image_uris = bitable_repo.photos_to_data_uris(photos.get("defect", []))

    input_data = HazardIdentificationInput(
        hazard_no=view.hazard_no or view.record_id[:8],
        description=view.description or "无描述",
        department=view.department or "",
        location=view.department or "",
        discovered_by_name=bitable_repo.f_person(view.raw, bitable_repo.F_INSPECTOR),
        discovered_at=view.discovered_at,
        defect_photos=image_uris,
    )

    ai_service = create_ai_service("vision" if image_uris else "text")
    try:
        knowledge_context = None
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            knowledge_context = await _load_knowledge_context(session, view.description)

        plugin_config = PluginConfig(
            temperature=0.05,
            strict_mode=False,
            enable_vision=bool(image_uris),
            enable_knowledge=bool(knowledge_context),
        )
        from app.modules.safety.ai_audit import ai_audit_scope

        with ai_audit_scope(
            scenario="hazard_identification",
            resource_type="hazard",
            channel="system",
            extra={"bitable_record_id": view.record_id, "source": "bitable_direct"},
        ):
            plugin = AIHazardIdentifier(
                ai_service, plugin_config, knowledge_context=knowledge_context
            )
            output = await plugin.identify(input_data)

        return {
            "key_defect": output.key_defect,
            "hazard_type": output.hazard_type.value,
            "hazard_category": output.hazard_category.value,
            "hazard_level": output.hazard_level.value,
            "major_hazard_basis": output.major_hazard_basis,
            "defect_substance": output.defect_substance.value,
            "defect_substance_reasoning": output.defect_substance_reasoning,
            "rectification_suggestion": {
                "corrective": output.rectification_suggestion.corrective,
                "preventive": output.rectification_suggestion.preventive,
            },
        }
    finally:
        await ai_service.close()


def _validate(output: dict[str, Any]) -> dict[str, Any]:
    """枚举校验：非法值直接丢弃（避免写脏 Bitable 选项）。"""
    for key, allowed in (
        ("hazard_type", VALID_TYPES),
        ("hazard_level", VALID_LEVELS),
        ("hazard_category", VALID_CATEGORIES),
    ):
        if output.get(key) and output[key] not in allowed:
            logger.warning("① AI 输出非法 %s=%s，丢弃", key, output[key])
            output[key] = None
    return output


def _supervision_label(view: bitable_repo.HazardView) -> str | None:
    """按现有规则计算督办等级标签（不依赖复核状态）。"""
    from app.modules.safety.feishu.bitable_handler import SUPERVISION_LEVEL_REVERSE
    from app.modules.safety.service.hazard_supervision import (
        calculate_supervision_level,
    )

    level = calculate_supervision_level(view)  # type: ignore[arg-type]
    return SUPERVISION_LEVEL_REVERSE.get(level, level) if level else None


async def run_ai_analysis_round(
    *, limit: int | None = None, notify: bool = True
) -> RoundResult:
    """执行一轮 ① 隐患AI分析。"""
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    result = RoundResult()
    client = SafetyBitableClient()
    records = await bitable_repo.search_pending_ai(client, limit=limit)
    result.total = len(records)
    if not records:
        logger.info("① 无待分析记录")
        return result

    logger.info("① 待分析 %d 条（判据: 隐患分类（AI）为空）", len(records))
    allocator = bitable_repo.HazardNoAllocator(client)
    write_lock = _WRITE_LOCK
    semaphore = asyncio.Semaphore(config.write_concurrency())

    async def _worker(record: dict[str, Any]) -> None:
        record_id = record.get("record_id", "")
        if not record_id:
            return
        async with bitable_repo.record_lock(record_id) as acquired:
            if not acquired:
                result.skipped += 1
                logger.info("① 跳过（记录锁被占用）: record_id=%s", record_id)
                return
            try:
                async with semaphore:
                    view = bitable_repo.to_view(record)
                    output = _validate(await _identify_one(client, view))

                async with write_lock:
                    hazard_no = None
                    if bitable_repo.is_placeholder_no(view.hazard_no):
                        hazard_no = await allocator.next_no()
                        logger.info(
                            "① 分配编号: record_id=%s %s → %s",
                            record_id, view.hazard_no or "(空)", hazard_no,
                        )
                    ok = await bitable_repo.write_ai_analysis(
                        client,
                        record_id,
                        hazard_no=hazard_no,
                        output={**output, "advice_text": _build_advice_text(output)},
                        supervision_label=_supervision_label(view),
                    )
                    if not ok:
                        raise RuntimeError("写回 Bitable 返回 False")

                result.succeeded += 1
                logger.info(
                    "① 完成: record_id=%s 分类=%s 级别=%s 类别=%s",
                    record_id, output.get("hazard_type"),
                    output.get("hazard_level"), output.get("hazard_category"),
                )
            except Exception as exc:
                result.failed += 1
                result.failures.append(
                    {"record_id": record_id, "reason": f"{type(exc).__name__}: {exc}"[:200]}
                )
                logger.exception("① 处理失败（不写字段，下轮自动重试）: record_id=%s", record_id)

    await asyncio.gather(*(_worker(rec) for rec in records))

    logger.info(
        "① 本轮结束: 总数=%d 成功=%d 失败=%d 跳过=%d",
        result.total, result.succeeded, result.failed, result.skipped,
    )
    if notify and len(result.failures) >= config.alert_min_failures():
        await notify_failures(
            result.job_label,
            failures=result.failures,
            total=result.total,
        )
    return result
