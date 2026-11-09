"""票据 08：hazard 回写迁移到底座 writer 后的语义保持单测。

背景：迁移前 write_ai_analysis / write_review 直接调 client.update_record；
迁移后走底座 write_serial（单条、无间隔）。本测试锁定对外可观察行为不变：
成功返回 True、失败或异常返回 False（调用方据此抛错）、只写预期字段、
单选字段不做数组包装。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.hazard_direct import bitable_repo


class FakeWriter:
    """替身：只实现底座写入协议 update_record(record_id, fields)。"""

    def __init__(self, *, ok: bool = True, boom: bool = False) -> None:
        self.ok = ok
        self.boom = boom
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def update_record(self, record_id: str, fields: dict[str, Any]) -> bool:
        self.calls.append((record_id, fields))
        if self.boom:
            raise RuntimeError("boom")
        return self.ok


async def test_write_review_returns_true_on_success() -> None:
    writer = FakeWriter()

    ok = await bitable_repo.write_review(
        writer, "rec1", conclusion="已通过", summary="说明"
    )

    assert ok is True
    assert writer.calls == [("rec1", {"AI初审结果": "已通过", "AI初审说明": "说明"})]


async def test_write_review_returns_false_when_client_returns_false() -> None:
    ok = await bitable_repo.write_review(
        FakeWriter(ok=False), "rec1", conclusion="已通过", summary="说明"
    )

    assert ok is False


async def test_write_review_returns_false_when_client_raises() -> None:
    """底座 write_serial 把异常记入 failed 不再上抛；对外仍是 False（调用方据此抛错）。"""
    ok = await bitable_repo.write_review(
        FakeWriter(boom=True), "rec1", conclusion="已通过", summary="说明"
    )

    assert ok is False


async def test_write_ai_analysis_keeps_single_select_labels_as_str() -> None:
    """4 个回写字段在生产表均为单选（type=3），整形后应原样写入字符串。"""
    writer = FakeWriter()
    output = {
        "hazard_type": "unsafe_action",
        "hazard_level": "general",
        "hazard_category": "equipment",
        "key_defect": "缺陷描述",
    }

    ok = await bitable_repo.write_ai_analysis(
        writer, "rec2", hazard_no=None, output=output, supervision_label="一般预警"
    )

    assert ok is True
    _, fields = writer.calls[0]
    for name in ("隐患分类（AI）", "隐患级别（AI）", "隐患类别（AI）", "督办等级"):
        assert name in fields, name
        assert isinstance(fields[name], str), name
    assert fields["隐患描述（AI）"] == "缺陷描述"


async def test_write_ai_analysis_skips_when_nothing_to_write() -> None:
    writer = FakeWriter()

    ok = await bitable_repo.write_ai_analysis(writer, "rec3", hazard_no=None, output={})

    assert ok is False
    assert writer.calls == []


# ═══════════════════════════════════════════════════════════════
# P1-2/D5：写回护栏 CAS（①③⑤ 写前回读，目标列变更即跳过）
# ═══════════════════════════════════════════════════════════════


class FakeCasWriter(FakeWriter):
    """FakeWriter + get_record 回读（current_fields 模拟写前现值）。"""

    def __init__(self, current_fields: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.current_fields = current_fields

    async def get_record(self, record_id: str) -> dict[str, Any]:
        return dict(self.current_fields or {})


def test_cas_field_conflicts_pure_compare() -> None:
    """纯比对：同值（含 list/str 多选格式等价）不算冲突；值变更/新增算。"""
    snapshot = {
        "隐患级别（AI）": "",
        "隐患分类（AI）": ["物的不安全状态"],
        "隐患描述（AI）": "旧描述",
    }
    same = {
        "隐患级别（AI）": None,
        "隐患分类（AI）": "物的不安全状态",
        "隐患描述（AI）": [{"type": "text", "text": "旧描述"}],
    }
    assert bitable_repo.cas_field_conflicts(
        snapshot, same,
        {"隐患级别（AI）": "select", "隐患分类（AI）": "select", "隐患描述（AI）": "text"},
    ) == []
    changed = dict(same, **{"隐患级别（AI）": "一般隐患"})
    assert bitable_repo.cas_field_conflicts(
        snapshot, changed, {"隐患级别（AI）": "select"}
    ) == ["隐患级别（AI）"]


async def test_write_ai_analysis_conflict_skips_put() -> None:
    """① CAS：分类（AI）已被并发写值 → 抛 WriteConflictError，零 PUT。"""

    writer = FakeCasWriter(current_fields={"隐患分类（AI）": "管理的缺陷"})
    snapshot = {"隐患分类（AI）": ""}

    with pytest.raises(bitable_repo.WriteConflictError):
        await bitable_repo.write_ai_analysis(
            writer,
            "rec-cas1",
            hazard_no=None,
            output={"hazard_type": "unsafe_action", "hazard_level": "general"},
            supervision_label=None,
            snapshot_fields=snapshot,
        )
    assert writer.calls == []


async def test_write_ai_analysis_no_conflict_writes() -> None:
    """① CAS：目标列与快照一致 → 正常 PUT。"""
    writer = FakeCasWriter(current_fields={"隐患分类（AI）": ""})
    snapshot = {"隐患分类（AI）": ""}

    ok = await bitable_repo.write_ai_analysis(
        writer,
        "rec-cas2",
        hazard_no="HZ-1",
        output={"hazard_type": "unsafe_action"},
        supervision_label=None,
        snapshot_fields=snapshot,
    )
    assert ok is True
    assert len(writer.calls) == 1


async def test_write_ai_analysis_cas_failopen_on_empty_read() -> None:
    """① CAS：get_record 返回空（客户端失败语义）→ fail-open 放行写入。"""
    writer = FakeCasWriter(current_fields=None)

    ok = await bitable_repo.write_ai_analysis(
        writer,
        "rec-cas3",
        hazard_no=None,
        output={"hazard_type": "unsafe_action"},
        supervision_label=None,
        snapshot_fields={"隐患分类（AI）": ""},
    )
    assert ok is True
    assert len(writer.calls) == 1


async def test_write_scoring_conflict_skips_put() -> None:
    """⑤ CAS：人工已填评分（快照时空）→ 冲突跳过，零 PUT。"""

    writer = FakeCasWriter(current_fields={"评分结果": 88.0})

    with pytest.raises(bitable_repo.WriteConflictError):
        await bitable_repo.write_scoring(
            writer,
            "rec-cas4",
            total=61.5,
            note="评分说明",
            snapshot_fields={},
        )
    assert writer.calls == []


async def test_write_scoring_no_conflict_writes() -> None:
    writer = FakeCasWriter(current_fields={"评分结果": None})

    ok = await bitable_repo.write_scoring(
        writer,
        "rec-cas5",
        total=61.5,
        note="评分说明",
        snapshot_fields={},
    )
    assert ok is True
    assert len(writer.calls) == 1


async def test_writeback_supervision_label_conflict_and_ok() -> None:
    """③ CAS：督办等级被并发改写 → 冲突跳过；未变 → 正常写。"""

    from app.modules.safety.service.hazard_direct import supervision

    # 冲突分支：快照=一般预警，回读=红色预警（窗口内被改）→ 抛错零写
    writer = FakeCasWriter(current_fields={"督办等级": "红色预警"})
    with pytest.raises(bitable_repo.WriteConflictError):
        await supervision.writeback_supervision_label(
            writer, "rec-cas6", "一般预警", snapshot_label="一般预警"
        )
    assert writer.calls == []

    # 未变分支：回读与快照一致 → 正常写
    writer2 = FakeCasWriter(current_fields={"督办等级": "一般预警"})
    await supervision.writeback_supervision_label(
        writer2, "rec-cas7", "红色预警", snapshot_label="一般预警"
    )
    assert len(writer2.calls) == 1
