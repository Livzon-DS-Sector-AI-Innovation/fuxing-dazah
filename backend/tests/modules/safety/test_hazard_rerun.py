"""P3-1 T03 —— ① 定向重跑核心下沉（hazard_direct.rerun.rerun_record）。

覆盖 ticket 03 验收：全链 fake（identify 固定 output → 写回成功 → 失败账本
清账）、dry-run 不调 AI 不写、记录不存在 skip。与 P2-4 脚本版语义一致（纯下沉）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.hazard_direct import (
    ai_analysis,
    bitable_repo,
    failure_ledger,
)
from app.modules.safety.service.hazard_direct.rerun import rerun_record


class FakeRerunClient:
    """get_record（取数）+ update_record（写回）双面假件。"""

    def __init__(self, fields: dict[str, Any] | None = None) -> None:
        self.fields = fields if fields is not None else {
            "隐患描述": "配电箱门未上锁",
            "隐患分类（AI）": "人的不安全行为",
        }
        self.updated: list[tuple[str, dict[str, Any]]] = []

    async def get_record(self, record_id: str) -> dict[str, Any]:
        return dict(self.fields)

    async def update_record(
        self, record_id: str, fields: dict[str, Any]
    ) -> bool:
        self.updated.append((record_id, fields))
        return True


class FakeLockRedis:
    """record_lock 所需最小 Redis（set NX/get/delete）。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)
        return len(keys)


@pytest.fixture
def rerun_env(monkeypatch: pytest.MonkeyPatch):
    """全链 fake：identify 固定输出 + 失败账本 spy + 记录锁内存化。"""
    calls: dict[str, int] = {"success": 0}

    async def fake_identify(client: Any, view: Any, **kw: Any) -> dict[str, Any]:
        return {
            "hazard_type": "人的不安全行为",
            "hazard_level": "一般隐患",
            "hazard_category": "设备设施",
            "key_defect": "箱门未锁",
            "major_hazard_basis": "《某制度》第3条",
        }

    async def fake_success(record_id: str, **kw: Any) -> None:
        calls["success"] += 1

    monkeypatch.setattr(ai_analysis, "_identify_one", fake_identify)
    monkeypatch.setattr(failure_ledger, "record_success", fake_success)
    monkeypatch.setattr(bitable_repo, "redis_client", FakeLockRedis())
    return calls


async def test_rerun_record_confirm_writes_and_settles(rerun_env) -> None:
    client = FakeRerunClient()

    status, detail = await rerun_record(client, "rec-1", confirm=True)

    assert status == "done"
    assert "一般隐患" in detail
    # 写回发生且只写 AI 列
    rid, written = client.updated[0]
    assert rid == "rec-1"
    assert "隐患分类（AI）" in written
    # 失败账本清账
    assert rerun_env["success"] == 1


async def test_rerun_record_dry_run_never_writes(rerun_env) -> None:
    client = FakeRerunClient()

    status, _ = await rerun_record(client, "rec-2", confirm=False)

    assert status == "dry-run"
    assert client.updated == []
    assert rerun_env["success"] == 0


async def test_rerun_record_missing_record_skips(rerun_env) -> None:
    client = FakeRerunClient(fields={})

    status, _ = await rerun_record(client, "rec-gone", confirm=True)

    assert status == "skip"
    assert client.updated == []


async def test_rerun_record_confirm_success_refreshes_fingerprint(
    rerun_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重算成功 → 双指纹基线刷新（stale 自愈，spec §2）。"""
    from app.modules.safety.service.hazard_direct import stale_state
    from tests.modules.safety.conftest import _MemoryRedis

    fake = _MemoryRedis()
    monkeypatch.setattr(stale_state, "_get_redis", lambda: fake)
    client = FakeRerunClient()

    status, _ = await rerun_record(client, "rec-heal", confirm=True)

    assert status == "done"
    assert stale_state.fingerprint_key("rec-heal") in fake.store


# ── T04：stale 按需重算模式 ──────────────────────────────────────


def _mutable_client(records: list[dict[str, Any]]) -> FakeRerunClient:
    """按 record_id 取数 + 写回合并进 fields 的可变假件（模拟 Bitable 写后读）。"""
    records_map = {r["record_id"]: dict(r["fields"]) for r in records}
    client = FakeRerunClient(fields={})

    async def get_record(record_id: str) -> dict[str, Any]:
        return dict(records_map.get(record_id) or {})

    async def update_record(record_id: str, fields: dict[str, Any]) -> bool:
        client.updated.append((record_id, fields))
        records_map[record_id].update(fields)
        return True

    client.get_record = get_record  # type: ignore[method-assign]
    client.update_record = update_record  # type: ignore[method-assign]
    return client


async def _seed_two_hashes(fake, record_id: str, *, ai_level: str) -> None:
    from app.modules.safety.service.hazard_direct import stale_state

    ok = await stale_state.record_fingerprint(
        record_id,
        snapshot_fields={
            "隐患描述": "描述甲",
            "缺陷图片": [{"file_token": "tok-1"}],
            "隐患级别（AI）": ai_level,
        },
        writeback={"隐患级别（AI）": ai_level},
        redis=fake,
    )
    assert ok is True


def _stale_records() -> list[dict[str, Any]]:
    """4 条：input×2（描述已人工改）+ ai_edited×1（级别（AI）被人工改）+ 无基线×1。"""
    return [
        {"record_id": "rec-in1", "fields": {
            "隐患描述": "描述甲（人工已改）", "缺陷图片": [{"file_token": "tok-1"}],
            "隐患级别（AI）": "较大隐患",
        }},
        {"record_id": "rec-in2", "fields": {
            "隐患描述": "描述乙（人工已改）", "缺陷图片": [],
            "隐患级别（AI）": "一般隐患",
        }},
        {"record_id": "rec-protect", "fields": {
            "隐患描述": "描述丙", "缺陷图片": [],
            "隐患级别（AI）": "重大隐患",  # 基线=较大 → 人工改过 AI 列
        }},
        {"record_id": "rec-nobase", "fields": {
            "隐患描述": "描述丁", "缺陷图片": [],
        }},
    ]


async def _seed_baselines(monkeypatch: pytest.MonkeyPatch):
    from app.modules.safety.service.hazard_direct import stale_state
    from tests.modules.safety.conftest import _MemoryRedis

    fake = _MemoryRedis()
    monkeypatch.setattr(stale_state, "_get_redis", lambda: fake)
    await _seed_two_hashes(fake, "rec-in1", ai_level="较大隐患")
    await _seed_two_hashes(fake, "rec-in2", ai_level="一般隐患")
    await _seed_two_hashes(fake, "rec-protect", ai_level="较大隐患")
    return fake


def _trace_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from app.modules.safety.service.hazard_direct import writeback_trace

    captured: list[dict[str, Any]] = []

    async def spy(**kw: Any) -> bool:
        captured.append(kw)
        return True

    monkeypatch.setattr(writeback_trace, "record_writeback", spy)
    return captured


async def test_stale_rerun_only_touches_input_changed(
    rerun_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--stale 语义：只重算 input_changed；ai_edited 保护、无基线不动。"""
    from app.modules.safety.service.hazard_direct.rerun import stale_rerun

    await _seed_baselines(monkeypatch)
    client = _mutable_client(_stale_records())
    trace = _trace_spy(monkeypatch)

    report = await stale_rerun(
        client,
        _stale_records(),
        limit=10,
        registry_cap=20,
        confirm=True,
    )

    assert report.done == 2
    touched = {rid for rid, _ in client.updated}
    assert touched == {"rec-in1", "rec-in2"}
    assert report.protected == ["rec-protect"]
    assert report.skipped == 0 and report.failed == 0
    # diff 留痕：writer=ai_rerun，note 含级别前后值
    rerun_traces = [t for t in trace if t.get("writer") == "ai_rerun"]
    assert len(rerun_traces) == 2
    notes = " ".join(t.get("note", "") for t in rerun_traces)
    assert "较大隐患 → 一般隐患" in notes  # rec-in1 级别被重算改写


async def test_stale_rerun_limit_clamps_to_registry_cap(
    rerun_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """双重钳制取小：CLI limit 50 > registry 3 → 只跑 3 条。"""
    from app.modules.safety.service.hazard_direct.rerun import stale_rerun

    fake = await _seed_baselines(monkeypatch)

    # 追加 3 条 input_changed（rec-x1..x3），共 5 条候选
    for i in range(1, 4):
        await _seed_two_hashes(fake, f"rec-x{i}", ai_level="一般隐患")
    records = _stale_records() + [
        {"record_id": f"rec-x{i}", "fields": {
            "隐患描述": f"描述x{i}（人工已改）", "缺陷图片": [],
            "隐患级别（AI）": "一般隐患",
        }}
        for i in range(1, 4)
    ]
    client = _mutable_client(records)

    report = await stale_rerun(
        client, records, limit=50, registry_cap=3, confirm=True
    )

    assert report.done == 3
    assert len(client.updated) == 3


async def test_stale_rerun_dry_run_writes_nothing(
    rerun_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.safety.service.hazard_direct.rerun import stale_rerun

    await _seed_baselines(monkeypatch)
    client = _mutable_client(_stale_records())

    report = await stale_rerun(
        client, _stale_records(), limit=10, registry_cap=20, confirm=False
    )

    assert client.updated == []
    assert report.done == 0
    assert report.dry_run == 2


async def test_stale_rerun_counts_skip_separately(
    rerun_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """候选记录读取失败（skip）单列计数，不算 failed（口径同脚本版）。"""
    from app.modules.safety.service.hazard_direct.rerun import stale_rerun

    await _seed_baselines(monkeypatch)
    # rec-in1 基线在、但取数失败：从可变假件里抹掉它的 fields → get_record 返回 {}
    records = _stale_records()
    client = _mutable_client(records)
    client.fields = {}
    original_get = client.get_record

    async def missing_get(record_id: str) -> dict[str, Any]:
        if record_id == "rec-in1":
            return {}
        return await original_get(record_id)

    client.get_record = missing_get  # type: ignore[method-assign]

    report = await stale_rerun(
        client, records, limit=10, registry_cap=20, confirm=True
    )

    assert report.done == 1  # rec-in2 正常
    assert report.skipped == 1  # rec-in1 skip
    assert report.failed == 0
