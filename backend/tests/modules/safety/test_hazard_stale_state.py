"""P3-1 T01 —— AI 结论时效双指纹核心（fake RedisLike 单测，不连真实 Redis）。

覆盖 ticket 01 验收（spec §5）：
- 输入指纹归一：文本 strip、附件 token 排序去重后稳定；描述/附件变化 → hash 变；
- AI 列指纹只覆盖 ① 写回的 6 个结论列（编号/督办等级不参与）；
  单选 str / list / 结构化选项归一后同 hash；
- record_fingerprint 落 JSON 基线；snapshot 缺失跳过；Redis 故障 fail-open；
- classify 四态：fresh / input_changed / ai_edited / no_baseline；
  双变时保护优先（ai_edited）；
- 写回挂钩：write_ai_analysis 成功后落指纹；CAS 冲突不落；无快照不落。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.safety.service.hazard_direct import bitable_repo, stale_state
from app.modules.safety.service.hazard_direct.field_authority import F_BASIS_AI


class FakeRedis:
    """最小 RedisLike 假件（get/set 即可，指纹存储只用这两个）。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.fail = False
        self.calls: list[str] = []

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def get(self, key: str) -> Any:
        self._check()
        self.calls.append(f"get:{key}")
        return self.store.get(key)

    async def set(
        self, key: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> Any:
        self._check()
        self.calls.append(f"set:{key}")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


def _fields(
    *,
    desc: str = "配电箱门未上锁",
    photos: list[str] | None = None,
    **ai_cols: Any,
) -> dict[str, Any]:
    """构造一条记录的 fields（描述 + 缺陷图 + 任意 AI 列覆盖）。"""
    fields: dict[str, Any] = {
        "隐患描述": desc,
        "缺陷图片": [{"file_token": tok} for tok in (photos or [])],
    }
    fields.update(ai_cols)
    return fields


# ── 输入指纹 ──────────────────────────────────────────────────────


def test_input_hash_stable_under_whitespace_and_photo_order() -> None:
    a = _fields(desc="  配电箱门未上锁  ", photos=["tok-b", "tok-a"])
    b = _fields(desc="配电箱门未上锁", photos=["tok-a", "tok-b"])
    assert stale_state.compute_input_hash(a) == stale_state.compute_input_hash(b)


def test_input_hash_changes_on_desc_or_photo() -> None:
    base = _fields(desc="配电箱门未上锁", photos=["tok-a"])
    changed_desc = _fields(desc="配电箱门未上锁且线缆裸露", photos=["tok-a"])
    changed_photo = _fields(desc="配电箱门未上锁", photos=["tok-a", "tok-b"])
    h = stale_state.compute_input_hash(base)
    assert stale_state.compute_input_hash(changed_desc) != h
    assert stale_state.compute_input_hash(changed_photo) != h


def test_input_hash_dedupes_repeated_photo_tokens() -> None:
    dup = _fields(photos=["tok-a", "tok-a"])
    once = _fields(photos=["tok-a"])
    assert stale_state.compute_input_hash(dup) == stale_state.compute_input_hash(once)


# ── AI 列指纹 ─────────────────────────────────────────────────────


def test_ai_hash_covers_six_conclusion_columns_only() -> None:
    base = {
        "隐患分类（AI）": "人的不安全行为",
        "隐患级别（AI）": "一般隐患",
        "隐患类别（AI）": "设备设施",
        "隐患描述（AI）": "箱门未锁",
        F_BASIS_AI: "《X》第1条",
        "整改建议（AI）": "立即上锁",
        # 以下两列在 ① 写回集合里但不属于结论列（编号非结论；督办多写者 C9）
        "隐患编号": "YH-001",
        "督办等级": "一般预警",
    }
    h = stale_state.compute_ai_hash(base)
    # 编号/督办变化不影响 AI 列指纹
    no_and_supervision_changed = {**base, "隐患编号": "YH-999", "督办等级": "红色预警"}
    assert stale_state.compute_ai_hash(no_and_supervision_changed) == h
    # 任一结论列变化 → hash 变（含第 6 列判定依据）
    level_changed = {**base, "隐患级别（AI）": "较大隐患"}
    assert stale_state.compute_ai_hash(level_changed) != h
    basis_changed = {**base, F_BASIS_AI: "《Y》第2条"}
    assert stale_state.compute_ai_hash(basis_changed) != h


def test_ai_hash_normalizes_select_str_and_list() -> None:
    as_str = {"隐患级别（AI）": "一般隐患"}
    as_list = {"隐患级别（AI）": ["一般隐患"]}
    structured = {"隐患级别（AI）": [{"name": "一般隐患"}]}
    h = stale_state.compute_ai_hash(as_str)
    assert stale_state.compute_ai_hash(as_list) == h
    assert stale_state.compute_ai_hash(structured) == h


# ── 基线存取与 fail-open ─────────────────────────────────────────


async def test_record_fingerprint_stores_baseline() -> None:
    redis = FakeRedis()
    snapshot = _fields(desc="描述甲", photos=["tok-1"])
    writeback = {"隐患分类（AI）": "人的不安全行为", "隐患编号": "YH-1"}
    ok = await stale_state.record_fingerprint(
        "rec-1", snapshot_fields=snapshot, writeback=writeback, redis=redis
    )
    assert ok is True
    raw = redis.store[stale_state.fingerprint_key("rec-1")]
    data = json.loads(raw)
    assert set(data) == {"input_hash", "ai_hash", "written_at"}
    assert data["input_hash"] == stale_state.compute_input_hash(snapshot)
    assert data["ai_hash"] == stale_state.compute_ai_hash(writeback)


async def test_record_fingerprint_failopen_on_redis_error() -> None:
    redis = FakeRedis()
    redis.fail = True
    ok = await stale_state.record_fingerprint(
        "rec-2", snapshot_fields=_fields(), writeback={}, redis=redis
    )
    assert ok is False  # 不抛


async def test_record_fingerprint_without_snapshot_skips() -> None:
    redis = FakeRedis()
    ok = await stale_state.record_fingerprint(
        "rec-3", snapshot_fields=None, writeback={}, redis=redis
    )
    assert ok is False
    assert not any(c.startswith("set:") for c in redis.calls)


async def test_record_fingerprint_merges_unwritten_columns() -> None:
    """D6 精确性：①逐列条件写——output 空的列不写、Bitable 留旧值；基线
    必须取「snapshot ∪ writeback」合并态，否则未写列被归一为空 → 下次扫描
    误判 ai_edited（保护清单假阳性，永不重算）。"""
    redis = FakeRedis()
    snapshot = _fields(
        desc="描述甲",
        **{
            "隐患分类（AI）": "人的不安全行为",
            F_BASIS_AI: "《旧制度》第1条",  # 本次 output 无依据 → 不写、留旧值
        },
    )
    writeback = {"隐患分类（AI）": "人的不安全行为", "隐患编号": "YH-1"}

    ok = await stale_state.record_fingerprint(
        "rec-merge", snapshot_fields=snapshot, writeback=writeback, redis=redis
    )
    assert ok is True

    # 扫描时记录现值=合并态（分类新值+依据旧值）→ fresh，不误判保护
    current = _fields(
        desc="描述甲",
        **{
            "隐患分类（AI）": "人的不安全行为",
            F_BASIS_AI: "《旧制度》第1条",
        },
    )
    assert await stale_state.classify("rec-merge", current, redis=redis) == "fresh"


# ── 分类四态 ──────────────────────────────────────────────────────


async def _seed(redis: FakeRedis, record_id: str) -> None:
    """统一基线：描述甲 + tok-1 + 分类（AI）=人的不安全行为。"""
    seeded = await stale_state.record_fingerprint(
        record_id,
        snapshot_fields=_fields(
            desc="描述甲", photos=["tok-1"], **{"隐患分类（AI）": "人的不安全行为"}
        ),
        writeback={"隐患分类（AI）": "人的不安全行为"},
        redis=redis,
    )
    assert seeded is True


async def test_classify_four_states() -> None:
    redis = FakeRedis()
    for rid in ("rec-fresh", "rec-input", "rec-aiedit", "rec-both"):
        await _seed(redis, rid)

    unchanged = _fields(
        desc="描述甲", photos=["tok-1"], **{"隐患分类（AI）": "人的不安全行为"}
    )
    assert await stale_state.classify("rec-fresh", unchanged, redis=redis) == "fresh"
    assert (
        await stale_state.classify("rec-nobase", unchanged, redis=redis)
        == "no_baseline"
    )

    desc_changed = _fields(
        desc="描述甲（人工已改）", photos=["tok-1"],
        **{"隐患分类（AI）": "人的不安全行为"},
    )
    assert (
        await stale_state.classify("rec-input", desc_changed, redis=redis)
        == "input_changed"
    )

    ai_changed = _fields(
        desc="描述甲", photos=["tok-1"], **{"隐患分类（AI）": "管理缺陷"}
    )
    assert (
        await stale_state.classify("rec-aiedit", ai_changed, redis=redis) == "ai_edited"
    )

    both_changed = _fields(
        desc="描述甲（人工已改）", photos=["tok-1"],
        **{"隐患分类（AI）": "管理缺陷"},
    )
    # 双变 → 保护优先：判 ai_edited，不进自动重算
    assert (
        await stale_state.classify("rec-both", both_changed, redis=redis) == "ai_edited"
    )


async def test_classify_redis_error_returns_no_baseline() -> None:
    redis = FakeRedis()
    redis.fail = True
    assert await stale_state.classify("rec-x", _fields(), redis=redis) == "no_baseline"


# ── 全表扫描（T02） ───────────────────────────────────────────────


async def test_scan_records_groups_and_counts() -> None:
    redis = FakeRedis()
    for rid in ("rec-fresh", "rec-input", "rec-aiedit"):
        await _seed(redis, rid)

    def _record(rid: str, **override: Any) -> dict[str, Any]:
        base = _fields(
            desc="描述甲",
            photos=["tok-1"],
            **{"隐患分类（AI）": "人的不安全行为"},
        )
        base.update(override)
        return {"record_id": rid, "fields": base}

    records = [
        _record("rec-fresh", **{"隐患编号": "YH-001"}),
        _record("rec-input", 隐患描述="描述乙"),
        _record("rec-aiedit", **{"隐患分类（AI）": "管理缺陷"}),
        _record("rec-nobase", 隐患描述="描述丙"),
    ]
    result = await stale_state.scan_records(records, redis=redis)

    assert result.total == 4
    assert [c.record_id for c in result.input_changed] == ["rec-input"]
    assert [c.record_id for c in result.ai_edited] == ["rec-aiedit"]
    assert result.fresh == 1
    assert result.no_baseline == 1
    # 候选行带台账摘要字段（编号/描述）供报告展示
    assert result.input_changed[0].hazard_no == ""
    assert result.input_changed[0].description == "描述乙"


async def test_scan_records_redis_error_all_no_baseline() -> None:
    redis = FakeRedis()
    redis.fail = True
    records = [{"record_id": f"rec-{i}", "fields": _fields()} for i in range(3)]
    result = await stale_state.scan_records(records, redis=redis)
    assert result.no_baseline == 3
    assert result.input_changed == [] and result.ai_edited == []
    assert result.total == 3


# ── AI 列 diff（T04：重算前后差异摘要） ──────────────────────────


def test_ai_diff_reports_changed_columns_only() -> None:
    before = {
        "隐患分类（AI）": "人的不安全行为",
        "隐患级别（AI）": "一般隐患",
        "隐患描述（AI）": "旧描述",
    }
    after = {
        "隐患分类（AI）": "人的不安全行为",  # 未变
        "隐患级别（AI）": "重大隐患",
        "隐患描述（AI）": "新描述",
    }
    diff = stale_state.ai_diff(before, after)
    assert diff == {
        "隐患级别（AI）": "一般隐患 → 重大隐患",
        "隐患描述（AI）": "旧描述 → 新描述",
    }


# ── 写回挂钩（write_ai_analysis 行为面） ─────────────────────────


class FakeWriter:
    """bitable_writer.write_serial 假件（成功写回；形态同既有 writeback 测试）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def update_record(self, record_id: str, fields: dict[str, Any]) -> bool:
        self.calls.append((record_id, fields))
        return True


class FakeCasWriter(FakeWriter):
    """+ get_record 回读（current_fields 模拟写前现值；值变即冲突）。"""

    def __init__(self, current_fields: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.current_fields = current_fields

    async def get_record(self, record_id: str) -> dict[str, Any]:
        return dict(self.current_fields or {})


_OUTPUT = {
    "hazard_type": "unsafe_action",
    "hazard_level": "general",
    "hazard_category": "equipment",
    "key_defect": "箱门未锁",
    "major_hazard_basis": "《X》第1条",
}


async def test_write_ai_analysis_records_fingerprint_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(stale_state, "_get_redis", lambda: redis)
    writer = FakeWriter()
    snapshot = _fields(desc="描述甲", photos=["tok-1"])

    ok = await bitable_repo.write_ai_analysis(
        writer,  # type: ignore[arg-type]
        "rec-ok",
        hazard_no="YH-1",
        output=dict(_OUTPUT),
        snapshot_fields=snapshot,
    )

    assert ok is True
    assert stale_state.fingerprint_key("rec-ok") in redis.store


async def test_write_ai_analysis_conflict_writes_no_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.service.hazard_direct.bitable_repo import (
        WriteConflictError,
    )

    redis = FakeRedis()
    monkeypatch.setattr(stale_state, "_get_redis", lambda: redis)
    # 快照分类（AI）为空；写前回读已被并发填值 → 冲突
    writer = FakeCasWriter(current_fields={"隐患分类（AI）": "管理的缺陷"})

    with pytest.raises(WriteConflictError):
        await bitable_repo.write_ai_analysis(
            writer,  # type: ignore[arg-type]
            "rec-conflict",
            hazard_no=None,
            output=dict(_OUTPUT),
            snapshot_fields={"隐患分类（AI）": ""},
        )
    assert stale_state.fingerprint_key("rec-conflict") not in redis.store


async def test_write_ai_analysis_without_snapshot_no_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(stale_state, "_get_redis", lambda: redis)
    writer = FakeWriter()

    ok = await bitable_repo.write_ai_analysis(
        writer,  # type: ignore[arg-type]
        "rec-nosnap",
        hazard_no=None,
        output=dict(_OUTPUT),
    )

    assert ok is True
    assert not redis.store
