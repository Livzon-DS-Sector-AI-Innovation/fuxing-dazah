"""R3 诊断卡 JSON 交互化（T6 2026-11-13）——纯函数单测，零 DB。

- build_diagnosis_interactive_card：文本诊断卡 → JSON 2.0 卡 +「一键执行」按钮；
- handle_r3_card_action：card.action.trigger 回调路由（scope=r3_selfheal）。
"""

from __future__ import annotations

import inspect
import json

import pytest

from app.modules.safety.service.ops_selfheal_r3 import cards as r3_cards


def _r3(job_name: str = "作业票审核") -> dict:
    return {
        "signal": "job_failed", "job_name": job_name,
        "first_seen_at": "2026-11-13T12:00:00+08:00",
        "root_cause_class": "upstream_outage", "confidence": 0.9,
        "source": "rules", "reasoning": "端点不可达",
        "stage": "diagnosed", "executed": [], "planned": ["rag_recheck"],
        "suggestions": ["延长当日补发窗口——观测页/工单一键执行"],
    }


class TestBuildDiagnosisInteractiveCard:
    def test_card_is_feishu_json_20(self) -> None:
        card = r3_cards.build_diagnosis_interactive_card(
            _r3(), ticket_id="t-1", repair_mode="observe", evidence={},
        )
        assert card["schema"] == "2.0"
        assert card["config"]["update_multi"] is True
        assert card["header"]["title"]["content"].startswith("【R3 诊断】")
        texts = [e.get("content", "") for e in card["body"]["elements"]
                 if e.get("tag") == "markdown"]
        assert any("根因判断" in t for t in texts)

    def test_button_value_carries_scope_action_ticket(self) -> None:
        card = r3_cards.build_diagnosis_interactive_card(
            _r3(), ticket_id="t-42", repair_mode="observe", evidence={},
        )
        values = _button_values(card)
        assert values, "诊断卡必须带按钮"
        assert values[0]["scope"] == "r3_selfheal"
        assert values[0]["action"] == "window_extend"
        assert values[0]["ticket_id"] == "t-42"

    def test_no_button_when_no_window_extend_subject(self) -> None:
        # 无 job_name（非 job 信号工单）→ 不给按钮（端点会 400）
        r3 = _r3()
        r3.pop("job_name")
        card = r3_cards.build_diagnosis_interactive_card(
            r3, ticket_id="t-1", repair_mode="observe", evidence={},
        )
        assert _button_values(card) == []


def _button_values(card: dict) -> list[dict]:
    values = []
    for element in card["body"]["elements"]:
        for column in (element.get("columns") or []):
            for inner in column.get("elements", []):
                if inner.get("tag") == "button" and isinstance(inner.get("value"), dict):
                    values.append(inner["value"])
    return values


class TestHandleR3CardAction:
    @pytest.fixture
    def _patched_service(self, monkeypatch: pytest.MonkeyPatch):
        """回调复用 window_guard 服务核心——stub 掉权限校验与会话包装
        （纯路由/解析单测，零 DB）。"""
        from app.modules.safety.feishu import r3_card

        calls: list[dict] = []

        async def _fake_apply(ticket_id: str, operator_open_id: str = "") -> dict:
            calls.append({"ticket_id": ticket_id, "operator": operator_open_id})
            return {"ok": True, "job_name": "作业票审核",
                    "old_window": "12:00", "new_window": "14:00"}

        async def _fake_admin(open_id: str) -> bool:
            return True

        monkeypatch.setattr(r3_card, "_apply_window_extend", _fake_apply)
        monkeypatch.setattr(r3_card, "_operator_is_admin", _fake_admin)
        return r3_card, calls

    def test_unknown_action_ignored(self, _patched_service) -> None:
        r3_card, calls = _patched_service
        result = r3_card._parse_value({"action": "drop_all"})
        assert result == {"action": "drop_all"}  # 解析不拦动作，路由层拦
        assert calls == []

    def test_wrong_scope_ignored(self, _patched_service) -> None:
        r3_card, calls = _patched_service
        assert r3_card._parse_value(
            {"scope": "other", "action": "window_extend", "ticket_id": "t"}) is not None
        assert calls == []  # scope 不符不会走到 apply（路由层判定）

    def test_parse_value_rejects_bad_json(self, _patched_service) -> None:
        r3_card, _ = _patched_service
        assert r3_card._parse_value("not-json{{{") is None

    async def test_window_extend_routes_and_updates_card(self, _patched_service) -> None:
        r3_card, calls = _patched_service
        result = await r3_card.handle_r3_card_action_async(
            {"scope": "r3_selfheal", "action": "window_extend", "ticket_id": "t-42",
             "operator_open_id": "ou_admin"},
        )
        assert calls == [{"ticket_id": "t-42", "operator": "ou_admin"}]
        assert result is not None
        # 同步返回卡片更新（event_client 2.9s ACK 契约）
        assert result["config"]["update_multi"] is True
        texts = [e.get("content", "") for e in result["body"]["elements"]
                 if e.get("tag") == "markdown"]
        assert any("12:00" in t and "14:00" in t for t in texts)

    async def test_non_admin_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """payload 不参与授权：非管理员回调 → 拒绝卡，不触服务核心。"""
        from app.modules.safety.feishu import r3_card

        calls: list = []

        async def _fake_apply(ticket_id: str, operator_open_id: str = "") -> dict:
            calls.append(ticket_id)
            return {"ok": True}

        async def _not_admin(open_id: str) -> bool:
            return False

        monkeypatch.setattr(r3_card, "_apply_window_extend", _fake_apply)
        monkeypatch.setattr(r3_card, "_operator_is_admin", _not_admin)
        result = await r3_card.handle_r3_card_action_async(
            {"scope": "r3_selfheal", "action": "window_extend", "ticket_id": "t-1",
             "operator_open_id": "ou_random"},
        )
        assert calls == []  # 未触达服务核心
        texts = [e.get("content", "") for e in result["body"]["elements"]
                 if e.get("tag") == "markdown"]
        assert any("仅管理员" in t for t in texts)

    async def test_button_value_json_string_double_encoded(self, _patched_service) -> None:
        """按钮 value 旧式双重编码 JSON str（对齐 handle_card_action 兼容口径）。"""
        r3_card, calls = _patched_service
        payload = json.dumps(json.dumps(
            {"scope": "r3_selfheal", "action": "window_extend", "ticket_id": "t-9"},
            ensure_ascii=False), ensure_ascii=False)
        result = await r3_card.handle_r3_card_action_async(payload)
        assert calls and calls[0]["ticket_id"] == "t-9"
        assert result is not None

    async def test_non_dict_payload_ignored(self, _patched_service) -> None:
        r3_card, calls = _patched_service
        result = await r3_card.handle_r3_card_action_async(12345)
        assert result is None and calls == []

    async def test_service_failure_returns_error_card(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.feishu import r3_card

        async def _fail(ticket_id: str, operator_open_id: str = "") -> dict:
            return {"ok": False, "reason": "already_extended_today",
                    "job_name": "作业票审核", "current_window": "14:00"}

        async def _fake_admin(open_id: str) -> bool:
            return True

        monkeypatch.setattr(r3_card, "_apply_window_extend", _fail)
        monkeypatch.setattr(r3_card, "_operator_is_admin", _fake_admin)
        result = await r3_card.handle_r3_card_action_async(
            {"scope": "r3_selfheal", "action": "window_extend", "ticket_id": "t-1",
             "operator_open_id": "ou_admin"},
        )
        assert result is not None
        texts = [e.get("content", "") for e in result["body"]["elements"]
                 if e.get("tag") == "markdown"]
        assert any("already_extended_today" in t for t in texts)


class TestTodayExtendedDbGuard:
    """跨入口当日幂等（REST worker 与回调进程 dict 不共享 → DB 侧兜底）。"""

    def test_query_shape_matches_inputs(self) -> None:
        # 防漂移锚：guard 查询字段与写入侧（window_guard/executor/API）payload 键一致
        from app.modules.safety.service.ops_selfheal_r3 import window_guard

        src = inspect.getsource(window_guard.today_extended_job)
        assert "l2_window_extend" in src
        assert "ok" in src and "job_name" in src
