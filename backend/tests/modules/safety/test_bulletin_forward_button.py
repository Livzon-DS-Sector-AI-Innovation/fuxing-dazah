"""速递督办通报格子「📤 推送到群 / 🗑 撤回推送」按钮的单元测试。

纯内存桩验证，不打飞书网络：
- 按钮渲染：仅 hazard_bulletin 格子且配置了目标群时渲染（双按钮横排）；转发单格卡不渲染；
- 推送回调：成功推送 / 未配置目标群 / 今日无格子 / 发送失败 四分支 toast；
- 撤回回调：撤回成功清记录 / 未推送 / 删除失败保留记录 / 撤回后再推送转新发。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.safety.feishu import daily_digest
from app.modules.safety.feishu.daily_digest import DigestCell


def _cell() -> dict[str, Any]:
    return {
        "tag_color": "yellow", "tag_text": "隐患督办",
        "title": "隐患督办通报",
        "stats": "未关闭 **29** 项",
        "zone": "请尽快反馈整改进展",
        "detail": "【隐患督办通报】明细",
    }


# ── 按钮渲染 ─────────────────────────────────────────────────────


async def test_cell_element_renders_forward_button_for_bulletin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily_digest, "forward_chat_id", lambda: "oc_target")
    el = await daily_digest._cell_element(_cell(), None, key="hazard_bulletin")
    # 单列布局：overview → 查看详情面板 → 双按钮横排行（面板下方，不悬浮右侧）
    assert len(el["columns"]) == 1
    elements = el["columns"][0]["elements"]
    assert elements[0]["tag"] == "markdown"
    assert elements[1]["tag"] == "collapsible_panel"
    row = elements[2]
    assert row["tag"] == "column_set"
    buttons = [
        col["elements"][0]
        for col in row["columns"]
        if col["elements"] and col["elements"][0].get("tag") == "button"
    ]
    assert len(buttons) == 2
    by_action = {b["value"]["action"]: b for b in buttons}
    forward, recall = by_action["forward"], by_action["recall"]
    assert forward["value"]["scope"] == "hazard_bulletin_forward"
    assert forward["type"] == "primary"
    assert forward["behaviors"][0]["type"] == "callback"
    assert recall["type"] == "danger"
    assert recall["behaviors"][0]["type"] == "callback"
    assert recall["confirm"]["title"]["content"]  # 撤回带二次确认


async def test_cell_element_button_without_detail_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无明细（无折叠面板）时按钮行紧随概览文本。"""
    monkeypatch.setattr(daily_digest, "forward_chat_id", lambda: "oc_target")
    cell = _cell()
    cell["detail"] = ""
    el = await daily_digest._cell_element(cell, None, key="hazard_bulletin")
    elements = el["columns"][0]["elements"]
    assert [e["tag"] for e in elements] == ["markdown", "column_set"]


async def test_cell_element_no_button_when_unconfigured_or_other_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daily_digest, "forward_chat_id", lambda: "")
    el = await daily_digest._cell_element(_cell(), None, key="hazard_bulletin")
    assert len(el["columns"][0]["elements"]) == 2  # overview + panel

    monkeypatch.setattr(daily_digest, "forward_chat_id", lambda: "oc_target")
    other = await daily_digest._cell_element(_cell(), None, key="fire_alarm")
    assert len(other["columns"][0]["elements"]) == 2
    # 转发单格卡场景不传 key（转出去的卡不再带按钮）
    forwarded = await daily_digest._cell_element(_cell(), None)
    assert len(forwarded["columns"][0]["elements"]) == 2


# ── 回调处理 ─────────────────────────────────────────────────────


class _FakeStore:
    """最小 Redis 桩：hget 读格子 / get-set 记录已推送卡 / delete 撤记录。"""

    def __init__(self, raw: str | None) -> None:
        self.raw = raw
        self.kv: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []
        self.deleted_keys: list[str] = []

    async def hget(self, key: str, field: str) -> str | None:
        return self.raw

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.kv[key] = value
        self.set_calls.append((key, value))

    async def delete(self, key: str) -> None:
        self.kv.pop(key, None)
        self.deleted_keys.append(key)


def _patch_forward(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target: str,
    cell_raw: str | None = None,
    sent_msg_id: str | None = "om_new",
    update_ok: bool = True,
    delete_ok: bool = True,
) -> tuple[list[tuple[DigestCell, str]], list[str], list[str], _FakeStore]:
    """桩掉 Redis/推送/更新/撤回；返回（发送记录, 更新记录, 撤回记录, store）。"""
    sent: list[tuple[DigestCell, str]] = []
    updated: list[str] = []
    deleted: list[str] = []
    store = _FakeStore(cell_raw)

    async def fake_redis() -> _FakeStore:
        return store

    async def fake_send(cell: DigestCell, *, chat_id: str | None = None,
                        **kw: Any) -> str | None:
        sent.append((cell, chat_id or ""))
        return sent_msg_id

    async def fake_update(msg_id: str, card: dict) -> bool:
        updated.append(msg_id)
        return update_ok

    async def fake_delete(msg_id: str) -> bool:
        deleted.append(msg_id)
        return delete_ok

    monkeypatch.setattr(daily_digest, "forward_chat_id", lambda: target)
    monkeypatch.setattr(daily_digest, "get_redis", fake_redis)
    monkeypatch.setattr(daily_digest, "send_digest_cell_card", fake_send)
    monkeypatch.setattr(daily_digest, "update_card", fake_update)
    monkeypatch.setattr(daily_digest, "delete_message", fake_delete)
    return sent, updated, deleted, store


def _event() -> dict[str, Any]:
    return {"operator": {"open_id": "ou_op"}}


def _cell_raw() -> str:
    return json.dumps(_cell(), ensure_ascii=False)


def _forward_key() -> str:
    """与实现同源的当日推送记录 key（handle_bulletin_forward 按 _bj_today 拼键）。"""
    return daily_digest._FORWARD_KEY.format(
        date=daily_digest._bj_today().isoformat(),
    )


async def test_forward_first_click_sends_and_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_target", cell_raw=_cell_raw(),
    )
    result = await daily_digest.handle_bulletin_forward(_event())
    assert result["toast"]["type"] == "success"
    assert len(sent) == 1 and sent[0][1] == "oc_target"
    assert updated == []  # 首推不走更新
    assert len(store.set_calls) == 1
    recorded = json.loads(store.set_calls[0][1])
    assert recorded == {"chat": "oc_target", "msg_id": "om_new"}


async def test_forward_second_click_updates_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_target", cell_raw=_cell_raw(),
    )
    store.kv[_forward_key()] = json.dumps(
        {"chat": "oc_target", "msg_id": "om_old"},
    )
    result = await daily_digest.handle_bulletin_forward(_event())
    assert result["toast"]["type"] == "success"
    assert "更新" in result["toast"]["content"]
    assert updated == ["om_old"]
    assert sent == []  # 不再发新卡


async def test_forward_target_changed_resends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """记录的群与当前目标群不同 → 发新卡并改写记录。"""
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_new", cell_raw=_cell_raw(),
    )
    store.kv[_forward_key()] = json.dumps(
        {"chat": "oc_old", "msg_id": "om_old"},
    )
    result = await daily_digest.handle_bulletin_forward(_event())
    assert result["toast"]["type"] == "success"
    assert updated == [] and len(sent) == 1
    assert json.loads(store.set_calls[-1][1])["chat"] == "oc_new"


async def test_forward_update_failure_falls_back_to_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧卡已删（PATCH 失败）→ 转新发并改写记录。"""
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_target", cell_raw=_cell_raw(), update_ok=False,
    )
    store.kv[_forward_key()] = json.dumps(
        {"chat": "oc_target", "msg_id": "om_gone"},
    )
    result = await daily_digest.handle_bulletin_forward(_event())
    assert result["toast"]["type"] == "success"
    assert updated == ["om_gone"]  # 尝试过更新
    assert len(sent) == 1  # 兜底新发
    assert json.loads(store.set_calls[-1][1])["msg_id"] == "om_new"


async def test_forward_without_target_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent, updated, deleted, store = _patch_forward(monkeypatch, target="", cell_raw="{}")
    result = await daily_digest.handle_bulletin_forward(_event())
    assert result["toast"]["type"] == "error"
    assert sent == [] and store.set_calls == []


async def test_forward_without_today_cell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_target", cell_raw=None,
    )
    result = await daily_digest.handle_bulletin_forward(_event())
    assert result["toast"]["type"] == "error"
    assert "暂无" in result["toast"]["content"]
    assert sent == [] and store.set_calls == []


async def test_forward_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_target", cell_raw=_cell_raw(), sent_msg_id=None,
    )
    result = await daily_digest.handle_bulletin_forward(_event())
    assert result["toast"]["type"] == "error"
    assert len(sent) == 1  # 尝试过发送但失败
    assert store.set_calls == []  # 失败不记录，下次仍走新发


# ── 撤回回调 ─────────────────────────────────────────────────────


async def test_recall_success_deletes_card_and_clears_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有当日推送记录 → 删群内卡片 + 清记录，再点推送走重新推送。"""
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_target", cell_raw=_cell_raw(),
    )
    store.kv[_forward_key()] = json.dumps(
        {"chat": "oc_target", "msg_id": "om_pushed"},
    )
    result = await daily_digest.handle_bulletin_forward_recall(_event())
    assert result["toast"]["type"] == "success"
    assert "撤回" in result["toast"]["content"]
    assert deleted == ["om_pushed"]  # 撤回的就是当天推送的卡
    assert store.deleted_keys == [_forward_key()]  # 记录已清

    # 撤回后再点推送：无记录 → 不走原地更新，重新推送新卡
    result2 = await daily_digest.handle_bulletin_forward(_event())
    assert result2["toast"]["type"] == "success"
    assert updated == [] and len(sent) == 1


async def test_recall_without_today_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当天未推送过（含已撤回）→ 无需撤回，不发起删除。"""
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_target", cell_raw=_cell_raw(),
    )
    result = await daily_digest.handle_bulletin_forward_recall(_event())
    assert result["toast"]["type"] == "error"
    assert "尚未推送" in result["toast"]["content"]
    assert deleted == [] and store.deleted_keys == []


async def test_recall_delete_failure_keeps_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """群内删除失败（卡片已被手动删除/权限异常）→ 保留记录，报错不误报成功。"""
    sent, updated, deleted, store = _patch_forward(
        monkeypatch, target="oc_target", cell_raw=_cell_raw(), delete_ok=False,
    )
    store.kv[_forward_key()] = json.dumps(
        {"chat": "oc_target", "msg_id": "om_pushed"},
    )
    result = await daily_digest.handle_bulletin_forward_recall(_event())
    assert result["toast"]["type"] == "error"
    assert deleted == ["om_pushed"]  # 尝试过撤回
    assert store.deleted_keys == []  # 记录保留：推送侧仍有 PATCH 失败兜底
    assert _forward_key() in store.kv
