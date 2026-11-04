"""台账署名追加（留痕方向 A）—— 覆盖写改追加，提交带【卡片提交·时间·姓名】前缀。

设计依据：DM 卡表单交互零变化，只改写入语义——「目前进展」从「最新一段覆盖」
变成「有 attribution 的追加历史」。③轮询 compute_marks 按全文字 hash 判进展
变化，追加语义天然兼容。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.safety.feishu import progress_card
from app.modules.safety.feishu.progress_card import (
    append_progress_value,
    build_submission_line,
    push_progress_note_to_bitable,
    resolve_operator_name,
)

_BJ = ZoneInfo("Asia/Shanghai")


# ═══════════════════════════════════════════════════════════════
# 纯函数：行格式 / 追加 / 署名解析
# ═══════════════════════════════════════════════════════════════


def test_submission_line_format() -> None:
    """【卡片提交·YYYY-MM-DD HH:mm·姓名】原文（北京时间）。"""
    line = build_submission_line(
        "明天施工", "张三", at=datetime(2026, 11, 4, 9, 5, tzinfo=_BJ),
    )
    assert line == "【卡片提交·2026-11-04 09:05·张三】明天施工"


def test_append_progress_value() -> None:
    """空值=仅新行；有值=空行分隔追加（不改写历史）；尾部空白规整。"""
    line = "【卡片提交·2026-11-04 09:05·张三】明天施工"
    assert append_progress_value("", line) == line
    assert append_progress_value("原有进展A", line) == "原有进展A\n\n" + line
    assert append_progress_value("原有进展A\n", line) == "原有进展A\n\n" + line


def test_resolve_operator_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """三层：open_id 反查 / user_id 直查 / 兜底尾 12 位 / 空=未知。"""
    from app.modules.safety.feishu import bitable_id_mapper

    monkeypatch.setattr(
        bitable_id_mapper, "get_name_by_bitable_open_id",
        lambda oid: "张三" if oid == "ou_hit" else None,
    )
    monkeypatch.setattr(
        bitable_id_mapper, "get_name_by_user_id",
        lambda uid: "李四" if uid == "111003032" else None,
    )
    assert resolve_operator_name("ou_hit") == "张三"
    assert resolve_operator_name("111003032") == "李四"
    assert resolve_operator_name("ou_abcdef1234567890abcd") == "ou_abcdef1234567890abcd"[-12:]
    assert resolve_operator_name("") == "未知"


# ═══════════════════════════════════════════════════════════════
# 写回链：读现值→追加署名行→只写「目前进展」
# ═══════════════════════════════════════════════════════════════


class FakeBitableClient:
    def __init__(self, *, progress: Any = "旧进展A") -> None:
        self.progress = progress
        self.update_calls: list[dict] = []

    async def get_record(self, record_id: str) -> dict:
        return {"整改状态": "未关闭", "目前进展": self.progress}

    async def update_record(self, record_id: str, fields: dict) -> bool:
        self.update_calls.append(dict(fields))
        return True


@pytest.fixture(autouse=True)
def _no_sync_ignore(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*a: Any, **kw: Any) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.safety.feishu.bitable_handler._set_sync_ignore", _noop,
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: FakeBitableClient) -> None:
    monkeypatch.setattr(
        "app.modules.safety.feishu.progress_card.SafetyBitableClient",
        lambda: fake,
    )
    from app.modules.safety.feishu import bitable_id_mapper

    monkeypatch.setattr(
        bitable_id_mapper, "get_name_by_bitable_open_id",
        lambda oid: "张三" if oid == "ou_zhang" else None,
    )
    monkeypatch.setattr(
        bitable_id_mapper, "get_name_by_user_id",
        lambda uid: "李四" if uid == "111003032" else None,
    )


async def test_push_appends_attributed_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """提交=现值+署名行追加；只写「目前进展」一个字段。"""
    fake = FakeBitableClient(progress="旧进展A")
    _patch_client(monkeypatch, fake)

    ok = await push_progress_note_to_bitable(
        "rec_a1", "明天施工", operator_open_id="ou_zhang",
    )

    assert ok is True
    assert len(fake.update_calls) == 1
    value = fake.update_calls[0]["目前进展"]
    assert value.startswith("旧进展A\n\n【卡片提交·")
    assert value.endswith("·张三】明天施工")
    assert set(fake.update_calls[0]) == {"目前进展"}


async def test_push_appends_to_rich_text_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """现值为富文本 list → 拼接为纯文本再追加（Bitable 字段形态兼容）。"""
    fake = FakeBitableClient(
        progress=[{"type": "text", "text": "旧进展"}, {"type": "text", "text": "B"}],
    )
    _patch_client(monkeypatch, fake)

    ok = await push_progress_note_to_bitable(
        "rec_a2", "已完成", operator_open_id="ou_zhang",
    )

    assert ok is True
    value = fake.update_calls[0]["目前进展"]
    assert value.startswith("旧进展B\n\n【卡片提交·")


async def test_push_empty_operator_marks_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 operator（理论不应发生）→ 署名「未知」，不影响追加。"""
    fake = FakeBitableClient(progress="")
    _patch_client(monkeypatch, fake)

    await push_progress_note_to_bitable("rec_a3", "明天施工")

    assert fake.update_calls[0]["目前进展"].startswith("【卡片提交·")
    assert "·未知】明天施工" in fake.update_calls[0]["目前进展"]


async def test_push_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """update 失败 → False（best-effort 契约不变，仅告警不抛）。"""
    fake = FakeBitableClient()

    async def failing_update(record_id: str, fields: dict) -> bool:
        fake.update_calls.append(dict(fields))
        return False

    fake.update_record = failing_update  # type: ignore[method-assign]
    _patch_client(monkeypatch, fake)

    ok = await push_progress_note_to_bitable(
        "rec_a4", "明天施工", operator_open_id="ou_zhang",
    )
    assert ok is False


async def test_direct_submit_handler_passes_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """直读回调链：handle_progress_submit_direct → 回写带署名追加。"""
    fake = FakeBitableClient(progress="旧进展A")
    _patch_client(monkeypatch, fake)

    ack = await progress_card.handle_progress_submit_direct(
        "rec_direct1",
        {
            "action": {"form_value": {"progress": "阀门已订购"}},
            "operator": {"open_id": "ou_zhang", "user_id": ""},
        },
    )

    assert ack is None or isinstance(ack, dict)  # 无错误 toast 即成功路径
    value = fake.update_calls[-1]["目前进展"]
    assert value.startswith("旧进展A\n\n【卡片提交·")
    assert value.endswith("·张三】阀门已订购")
