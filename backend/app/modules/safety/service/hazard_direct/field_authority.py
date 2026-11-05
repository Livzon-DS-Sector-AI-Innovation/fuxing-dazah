"""隐患字段权威矩阵 —— 单一事实源（P0-B）。

背景（见 `docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md` §2）：
隐患主表存在「人工列 / AI 列」双轨同义字段。写路径可以靠约定约束，但读口径
会各自漂移（页面筛选读 AI 值、展示读人工值、评分读 AI 值……）。本模块把
「字段 → owner → 权威列 → fallback → 下游读策略 → 允许写链」固化为单一事实源：

- **owner**：`HUMAN`（人工填报）/`AI`（AI 产出）/`SYSTEM`（系统规则写）/
  `DERIVED`（派生列，单一写者）/`FORMULA`（飞书公式列，只读）。
- **权威列**：每个业务语义（level/type/category）只认一个 owner=HUMAN 的列；
  AI 同义列只是候选证据，仅在人工列空值时 fallback（并显式标注来源）。
- **写链白名单**：`writer_whitelist()` 给出每个写链允许写的列；AI 写路径运行期
  调用 `assert_write_allowed()`，人工列一旦混入立即抛错（B1 验收钉子）。
- **督办单写者守卫**：`supervision_write_allowed()` 只在 ③ 督办轮询未开启时
  允许 ① 回退写「督办等级」，否则 ① 只算不写（B3）。

本模块顶层只依赖 stdlib；CN↔EN 枚举映射与 config 开关一律函数内惰性 import，
避免 `bitable_handler ↔ field_authority` 循环依赖（与仓库既有惰性 import 风格一致）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

# ═══════════════════════════════════════════════════════════════
# Bitable 字段名常量（唯一事实源；bitable_repo 同名 re-export）
# ═══════════════════════════════════════════════════════════════

# ── 人工列（业务事实源）──
F_NO = "隐患编号"
F_DESC = "隐患描述"
F_DATE = "检查日期"
F_INSPECTOR = "检查人员"
F_INSPECTOR_DEPT = "检查人员.部门"
F_INSPECTION_CATEGORY = "检查类别"
F_DEPT = "整改责任人.部门"
F_RESPONSIBLE = "整改责任人"
F_LEVEL_MANUAL = "隐患级别"
F_TYPE_MANUAL = "隐患分类"
F_CATEGORY_MANUAL = "隐患类别"
F_RECTIFY_STATUS = "整改状态"
F_RECTIFY_REPLY = "纠正预防措施"
F_RECTIFY_DONE_AT = "整改完成时间"
F_DEADLINE = "整改期限"
F_PROGRESS = "目前进展"
F_PHOTO_DEFECT = "缺陷图片"
F_PHOTO_RECTIFY = "整改后图片"

# ── AI 列（候选/证据，不进入权威口径）──
F_DESC_AI = "隐患描述（AI）"
F_LEVEL_AI = "隐患级别（AI）"
F_TYPE_AI = "隐患分类（AI）"
F_CATEGORY_AI = "隐患类别（AI）"
F_BASIS_AI = "隐患判定依据（AI）"
F_ADVICE_AI = "整改建议（AI）"
F_REVIEW_RESULT = "AI初审结果"
F_REVIEW_NOTE = "AI初审说明"

# ── 系统/派生列 ──
F_SUPERVISION = "督办等级"
F_SCORE = "评分结果"
F_SCORING_NOTE = "评分说明"

# ── 督办等级回退期告警节流（秒）──
SUPERVISION_FALLBACK_WARN_INTERVAL_SECONDS = 300.0

logger = logging.getLogger(__name__)


class FieldOwner(StrEnum):
    """字段归属（谁产生该列的业务事实）。"""

    HUMAN = "HUMAN"
    AI = "AI"
    SYSTEM = "SYSTEM"
    DERIVED = "DERIVED"
    FORMULA = "FORMULA"


class ReadPolicy(StrEnum):
    """下游读策略。"""

    HUMAN_FIRST_AI_FALLBACK = "human_first_ai_fallback"
    AI_ONLY = "ai_only"
    SYSTEM_SINGLE_WRITER = "system_single_writer"
    FORMULA_READONLY = "formula_readonly"
    DEPRECATED = "deprecated"


# 写链标识（写路径声明自己的 writer 名，白名单从这里派生）
WRITER_AI_ANALYSIS = "ai_analysis"  # ① 隐患 AI 识别轮询
WRITER_REVIEW = "review"  # ② AI 整改初审
WRITER_SCORING = "scoring"  # ⑤ AI 评分
WRITER_SUPERVISION = "supervision"  # ③ 督办等级计算
WRITER_SYSTEM = "system"  # 系统规则（编号分配等）
WRITER_LEGACY_EVENT = "legacy_event"  # 旧事件通道（已废弃，B5 拒写）


@dataclass(frozen=True)
class FieldRule:
    """字段权威矩阵的一行。"""

    field: str
    owner: FieldOwner
    semantic: str | None = None
    authoritative: bool = False
    fallback: str | None = None
    read_policy: ReadPolicy = ReadPolicy.AI_ONLY
    writers: frozenset[str] = frozenset()
    note: str = ""


_LEGACY = frozenset({WRITER_LEGACY_EVENT})

FIELD_RULES: tuple[FieldRule, ...] = (
    # ── 人工列：检查信息 ──
    FieldRule(
        F_DATE,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_INSPECTOR,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_INSPECTOR_DEPT,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_INSPECTION_CATEGORY,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_DEPT,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        note="整改责任人部门；隐患责任人.部门为历史同义列",
        writers=_LEGACY,
    ),
    FieldRule(
        F_RESPONSIBLE,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
    ),
    # ── 人工列：业务事实 ──
    FieldRule(
        F_DESC,
        FieldOwner.HUMAN,
        semantic="description",
        authoritative=True,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_LEVEL_MANUAL,
        FieldOwner.HUMAN,
        semantic="level",
        authoritative=True,
        fallback=F_LEVEL_AI,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
        note="人工级别为多选；effective 归一按最高严重度",
    ),
    FieldRule(
        F_TYPE_MANUAL,
        FieldOwner.HUMAN,
        semantic="type",
        authoritative=True,
        fallback=F_TYPE_AI,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        note="人工「隐患分类」与「隐患分类（AI）」选项标签同集",
    ),
    FieldRule(
        F_CATEGORY_MANUAL,
        FieldOwner.HUMAN,
        semantic="category",
        authoritative=True,
        fallback=F_CATEGORY_AI,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        note="人工「隐患类别」与「隐患类别（AI）」选项标签同集",
    ),
    FieldRule(
        F_RECTIFY_STATUS,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_RECTIFY_REPLY,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_RECTIFY_DONE_AT,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_DEADLINE,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        writers=_LEGACY,
    ),
    FieldRule(
        F_PROGRESS,
        FieldOwner.HUMAN,
        read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK,
        note="单向：Bitable → 平台，不回写",
    ),
    FieldRule(
        F_PHOTO_DEFECT, FieldOwner.HUMAN, read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK
    ),
    FieldRule(
        F_PHOTO_RECTIFY, FieldOwner.HUMAN, read_policy=ReadPolicy.HUMAN_FIRST_AI_FALLBACK
    ),
    # ── AI 列 ──
    FieldRule(
        F_DESC_AI,
        FieldOwner.AI,
        semantic="key_defect",
        writers=frozenset({WRITER_AI_ANALYSIS, WRITER_LEGACY_EVENT}),
    ),
    FieldRule(
        F_LEVEL_AI,
        FieldOwner.AI,
        semantic="level",
        read_policy=ReadPolicy.AI_ONLY,
        writers=frozenset({WRITER_AI_ANALYSIS, WRITER_LEGACY_EVENT}),
    ),
    FieldRule(
        F_TYPE_AI,
        FieldOwner.AI,
        semantic="type",
        read_policy=ReadPolicy.AI_ONLY,
        writers=frozenset({WRITER_AI_ANALYSIS, WRITER_LEGACY_EVENT}),
    ),
    FieldRule(
        F_CATEGORY_AI,
        FieldOwner.AI,
        semantic="category",
        read_policy=ReadPolicy.AI_ONLY,
        writers=frozenset({WRITER_AI_ANALYSIS, WRITER_LEGACY_EVENT}),
    ),
    FieldRule(
        F_BASIS_AI,
        FieldOwner.AI,
        semantic="basis",
        writers=frozenset({WRITER_AI_ANALYSIS, WRITER_LEGACY_EVENT}),
    ),
    FieldRule(
        F_ADVICE_AI,
        FieldOwner.AI,
        semantic="advice",
        writers=frozenset({WRITER_AI_ANALYSIS, WRITER_LEGACY_EVENT}),
    ),
    FieldRule(
        F_REVIEW_RESULT,
        FieldOwner.AI,
        semantic="review",
        read_policy=ReadPolicy.AI_ONLY,
        writers=frozenset({WRITER_REVIEW, WRITER_LEGACY_EVENT}),
    ),
    FieldRule(
        F_REVIEW_NOTE,
        FieldOwner.AI,
        semantic="review",
        read_policy=ReadPolicy.AI_ONLY,
        writers=frozenset({WRITER_REVIEW, WRITER_LEGACY_EVENT}),
    ),
    # ── 系统/派生列 ──
    FieldRule(
        F_NO,
        FieldOwner.SYSTEM,
        semantic="hazard_no",
        read_policy=ReadPolicy.SYSTEM_SINGLE_WRITER,
        writers=frozenset({WRITER_AI_ANALYSIS, WRITER_LEGACY_EVENT, WRITER_SYSTEM}),
        note="编号分配器兜底写入；本窗口不新增写路径",
    ),
    FieldRule(
        F_SUPERVISION,
        FieldOwner.DERIVED,
        semantic="supervision",
        read_policy=ReadPolicy.SYSTEM_SINGLE_WRITER,
        writers=frozenset(
            {WRITER_SUPERVISION, WRITER_AI_ANALYSIS, WRITER_LEGACY_EVENT}
        ),
        note="③ 唯一写者；① 仅在 ③ 轮询未开启时回退写（B3 守卫）",
    ),
    FieldRule(
        F_SCORE,
        FieldOwner.SYSTEM,
        semantic="score",
        read_policy=ReadPolicy.SYSTEM_SINGLE_WRITER,
        writers=frozenset({WRITER_SCORING}),
    ),
    FieldRule(
        F_SCORING_NOTE,
        FieldOwner.SYSTEM,
        semantic="score",
        read_policy=ReadPolicy.SYSTEM_SINGLE_WRITER,
        writers=frozenset({WRITER_SCORING}),
    ),
    # ── 公式/遗留列（只读，无写入方）──
    FieldRule("测试", FieldOwner.FORMULA, read_policy=ReadPolicy.FORMULA_READONLY),
    FieldRule("月份", FieldOwner.FORMULA, read_policy=ReadPolicy.FORMULA_READONLY),
    FieldRule("预警状态", FieldOwner.FORMULA, read_policy=ReadPolicy.FORMULA_READONLY),
    FieldRule(
        "AI审核结论",
        FieldOwner.AI,
        read_policy=ReadPolicy.DEPRECATED,
        note="历史遗留，无写入代码（P1 清理）",
    ),
    FieldRule("AI审核理由", FieldOwner.AI, read_policy=ReadPolicy.DEPRECATED),
    FieldRule("AI发现问题", FieldOwner.AI, read_policy=ReadPolicy.DEPRECATED),
    FieldRule("AI补充建议", FieldOwner.AI, read_policy=ReadPolicy.DEPRECATED),
    FieldRule("AI审核时间", FieldOwner.AI, read_policy=ReadPolicy.DEPRECATED),
    FieldRule(
        "重复标签（AI）",
        FieldOwner.AI,
        note="写入方不明（疑飞书自动化），P1 治理",
    ),
)


def _build_indexes() -> tuple[
    dict[str, FieldRule], dict[str, FieldRule], dict[str, frozenset[str]]
]:
    by_field = {rule.field: rule for rule in FIELD_RULES}
    authoritative = {r.semantic: r for r in FIELD_RULES if r.authoritative and r.semantic}
    writer_fields: dict[str, set[str]] = {}
    for rule in FIELD_RULES:
        for writer in rule.writers:
            writer_fields.setdefault(writer, set()).add(rule.field)
    return by_field, authoritative, {
        w: frozenset(fields) for w, fields in writer_fields.items()
    }


_BY_FIELD, _AUTHORITATIVE, _WRITER_FIELDS = _build_indexes()

_LEVEL_RANK = {"general": 1, "serious": 2, "major": 3}
_EFFECTIVE_SEMANTICS = frozenset({"level", "type", "category"})

_SPLIT_RE = re.compile(r"[,，、;；/]+")


class FieldAuthorityError(ValueError):
    """写链越权写字段（如 AI 写路径混入人工列）。"""


@dataclass(frozen=True)
class EffectiveValue:
    """人工优先 + AI fallback 的读口径结果。"""

    value: str | None
    source: Literal["human", "ai"] | None
    mismatch: bool


# ═══════════════════════════════════════════════════════════════
# 查询 API
# ═══════════════════════════════════════════════════════════════


def rule_of(field: str) -> FieldRule | None:
    """字段 → 权威矩阵行（未登记返回 None）。"""
    return _BY_FIELD.get(field)


def owner_of(field: str) -> FieldOwner | None:
    """字段 → owner（未登记返回 None）。"""
    rule = _BY_FIELD.get(field)
    return rule.owner if rule else None


def is_human_owned(field: str) -> bool:
    """是否人工列（未登记字段不算人工列）。"""
    return owner_of(field) is FieldOwner.HUMAN


def authoritative_field(semantic: str) -> str | None:
    """业务语义 → 人工权威列名。"""
    rule = _AUTHORITATIVE.get(semantic)
    return rule.field if rule else None


def fallback_field(semantic: str) -> str | None:
    """业务语义 → AI fallback 列名（无则 None）。"""
    rule = _AUTHORITATIVE.get(semantic)
    return rule.fallback if rule else None


def writer_whitelist(writer: str) -> frozenset[str]:
    """写链 → 允许写的字段集合（未登记写链返回空集合）。"""
    return _WRITER_FIELDS.get(writer, frozenset())


def assert_write_allowed(writer: str, fields: Iterable[str]) -> None:
    """断言写链只写白名单内字段，越权（尤其人工列）立即抛错。"""
    allowed = writer_whitelist(writer)
    violations = [f for f in fields if f not in allowed]
    if violations:
        detail = "、".join(f"{f}(owner={_owner_label(f)})" for f in violations)
        raise FieldAuthorityError(
            f"写链 {writer} 越权写字段（白名单外）: {detail}"
        )


def _owner_label(field: str) -> str:
    owner = owner_of(field)
    return owner.value if owner else "UNKNOWN"


def assert_no_human_fields(fields: Iterable[str]) -> None:
    """断言字段集合不含任何人工列（AI 写路径验收钉子）。"""
    human = [f for f in fields if is_human_owned(f)]
    if human:
        raise FieldAuthorityError(f"AI 写路径包含人工列: {'、'.join(human)}")


# ═══════════════════════════════════════════════════════════════
# CN/EN 归一（惰性 import 映射表，避免循环依赖）
# ═══════════════════════════════════════════════════════════════


def _level_maps() -> tuple[dict[str, str], frozenset[str]]:
    from app.modules.safety.feishu.bitable_handler import (
        HAZARD_LEVEL_MAP,
        HAZARD_LEVEL_REVERSE,
    )

    return HAZARD_LEVEL_MAP, frozenset(HAZARD_LEVEL_REVERSE)


def _type_maps() -> tuple[dict[str, str], frozenset[str]]:
    from app.modules.safety.feishu.bitable_handler import (
        HAZARD_TYPE_MAP,
        HAZARD_TYPE_REVERSE,
    )

    return HAZARD_TYPE_MAP, frozenset(HAZARD_TYPE_REVERSE)


def _category_maps() -> tuple[dict[str, str], frozenset[str]]:
    from app.modules.safety.feishu.bitable_handler import (
        HAZARD_CATEGORY_MAP,
        HAZARD_CATEGORY_REVERSE,
    )

    return HAZARD_CATEGORY_MAP, frozenset(HAZARD_CATEGORY_REVERSE)


def _tokens(raw: object) -> list[str]:
    """把 str / list / 逗号串统一拆成去空白 token 列表。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items: list[str] = []
        for item in raw:
            items.extend(_tokens(item))
        return items
    text = str(raw).strip()
    if not text:
        return []
    return [part.strip() for part in _SPLIT_RE.split(text) if part.strip()]


def normalize_level_manual(raw: object) -> str | None:
    """人工「隐患级别」（多选/中文/英文/逗号串）→ EN 枚举码。

    多值按 重大 > 较大 > 一般 取最高严重度（安全侧升级）；未知值忽略。
    """
    mapping, known = _level_maps()
    levels: list[str] = []
    for token in _tokens(raw):
        code = mapping.get(token)
        if code is None and token in known:
            code = token
        if code in _LEVEL_RANK:
            levels.append(code)
    if not levels:
        return None
    return max(levels, key=_LEVEL_RANK.__getitem__)


def _normalize_enum(raw: object, mapping: dict[str, str], known: frozenset[str]) -> str | None:
    """单选枚举（中文/英文）→ EN 枚举码；未知值返回 None。"""
    for token in _tokens(raw):
        code = mapping.get(token)
        if code is None and token in known:
            code = token
        if code:
            return code
    return None


def _normalizer_for(semantic: str) -> Callable[[object], str | None]:
    """业务语义 → 归一化函数（单一派发表：新增语义只改这里 + FIELD_RULES）。"""
    if semantic not in _EFFECTIVE_SEMANTICS:
        raise ValueError(f"不支持的 effective 语义: {semantic!r}")
    if semantic == "level":
        return normalize_level_manual
    if semantic == "type":
        mapping, known = _type_maps()
        return lambda raw: _normalize_enum(raw, mapping, known)
    mapping, known = _category_maps()
    return lambda raw: _normalize_enum(raw, mapping, known)


_unmappable_warned: set[str] = set()


def _warn_unmappable_manual(semantic: str, raw: object) -> None:
    """人工枚举值无法归一告警（每进程每语义一次，避免刷日志）。"""
    if semantic in _unmappable_warned:
        return
    _unmappable_warned.add(semantic)
    logger.warning(
        "人工枚举值无法归一（疑似 Bitable 选项新增/标签漂移，%s 不会回退 AI 值）: %r",
        semantic,
        raw,
    )


def resolve_effective(manual: object, ai: object, semantic: str) -> EffectiveValue:
    """人工优先 + AI fallback 解析（level/type/category）。

    权威列/fallback 列由 ``FIELD_RULES`` 登记，本函数只做值归一 + 合并；
    - manual 非空 → 权威值，source=human；
    - manual 空、ai 非空 → ai，source=ai；
    - 双方均有值且不相等 → mismatch=True（单边有值不算不一致）。
    """
    normalizer = _normalizer_for(semantic)
    manual_present = bool(_tokens(manual))
    manual_norm = normalizer(manual)
    ai_norm = normalizer(ai)
    if manual_norm is None and manual_present:
        # 人工列有值但无法归一（Bitable 新增选项/标签漂移）→ 人工仍为权威，
        # **不得静默回退 AI**（否则人工结论被 AI 覆盖）；只告警提示核对枚举映射。
        _warn_unmappable_manual(semantic, manual)
        return EffectiveValue(value=None, source="human", mismatch=False)

    if manual_norm:
        return EffectiveValue(
            value=manual_norm,
            source="human",
            mismatch=bool(ai_norm and ai_norm != manual_norm),
        )
    if ai_norm:
        return EffectiveValue(value=ai_norm, source="ai", mismatch=False)
    return EffectiveValue(value=None, source=None, mismatch=False)


# ═══════════════════════════════════════════════════════════════
# B3 督办单写者守卫
# ═══════════════════════════════════════════════════════════════


def _supervision_poll_enabled() -> bool:
    from app.modules.safety.service.hazard_direct import config

    return config.supervision_poll_enabled()


def supervision_write_allowed(poll_enabled: bool | None = None) -> bool:
    """① 是否允许回退写「督办等级」。

    - ③ 督办轮询开启 → False（① 只算不写，唯一写者是 ③）；
    - ③ 未开启 → True（① 保留写，避免上线顺序错误导致督办断更）。
    """
    enabled = _supervision_poll_enabled() if poll_enabled is None else poll_enabled
    return not enabled


def supervision_writer_role(poll_enabled: bool | None = None) -> Literal["supervision", "ai"]:
    """当前督办等级实际写者（supervision=③ / ai=① 回退）。"""
    return "ai" if supervision_write_allowed(poll_enabled) else "supervision"
