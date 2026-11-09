"""① 隐患AI分析轮询 — 直读多维表格，不落库。

链路：
    search(隐患分类（AI）isEmpty) → RAG 预检 → per-record 锁 → 下载缺陷图
      → 视觉AI + RAG → 结构化输出 + 枚举校验 + 输出质量闸门
      → 写回 Bitable（7 字段 + 督办等级）→ 释放锁

失败语义：**不写任何 AI 字段** → 下一轮仍命中同一判据 → 自动重试。
（对比旧路径：失败时把 ERROR 标记写进「隐患编号」，导致永久不再重试。）

A3 质量闸门（2026-11-05）：
- RAG 检索降级 / 零召回 → 本条直接失败，不调 AI、不写字段；
- 输出依据为空 / 命中占位文案 / 无法规引用 → 不写回，保持「隐患分类（AI）」
  为空以便 RAG 恢复后自动重试；失败带 category。

A5 失败治理（2026-11-05）：
- 失败 attempts 落 Redis 失败账本，按 1/3/9 轮退避，第 5 次失败进死信；
- 每轮只处理「到点该重试」的记录，未到点/已死信计入 deferred，不烧 AI；
- 告警只统计本轮**新增失败**与新死信，不再每轮重复刷同一批失败。

F1 基础设施失败免死信化（2026-11-05）：
- AI 端点欠费/鉴权/服务端/超时/连接/配置异常与 RAG 不可用同语义：**不计
  attempts、不进死信、不占退避**（故障恢复后记录立即可重试，不再等 7 天 TTL）；
- ``RoundResult`` 区分 ``infra_failed`` / ``non_infra_failed``，调度器只按非
  infra 失败累计连续失败轮数；
- 告警分路去重：RAG infra 用 ``INFRA_ALERT_KEY``、AI infra 用独立
  ``AI_INFRA_ALERT_KEY``，均 30 分钟一次；
- 失败分类优先读插件结构化 ``IdentificationError.category``，中文子串仅兜底。

F2 队列饥饿修复（2026-11-05）：
- 取数改为「全量取 + 逐条预过滤」：死信/退避记录不占 ``batch_limit`` 窗口，
  仅可执行记录进入本轮处理；死信 ≥ 窗口时输出高水位 warning。

C2 引用来源强约束（2026-11-06，P0-C）：
- 开关 ``SAFETY_HAZARD_CITATION_STRICT_ENABLED``（默认开、热生效）开启时，用本轮
  RAG chunks 构造 ``CitationEvidence`` 传给插件与输出质量闸门；
- 插件零可验证引用 → 分类 ``invalid_citation``（失败账本/告警可聚合）；
- 闸门兜底：零可验证 → 不写回；
- 识别成功/失败都把引用质量维度（来源/总数/可验证数/不可验证清单/chunk_ids）
  合并进最近一次 AI 审计行 ``extra``（无审计行 no-op，失败不影响业务）。

C5(F9) RAG 全局降级短路熔断（2026-11-06，P0-C）：
- 本轮连续 ``RAG_BREAKER_CONSECUTIVE_FAILURES``(3) 条记录因 ``retrieval_degraded``
  失败 → 熔断本轮剩余：worker 入口直接计入 ``deferred`` 并跳过（不检索、不调 AI、
  不计 attempts、不进死信）；
- 轮末打一条 warning（含熔断原因与失败计数）+ 只发一次告警（独立 Redis 去重
  key），``RoundResult.breaker_tripped`` 标记供调度/告警观察；
- 只影响本轮：下一次调用从 0 重新计数，RAG 恢复后自动恢复正常。

编号：若「隐患编号」为空或以 ERROR: 开头 → 重新分配 HZ-YYYYMMDD-NNN 并覆盖。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.modules.safety.service.hazard_direct import (
    bitable_repo,
    config,
    failure_ledger,
    quality_gate,
)
from app.modules.safety.service.hazard_direct.alert import notify_admin, notify_failures
from app.modules.safety.service.hazard_direct.failure_ledger import (
    AI_INFRA_ALERT_KEY,
    DEAD_LETTERS_KEY,
    RAG_BREAKER_ALERT_KEY,
    format_dead_letter_lines,
)
from app.modules.safety.service.hazard_direct.field_authority import (
    HAZARD_CATEGORY_MAP,
    HAZARD_LEVEL_MAP,
    HAZARD_TYPE_MAP,
)
from app.modules.safety.service.hazard_direct.round_result import RoundResult

if TYPE_CHECKING:
    from app.modules.safety.knowledge.retriever import KnowledgeContext
    from app.modules.safety.service.hazard_direct.retrieval_query import RetrievalMeta

logger = logging.getLogger(__name__)

# 进程级写回锁：Bitable 单表写不支持并发（1254291 / 1254607）。
# 2026-11-05 收编到 bitable_repo.WRITE_LOCK（①识别/⑤评分共享同一把锁才真正串行）。
_WRITE_LOCK = bitable_repo.WRITE_LOCK

# 死信上限（只在告警文案展示，模块级常量避免把 failure_ledger 模块整体替换后失联）
_MAX_ATTEMPTS = failure_ledger.MAX_ATTEMPTS

# AI 输出合法值集从字段权威单一事实源派生（T01/D2，防手抄漂移）
VALID_TYPES = frozenset(HAZARD_TYPE_MAP.values())
VALID_LEVELS = frozenset(HAZARD_LEVEL_MAP.values())
VALID_CATEGORIES = frozenset(HAZARD_CATEGORY_MAP.values())


class _WritebackError(Exception):
    """写回 Bitable 失败（调用方据此归类 writeback_error）。"""


# RAG 基础设施失败分类：属「知识库/RAG 不可用」而非记录自身失败。
# 不累计 attempts、不进死信 —— RAG 恢复后记录仍在轮询队列、无退避可直接重试。
# 注：no_chunks 属数据性零召回（R1-3），按记录级失败计 attempts/死信，不在此集合。
RAG_INFRA_CATEGORIES = frozenset({quality_gate.RETRIEVAL_DEGRADED})

# C5(F9) RAG 全局降级短路熔断：本轮连续 N 条 retrieval_degraded 失败 → 熔断本轮
# 剩余记录（worker 入口直接计入 deferred，不检索/不调 AI、不计 attempts/不进死信）。
# 只影响本轮：下一次调用从 0 重新计数，RAG 恢复后自动恢复正常。
RAG_BREAKER_CONSECUTIVE_FAILURES = 3
# 熔断告警去重 key 常量收归 failure_ledger（与 INFRA/AI_INFRA 同区），此处 import。

# AI 基础设施失败分类：AI 端点欠费/鉴权/服务端/超时/连接/配置异常。
# 与 RAG infra 同语义：**不计 attempts、不进死信、不占退避**（F1）。
AI_INFRA_CATEGORIES = frozenset(
    {
        "api_auth",
        "api_quota",
        "api_server",
        "api_timeout",
        "api_connect",
        "api_config",
    }
)

# 全部基础设施失败分类：不累计 attempts / 不进死信 / 不占退避
_INFRA_FAILURE_CATEGORIES = AI_INFRA_CATEGORIES | RAG_INFRA_CATEGORIES


async def _load_knowledge_context(
    session: Any, description: str
) -> tuple[KnowledgeContext | None, RetrievalMeta | None]:
    """RAG 法规检索（知识库仍在平台数据库，与隐患记录无关）。

    P1-1 R1 多路检索：开关开（默认）→ ``build_retrieval_queries`` 产出
    清洗主路 + 关键词路（+ 可选 LLM 改写路），逐路 ``retrieve``（每路
    CANDIDATES 候选）后客户端 RRF 合并取 TOP_K；主路 degradation 决定
    合并结果（闸门输入语义不变），辅路异常只降辅路贡献。开关关 → 原单路
    路径（描述原文 + TOP_K，热回滚）。

    返回 ``(context, meta)``：context 供 RAG 预检与 prompt 注入（检索异常
    → ``(None, None)``，由质量闸门判失败）；meta 为检索可观测维度
    （``retrieval_query.RetrievalMeta``，审计 extra 用）。
    """
    from app.modules.safety.service.hazard_direct import retrieval_query

    try:
        from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever

        retriever = SafetyKnowledgeRetriever(session)

        if not retrieval_query.multi_query_enabled():
            context = await retriever.retrieve(
                description=description,
                target_chunks=retrieval_query.retrieval_top_k(),
            )
            logger.info(
                "① RAG 检索完成: chunks=%d degradation=%s len=%d",
                len(context.chunks), context.degradation, len(context.markdown),
            )
            return context, retrieval_query.single_route_meta(description, context)

        plan = retrieval_query.build_retrieval_queries(description)
        queries = list(plan.queries) or [description]
        if retrieval_query.llm_rewrite_enabled():
            rewritten = await retrieval_query.llm_rewrite_query(plan.primary)
            if rewritten and rewritten not in queries:
                queries.append(rewritten)

        contexts: list[KnowledgeContext] = []
        for index, query in enumerate(queries):
            try:
                contexts.append(
                    await retriever.retrieve(
                        description=query,
                        target_chunks=retrieval_query.retrieval_candidates(),
                    )
                )
            except Exception:
                if index == 0:
                    raise  # 主路失败 = 整体检索失败（外层收敛 None，闸门判失败）
                logger.warning(
                    "① 辅路检索失败（跳过该路，不影响主路）: query=%r",
                    query[:60], exc_info=True,
                )
        if not contexts:
            return None, None

        merged = retrieval_query.merge_route_contexts(
            contexts, top_k=retrieval_query.retrieval_top_k()
        )
        meta = retrieval_query.build_retrieval_meta(
            plan, merged, queries=tuple(queries)
        )
        logger.info(
            "① RAG 多路检索完成: routes=%d/%d chunks=%d degradation=%s len=%d",
            len(contexts), len(queries), len(merged.chunks),
            merged.degradation, len(merged.markdown),
        )
        return merged, meta
    except Exception:
        logger.warning("① RAG 法规检索失败", exc_info=True)
        return None, None


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


async def _load_context_for_view(
    view: bitable_repo.HazardView,
) -> tuple[KnowledgeContext | None, RetrievalMeta | None]:
    """用独立 session 做 RAG 检索（异常已在 _load_knowledge_context 内收敛为 None）。"""
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        return await _load_knowledge_context(session, view.description)


async def _record_citation_quality(
    plugin: Any,
    evidence: Any,
    *,
    strict: bool,
    retrieval_meta: Any = None,
) -> None:
    """把引用质量 + 检索维度合并进最近一次 AI 审计行 extra（C2/R5，best-effort）。

    - 无审计行 / 无报告时 mark_audit_extra 内部 no-op；
    - ``retrieval_meta``（``retrieval_query.RetrievalMeta``）非空时并入
      检索可观测字段（retrieval_query/multi_query_count/rewrite_hit/docs）；
    - 任何异常只告警，绝不影响识别/写回业务。
    """
    try:
        from app.modules.safety.ai_audit import audited_client
        from app.modules.safety.service.hazard_direct import retrieval_query

        report = getattr(plugin, "last_citation_report", None)
        fields: dict[str, Any] = quality_gate.citation_audit_fields(
            report, evidence, strict=strict
        )
        fields.update(retrieval_query.retrieval_audit_fields(retrieval_meta))
        await audited_client.mark_audit_extra(fields)
    except Exception:  # noqa: BLE001 — 审计质量维度失败不影响业务
        logger.warning("引用质量维度审计回写失败（不影响业务）", exc_info=True)


async def _identify_one(
    client: Any, view: bitable_repo.HazardView, *, round_id: str | None = None
) -> dict[str, Any]:
    """调用 AI 识别插件，返回结构化输出 dict（不做任何写回）。

    质量闸门顺序（A3）：
    1. RAG 预检 —— 降级/零召回直接抛 ``QualityGateError``，**不建 AI 客户端、不调 AI**；
    2. 只下载缺陷图（① 不用整改后图，下载量 -44%），图片编码放线程；
    3. AI 客户端用进程级单例（不再逐条 close），strict_mode=True；
    4. 输出枚举校验后走输出质量闸门（空依据/占位/无引用/引用零可验证
       ``invalid_citation`` → 失败不写回）。
    """
    from app.modules.safety.ai_hazard_identification import (
        AIHazardIdentifier,
        HazardIdentificationInput,
        PluginConfig,
    )
    from app.modules.safety.ai_hazard_identification.citation_evidence import (
        CitationEvidence,
    )
    from app.modules.safety.service.config import get_ai_service

    # ── 1. RAG 预检：失败即抛，不建客户端、不调 AI、不下载 ──
    # R5：预检失败发生在 ai_audit_scope 之前（无审计行可挂检索维度），
    # 检索 query/docs 维度进 warning 日志兜底，保证失败记录仍可按检索归因。
    knowledge_context, retrieval_meta = await _load_context_for_view(view)
    try:
        quality_gate.ensure_knowledge(knowledge_context)
    except quality_gate.QualityGateError:
        if retrieval_meta is not None:
            logger.warning(
                "① RAG 预检失败（检索维度归因）: queries=%s rewrite_hit=%s docs=%s",
                list(retrieval_meta.queries), retrieval_meta.rewrite_hit,
                list(retrieval_meta.docs[:5]),
            )
        raise
    assert knowledge_context is not None  # ensure_knowledge 已排除 None（供 mypy 收窄）
    knowledge_text = knowledge_context.markdown or None

    # C2 引用来源强约束：开关开 → 用本轮 chunks 构造证据（零可验证不写回）；
    # 开关关 → evidence=None，插件/闸门回退 P0-A 旧行为（可热回滚）。
    citation_strict = quality_gate.citation_strict_enabled()
    citation_evidence = (
        CitationEvidence.from_chunks(knowledge_context.chunks)
        if citation_strict
        else None
    )

    # ── 2. 只下缺陷图；图片编码/落盘走线程，不阻塞事件循环 ──
    photos = await bitable_repo.download_photos(
        client,
        view.raw,
        record_id=view.record_id,
        include_rectification=False,
    )
    image_uris = await asyncio.to_thread(
        bitable_repo.photos_to_data_uris, photos.get("defect", [])
    )

    input_data = HazardIdentificationInput(
        hazard_no=view.hazard_no or view.record_id[:8],
        description=view.description or "无描述",
        department=view.department or "",
        location=view.department or "",
        discovered_by_name=bitable_repo.f_person(view.raw, bitable_repo.F_INSPECTOR),
        discovered_at=view.discovered_at,
        defect_photos=image_uris,
    )

    # ── 3. AI 客户端单例（进程级生命周期；不在此处 close）──
    ai_service = get_ai_service("vision" if image_uris else "text")
    plugin_config = PluginConfig(
        temperature=0.05,
        strict_mode=True,
        enable_vision=bool(image_uris),
        enable_knowledge=bool(knowledge_text),
    )
    from app.modules.safety.ai_audit import ai_audit_scope

    with ai_audit_scope(
        scenario="hazard_identification",
        resource_type="hazard",
        channel="system",
        extra={
            "bitable_record_id": view.record_id,
            "source": "bitable_direct",
            "round_id": round_id,
        },
    ):
        plugin = AIHazardIdentifier(
            ai_service,
            plugin_config,
            knowledge_context=knowledge_text,
            citation_evidence=citation_evidence,
        )
        try:
            output = await plugin.identify(input_data)
        except Exception:
            # 失败也留引用质量+检索维度观测（否则无法定位失败记录的依据来源）
            await _record_citation_quality(
                plugin,
                citation_evidence,
                strict=citation_strict,
                retrieval_meta=retrieval_meta,
            )
            raise

    result = {
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
    # ── 4. 枚举校验 → 输出质量闸门（写回前最后一道）──
    # M4 验收修复：_validate 枚举失败也必须回写引用质量审计 extra（失败可观测）。
    try:
        _validate(result)
        quality_gate.ensure_output(result, evidence=citation_evidence)
    finally:
        await _record_citation_quality(
            plugin,
            citation_evidence,
            strict=citation_strict,
            retrieval_meta=retrieval_meta,
        )
    return result


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """异常链展平（``__cause__`` / ``__context__``，防环）。"""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _infra_category_from_exception(exc: BaseException) -> str | None:
    """单个异常节点 → AI 基础设施失败分类（非基础设施返回 None）。

    精确类型优先：httpx 状态码/超时/连接；配置类看安全模块的
    ``ScenarioDisabledError``（场景熔断叶子异常，**只继承 Exception、不是
    RuntimeError**，由 ``ai_audit.audited_client`` 在调用前抛出）与消息含
    「未配置」/「配置」/``SAFETY_AI_`` 的 ``RuntimeError``（中文子串仅兜底，
    spec §F1）。
    """
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return "api_auth"
        if status in (402, 429):
            return "api_quota"
        if 500 <= status <= 599:
            return "api_server"
        return None
    if isinstance(exc, httpx.TimeoutException):
        return "api_timeout"
    if isinstance(exc, httpx.ConnectError):
        return "api_connect"

    # 延迟 import：安全模块 ai_config.exceptions 是叶子模块（零业务 import），
    # ① 链路实际抛出的就是它（场景熔断在 ai_audit.audited_client 调用前拦截）
    from app.modules.safety.ai_config.exceptions import ScenarioDisabledError

    if isinstance(exc, ScenarioDisabledError):
        return "api_config"
    if isinstance(exc, RuntimeError):
        message = str(exc)
        if "未配置" in message or "配置" in message or "SAFETY_AI_" in message:
            return "api_config"
    return None


def _categorize_failure(exc: BaseException) -> str:
    """异常 → 失败分类（spec §F1 / F11，优先级从高到低）。

    1. ``QualityGateError`` → 自带 category；
    2. ``_WritebackError`` → ``writeback_error``；
    3. ``IdentificationError.category`` 非空 → **结构化优先**（F11）；
    4. 异常链基础设施失败（httpx / ScenarioDisabled / 配置类 RuntimeError）；
    5. 链上 ``AIOutputError`` → ``json_invalid``（兼容未包 category 的旧路径）；
    6. ``IdentificationError`` 中文子串兜底（``validation_failed`` / ``json_invalid``）；
    7. 其余 → ``api_error``。
    """
    if isinstance(exc, quality_gate.QualityGateError):
        return exc.category
    if isinstance(exc, _WritebackError):
        return "writeback_error"

    from app.modules.safety.ai_hazard_identification import IdentificationError

    # F11：插件/上层显式给出的结构化分类优先，中文子串不再参与判定
    if isinstance(exc, IdentificationError) and exc.category is not None:
        return exc.category

    chain = _exception_chain(exc)

    # 基础设施失败：精确异常类型（httpx 状态/超时/连接、场景熔断、配置类）
    for current in chain:
        infra = _infra_category_from_exception(current)
        if infra is not None:
            return infra

    # 兼容未包 category 的旧路径：链上 AIOutputError → json_invalid
    from app.platform.integrations.ai.client import AIOutputError

    if any(isinstance(current, AIOutputError) for current in chain):
        return "json_invalid"

    # 中文子串仅兜底（无结构化 category 的旧调用）
    if isinstance(exc, IdentificationError):
        message = str(exc)
        if "验证失败" in message or "校验" in message:
            return "validation_failed"
        if "解析失败" in message:
            return "json_invalid"
    return "api_error"


def _format_category_counts(failures: list[dict[str, str]]) -> str:
    """失败分类计数摘要（告警文案用）。"""
    counts: dict[str, int] = {}
    for item in failures:
        category = item.get("category") or "unknown"
        counts[category] = counts.get(category, 0) + 1
    return "分类计数：" + ", ".join(
        f"{category}={count}" for category, count in sorted(counts.items())
    )


def _format_dead_letter_alert(dead_letters: list[dict[str, Any]]) -> str:
    """新死信告警文案（record_id / 分类 / 次数 / 最近原因）。"""
    lines = [
        f"**隐患AI识别** 本轮新增死信 **{len(dead_letters)}** 条（已达 "
        f"{_MAX_ATTEMPTS} 次失败，不再自动重试，请人工处理）",
        f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "死信明细（最多 20 条）：",
    ]
    for item in dead_letters[:20]:
        lines.append(
            f"• `{item.get('record_id', '')}` [{item.get('category', 'unknown')}] "
            f"第 {item.get('attempts', '?')} 次 · {item.get('reason', '')}"
        )
    return "\n".join(lines)


def _new_round_id() -> str:
    """每轮唯一 round_id（写入该轮所有 AI 审计 extra，供按轮归因）。"""
    return f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"


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

    result = RoundResult(job_label="隐患AI分析轮询")
    round_id = _new_round_id()
    round_seq = await failure_ledger.next_round_seq()

    # F2 取数预过滤：死信/退避记录不占 batch_limit 窗口（改造前先截断再过滤，
    # 死信 ≥ batch_limit 时新记录永久饥饿）。计数只用于 deferred 与日志。
    queue_stats = {"backoff": 0, "dead": 0}

    async def _keep_record(record: dict[str, Any]) -> bool:
        record_id = record.get("record_id", "")
        if not record_id:
            return False
        status = await failure_ledger.retry_status(record_id, round_seq)
        if status == "ok":
            return True
        queue_stats[status] += 1
        return False

    client = SafetyBitableClient()
    records = await bitable_repo.search_pending_ai(
        client, limit=limit, keep=_keep_record
    )
    # F2 后 total=本轮可执行窗口条数（不含预过滤掉的退避/死信），故 deferred 可
    # 大于 total；正常路径（无死信/退避）与原语义一致（前 batch_limit 条）。
    result.total = len(records)
    window = limit or config.batch_limit()
    logger.info(
        "① 取数预过滤: 可执行=%d 退避中=%d 死信=%d（窗口=%d）",
        len(records), queue_stats["backoff"], queue_stats["dead"], window,
    )
    if queue_stats["dead"] >= window:
        logger.warning(
            "① 队列高水位：本轮预过滤死信 %d 条 ≥ 窗口 %d（死信清单 key=%s），"
            "新记录已按预过滤正常处理，但死信长期占位应尽快人工清理",
            queue_stats["dead"], window, DEAD_LETTERS_KEY,
        )
    # 未到重试点 / 已死信而跳过、不调 AI 的条数（语义同 _worker 内 deferred）
    result.deferred += queue_stats["backoff"] + queue_stats["dead"]
    if not records:
        logger.info("① 无待分析记录")
        return result

    logger.info(
        "① 待分析 %d 条（判据: 隐患分类（AI）为空）round_id=%s round_seq=%d",
        len(records), round_id, round_seq,
    )
    allocator = bitable_repo.HazardNoAllocator(client)
    write_lock = _WRITE_LOCK
    semaphore = asyncio.Semaphore(config.write_concurrency())

    # 告警收敛：只收集「本轮首次失败」与新死信（旧失败不重复告警）；
    # 基础设施失败（RAG/AI 不可用）按路分别聚合，走 Redis 去重告警且不进失败账本。
    new_failures: list[dict[str, str]] = []
    new_dead_letters: list[dict[str, Any]] = []
    rag_infra_failures: list[dict[str, str]] = []
    ai_infra_failures: list[dict[str, str]] = []

    # C5(F9) RAG 全局降级熔断状态（仅本轮有效）：连续 retrieval_degraded 计数、
    # 是否已熔断、熔断后在 worker 入口跳过的记录数（计入 deferred）。
    rag_consecutive_failures = 0
    rag_breaker_tripped = False
    rag_breaker_skipped = 0

    async def _worker(record: dict[str, Any]) -> None:
        nonlocal rag_consecutive_failures, rag_breaker_tripped
        nonlocal rag_breaker_skipped
        record_id = record.get("record_id", "")
        if not record_id:
            return
        # C5(F9)：RAG 全局降级已熔断 → 本轮剩余记录在入口直接跳过：
        # 不检索、不调 AI、不计 attempts、不进死信（恢复后下一轮自动重试）。
        if rag_breaker_tripped:
            rag_breaker_skipped += 1
            result.deferred += 1
            logger.info(
                "① RAG 全局降级已熔断本轮，跳过剩余记录（不检索/不调 AI）: "
                "record_id=%s",
                record_id,
            )
            return
        # 失败治理：未到重试轮次 / 已死信 → 不烧 AI（deferred），不计失败
        if not await failure_ledger.should_retry(record_id, round_seq):
            result.deferred += 1
            logger.info("① 延后（退避中或已死信，不调 AI）: record_id=%s", record_id)
            return
        async with bitable_repo.record_lock(record_id) as acquired:
            if not acquired:
                result.skipped += 1
                logger.info("① 跳过（记录锁被占用）: record_id=%s", record_id)
                return
            try:
                async with semaphore:
                    # C5(F9) 并发短路（T6-fix）：gather 一次性调度全部 worker，而
                    # 入口检查在各 worker 首个真实 await 之前，并发下必然全部先
                    # 通过；因此真正检索/调 AI 前（已历经 should_retry/record_lock
                    # 等 await）必须再检查一次，降级期间排队/在途记录才能短路。
                    if rag_breaker_tripped:
                        rag_breaker_skipped += 1
                        result.deferred += 1
                        logger.info(
                            "① RAG 全局降级已熔断本轮，跳过排队记录"
                            "（不检索/不调 AI）: record_id=%s",
                            record_id,
                        )
                        return
                    view = bitable_repo.to_view(record)
                    output = await _identify_one(client, view, round_id=round_id)

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
                        raise _WritebackError("写回 Bitable 返回 False")

                await failure_ledger.record_success(record_id)
                result.succeeded += 1
                # C5(F9)：成功记录打断 RAG 连续失败计数（已熔断后保留计数供轮末日志）
                if not rag_breaker_tripped:
                    rag_consecutive_failures = 0
                logger.info(
                    "① 完成: record_id=%s 分类=%s 级别=%s 类别=%s round_id=%s",
                    record_id, output.get("hazard_type"),
                    output.get("hazard_level"), output.get("hazard_category"),
                    round_id,
                )
            except Exception as exc:
                category = _categorize_failure(exc)
                reason = f"{type(exc).__name__}: {exc}"[:200]
                failure = {
                    "record_id": record_id,
                    "category": category,
                    "reason": reason,
                }
                result.failed += 1
                result.failures.append(failure)
                if category in _INFRA_FAILURE_CATEGORIES:
                    # 基础设施失败：可观测（failed/failures/infra_failed）但
                    # **不累计 attempts、不进死信** —— 故障恢复后记录可立即重试。
                    result.infra_failed += 1
                    result.infra_failures.append(failure)
                    if category in AI_INFRA_CATEGORIES:
                        ai_infra_failures.append(failure)
                        logger.warning(
                            "① AI 基础设施失败（不累计 attempts，端点恢复后可重试）: "
                            "record_id=%s category=%s",
                            record_id, category,
                        )
                    else:
                        rag_infra_failures.append(failure)
                        logger.warning(
                            "① RAG 基础设施失败（不累计 attempts，RAG 恢复后可重试）: "
                            "record_id=%s category=%s",
                            record_id, category,
                        )
                else:
                    state = await failure_ledger.record_failure(
                        record_id, round_seq, category, reason
                    )
                    if state.is_new:
                        new_failures.append(
                            {
                                "record_id": record_id,
                                "category": category,
                                "reason": reason,
                            }
                        )
                    if state.dead:
                        new_dead_letters.append(
                            {
                                "record_id": record_id,
                                "category": category,
                                "attempts": state.attempts,
                                "reason": reason,
                            }
                        )
                    logger.exception(
                        "① 处理失败（不写字段，按退避重试）: record_id=%s category=%s",
                        record_id, category,
                    )

                # C5(F9)：连续 retrieval_degraded 计数（成功/其它失败分类重置）；
                # 达到阈值 → 熔断本轮剩余记录（已在执行中的任务不取消，只跳过后继）。
                if category == quality_gate.RETRIEVAL_DEGRADED:
                    rag_consecutive_failures += 1
                    if (
                        not rag_breaker_tripped
                        and rag_consecutive_failures
                        >= RAG_BREAKER_CONSECUTIVE_FAILURES
                    ):
                        rag_breaker_tripped = True
                        result.breaker_tripped = True
                        logger.warning(
                            "① RAG 全局降级熔断本轮：连续 %d 条 retrieval_degraded "
                            "失败（本轮 failed=%d）→ 跳过剩余记录（不检索/不调 AI、"
                            "不计 attempts/不进死信），RAG 恢复后下一轮自动重试",
                            rag_consecutive_failures, result.failed,
                        )
                else:
                    # 已熔断后保留计数（供轮末日志/告警展示本次连续降级规模）
                    if not rag_breaker_tripped:
                        rag_consecutive_failures = 0

    await asyncio.gather(*(_worker(rec) for rec in records))

    result.breaker_tripped = rag_breaker_tripped
    dead_letters = await failure_ledger.list_dead_letters(limit=100)
    logger.info(
        "① 本轮结束: 总数=%d 成功=%d 失败=%d 跳过=%d 延后=%d 新增失败=%d "
        "新死信=%d 累计死信=%d 基础设施失败(RAG=%d/AI=%d) 熔断=%s round_id=%s",
        result.total, result.succeeded, result.failed, result.skipped,
        result.deferred, len(new_failures), len(new_dead_letters),
        len(dead_letters), len(rag_infra_failures), len(ai_infra_failures),
        "是" if rag_breaker_tripped else "否", round_id,
    )
    # C5(F9) 熔断轮：轮末单条 warning（含熔断原因与失败计数），便于日志排查。
    if rag_breaker_tripped:
        logger.warning(
            "① RAG 全局降级熔断本轮：连续 %d 条 retrieval_degraded 失败（failed=%d），"
            "跳过剩余 %d 条（deferred=%d，不检索/不调 AI、不计 attempts/不进死信）；"
            "仅影响本轮，RAG 恢复后下一轮自动重试 round_id=%s",
            rag_consecutive_failures, result.failed, rag_breaker_skipped,
            result.deferred, round_id,
        )
    # F8 死信可观测：轮末打印 top-N 明细（不再只有累计数量），人工排查无需进 Redis。
    for dead_letter_line in format_dead_letter_lines(dead_letters, limit=10):
        logger.info("① 死信明细: %s", dead_letter_line)
    if notify:
        # 告警收敛：阈值只看本轮新增失败（同一批失败不会每轮重复告警）
        if new_failures and len(new_failures) >= config.alert_min_failures():
            await notify_failures(
                result.job_label,
                failures=new_failures,
                total=result.total,
                error=_format_category_counts(new_failures),
            )
        if new_dead_letters:
            await notify_admin(
                "⚠️ 隐患AI识别死信告警", _format_dead_letter_alert(new_dead_letters)
            )
        # C5(F9) RAG 全局降级熔断：轮级事件优先——只发一次熔断告警（独立去重
        # key），文案含熔断原因 + 分类计数；该告警取代同轮常规单条 RAG infra
        # 告警，避免故障期间一轮双发（仍然 30 分钟窗口内只报一次）。
        if rag_breaker_tripped:
            if await failure_ledger.should_emit_infra_alert(
                round_seq, key=RAG_BREAKER_ALERT_KEY
            ):
                await notify_failures(
                    result.job_label,
                    failures=rag_infra_failures,
                    total=result.total,
                    error=(
                        f"RAG 全局降级熔断本轮：连续 {rag_consecutive_failures} 条 "
                        f"retrieval_degraded 失败（本轮 failed={result.failed}，"
                        f"跳过剩余 {rag_breaker_skipped} 条）；不累计 attempts、"
                        "不进死信，RAG 恢复后下一轮自动重试（30 分钟内只告警一次）："
                        + _format_category_counts(rag_infra_failures)
                    ),
                )
        # RAG 基础设施失败（未熔断的零散降级）：不累计 attempts/不进死信，但降级
        # 期间仍需可观测；用 Redis SET NX EX 去重（默认 30 分钟窗口），避免刷屏。
        elif (
            rag_infra_failures
            and len(rag_infra_failures) >= config.alert_min_failures()
            and await failure_ledger.should_emit_infra_alert(round_seq)
        ):
            await notify_failures(
                result.job_label,
                failures=rag_infra_failures,
                total=result.total,
                error=(
                    "RAG 基础设施失败（不累计 attempts、不进死信，恢复后可直接重试；"
                    "30 分钟内只告警一次）：" + _format_category_counts(rag_infra_failures)
                ),
            )
        # AI 基础设施失败：独立去重 key，与 RAG 路互不吞并（F1-3）。
        if (
            ai_infra_failures
            and len(ai_infra_failures) >= config.alert_min_failures()
            and await failure_ledger.should_emit_infra_alert(
                round_seq, key=AI_INFRA_ALERT_KEY
            )
        ):
            await notify_failures(
                result.job_label,
                failures=ai_infra_failures,
                total=result.total,
                error=(
                    "AI 基础设施失败（不累计 attempts、不进死信，恢复后可直接重试；"
                    "30 分钟内只告警一次）：" + _format_category_counts(ai_infra_failures)
                ),
            )
    return result
