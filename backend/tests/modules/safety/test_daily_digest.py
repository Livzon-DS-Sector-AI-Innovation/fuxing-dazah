"""「安全速递」总卡单元测试：存储、格子构建、建卡/PATCH 滚动、超限收缩、开关。

纯内存桩验证，不依赖 Redis / 飞书网络。总卡格子不带图片（纯文字概览+折叠面板）。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, cast

import pytest

from app.modules.safety.feishu import daily_digest
from app.modules.safety.feishu.daily_digest import (
    DigestCell,
    load_daily_digest_cells,
    upsert_daily_digest,
)
from app.modules.safety.feishu.notification import build_card_dict

D = date(2026, 9, 15)
# 历史日期护栏口径：以 _bj_today 判定「今天/昨天」，比 D 早 4 天（= 事故当天）
OLD = date(2026, 9, 11)


@pytest.fixture(autouse=True)
def _pin_bj_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """总卡重建护栏按北京时间「今天」放行；测试里把 D 钉为今天。"""
    monkeypatch.setattr(daily_digest, "_bj_today", lambda: D)


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


# ═══════════════════════════════════════════════════════════════════════════
# 历史日期护栏（2026-10-26 事故：手动对 09-11 投格，原卡键已过期 → 重建向
# 群里连发两张旧日期总卡）。仅「今天/昨天」允许重建发卡（今天由 autouse
# 夹具钉为 D；昨天=D-1=作业票审核投 review_date 的合法口径）。
# ═══════════════════════════════════════════════════════════════════════════


async def test_stale_date_no_card_never_rebuilds(monkeypatch: pytest.MonkeyPatch) -> None:
    """历史日期无存活卡片：只写存储，绝不向群里新发旧日期总卡。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    sent: list[dict[str, Any]] = []

    async def sender(**kw: Any) -> str | None:
        sent.append(kw)
        return "om_should_not_happen"

    ok = await upsert_daily_digest(
        OLD, "special_op", _cell(), store=store, sender=sender, updater=_ok_updater,
    )
    assert ok is False
    assert sent == []
    # 格子照写（驾驶舱回放仍可见），但不留卡片键
    stored = await store.hgetall(f"safety:daily_digest:{OLD.isoformat()}")
    assert set(stored) == {"special_op"}
    assert f"safety:daily_digest:card:{OLD.isoformat()}" not in store.strings


async def test_stale_date_live_card_patch_still_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """历史日期但卡片仍存活（TTL 7 天内）：原地 PATCH 放行，不发新卡。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    store.strings[f"safety:daily_digest:card:{OLD.isoformat()}"] = "om_alive"
    sent: list[dict[str, Any]] = []
    patched: list[str] = []

    async def sender(**kw: Any) -> str | None:
        sent.append(kw)
        return "om_should_not_happen"

    async def updater(msg_id: str, card: dict[str, Any]) -> bool:
        patched.append(msg_id)
        return True

    ok = await upsert_daily_digest(
        OLD, "special_op", _cell(), store=store, sender=sender, updater=updater,
    )
    assert ok is True
    assert patched == ["om_alive"]
    assert sent == []


async def test_stale_date_patch_fail_does_not_recreate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """历史日期 PATCH 失败（卡被删）：不重建（事故当天 15:28 第二张卡的路径）。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    store.strings[f"safety:daily_digest:card:{OLD.isoformat()}"] = "om_dead"
    sent: list[dict[str, Any]] = []

    async def sender(**kw: Any) -> str | None:
        sent.append(kw)
        return "om_should_not_happen"

    async def updater(msg_id: str, card: dict[str, Any]) -> bool:
        return False

    ok = await upsert_daily_digest(
        OLD, "special_op", _cell(), store=store, sender=sender, updater=updater,
    )
    assert ok is False
    assert sent == []


async def test_yesterday_rebuild_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """昨天仍允许重建发卡（当日补发窗口兜底；作业票审核已改按运行日投格）。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    sent: list[dict[str, Any]] = []

    async def sender(**kw: Any) -> str | None:
        sent.append(kw)
        return "om_card_y"

    ok = await upsert_daily_digest(
        D - timedelta(days=1), "workticket", _cell(),
        store=store, sender=sender, updater=_ok_updater,
    )
    assert ok is True
    assert sent and sent[0]["title"].endswith((D - timedelta(days=1)).isoformat())


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


async def test_full_detail_stored_and_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    """明细完整展示：不截断，存储与卡片均为全文。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    captured: list[dict[str, Any]] = []

    async def sender(**kw: Any) -> str | None:
        captured.append(kw)
        return "om_1"

    long_detail = "洗罐排污期间甲烷逸散，被可燃气体探测器检出。" * 60  # ~2.5K 字
    await upsert_daily_digest(
        D, "special_op", _cell(detail=long_detail), store=store, sender=sender,
        updater=_ok_updater,
    )
    raw = await store.hgetall("safety:daily_digest:2026-09-15")
    saved = json.loads(raw["special_op"])
    assert saved["detail"] == long_detail  # 存储不截断

    card = build_card_dict(
        captured[0]["title"], captured[0]["content"], "blue", captured[0]["elements"],
    )
    cell = _first_cell_dict(card)
    panel_md = cell["columns"][0]["elements"][1]["elements"][0]["content"]
    assert panel_md == long_detail  # 卡片完整展示
    assert "已截断" not in panel_md


async def test_emergency_shrink_only_when_extreme(monkeypatch: pytest.MonkeyPatch) -> None:
    """仅当整卡超过 140KB 预算时才兜底减半明细（正常数据远达不到）。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()
    captured: list[dict[str, Any]] = []

    async def sender(**kw: Any) -> str | None:
        captured.append(kw)
        return "om_1"

    huge = "x" * 200_000
    ok = await upsert_daily_digest(
        D, "special_op", _cell(detail=huge), store=store, sender=sender,
        updater=_ok_updater,
    )
    assert ok is True
    card = build_card_dict(
        captured[0]["title"], captured[0]["content"], "blue", captured[0]["elements"],
    )
    size = len(json.dumps(card, ensure_ascii=False).encode("utf-8"))
    assert size <= daily_digest._MAX_CARD_BYTES
    cell = _first_cell_dict(card)
    panel_md = cell["columns"][0]["elements"][1]["elements"][0]["content"]
    assert "…（明细过长已截断）" in panel_md  # 兜底收缩带标记


async def test_sender_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()

    async def sender(**kw: Any) -> str | None:
        return None

    ok = await upsert_daily_digest(
        D, "special_op", _cell(), store=store, sender=sender, updater=_ok_updater,
    )
    assert ok is False


# ═══════════════════════════════════════════════════════════════════════════
# load_daily_digest_cells — 只读回放（驾驶舱「今日安全速递」数据源）
# ═══════════════════════════════════════════════════════════════════════════


async def test_load_cells_ordered_with_sent_at(monkeypatch: pytest.MonkeyPatch) -> None:
    """按 CELL_ORDER 顺序返回格子，带推送时间与全文；只读不改卡片链路。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()

    async def sender(**kw: Any) -> str | None:
        return "om_1"

    # 先推消防（CELL_ORDER 靠后）再推特殊作业（靠前）——回放顺序仍按 CELL_ORDER
    await upsert_daily_digest(
        D, "fire_alarm", _cell(), store=store, sender=sender, updater=_ok_updater,
    )
    await upsert_daily_digest(
        D, "special_op", _cell(detail="作业明细全文"), store=store, sender=sender,
        updater=_ok_updater,
    )

    cells = await load_daily_digest_cells(D, store=store)
    assert [c["key"] for c in cells] == ["special_op", "fire_alarm"]
    assert cells[0]["title"] == "特殊作业日报"
    assert cells[0]["detail"] == "作业明细全文"
    assert cells[0]["sent_at"] is not None and "T" in cells[0]["sent_at"]
    # 未推送当日成立即空列表（非 None），前端显示空态
    assert await load_daily_digest_cells(date(2026, 1, 1), store=store) == []


async def test_standard_compliance_cell_tail_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S1 二期季度符合性格子：CELL_ORDER 队尾，与设施/报警格同卡共存。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    store = _FakeStore()

    async def sender(**kw: Any) -> str | None:
        return "om_1"

    await upsert_daily_digest(
        D, "standard_compliance", _cell(), store=store, sender=sender,
        updater=_ok_updater,
    )
    await upsert_daily_digest(
        D, "telemetry_alarm", _cell(), store=store, sender=sender,
        updater=_ok_updater,
    )
    cells = await load_daily_digest_cells(D, store=store)
    assert [c["key"] for c in cells] == ["telemetry_alarm", "standard_compliance"]
    assert cells[-1]["key"] == "standard_compliance"


async def test_load_cells_legacy_without_sent_at() -> None:
    """补记上线前的历史格子：主 hash 有内容但无 sent_at → 该字段为 None。"""
    store = _FakeStore()
    store.hashes.setdefault("safety:daily_digest:2026-09-01", {})["special_op"] = json.dumps(
        {
            "tag_color": "blue", "tag_text": "特殊作业", "title": "特殊作业日报",
            "stats": "今日计划 1 项", "zone": "", "detail": "历史明细",
        },
        ensure_ascii=False,
    )
    cells = await load_daily_digest_cells(date(2026, 9, 1), store=store)
    assert len(cells) == 1
    assert cells[0]["sent_at"] is None


# ═══════════════════════════════════════════════════════════════════════════
# send_digest_cell_card — 单格速递卡片独立投递（2026-09-30 需求）
# ═══════════════════════════════════════════════════════════════════════════


async def test_send_digest_cell_card_uses_cell_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """独立投递的卡片与总卡格子同款版式：灰底列 + 折叠详情面板。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)
    sent: list[dict[str, Any]] = []

    async def sender(**kw: Any) -> str | None:
        sent.append(kw)
        return "om_cell_1"

    msg_id = await daily_digest.send_digest_cell_card(
        _cell(), chat_id="oc_extra", title="📌 危化品库存日报 | 2026-09-30",
        sender=sender,
    )
    assert msg_id == "om_cell_1"
    assert sent[0]["chat_id"] == "oc_extra"
    assert sent[0]["header_template"] == "blue"

    card = build_card_dict(
        sent[0]["title"], sent[0]["content"], "blue", sent[0]["elements"],
    )
    cell = _first_cell_dict(card)
    assert cell["tag"] == "column_set"
    assert cell["background_style"] == "grey"
    text_md = cell["columns"][0]["elements"][0]["content"]
    assert "<text_tag color='blue'>特殊作业</text_tag>" in text_md
    assert "**特殊作业日报**" in text_md
    panel = cell["columns"][0]["elements"][1]
    assert panel["tag"] == "collapsible_panel"
    assert panel["expanded"] is False


async def test_send_digest_cell_card_failure_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """发送失败/异常只返回 None，不向上抛（不影响报告主链路）。"""
    monkeypatch.delenv("SAFETY_DAILY_DIGEST_ENABLED", raising=False)

    async def sender(**kw: Any) -> str | None:
        return None

    assert await daily_digest.send_digest_cell_card(
        _cell(), chat_id="oc_extra", sender=sender,
    ) is None

    async def boom(**kw: Any) -> str | None:
        raise RuntimeError("network down")

    assert await daily_digest.send_digest_cell_card(
        _cell(), chat_id="oc_extra", sender=boom,
    ) is None
