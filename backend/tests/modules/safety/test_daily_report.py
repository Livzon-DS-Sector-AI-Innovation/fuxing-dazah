"""AI+安全日报一期单测——卡片结构/评价与汇总契约/store upsert/服务状态机/回调路由。

零真机：Bitable 客户端与推送层全 stub（conftest autouse 已钉推送隔离，
本文件再对 daily_report 自身引用点显式打桩，防 DM/群卡真发）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.modules.safety.feishu import daily_report_card as dr_card
from app.modules.safety.service.daily_report import (
    cards,
    config,
    evaluation,
    service,
    store,
)

# ═══════════════════════════════════════════════════════════
# 工具：stub Bitable 客户端 / 开闸
# ═══════════════════════════════════════════════════════════

class StubClient:
    """SafetyBitableClient 假件：内存行 + 调用记录。"""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows: list[dict] = rows or []  # [{"record_id","fields"}]
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    async def list_all_records(self, table_id=None, *, filter_str=None,
                               filter_info=None, strict=False, **kw):
        # 对齐真机口径：reports/summary 读路径按日期键结构化过滤
        if filter_info:
            conds = filter_info.get("conditions", [])
            date_conds = [c for c in conds if c.get("field_name") == "日期键"]
            if date_conds:
                key = (date_conds[0].get("value") or [""])[0]
                return [r for r in self.rows if r["fields"].get("日期键") == key]
        if filter_str and "日期键" in filter_str:
            key = filter_str.split('="')[1].rstrip('"')
            return [r for r in self.rows if r["fields"].get("日期键") == key]
        return list(self.rows)

    async def create_record(self, fields, table_id=None):
        rid = f"rec_new_{len(self.created) + 1}"
        self.created.append(fields)
        self.rows.append({"record_id": rid, "fields": dict(fields)})
        return {"record_id": rid, "shared_url": ""}

    async def update_record(self, record_id, fields, table_id=None):
        self.updated.append((record_id, fields))
        for row in self.rows:
            if row["record_id"] == record_id:
                row["fields"].update(fields)
        return True


@pytest.fixture()
def gate_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "enabled", lambda: True)


@pytest.fixture()
def push_pinned(monkeypatch: pytest.MonkeyPatch):
    """钉死 DM/群卡/卡片更新真实投递（记录调用即可）。"""
    sent: dict[str, list] = {"dm": [], "group": [], "patch": []}

    async def _dm(open_id, card, *a, **kw):
        sent["dm"].append((open_id, card))
        return "om_dm_test"

    async def _group(chat_id, title, content, *a, **kw):
        sent["group"].append((chat_id, title))
        return "om_group_test"

    async def _patch(message_id, card):
        sent["patch"].append(message_id)
        return True

    import app.modules.safety.feishu.notification as notification

    monkeypatch.setattr(notification, "send_user_card_dict", _dm)
    monkeypatch.setattr(notification, "send_group_card", _group)
    monkeypatch.setattr(notification, "update_card", _patch)
    return sent


def _report_row(open_id="ou_test01", name="张三", status="待补充",
                date_key="2026-11-18", advice="") -> dict:
    return {
        "record_id": f"rec_{open_id[-4:]}",
        "fields": {
            "日期键": date_key,
            "员工OpenID": open_id,
            "员工姓名": name,
            "日报状态": status,
            "AI评价与建议": advice,
            "今日重点工作": "作业票办理",
            "完成情况": "完成",
            "问题与协调": "无",
            "明日计划": "",
        },
    }


# ═══════════════════════════════════════════════════════════
# 1. 卡片构建
# ═══════════════════════════════════════════════════════════

class TestFormCard:
    @staticmethod
    def _form(card: dict) -> dict:
        return next(e for e in card["body"]["elements"] if e.get("tag") == "form")

    def test_four_multiline_inputs_and_submit_routing(self):
        card = cards.build_form_card("2026-11-18")
        form = self._form(card)
        assert form["tag"] == "form"
        inputs = [e for e in form["elements"] if e["tag"] == "input"]
        assert [i["name"] for i in inputs] == ["work", "done", "issue", "plan"]
        assert all(i["input_type"] == "multiline_text" for i in inputs)
        # 前三段必填，明日计划可空
        assert [i["required"] for i in inputs] == [True, True, True, False]
        submit = [e for e in form["elements"] if e["tag"] == "button"][0]
        assert submit["name"] == cards.FORM_SUBMIT_NAME == "dr_submit"
        assert submit["form_action_type"] == "submit"
        value = json.loads(submit["value"])
        assert value["scope"] == cards.SCOPE == "daily_report"

    def test_modify_mode_prefills_defaults(self):
        card = cards.build_form_card("2026-11-18", {"work": "原文工作"})
        inputs = [e for e in self._form(card)["elements"] if e["tag"] == "input"]
        by_name = {i["name"]: i for i in inputs}
        assert by_name["work"].get("default_value") == "原文工作"
        assert "default_value" not in by_name["plan"]


class TestDailyCard:
    def _state(self, **kw) -> cards.DailyCardState:
        base = dict(
            date_key="2026-11-18", done_count=1, total=3,
            pending=(("李四", "ou_lisi"),), not_submitted=("王五",),
        )
        base.update(kw)
        return cards.DailyCardState(**base)

    def test_markdown_shows_progress_and_lists(self):
        md = cards.daily_card_markdown(self._state())
        assert "**1/3**" in md
        assert "<at id=ou_lisi></at>" in md  # 待补充 @ 催办
        assert "王五" in md

    def test_buttons_by_stage(self):
        # 无草稿 → 填写 + 生成
        names = json.dumps(cards.daily_card_elements(self._state()), ensure_ascii=False)
        assert "填写今日日报" in names and "生成负责人日报" in names
        assert "发布" not in names
        # 有草稿未发布 → 填写 + 发布 + 草稿预览
        names = json.dumps(
            cards.daily_card_elements(self._state(draft_markdown="一、今日重点工作\n…")),
            ensure_ascii=False,
        )
        assert "发布负责人日报" in names and "生成负责人日报" not in names
        # 已发布 → 只剩填写
        names = json.dumps(
            cards.daily_card_elements(self._state(published_at="2026-11-18 18:00")),
            ensure_ascii=False,
        )
        assert "填写今日日报" in names and "发布" not in names and "生成" not in names


class TestDMCards:
    def test_suggestion_card_numbered_with_modify_button(self):
        card = cards.build_suggestion_card(
            "2026-11-18", "张三", {"work": "巡查"}, ["建议一", "建议二", "建议三"], "总评",
        )
        text = json.dumps(card, ensure_ascii=False)
        assert "1. 建议一" in text and "3. 建议三" in text
        assert "修改并完成" in text

    def test_eval_fail_card_has_retry_button(self):
        card = cards.build_eval_fail_card("2026-11-18", "超时")
        text = json.dumps(card, ensure_ascii=False)
        assert "重试AI评价" in text and "超时" in text


# ═══════════════════════════════════════════════════════════
# 2. AI 契约校验
# ═══════════════════════════════════════════════════════════

class TestEvalContract:
    def test_valid_three_suggestions(self):
        out = evaluation.validate_eval_output(
            {"suggestions": ["a", "b", "c"], "overall": "总评"},
        )
        assert out == {"suggestions": ["a", "b", "c"], "overall": "总评"}

    def test_too_few_after_dedupe_rejected(self):
        assert evaluation.validate_eval_output(
            {"suggestions": ["a", "a", "  ", "b"], "overall": "总评"},
        ) is None

    def test_seven_suggestions_rejected(self):
        assert evaluation.validate_eval_output(
            {"suggestions": list("abcdefg"), "overall": "总评"},
        ) is None

    def test_non_str_filtered_and_overall_required(self):
        assert evaluation.validate_eval_output(
            {"suggestions": ["a", 1, "b", "c"], "overall": ""},
        ) is None
        assert evaluation.validate_eval_output("not a dict") is None

    async def test_evaluate_sections_degrades_on_contract_violation(self, monkeypatch):
        class FakeService:
            async def chat_parsed(self, *a, **kw):
                return {"suggestions": ["只有一条"]}

            async def close(self):
                return None

        monkeypatch.setattr(evaluation, "create_ai_service", lambda *a, **kw: FakeService())
        result = await evaluation.evaluate_sections({"work": "x"})
        assert result["ok"] is False

    async def test_evaluate_sections_success(self, monkeypatch):
        class FakeService:
            async def chat_parsed(self, *a, **kw):
                return {"suggestions": ["s1", "s2", "s3"], "overall": "总评"}

            async def close(self):
                return None

        monkeypatch.setattr(evaluation, "create_ai_service", lambda *a, **kw: FakeService())
        result = await evaluation.evaluate_sections({"work": "x"})
        assert result["ok"] is True and len(result["suggestions"]) == 3


class TestAggContract:
    def test_valid_markdown(self):
        out = aggregation_validate(
            {"report_markdown": "一、今日重点工作\n二、数据项目\n三、协调事项\n四、风险报备"},
        )
        assert out is not None

    def test_missing_header_rejected(self):
        assert aggregation_validate({"report_markdown": "一、a\n二、b"}) is None
        assert aggregation_validate({"report_markdown": ""}) is None

    async def test_empty_reports_error(self):
        from app.modules.safety.service.daily_report import aggregation

        result = await aggregation.aggregate_reports([], "2026-11-18")
        assert result["ok"] is False


def aggregation_validate(raw: Any) -> dict | None:
    from app.modules.safety.service.daily_report import aggregation

    return aggregation.validate_agg_output(raw)


# ═══════════════════════════════════════════════════════════
# 3. store：查重 upsert / 名单 / 汇总
# ═══════════════════════════════════════════════════════════

async def test_upsert_report_first_submit_creates_pending(monkeypatch):
    stub = StubClient()
    monkeypatch.setattr(store, "client_for", lambda kind: stub)
    rid, created = await store.upsert_report(
        "2026-11-18", "ou_test01", "张三",
        {"work": "w", "done": "d", "issue": "i", "plan": ""},
        config.bj_now(),
    )
    assert created is True and rid.startswith("rec_")
    fields = stub.created[0]
    assert fields["日报状态"] == store.ST_PENDING
    assert fields["首次提交时间"] and fields["员工OpenID"] == "ou_test01"


async def test_upsert_report_final_marks_done(monkeypatch):
    stub = StubClient([_report_row(status="待补充")])
    monkeypatch.setattr(store, "client_for", lambda kind: stub)
    rid, created = await store.upsert_report(
        "2026-11-18", "ou_test01", "张三",
        {"work": "w2", "done": "d2", "issue": "i2", "plan": ""},
        config.bj_now(),
    )
    assert created is False and rid == "rec_st01"
    _, fields = stub.updated[0]
    assert fields["日报状态"] == store.ST_DONE and fields["完成提交时间"]


async def test_upsert_report_done_then_revise_keeps_status(monkeypatch):
    stub = StubClient([_report_row(status="已完成")])
    monkeypatch.setattr(store, "client_for", lambda kind: stub)
    await store.upsert_report(
        "2026-11-18", "ou_test01", "张三",
        {"work": "w3", "done": "d", "issue": "i", "plan": ""},
        config.bj_now(),
    )
    _, fields = stub.updated[0]
    assert "日报状态" not in fields  # 修订不动状态
    assert fields["完成提交时间"]


async def test_load_roster_person_parse(monkeypatch):
    stub = StubClient([{
        "record_id": "rec_r1",
        "fields": {"成员": [{"id": "ou_leader", "name": "许康福"}], "角色": "负责人"},
    }])
    monkeypatch.setattr(store, "client_for", lambda kind: stub)
    roster = await store.load_roster()
    assert roster == [store.RosterMember("ou_leader", "许康福", "负责人")]


async def test_summary_upsert_and_publish(monkeypatch):
    stub = StubClient()
    monkeypatch.setattr(store, "client_for", lambda kind: stub)
    rid = await store.upsert_summary("2026-11-18", "一、x", config.bj_now())
    assert rid.startswith("rec_")
    assert await store.mark_summary_published(rid, config.bj_now()) is True
    got = await store.get_summary("2026-11-18")
    assert got is not None and got[1] == "一、x" and got[2]  # 发布时间已写


# ═══════════════════════════════════════════════════════════
# 4. service：状态机 / 评价闭环 / 汇总权限
# ═══════════════════════════════════════════════════════════

@pytest.fixture()
def store_stub(monkeypatch: pytest.MonkeyPatch):
    """四 kind 共用一个内存 stub，service 全链可跑。

    同时钉死 get_redis：真 Redis 客户端绑定首个测试的事件循环，
    后续测试（新 loop）复用会 Future attached to a different loop。
    """
    stub = StubClient()
    monkeypatch.setattr(store, "client_for", lambda kind: stub)
    monkeypatch.setattr(service, "get_redis", _async_value(FakeRedis()))
    return stub


async def test_submit_first_then_final_stages(
    monkeypatch, gate_on, store_stub, push_pinned,
):
    monkeypatch.setattr(service, "_roster_name", _async_value("张三"))
    result = await service.submit("ou_test01", {
        "work": "作业票办理", "done": "完成", "issue": "无", "plan": "",
    })
    assert result["ok"] and result["stage"] == service.STAGE_FIRST
    # 第二次提交（模拟消化建议后）→ 最终提交
    result2 = await service.submit("ou_test01", {
        "work": "作业票3张", "done": "全部办结", "issue": "无", "plan": "继续",
    })
    assert result2["ok"] and result2["stage"] == service.STAGE_FINAL
    row = next(r for r in store_stub.rows if r["fields"].get("员工OpenID") == "ou_test01")
    assert row["fields"]["日报状态"] == store.ST_DONE
    # 历史表两行（首次+最终）
    hist = [r for r in store_stub.rows if r["fields"].get("阶段")]
    assert {h["fields"]["阶段"] for h in hist} == {store.HIST_FIRST, store.HIST_FINAL}


async def test_run_evaluation_refuses_done_and_repeats(
    monkeypatch, gate_on, store_stub, push_pinned,
):
    store_stub.rows.append(_report_row(status="已完成", advice="x"))
    out = await service.run_evaluation("2026-11-18", "ou_test01")
    assert out["ok"] is False and "最终版" in out["error"]
    # 已有建议未 force → 拒绝重复评价
    store_stub.rows[0]["fields"]["日报状态"] = store.ST_PENDING
    out2 = await service.run_evaluation("2026-11-18", "ou_test01")
    assert out2["ok"] is False and "一轮" in out2["error"]


async def test_run_evaluation_success_writes_and_dms(
    monkeypatch, gate_on, store_stub, push_pinned,
):
    store_stub.rows.append(_report_row(status="待补充", advice=""))
    monkeypatch.setattr(
        "app.modules.safety.service.daily_report.evaluation.evaluate_sections",
        _async_value({"ok": True, "suggestions": ["a", "b", "c"], "overall": "总评"}),
    )
    out = await service.run_evaluation("2026-11-18", "ou_test01", force=True)
    assert out["ok"] is True and out["count"] == 3
    row = store_stub.rows[0]
    assert "1. a" in row["fields"]["AI评价与建议"]
    assert len(push_pinned["dm"]) == 1  # 建议 DM 已发
    assert push_pinned["group"] or push_pinned["patch"]  # 群卡已刷新


async def test_run_evaluation_failure_marks_error(
    monkeypatch, gate_on, store_stub, push_pinned,
):
    store_stub.rows.append(_report_row(status="待补充", advice=""))
    monkeypatch.setattr(
        "app.modules.safety.service.daily_report.evaluation.evaluate_sections",
        _async_value({"ok": False, "error": "AI 调用失败"}),
    )
    out = await service.run_evaluation("2026-11-18", "ou_test01", force=True)
    assert out["ok"] is False
    assert store_stub.rows[0]["fields"]["日报状态"] == store.ST_EVAL_ERROR
    assert len(push_pinned["dm"]) == 1  # 失败卡（带重试按钮）已 DM


async def test_generate_leader_permission_and_flow(
    monkeypatch, gate_on, store_stub, push_pinned,
):
    # 非负责人非 admin → 拒绝
    monkeypatch.setattr(service, "_is_leader", _async_value(False))
    out = await service.generate_leader("ou_stranger")
    assert out["ok"] is False and "负责人" in out["error"]
    # 负责人 + 一条已完成 → 汇总写入
    monkeypatch.setattr(service, "_is_leader", _async_value(True))
    store_stub.rows.append(_report_row(status="已完成"))
    monkeypatch.setattr(
        "app.modules.safety.service.daily_report.aggregation.aggregate_reports",
        _async_value({"ok": True, "report_markdown": "一、a\n二、b\n三、c\n四、d"}),
    )
    out2 = await service.generate_leader("ou_leader")
    assert out2["ok"] is True and out2["based_on"] == 1
    assert any(r["fields"].get("负责人日报") for r in store_stub.rows)


async def test_publish_requires_draft(
    monkeypatch, gate_on, store_stub, push_pinned,
):
    monkeypatch.setattr(service, "_is_leader", _async_value(True))
    out = await service.publish("ou_leader")
    assert out["ok"] is False and "草稿" in out["error"]


async def test_compute_state_roster_diff(store_stub):
    store_stub.rows.append(_report_row(open_id="ou_a", name="张三", status="已完成"))
    store_stub.rows.append(_report_row(open_id="ou_b", name="李四", status="待补充"))
    store_stub.rows.append({"record_id": "rec_roster1", "fields": {
        "成员": [{"id": "ou_a", "name": "张三"}], "角色": "员工"}})
    store_stub.rows.append({"record_id": "rec_roster2", "fields": {
        "成员": [{"id": "ou_c", "name": "王五"}], "角色": "员工"}})
    state = await service.compute_state("2026-11-18")
    assert (state.done_count, state.total) == (1, 2)
    assert [n for n, _ in state.pending] == ["李四"]
    assert state.not_submitted == ("王五",)


# ═══════════════════════════════════════════════════════════
# 5. 回调路由（快路径）
# ═══════════════════════════════════════════════════════════

def _event(action_name: str = "", form_value: dict | None = None,
           operator: str = "ou_test01") -> dict:
    action: dict[str, Any] = {"name": action_name, "value": "{}"}
    if form_value is not None:
        action["form_value"] = form_value
    return {"action": action, "operator": {"open_id": operator}}


async def test_card_submit_routes_and_toast(monkeypatch, gate_on, store_stub, push_pinned):
    called: list[dict] = []

    async def _submit(operator, sections, date_key=None):
        called.append({"operator": operator, "sections": sections})
        return {"ok": True, "stage": "first", "message": "初稿已提交"}

    monkeypatch.setattr(service, "submit", _submit)
    # 后处理不真跑（避免 LLM stub 链）
    monkeypatch.setattr(service, "post_submit", _noop_async)
    result = await dr_card.handle_daily_report_card_action(
        {"scope": "daily_report", "action": "submit"},
        _event("dr_submit", {"work": "w", "done": "d", "issue": "i"}),
    )
    assert result == cards.toast("初稿已提交")
    assert called[0]["operator"] == "ou_test01"
    assert called[0]["sections"]["work"] == "w"


async def test_card_submit_missing_required_blocks(monkeypatch, gate_on, store_stub):
    result = await dr_card.handle_daily_report_card_action(
        {"scope": "daily_report", "action": "submit"},
        _event("dr_submit", {"plan": "只填了计划"}),
    )
    assert result["toast"]["type"] == "error"


async def test_card_gate_off_returns_disabled_toast(monkeypatch, store_stub):
    monkeypatch.setattr(config, "enabled", lambda: False)
    result = await dr_card.handle_daily_report_card_action(
        {"scope": "daily_report", "action": "open_form"}, _event("dr_x"),
    )
    assert result == cards.toast("AI+安全日报功能未开启")


async def test_card_unknown_action_returns_none(monkeypatch, gate_on, store_stub):
    result = await dr_card.handle_daily_report_card_action(
        {"scope": "daily_report", "action": "what"}, _event("dr_x"),
    )
    assert result is None


async def test_card_submit_fallback_when_value_missing(
    monkeypatch, gate_on, store_stub, push_pinned,
):
    """回归（审查 MAJOR）：form 回调 action.value 不一定返回——按钮 name
    dr_submit 本身即提交动作，payload 缺 action 时必须兜底，防提交静默丢弃。"""
    called: list[dict] = []

    async def _submit(operator, sections, date_key=None):
        called.append({"operator": operator, "sections": sections})
        return {"ok": True, "stage": "first", "message": "初稿已提交"}

    monkeypatch.setattr(service, "submit", _submit)
    monkeypatch.setattr(service, "post_submit", _noop_async)
    # payload 为空 dict（value 解析不出），路由只靠 event.action.name
    result = await dr_card.handle_daily_report_card_action(
        {}, _event("dr_submit", {"work": "w", "done": "d", "issue": "i"}),
    )
    assert result == cards.toast("初稿已提交")
    assert called and called[0]["sections"]["work"] == "w"


async def test_open_form_dms_prefilled(monkeypatch, gate_on, store_stub, push_pinned):
    store_stub.rows.append(_report_row())
    result = await dr_card.handle_daily_report_card_action(
        {"scope": "daily_report", "action": "open_form"}, _event("btn"),
    )
    assert "私信" in result["toast"]["content"]
    assert len(push_pinned["dm"]) == 1


# ═══════════════════════════════════════════════════════════
# 6. 入口卡 upsert（Redis 锚）
# ═══════════════════════════════════════════════════════════

class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value


async def test_refresh_daily_card_gated_off(monkeypatch, store_stub):
    monkeypatch.setattr(config, "enabled", lambda: False)
    assert await service.refresh_daily_card() is None


async def test_refresh_daily_card_anchor_patch_then_rebuild(
    monkeypatch, gate_on, store_stub, push_pinned,
):
    fake_redis = FakeRedis()
    monkeypatch.setattr(service, "get_redis", _async_value(fake_redis))
    monkeypatch.setattr(config, "today_key", lambda: "2026-11-18")
    # 首发建卡 + 锚写入
    msg_id = await service.refresh_daily_card("2026-11-18")
    assert msg_id == "om_group_test" and len(push_pinned["group"]) == 1
    assert fake_redis.data["safety:daily_report:card_msg:2026-11-18"] == msg_id
    # 再刷 → PATCH 原卡不再发新卡
    await service.refresh_daily_card("2026-11-18")
    assert len(push_pinned["group"]) == 1 and len(push_pinned["patch"]) == 1
    # 历史日期无锚 → 拒绝重建
    assert await service.refresh_daily_card("2026-11-01") is None
    assert len(push_pinned["group"]) == 1


# ═══════════════════════════════════════════════════════════

async def _noop_async(*a, **kw):
    return None


def _async_value(value):
    async def _wrapper(*a, **kw):
        return value

    return _wrapper
