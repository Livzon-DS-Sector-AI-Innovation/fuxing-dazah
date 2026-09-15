"""「安全速递」总卡单元测试：存储、格子构建、建卡/PATCH 滚动、超限收缩、开关。

纯内存桩验证，不依赖 Redis / 飞书网络。总卡格子不带图片（纯文字概览+折叠面板）。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, cast

import pytest

from app.modules.safety.feishu.daily_digest import DigestCell, upsert_daily_digest
from app.modules.safety.feishu.notification import build_card_dict

D = date(2026, 9, 15)


class _FakeStore:
    """内存版 redis hash/string 桩。"""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}

    async def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def expire(self, key: str, ttl: int) -> None:
        self.strings[f"ttl:{key}"] = str(ttl)

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self.strings[key] = value

    async def delete(self, key: str) -> None:
        self.strings.pop(key, None)
        self.hashes.pop(key, None)


def _cell(detail: str = "明细内容") -> DigestCell:
    return DigestCell(
        tag_color="blue", tag_text="特殊作业", title="特殊作业日报",
        stats="今日计划 **14** 项", zone="高风险集中在发酵工程部",
        detail=detail,
    )


async def _ok_updater(msg_id: str, card: dict[str, Any]) -> bool:
    return True


def _first_cell_dict(card: dict[str, Any]) -> dict[str, Any]:
    # build_card_dict 的 body.elements[0] 是问候语 markdown，格子在其后
    return cast(dict[str, Any], card["body"]["elements"][1])


async def test_first_upsert_creates_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    sent: list[dict[str, Any]] = []
    updated: list[str] = []

    async def sender(**kw: Any) -> str | None:
        sent.append(kw)
        return "om_card_1"

    async def updater(msg_id: str, card: dict[str, Any]) -> bool:
        updated.append(msg_id)
        return True

    ok = await upsert_daily_digest(
        D, "special_op", _cell(), store=store, sender=sender, updater=updater,
    )
    assert ok is True
    assert sent and sent[0]["title"] == "📌 安全速递 | 2026-09-15"
    assert sent[0]["subtitle"] == "今日已汇总 1 项安全动态"
    assert updated == []  # 首格直接建卡，不走 PATCH
    assert store.strings["safety:daily_digest:card:2026-09-15"] == "om_card_1"

    # 卡片结构：蓝头 + 格子（灰底、纯文字列、含折叠面板、无图片）
    card = build_card_dict(
        sent[0]["title"], sent[0]["content"], "blue", sent[0]["elements"],
    )
    cell = _first_cell_dict(card)
    assert cell["tag"] == "column_set"
    assert cell["background_style"] == "grey"
    assert len(cell["columns"]) == 1  # 不带图片，只有文字列
    text_md = cell["columns"][0]["elements"][0]["content"]
    assert "<text_tag color='blue'>特殊作业</text_tag>" in text_md
    panel = cell["columns"][0]["elements"][1]
    assert panel["tag"] == "collapsible_panel"
    assert panel["expanded"] is False
    assert panel["header"]["title"]["content"] == "📄 查看详情"
    card_json = json.dumps(card, ensure_ascii=False)
    assert '"img"' not in card_json  # 整卡无图片元素


async def test_second_upsert_patches_same_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    calls: list[str] = []

    async def sender(**kw: Any) -> str | None:
        calls.append("create")
        return "om_card_1"

    async def updater(msg_id: str, card: dict[str, Any]) -> bool:
        calls.append(f"patch:{msg_id}")
        return True

    await upsert_daily_digest(
        D, "special_op", _cell(), store=store, sender=sender, updater=updater,
    )
    fire_cell = DigestCell(
        tag_color="red", tag_text="消防报警", title="消防报警日报",
        stats="今日报警 **6** 起", zone="误报 3", detail="报警明细",
    )
    ok = await upsert_daily_digest(
        D, "fire_alarm", fire_cell, store=store, sender=sender, updater=updater,
    )
    assert ok is True
    assert calls == ["create", "patch:om_card_1"]

    # 当日存储包含两个格子
    stored = await store.hgetall("safety:daily_digest:2026-09-15")
    assert set(stored) == {"special_op", "fire_alarm"}


async def test_patch_failure_falls_back_to_recreate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    calls: list[str] = []

    async def sender(**kw: Any) -> str | None:
        calls.append("create")
        return f"om_card_{len(calls)}"

    async def updater(msg_id: str, card: dict[str, Any]) -> bool:
        return False  # 模拟 PATCH 失败（如卡片被删）

    await upsert_daily_digest(
        D, "special_op", _cell(), store=store, sender=sender, updater=updater,
    )
    ok = await upsert_daily_digest(
        D, "fire_alarm", _cell(), store=store, sender=sender, updater=updater,
    )
    assert ok is True
    assert calls == ["create", "create"]  # PATCH 失败 → 重建新卡
    assert store.strings["safety:daily_digest:card:2026-09-15"] == "om_card_2"


async def test_disabled_flag_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_DAILY_DIGEST_ENABLED", "false")
    store = _FakeStore()
    called: list[bool] = []

    async def sender(**kw: Any) -> str | None:
        called.append(True)
        return "om_x"

    ok = await upsert_daily_digest(
        D, "special_op", _cell(), store=store, sender=sender, updater=_ok_updater,
    )
    assert ok is False
    assert called == []
    assert store.hashes == {}


async def test_detail_capped_on_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    captured: list[dict[str, Any]] = []

    async def sender(**kw: Any) -> str | None:
        captured.append(kw)
        return "om_1"

    await upsert_daily_digest(
        D, "special_op", _cell(detail="x" * 5000), store=store, sender=sender,
        updater=_ok_updater,
    )
    # 存储里的明细已截断到上限（1600 + 截断提示）
    raw = await store.hgetall("safety:daily_digest:2026-09-15")
    saved = json.loads(raw["special_op"])
    assert len(saved["detail"]) <= 1700
    assert saved["detail"].endswith("…（明细过长已截断）")


async def test_sender_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()

    async def sender(**kw: Any) -> str | None:
        return None

    ok = await upsert_daily_digest(
        D, "special_op", _cell(), store=store, sender=sender, updater=_ok_updater,
    )
    assert ok is False
