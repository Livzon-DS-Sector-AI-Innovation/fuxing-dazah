"""P1-3 —— 隐患AI识别「例外复核员」（observe 期）。

设计定位（docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md §4.3 方案B）：
主链保持确定性单次调用；**例外条目**（死信 / 人工指定）交复核员多步补检，
产出结构化复核报告。observe 期铁律：

- **绝不写回任何 Bitable 列**（人工列唯一权威，AI 列仅候选证据）；
- 报告落 Redis（TTL 30 天）+ LLM 调用走 ai_audit 审计留痕；
- 成本硬上限：单条 LLM ≤3 次 + 工具 ≤8 次、每日 ≤20 条。

本文件先落 E1/E5 的纯函数层（判据 / 捞取 / rescued 判定 / 报告 schema /
指标汇总）与 T2 的复核 runner（``run_exception_review`` 服务层单接缝：
依赖全注入、成本护栏硬上限、报告落 Redis + ai_audit 审计行、
**全程无任何 Bitable 写路径**）。
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import BinaryContent

from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
    EvidenceEntry,
    verify_citations,
)
from app.modules.safety.ai_hazard_identification.citations import (
    is_placeholder_basis,
    is_placeholder_variant,
)
from app.modules.safety.service.hazard_direct.failure_ledger import (
    RedisLike,
    list_dead_letters,
)

logger = logging.getLogger(__name__)

# 复核报告 Redis hash（field=record_id，TTL 30 天，写序对齐 failure_ledger）
REVIEWS_KEY = "safety:hazard:ai:exception_reviews"
REVIEWS_TTL_SECONDS = 30 * 24 * 3600
class ExceptionLabel(StrEnum):
    """例外分类标签（E1）：由既有失败分类归并，不发明新失败语义。"""

    RAG_DEGRADED = "rag_degraded"  # RAG 降级
    NO_CHUNKS = "no_chunks"  # 零召回
    BASIS_MISSING = "basis_missing"  # 依据空 / 占位
    CITATION_UNVERIFIED = "citation_unverified"  # 引用不可验证
    JSON_INVALID = "json_invalid"  # JSON 持续非法
    VALIDATION_FAILED = "validation_failed"  # 枚举/规则校验失败
    WRITEBACK_ERROR = "writeback_error"  # 写回失败
    MANUAL_PICK = "manual_pick"  # 人工指定（无失败状态）
    OTHER = "other"  # 未知/兜底（含 AI 基础设施类——不进死信，仅人工点名时可能路过）


# 失败分类 → 例外标签（quality_gate 分类 + ai_analysis 分类全覆盖）
_CATEGORY_TO_LABEL: dict[str, ExceptionLabel] = {
    "retrieval_degraded": ExceptionLabel.RAG_DEGRADED,
    "no_chunks": ExceptionLabel.NO_CHUNKS,
    "empty_basis": ExceptionLabel.BASIS_MISSING,
    "placeholder_basis": ExceptionLabel.BASIS_MISSING,
    "no_citation": ExceptionLabel.CITATION_UNVERIFIED,
    "invalid_citation": ExceptionLabel.CITATION_UNVERIFIED,
    "json_invalid": ExceptionLabel.JSON_INVALID,
    "validation_failed": ExceptionLabel.VALIDATION_FAILED,
    "writeback_error": ExceptionLabel.WRITEBACK_ERROR,
}


def classify_exception(category: str | None, *, manual: bool = False) -> ExceptionLabel:
    """失败分类 → 例外标签（纯函数）。

    ``manual=True``（人工指定，无失败状态）恒为 :attr:`ExceptionLabel.MANUAL_PICK`；
    未知/空分类兜底 :attr:`ExceptionLabel.OTHER`。
    """
    if manual:
        return ExceptionLabel.MANUAL_PICK
    return _CATEGORY_TO_LABEL.get(str(category or ""), ExceptionLabel.OTHER)


@dataclass(frozen=True)
class ExceptionItem:
    """一条待复核的例外（死信或人工指定）。"""

    record_id: str
    source: str  # "dead_letter" | "manual"
    category: str | None
    reason: str
    attempts: int
    label: ExceptionLabel


async def pick_exceptions(
    *,
    manual_record_ids: list[str] | None = None,
    limit: int = 20,
    redis: RedisLike | None = None,
) -> list[ExceptionItem]:
    """捞取例外清单：死信 + 人工指定合并去重，上限截断。

    - 人工指定优先排在前面（管理员点名先复核）；与死信重合的 record_id
      保留死信上下文（attempts/category），只出一条；
    - ``list_dead_letters`` 自身 Redis 异常 fail-open 返回空（不向上抛），
      人工指定部分不受影响。
    """
    manual_ids = [rid for rid in (manual_record_ids or []) if rid]
    dead_items = await list_dead_letters(redis=redis)
    dead_by_id = {item["record_id"]: item for item in dead_items}

    picked: list[ExceptionItem] = []
    seen: set[str] = set()
    for record_id in manual_ids:
        dead = dead_by_id.get(record_id)
        if dead is not None:
            picked.append(
                ExceptionItem(
                    record_id=record_id,
                    source="dead_letter",
                    category=str(dead.get("category") or ""),
                    reason=str(dead.get("reason") or ""),
                    attempts=int(dead.get("attempts") or 0),
                    label=classify_exception(dead.get("category")),
                )
            )
        else:
            picked.append(
                ExceptionItem(
                    record_id=record_id,
                    source="manual",
                    category=None,
                    reason="",
                    attempts=0,
                    label=classify_exception(None, manual=True),
                )
            )
        seen.add(record_id)
    for dead in dead_items:
        record_id = str(dead.get("record_id") or "")
        if not record_id or record_id in seen:
            continue
        picked.append(
            ExceptionItem(
                record_id=record_id,
                source="dead_letter",
                category=str(dead.get("category") or ""),
                reason=str(dead.get("reason") or ""),
                attempts=int(dead.get("attempts") or 0),
                label=classify_exception(dead.get("category")),
            )
        )
        seen.add(record_id)
    return picked[: max(0, int(limit))]


def judge_rescued(
    new_basis: str, *, evidence: CitationEvidence | None
) -> bool:
    """rescued 程序判定（observe 口径，P1-3 拍板 ⑨）。

    True 需同时满足：
    1. AI 新结论的判定依据非空且非占位（精确标记与变体，唯一事实源
       ``ai_hazard_identification.citations``）；
    2. 依据引用能在本次检索证据中命中至少一条（``verify_citations``，
       与主链引用强校验同源，避免两套口径漂移）。
    """
    text = str(new_basis or "").strip()
    if not text:
        return False
    if is_placeholder_basis(text) or is_placeholder_variant(text):
        return False
    if evidence is None or evidence.is_empty:
        return False
    return verify_citations(text, evidence).has_verified


class EvidenceSnippet(BaseModel):
    """复核报告引用的检索证据（候选证据语义）。"""

    doc_name: str = ""
    source_article: str = ""
    quote: str = ""
    chunk_id: str = ""


class ReviewConclusion(BaseModel):
    """AI 复核新结论（与主链输出同键；observe 期仅候选证据）。"""

    classification: str | None = None
    hazard_level: str | None = None
    major_hazard_basis: str = ""
    rectification_suggestion: str | None = None


class DiffItem(BaseModel):
    """AI 新结论 vs 人工结论 的单字段差异。"""

    field: str
    ai_value: str | None = None
    manual_value: str | None = None
    agree: bool = False


class ProposedAction(StrEnum):
    """建议动作（observe 期纯建议，无执行路径）。"""

    ADOPT_AI = "adopt_ai"  # AI 结论更优，建议人工采纳
    KEEP_MANUAL = "keep_manual"  # 人工结论无误，维持
    ESCALATE = "escalate"  # 分歧重大（如级别 major vs general），提请人工专审
    INSUFFICIENT = "insufficient"  # 证据不足，建议补录知识库后重试


class ReviewSource(StrEnum):
    DEAD_LETTER = "dead_letter"
    MANUAL = "manual"


def _validate_label(value: str) -> ExceptionLabel:
    return ExceptionLabel(value)


class ExceptionReviewReport(BaseModel):
    """结构化复核报告（Redis hash 存取、看板 Tab 消费）。"""

    record_id: str
    exception_label: ExceptionLabel
    failure_category: str | None = None
    failure_reason: str = ""
    review_source: ReviewSource
    evidence: list[EvidenceSnippet] = Field(default_factory=list)
    ai_conclusion: ReviewConclusion
    manual_conclusion: dict[str, Any] = Field(default_factory=dict)
    diff: list[DiffItem] = Field(default_factory=list)
    proposed_action: ProposedAction
    rescued: bool = False
    observed_at: datetime
    reviewer_prompt_version: str = ""
    round_note: str = ""  # 预算截断/降级等备注

    @field_validator("exception_label", mode="before")
    @classmethod
    def _coerce_label(cls, value: Any) -> ExceptionLabel:
        return _validate_label(value)

    def summary(self) -> dict[str, Any]:
        """清单摘要行（入口工具/看板 Tab 共用口径）。"""
        return {
            "record_id": self.record_id,
            "source": str(self.review_source.value),
            "label": str(self.exception_label.value),
            "rescued": self.rescued,
            "action": str(self.proposed_action.value),
            "ai_basis": self.ai_conclusion.major_hazard_basis[:160],
            "observed_at": self.observed_at.isoformat(),
            "note": self.round_note,
        }


def summarize_exception_metrics(
    *,
    exception_count: int,
    analyzed_count: int,
    reviewed_count: int,
    rescued_count: int,
) -> dict[str, float | int]:
    """例外率 / rescued 率（E5 纯函数；零分母安全返回 0.0）。

    - 例外率 = 例外条数 / 窗口内已分析条数（分母由看板端点从审计计数注入）；
    - rescued 率 = rescued 条数 / 已复核条数。
    """
    analyzed = max(0, int(analyzed_count))
    reviewed = max(0, int(reviewed_count))
    return {
        "exception_count": max(0, int(exception_count)),
        "analyzed_count": analyzed,
        "exception_rate": (
            round(max(0, int(exception_count)) / analyzed, 4) if analyzed else 0.0
        ),
        "reviewed": reviewed,
        "rescued": max(0, int(rescued_count)),
        "rescued_rate": (
            round(max(0, int(rescued_count)) / reviewed, 4) if reviewed else 0.0
        ),
    }


def _now_utc() -> datetime:
    return datetime.now(UTC)


# ═══════════════════════════════════════════════════════════════════════════
# T2 —— 复核 runner（服务层单接缝）：五工具 impl + 成本护栏 + observe 零写
# ═══════════════════════════════════════════════════════════════════════════

# 复核员场景（ai_config 场景注册表 + ai_audit scenario 同名）
REVIEWER_SCENARIO = "hazard_exception_review"

# 每日复核计数 key 前缀（后接 YYYYMMDD，TTL 48h 跨日自然过期）
_DAILY_KEY_PREFIX = "safety:hazard:ai:exception_reviews:daily"
_DAILY_TTL_SECONDS = 48 * 3600


class RecordReader(Protocol):
    """记录读取协议（Bitable 只读；测试注入 fake，写 canary 由调用方自加）。"""

    async def get_fields(self, record_id: str) -> dict[str, Any] | None: ...

    async def defect_images(self, record_id: str) -> list[str]:
        """缺陷图 data URI 列表（复用主链「只下缺陷图」口径）。"""


class RegulationSearcher(Protocol):
    """法规检索协议（返回 chunk dict：source_doc/source_article/chunk_text/chunk_id）。"""

    async def search(self, query: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ReviewBudget:
    """成本护栏（拍板 ⑥）：上限可由 app_config 覆盖（T3 接线）。"""

    llm_call_limit: int = 3
    tool_call_limit: int = 8
    daily_limit: int = 20


@dataclass
class ReviewDeps:
    """复核依赖（全注入；测试全 fake，无网络无真实 AI）。"""

    reader: RecordReader
    searcher: RegulationSearcher
    model_factory: Callable[[], Any]  # → pydantic-ai Model
    redis: RedisLike | None = None
    budget: ReviewBudget = field(default_factory=ReviewBudget)


# ── 复核员 prompt（E4 skills 化：md 优先，本常量为离线兜底）────────────────


def reviewer_prompt() -> str:
    """复核员 prompt（prompt_skills/exception-reviewer.md 热缓存；缺失回落常量）。"""
    from app.modules.safety.ai_hazard_identification.prompt_loader import (
        load_text_block,
    )

    return load_text_block("exception-reviewer", fallback=REVIEWER_PROMPT)


def reviewer_prompt_version() -> str:
    from app.modules.safety.ai_hazard_identification.prompt_loader import block_version

    return block_version("exception-reviewer")

REVIEWER_PROMPT = """你是隐患 AI 识别「例外复核员」（observe 模式）。

背景：主链是确定性单次调用管线，个别记录因检索降级 / JSON 持续非法 / 依据空 /
引用不可验证等原因失败进入死信。你负责对这些**例外记录**做多步补检，给出
结构化复核结论。observe 铁律（最高优先级，不可违反）：

1. **你处于 observe 模式：绝不写回任何表格列**。你的全部产出是「候选证据」，
   人工列是唯一权威——你给出的任何结论都只是给安全管理员的复核建议；
2. 你最多进行少量多步补检（看图 → 二次检索 → 交叉核对），务必珍惜调用次数；
3. 引用必须来自你本次 search_regulations 检索到的条款原文，禁止凭记忆编造；
   知识库确无对应条文时，如实输出 insufficient，宁缺毋滥；
4. 与人工结论的分歧不是错误：分歧点要在结论中明确列出，由人裁决。

工作步骤（建议顺序）：
- get_record_context：读记录人工列/AI列当前值与失败原因；
- view_images：查看缺陷图（若存在）；
- search_regulations：用「设备/物质/行为/场所+标准关键词」检索法规条文；
- cross_check：把你的新结论与人工结论逐字段比对，并核验引用可验证性；
- propose_writeback：把最终建议结构化（observe 期仅生成建议，不写回）。

最终输出字段：classification（分类）/ hazard_level（级别 general|serious|major）/
major_hazard_basis（判定依据，引用格式《法规名》第X条：'原文'）/
rectification_suggestion（整改建议）/ proposed_action（adopt_ai|keep_manual|
escalate|insufficient）/ note（分歧与备注）。
"""


class ReviewerFinalOutput(BaseModel):
    """复核员最终输出（硬 schema 留代码——md 改不动这里的枚举与必填）。"""

    classification: str | None = None
    hazard_level: str | None = None
    major_hazard_basis: str = ""
    rectification_suggestion: str | None = None
    proposed_action: str = "insufficient"
    note: str = ""

    @field_validator("hazard_level")
    @classmethod
    def _validate_level(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"general", "serious", "major"}
        if value not in allowed:
            raise ValueError(f"hazard_level 非法: {value!r}，允许 {sorted(allowed)}")
        return value

    @field_validator("proposed_action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        allowed = {a.value for a in ProposedAction}
        if value not in allowed:
            raise ValueError(f"proposed_action 非法: {value!r}，允许 {sorted(allowed)}")
        return value


# ── 五工具 impl（BA 薄适配与 runner 闭包共用）─────────────────────────────

# 人工列语义键（读口径与 field_authority 常量一致；此处只取复核所需子集）
_MANUAL_FIELDS = {
    "hazard_level": "隐患级别",
    "hazard_type": "隐患分类",
    "hazard_category": "隐患类别",
}
_AI_FIELDS = {
    "hazard_level": "隐患级别（AI）",
    "hazard_type": "隐患分类（AI）",
    "hazard_category": "隐患类别（AI）",
}


def _cell_text(fields: dict[str, Any], name: str) -> str:
    """Bitable 单元格文本化（select/text 兼容；与 bitable_repo.f_* 同语义的
    最小实现，避免引入重依赖）。"""
    value = fields.get(name)
    if value is None:
        return ""
    if isinstance(value, dict):
        # select 类型 {"text": ...} / 人员 {"name": ...}
        for key in ("text", "name", "value"):
            inner = value.get(key)
            if isinstance(inner, str):
                return inner
        return ""
    if isinstance(value, list):
        texts = [_cell_text({"v": item}, "v") for item in value]
        return "/".join(t for t in texts if t)
    return str(value)


def extract_conclusions(fields: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """从记录字段提取（人工结论, AI结论）——复核 diff 的两轴。"""
    manual = {
        key: (_cell_text(fields, name) or None) for key, name in _MANUAL_FIELDS.items()
    }
    manual["description"] = _cell_text(fields, "隐患描述") or None
    ai = {
        key: (_cell_text(fields, name) or None) for key, name in _AI_FIELDS.items()
    }
    ai["major_hazard_basis"] = _cell_text(fields, "隐患判定依据（AI）") or None
    return manual, ai


async def fetch_record_context(
    *, reader: RecordReader, redis: RedisLike | None, record_id: str
) -> dict[str, Any] | None:
    """get_record_context impl：记录字段 + 失败账本状态 → 上下文 dict。"""
    fields = await reader.get_fields(record_id)
    if fields is None:
        return None
    manual, ai = extract_conclusions(fields)
    failure: dict[str, Any] | None = None
    try:
        raw = await _hget_failover(redis, record_id)
        if raw:
            failure = {
                "category": raw.get("category"),
                "attempts": raw.get("attempts"),
                "reason": raw.get("last_reason", ""),
                "dead": bool(raw.get("dead")),
            }
    except Exception:  # noqa: BLE001 — 账本读取失败不阻断复核
        logger.warning("复核读取失败账本异常: record_id=%s", record_id, exc_info=True)
    return {
        "record_id": record_id,
        "manual_conclusion": manual,
        "ai_conclusion": ai,
        "failure": failure,
    }


async def _hget_failover(
    redis: RedisLike | None, record_id: str
) -> dict[str, Any] | None:
    """失败状态：attempts key 优先，缺失时回退死信 hash（死信 7 天 TTL 后仍可查）。"""
    from app.modules.safety.service.hazard_direct.failure_ledger import (
        DEAD_LETTERS_KEY,
        attempts_key,
    )

    if redis is None:
        client: RedisLike = review_redis_client()
    else:
        client = redis
    raw = await client.get(attempts_key(record_id))
    if not raw:
        raw = await client.hget(DEAD_LETTERS_KEY, record_id)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


async def search_regulation_chunks(
    searcher: RegulationSearcher, query: str
) -> list[dict[str, Any]]:
    """search_regulations impl：法规检索 → chunk dict 列表（候选证据源）。"""
    chunks = await searcher.search(query)
    return [
        {
            "source_doc": str(c.get("source_doc") or ""),
            "source_article": str(c.get("source_article") or ""),
            "chunk_text": str(c.get("chunk_text") or ""),
            "chunk_id": str(c.get("chunk_id") or ""),
        }
        for c in chunks
    ]


def cross_check_conclusion(
    *,
    ai_conclusion: dict[str, Any],
    manual_conclusion: dict[str, Any],
    evidence_entries: list[dict[str, Any]] | None,
    ai_basis: str = "",
) -> dict[str, Any]:
    """cross_check impl：AI vs 人工逐字段 diff + 引用可验证性。"""
    diff: list[dict[str, Any]] = []
    for key in ("hazard_level", "hazard_type", "hazard_category"):
        ai_value = ai_conclusion.get(key)
        manual_value = manual_conclusion.get(key)
        diff.append(
            {
                "field": key,
                "ai_value": ai_value,
                "manual_value": manual_value,
                "agree": bool(ai_value and manual_value and str(ai_value) == str(manual_value)),
            }
        )
    basis = ai_basis or str(ai_conclusion.get("major_hazard_basis") or "")
    citation_verified = False
    if evidence_entries:
        evidence = _evidence_from_entries(evidence_entries)
        citation_verified = (
            bool(basis.strip())
            and not is_placeholder_basis(basis)
            and verify_citations(basis, evidence).has_verified
        )
    return {"diff": diff, "citation_verified": citation_verified}


def _evidence_from_entries(entries: list[dict[str, Any]]) -> CitationEvidence:
    return CitationEvidence(
        entries=tuple(
            EvidenceEntry(
                doc_name=str(e.get("source_doc") or ""),
                source_article=str(e.get("source_article") or ""),
                chunk_text=str(e.get("chunk_text") or ""),
                chunk_id=str(e.get("chunk_id") or ""),
            )
            for e in entries
            if e.get("source_doc") or e.get("chunk_text")
        )
    )


def build_proposal(record_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
    """propose_writeback impl（observe 期 = propose_only）。

    只做结构化与标记，**不存在任何写执行路径**；P2-1 升格时才接入写前
    人工确认。返回体显式标注 observe_only / writeback=disabled。
    """
    return {
        "record_id": record_id,
        "proposal": proposal,
        "observe_only": True,
        "writeback": "disabled",
        "note": "observe 期复核建议不写回；人工列唯一权威",
    }


def data_uri_to_binary(uri: str) -> tuple[bytes, str] | None:
    """data URI → (bytes, media_type)；非 data URI 返回 None。"""
    if not uri.startswith("data:"):
        return None
    try:
        header, _, payload = uri.partition(",")
        media_type = header[5:].split(";", 1)[0] or "image/jpeg"
        return base64.b64decode(payload), media_type
    except Exception:  # noqa: BLE001 — 单图解析失败跳过，不阻断复核
        return None


# ── runner ─────────────────────────────────────────────────────────────────


@dataclass
class ReviewRunResult:
    """一次复核批的结果汇总（入口工具/定时任务/看板共用）。"""

    reports: list[ExceptionReviewReport] = field(default_factory=list)
    reviewed: int = 0
    rescued: int = 0
    skipped: int = 0  # 因每日上限未复核
    stopped_reason: str = ""


async def _check_daily_budget(
    redis: RedisLike | None, daily_limit: int, *, now: datetime | None = None
) -> bool:
    """本批还能否再复核 1 条（Redis INCR 日计数；fail-open 允许）。"""
    if redis is None:
        return True
    day = (now or datetime.now(UTC)).strftime("%Y%m%d")
    daily_key = f"{_DAILY_KEY_PREFIX}:{day}"
    try:
        count = int(await redis.incr(daily_key))
        await redis.expire(daily_key, _DAILY_TTL_SECONDS)
        return count <= daily_limit
    except Exception:  # noqa: BLE001 — Redis 抖动不阻断复核（fail-open）
        logger.warning("每日复核计数失败，fail-open 放行", exc_info=True)
        return True


async def _save_report(
    report: ExceptionReviewReport, redis: RedisLike | None
) -> None:
    """报告落 Redis hash（TTL 30 天；写失败只告警不阻断）。"""
    if redis is None:
        return
    try:
        await redis.hset(
            REVIEWS_KEY, report.record_id, report.model_dump_json()
        )
        await redis.expire(REVIEWS_KEY, REVIEWS_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning(
            "复核报告落 Redis 失败（不影响复核结果）: record_id=%s",
            report.record_id,
            exc_info=True,
        )


async def _write_review_audit(
    report: ExceptionReviewReport, *, model_name: str, extra: dict[str, Any]
) -> None:
    """审计留痕（ai_call_audits 一行/条；write_audit_record 自身不向上抛）。"""
    try:
        from app.modules.safety.ai_audit.audited_client import write_audit_record

        await write_audit_record(
            model=model_name,
            scenario=REVIEWER_SCENARIO,
            input_text=f"exception review record={report.record_id}",
            output_text=report.model_dump_json(),
            status="success",
            channel_override="system",
            extra={
                "bitable_record_id": report.record_id,
                "rescued": report.rescued,
                "exception_label": str(report.exception_label.value),
                "review_source": str(report.review_source.value),
                "proposed_action": str(report.proposed_action.value),
                **extra,
            },
        )
    except Exception:  # noqa: BLE001 — 审计失败不影响复核
        logger.warning("复核审计写入失败", exc_info=True)


def _insufficient_report(
    item: ExceptionItem, *, note: str
) -> ExceptionReviewReport:
    return ExceptionReviewReport(
        record_id=item.record_id,
        exception_label=item.label,
        failure_category=item.category,
        failure_reason=item.reason,
        review_source=ReviewSource(item.source),
        ai_conclusion=ReviewConclusion(),
        manual_conclusion={},
        diff=[],
        proposed_action=ProposedAction.INSUFFICIENT,
        rescued=False,
        observed_at=_now_utc(),
        round_note=note,
    )


async def review_single(
    item: ExceptionItem,
    *,
    deps: ReviewDeps,
) -> ExceptionReviewReport:
    """单条记录的复核（runner 内部步进单元；预算/缺记录均收敛为报告）。"""
    from pydantic_ai import Agent
    from pydantic_ai.usage import UsageLimits

    budget = deps.budget
    context = await fetch_record_context(
        reader=deps.reader, redis=deps.redis, record_id=item.record_id
    )
    if context is None:
        report = _insufficient_report(item, note="record_not_found")
        await _save_report(report, deps.redis)
        await _write_review_audit(
            report, model_name="reviewer", extra={"truncated": "record_not_found"}
        )
        return report

    searched_entries: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()

    # ── 五工具（绑定本记录依赖；search 结果累积为 rescued 判定证据）──
    async def get_record_context() -> dict[str, Any]:
        return context

    async def view_images() -> list[BinaryContent]:
        uris = await deps.reader.defect_images(item.record_id)
        binaries: list[BinaryContent] = []
        for uri in uris[:4]:  # 与识图链路上限一致：≤4 张
            parsed = data_uri_to_binary(uri)
            if parsed is not None:
                binaries.append(BinaryContent(parsed[0], media_type=parsed[1]))
        return binaries

    async def search_regulations(query: str) -> list[dict[str, Any]]:
        chunks = await search_regulation_chunks(deps.searcher, query)
        for chunk in chunks:
            cid = chunk.get("chunk_id") or f"{chunk.get('source_doc')}:{chunk.get('source_article')}"
            if cid in seen_chunk_ids:
                continue
            seen_chunk_ids.add(cid)
            searched_entries.append(chunk)
        return chunks

    async def cross_check(ai_conclusion: dict[str, Any]) -> dict[str, Any]:
        merged = {
            **(context.get("ai_conclusion") or {}),
            **(ai_conclusion or {}),
        }
        return cross_check_conclusion(
            ai_conclusion=merged,
            manual_conclusion=context.get("manual_conclusion") or {},
            evidence_entries=searched_entries,
            ai_basis=str(ai_conclusion.get("major_hazard_basis") or ""),
        )

    async def propose_writeback(proposal: dict[str, Any]) -> dict[str, Any]:
        return build_proposal(item.record_id, proposal or {})

    try:
        agent: Any = Agent(
            deps.model_factory(),
            instructions=reviewer_prompt(),
            tools=[
                get_record_context,
                view_images,
                search_regulations,
                cross_check,
                propose_writeback,
            ],
            output_type=ReviewerFinalOutput,
        )
        prompt = (
            f"复核例外记录 {item.record_id}（失败分类 {item.category}：{item.reason}）。"
            "按工作步骤补检后给出最终结构化结论。"
        )
        result = await agent.run(
            prompt,
            usage_limits=UsageLimits(
                request_limit=budget.llm_call_limit,
                tool_calls_limit=budget.tool_call_limit,
            ),
        )
        final: ReviewerFinalOutput = result.output
        evidence = _evidence_from_entries(searched_entries)
        rescued = judge_rescued(final.major_hazard_basis, evidence=evidence)
        check = cross_check_conclusion(
            ai_conclusion=final.model_dump(),
            manual_conclusion=context.get("manual_conclusion") or {},
            evidence_entries=searched_entries,
            ai_basis=final.major_hazard_basis,
        )
        diff = [
            DiffItem(
                field=d["field"],
                ai_value=d["ai_value"],
                manual_value=d["manual_value"],
                agree=d["agree"],
            )
            for d in check["diff"]
        ]
        report = ExceptionReviewReport(
            record_id=item.record_id,
            exception_label=item.label,
            failure_category=item.category,
            failure_reason=item.reason,
            review_source=ReviewSource(item.source),
            evidence=[
                EvidenceSnippet(
                    doc_name=e["source_doc"],
                    source_article=e["source_article"],
                    quote=e["chunk_text"][:120],
                    chunk_id=e["chunk_id"],
                )
                for e in searched_entries[:8]
            ],
            ai_conclusion=ReviewConclusion(
                classification=final.classification,
                hazard_level=final.hazard_level,
                major_hazard_basis=final.major_hazard_basis,
                rectification_suggestion=final.rectification_suggestion,
            ),
            manual_conclusion=context.get("manual_conclusion") or {},
            diff=diff,
            proposed_action=ProposedAction(final.proposed_action),
            rescued=rescued,
            observed_at=_now_utc(),
            reviewer_prompt_version=reviewer_prompt_version(),
        )
        await _save_report(report, deps.redis)
        await _write_review_audit(
            report,
            model_name="reviewer",
            extra={
                "truncated": "",
                "evidence_chunks": len(searched_entries),
            },
        )
        return report
    except Exception as exc:  # noqa: BLE001 — 任何异常收敛为 insufficient 报告
        logger.warning(
            "复核单条异常收敛为 insufficient: record_id=%s", item.record_id, exc_info=True
        )
        report = _insufficient_report(item, note=f"budget_truncated:{type(exc).__name__}")
        await _save_report(report, deps.redis)
        await _write_review_audit(
            report,
            model_name="reviewer",
            extra={"truncated": type(exc).__name__},
        )
        return report


async def run_exception_review(
    items: list[ExceptionItem],
    *,
    deps: ReviewDeps,
) -> ReviewRunResult:
    """服务层单接缝：一批例外 → 结构化复核报告（observe，零写回）。

    每日上限：按条扣减（Redis INCR 日计数），超限停止并汇总剩余条数
    （``skipped``）；单条 LLM/工具上限由 pydantic-ai UsageLimits 截断，
    收敛为 ``insufficient`` 报告（round_note=budget_truncated:*）。
    """
    result = ReviewRunResult()
    for item in items:
        if not await _check_daily_budget(deps.redis, deps.budget.daily_limit):
            result.skipped = len(items) - result.reviewed
            result.stopped_reason = "daily_limit"
            break
        report = await review_single(item, deps=deps)
        result.reports.append(report)
        result.reviewed += 1
        if report.rescued:
            result.rescued += 1
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 默认依赖实现（BA 工具适配与定时任务共用；测试注入 fake 替换）
# ═══════════════════════════════════════════════════════════════════════════


class BitableRecordReader:
    """默认记录读取：SafetyBitableClient 直读隐患登记表（只读）。"""

    def __init__(self) -> None:
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        self._client = SafetyBitableClient()

    async def get_fields(self, record_id: str) -> dict[str, Any] | None:
        record = await self._client.get_record(record_id=record_id)
        if not isinstance(record, dict):
            return None
        fields = record.get("fields")
        return fields if isinstance(fields, dict) else None

    async def defect_images(self, record_id: str) -> list[str]:
        from app.modules.safety.service.hazard_direct import bitable_repo

        fields = await self.get_fields(record_id)
        if fields is None:
            return []
        photos = await bitable_repo.download_photos(
            self._client, fields, record_id=record_id, include_rectification=False
        )
        return bitable_repo.photos_to_data_uris(photos.get("defect", []))


class RetrieverSearcher:
    """默认法规检索：SafetyKnowledgeRetriever（需 db session）。"""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def search(self, query: str) -> list[dict[str, Any]]:
        from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever

        retriever = SafetyKnowledgeRetriever(self._db)
        context = await retriever.retrieve(description=query)
        chunks = getattr(context, "chunks", None) or []
        return [
            {
                "source_doc": getattr(c, "source_doc", ""),
                "source_article": getattr(c, "source_article", ""),
                "chunk_text": getattr(c, "chunk_text", ""),
                "chunk_id": getattr(c, "chunk_id", ""),
            }
            for c in chunks
        ]


def _reviewer_model_factory() -> Any:
    """复核员模型（ai_config：hazard_exception_review 场景绑定 → 默认 profile）。"""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.deepseek import DeepSeekProvider

    from app.modules.safety.ai_config.scenario_store import scenario_store
    from app.modules.safety.ai_config.store import store as ai_config_store

    profile = scenario_store.get_effective_profile(REVIEWER_SCENARIO)
    config = ai_config_store.get_profile_config(profile)
    api_key = config.get("api_key") or ""
    model = config.get("model") or "deepseek-flash"
    return OpenAIChatModel(model, provider=DeepSeekProvider(api_key=api_key))


def _review_budget() -> ReviewBudget:
    """护栏上限（app_config 可调；默认 3/8/20）。"""
    from app.modules.safety.service.hazard_direct.config import review_budget

    return review_budget()


def build_default_review_deps(db: Any = None) -> ReviewDeps:
    """默认复核依赖（真实链路）；测试 monkeypatch 本函数注入全 fake。"""
    return ReviewDeps(
        reader=BitableRecordReader(),
        searcher=RetrieverSearcher(db),
        model_factory=_reviewer_model_factory,
        redis=review_redis_client(),  # 真客户端：每日护栏/报告落盘/看板数据链
        budget=_review_budget(),
    )


def review_redis_client() -> RedisLike:
    """复核用 Redis 客户端（死信捞取/日计数/报告存储共用；测试注入点）。"""
    from typing import cast

    from app.core.redis import redis_client

    return cast(RedisLike, redis_client)


async def run_scheduled_review(chat_id: str | None) -> dict[str, Any]:
    """定时任务体（每日 09:00，默认关）：捞死信 → 复核 → 卡片到配置群。

    observe 语义不变：不写回、不发普通通知（仅确认卡形态到 ``chat_id``）；
    ``chat_id`` 为空时只跑复核与留痕（Redis 报告 + 审计行），不发卡。
    """
    from app.modules.safety.feishu.exception_review_card import (
        send_review_summary_card,
    )

    redis = review_redis_client()
    items = await pick_exceptions(redis=redis, limit=_review_budget().daily_limit)
    if not items:
        logger.info("例外复核定时任务：当前无死信，空跑")
        return {"reviewed": 0, "skipped": 0, "rescued": 0, "card_sent": False}
    result = await run_exception_review(
        items, deps=build_default_review_deps()
    )
    card_sent = False
    if chat_id:
        message_id = await send_review_summary_card(chat_id, result)
        card_sent = message_id is not None
    return {
        "reviewed": result.reviewed,
        "skipped": result.skipped,
        "rescued": result.rescued,
        "card_sent": card_sent,
    }
