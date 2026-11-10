"""① AI 结论时效双指纹 —— stale 判定基线（P3-1 / C7 闭环）。

背景（docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md §2.2-C7）：人工修改
隐患描述/补充缺陷图后，①写回的 AI 结论列永久保留旧值——无 stale 标记、无重算
路径；人工直接编辑 AI 结论列后，批量重跑还会覆盖人工修正。

本模块在 ① 每次写回成功时落**双指纹基线**（Redis，failure_ledger 同款
RedisLike 注入 + fail-open）：

- 输入指纹 = sha256(隐患描述 + 缺陷图 file_token 清单)——① 的真实输入集；
- AI 列指纹 = sha256(①写回的 6 个结论列现值)。排除 隐患编号（非结论列）与
  督办等级（C9 多写者：③开启时 ① 只算不写，纳入会把 ③ 写回误判为人工编辑）。

扫描时重算双指纹与基线比对 → 四态分类（``classify``）：

- ``fresh``：与基线一致；
- ``input_changed``：人工改了输入（描述/缺陷图）→ 可按需重算（spec US1）；
- ``ai_edited``：人工直接改了 AI 结论列 → 保护清单，永不自动重跑（US2，
  设计原则 5「重跑不覆盖人工」）；输入与 AI 列都变时保护优先；
- ``no_baseline``：无基线（历史存量 / Redis 清空）→ 不判定——天然防重算
  风暴：stale 治理只覆盖部署后 ① 写回过的记录（US6）。

Redis 异常一律 fail-open（不抛、只记日志）：基线读写失败最多退化为
「不判定」，绝不阻塞识别/写回主链（US5）。键无 TTL——基线与记录共存亡，
删除键即放弃该记录的时效治理。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.hazard_direct.field_authority import (
    F_ADVICE_AI,
    F_BASIS_AI,
    F_CATEGORY_AI,
    F_DESC,
    F_DESC_AI,
    F_LEVEL_AI,
    F_NO,
    F_PHOTO_DEFECT,
    F_TYPE_AI,
)

logger = logging.getLogger(__name__)

KEY_PREFIX = "safety:hazard:ai:fingerprint"

# AI 结论列指纹范围（D7）：① 写回集合中的 6 个结论列。
AI_HASH_FIELDS: tuple[str, ...] = (
    F_TYPE_AI,
    F_LEVEL_AI,
    F_CATEGORY_AI,
    F_DESC_AI,
    F_BASIS_AI,
    F_ADVICE_AI,
)

# 分类四态（spec §4-D1）
STATE_FRESH = "fresh"
STATE_INPUT_CHANGED = "input_changed"
STATE_AI_EDITED = "ai_edited"
STATE_NO_BASELINE = "no_baseline"

# 结论列中的单选/多选列（str / list / [{"name"}] 三形态归一；其余按文本归一）
_AI_SELECT_FIELDS = frozenset({F_TYPE_AI, F_LEVEL_AI, F_CATEGORY_AI})


class RedisLike(Protocol):
    """本模块用到的最小 Redis 协议（测试注入内存假件）。"""

    async def get(self, key: str) -> Any: ...

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> Any: ...


def _get_redis() -> RedisLike:
    """默认 Redis 客户端（延迟 import：避免测试收集期触碰配置）。"""
    from app.core.redis import redis_client

    return cast(RedisLike, redis_client)


def _resolve(redis: RedisLike | None) -> RedisLike:
    return redis if redis is not None else _get_redis()


def fingerprint_key(record_id: str) -> str:
    return f"{KEY_PREFIX}:{record_id}"


def _hash(payload: dict[str, Any]) -> str:
    """稳定 hash：键排序 + 紧凑分隔符，与字段顺序无关。"""
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _norm_text(value: Any) -> str:
    return (bd_fields.rich_text(value) or "").strip()


def _norm_select(value: Any) -> str:
    # 多选排序去重后拼接：选项顺序变化不算内容变化
    return ", ".join(sorted(set(bd_fields.select_values(value))))


def _norm_ai_value(name: str, value: Any) -> str:
    if name in _AI_SELECT_FIELDS:
        return _norm_select(value)
    return _norm_text(value)


def compute_input_hash(fields: dict[str, Any]) -> str:
    """输入指纹：隐患描述 + 缺陷图 file_token 清单（排序去重）。"""
    tokens = sorted(
        {
            item["file_token"]
            for item in bd_fields.attachment_list(fields.get(F_PHOTO_DEFECT))
        }
    )
    return _hash({"desc": _norm_text(fields.get(F_DESC)), "photos": tokens})


def compute_ai_hash(values: dict[str, Any]) -> str:
    """AI 结论列指纹：6 个结论列归一值（写回 dict 与记录 fields 同口径）。"""
    return _hash(
        {name: _norm_ai_value(name, values.get(name)) for name in AI_HASH_FIELDS}
    )


async def record_fingerprint(
    record_id: str,
    *,
    snapshot_fields: dict[str, Any] | None,
    writeback: dict[str, Any],
    redis: RedisLike | None = None,
) -> bool:
    """① 写回成功后落双指纹基线（fail-open，失败只记日志）。

    ``snapshot_fields`` 是轮询/重跑取数时的 fields（输入指纹来源，零额外读）；
    ``writeback`` 是本次实际写回的列值 dict。AI 列指纹取**合并写后态**：
    ``snapshot_fields ∪ writeback``（写了的列用新值、output 为空未写的列保留
    快照旧值）——``write_ai_analysis`` 逐列条件写（`if output.get(...)`），
    直接用 writeback 会把未写列归一为空，下次扫描误判 ai_edited。
    缺 ``snapshot_fields`` 的调用方（无快照路径）跳过——无输入快照不落基线。
    """
    if not record_id or snapshot_fields is None:
        return False
    try:
        merged_after = {**snapshot_fields, **writeback}
        payload = {
            "input_hash": compute_input_hash(snapshot_fields),
            "ai_hash": compute_ai_hash(merged_after),
            "written_at": time.time(),
        }
        await _resolve(redis).set(
            fingerprint_key(record_id), json.dumps(payload, ensure_ascii=False)
        )
        return True
    except Exception:  # noqa: BLE001 — 基线写入失败不影响写回主链
        logger.exception(
            "指纹基线写入失败（fail-open）: record_id=%s", record_id
        )
        return False


async def load_fingerprint(
    record_id: str,
    *,
    redis: RedisLike | None = None,
) -> dict[str, Any] | None:
    """读基线（无键/损坏/Redis 故障 → None，fail-open）。"""
    try:
        raw = await _resolve(redis).get(fingerprint_key(record_id))
    except Exception:  # noqa: BLE001
        logger.warning(
            "指纹基线读取失败（按无基线处理）: record_id=%s",
            record_id,
            exc_info=True,
        )
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("指纹基线损坏（按无基线处理）: record_id=%s", record_id)
        return None
    if not isinstance(data, dict) or "input_hash" not in data or "ai_hash" not in data:
        return None
    return data


async def classify(
    record_id: str,
    current_fields: dict[str, Any],
    *,
    redis: RedisLike | None = None,
) -> str:
    """按当前记录 fields 与基线比对 → 四态之一（见模块 docstring）。"""
    baseline = await load_fingerprint(record_id, redis=redis)
    if baseline is None:
        return STATE_NO_BASELINE
    if compute_ai_hash(current_fields) != baseline.get("ai_hash"):
        return STATE_AI_EDITED  # 保护优先：输入与 AI 列都变也判 ai_edited
    if compute_input_hash(current_fields) != baseline.get("input_hash"):
        return STATE_INPUT_CHANGED
    return STATE_FRESH


# ── 全表扫描（T02：纯聚合，吃 Bitable records，零取数 IO） ────────


@dataclass
class StaleCandidate:
    """一条 stale 候选（带台账摘要，供 dry-run 报告与重算清单展示）。"""

    record_id: str
    hazard_no: str
    description: str
    state: str  # STATE_INPUT_CHANGED | STATE_AI_EDITED


@dataclass
class StaleScanResult:
    """全表扫描结果：两组候选清单 + 两态计数（fresh/no_baseline 不列明细）。"""

    input_changed: list[StaleCandidate] = field(default_factory=list)
    ai_edited: list[StaleCandidate] = field(default_factory=list)
    fresh: int = 0
    no_baseline: int = 0
    total: int = 0


def ai_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, str]:
    """6 个结论列的前后差异摘要（未变列不出现；空值显示「空」）。

    供 stale 按需重算的前后 diff 留痕与报告（spec US4）。
    """
    diff: dict[str, str] = {}
    for name in AI_HASH_FIELDS:
        old = _norm_ai_value(name, before.get(name))
        new = _norm_ai_value(name, after.get(name))
        if old != new:
            diff[name] = f"{old or '空'} → {new or '空'}"
    return diff


async def scan_records(
    records: list[dict[str, Any]],
    *,
    redis: RedisLike | None = None,
) -> StaleScanResult:
    """对全表 records 逐条 ``classify`` → 分组聚合（Redis 故障全表降级
    no_baseline，不抛——dry-run 报告仍可产出）。"""
    result = StaleScanResult(total=len(records))
    for record in records:
        record_id = record.get("record_id") or ""
        fields_dict = record.get("fields") or {}
        state = await classify(record_id, fields_dict, redis=redis)
        if state in (STATE_INPUT_CHANGED, STATE_AI_EDITED):
            candidate = StaleCandidate(
                record_id=record_id,
                hazard_no=(bd_fields.text(fields_dict, F_NO) or ""),
                description=(bd_fields.text(fields_dict, F_DESC) or "")[:40],
                state=state,
            )
            (
                result.input_changed
                if state == STATE_INPUT_CHANGED
                else result.ai_edited
            ).append(candidate)
        elif state == STATE_FRESH:
            result.fresh += 1
        else:
            result.no_baseline += 1
    return result
