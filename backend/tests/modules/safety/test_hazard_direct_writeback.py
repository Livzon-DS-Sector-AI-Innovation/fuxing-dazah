"""票据 08：hazard 回写迁移到底座 writer 后的语义保持单测。

背景：迁移前 write_ai_analysis / write_review 直接调 client.update_record；
迁移后走底座 write_serial（单条、无间隔）。本测试锁定对外可观察行为不变：
成功返回 True、失败或异常返回 False（调用方据此抛错）、只写预期字段、
单选字段不做数组包装。
"""

from __future__ import annotations

from typing import Any

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
