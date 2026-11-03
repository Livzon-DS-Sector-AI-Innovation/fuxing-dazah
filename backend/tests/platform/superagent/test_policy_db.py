"""策略层测试 —— A 层版本哈希/Gate 矩阵/规则求值 + B 层研判管线/observe-auto/改版。

红线⑦探针：判定永不读 payload 消息文本——恶意指令文本不影响 Gate。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.platform.superagent.ingest import ingest_draft
from app.platform.superagent.models import (
    AgentInput,
    AgentSource,
    AgentTask,
)
from app.platform.superagent.policy import (
    MODE_AUTO,
    MODE_OBSERVE,
    LlmAssessor,
    apply_new_policy,
    evaluate_condition,
    evaluate_rule,
    evaluate_trigger,
    gate_admission,
    get_current_policy,
    policy_version_hash,
)
from app.platform.superagent.sources import TriggerDraft

# ═══════════════════════════════════════════════════════════════
# A 层：版本哈希
# ═══════════════════════════════════════════════════════════════


def test_version_hash_stable_and_order_insensitive() -> None:
    """同内容同哈希；rules 内键序无关（canonical json）。"""
    a = policy_version_hash(
        [{"rule_id": "r1", "conditions": [{"field": "f", "op": "equals", "values": ["x"]}]}],
        "observe", {},
    )
    b = policy_version_hash(
        [{"conditions": [{"values": ["x"], "op": "equals", "field": "f"}], "rule_id": "r1"}],
        "observe", {},
    )
    assert a == b


def test_version_hash_differs_on_content_change() -> None:
    base = ([{"rule_id": "r1"}], "observe", {})
    assert policy_version_hash(*base) != policy_version_hash(
        [{"rule_id": "r1"}], "auto", {},
    )
    assert policy_version_hash(*base) != policy_version_hash(
        [{"rule_id": "r2"}], "observe", {},
    )


# ═══════════════════════════════════════════════════════════════
# A 层：Gate 三维准入矩阵
# ═══════════════════════════════════════════════════════════════


def test_gate_default_matrix() -> None:
    assert gate_admission({}, "s", sender_in_list=True, addressed=True) == "explicit"
    assert gate_admission({}, "s", sender_in_list=True, addressed=False) == "inferred"
    assert gate_admission({}, "s", sender_in_list=False, addressed=True) == "deny"
    assert gate_admission({}, "s", sender_in_list=False, addressed=False) == "deny"


def test_gate_scope_override_for_followup() -> None:
    """名单外点名=跟进场景：按 scope 覆写为 inferred。"""
    admission = {"scopes": {"chat_ops": {"out_list_addressed": "inferred"}}}
    assert gate_admission(admission, "chat_ops", sender_in_list=False, addressed=True) == "inferred"
    # 其他 scope 不受影响
    assert gate_admission(admission, "chat_other", sender_in_list=False, addressed=True) == "deny"


def test_gate_never_reads_message_text() -> None:
    """红线⑦探针：Gate 入参只有结构化 meta，无 payload 通道（结构性保证）。"""
    import inspect

    sig = inspect.signature(gate_admission)
    assert "payload" not in sig.parameters
    assert "text" not in sig.parameters


# ═══════════════════════════════════════════════════════════════
# A 层：规则求值
# ═══════════════════════════════════════════════════════════════


def test_condition_in_with_rich_text() -> None:
    payload = {"fields": {"报警性质": [{"type": "text", "text": "泄漏报警"}]}}
    assert evaluate_condition(payload, {"field": "fields.报警性质", "op": "in", "values": ["泄漏报警", "火警"]})
    assert not evaluate_condition(payload, {"field": "fields.报警性质", "op": "in", "values": ["误报"]})


def test_condition_not_in_and_empty() -> None:
    payload = {"fields": {"原因分类": "测试", "处理情况": None}}
    assert evaluate_condition(payload, {"field": "fields.原因分类", "op": "not_in", "values": ["现场着火"]})
    assert evaluate_condition(payload, {"field": "fields.处理情况", "op": "is_empty"})


def test_rule_all_conditions_required() -> None:
    rule = {"rule_id": "r", "conditions": [
        {"field": "a", "op": "equals", "values": ["1"]},
        {"field": "b", "op": "equals", "values": ["2"]},
    ]}
    hit, reason = evaluate_rule(rule, {"a": "1", "b": "2"})
    assert hit
    hit, reason = evaluate_rule(rule, {"a": "1", "b": "9"})
    assert not hit and reason["missed"]["field"] == "b"


# ═══════════════════════════════════════════════════════════════
# LLM 骨架
# ═══════════════════════════════════════════════════════════════


def test_llm_assessor_skeleton_unavailable() -> None:
    out = LlmAssessor().assess([{"trigger_id": "x", "payload": {}}], {}, {})
    assert out["x"]["__llm__"]["outcome"] == "unavailable"


# ═══════════════════════════════════════════════════════════════
# B 层：Policy 版本 + 研判管线
# ═══════════════════════════════════════════════════════════════


async def _seed(db_session, *, config: dict | None = None) -> tuple[AgentSource, str]:
    row = AgentSource(kind="test_echo", name=f"test.policy.{uuid.uuid4().hex[:6]}",
                      config=config or {"evaluate": True}, enabled=True)
    db_session.add(row)
    await db_session.flush()
    return row, row.name


_RULES = [{
    "rule_id": "fire_candidate", "enabled": True, "source_kind": "bitable_poll",
    "conditions": [
        {"field": "fields.报警性质", "op": "in", "values": ["泄漏报警", "火警"]},
        {"field": "fields.原因分类", "op": "not_in", "values": ["测试", "演练引发"]},
    ],
}]


async def test_observe_mode_records_decision_without_task(db_session) -> None:
    """observe 默认：机器事件评估通过只记 would_accept，不建任务。"""
    policy, _ = await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_OBSERVE)
    src, src_name = await _seed(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="f-1", thread_key="t:fire-1",
        payload={"fields": {"报警性质": "泄漏报警", "原因分类": "氨水引发"}},
    ))

    decisions = await evaluate_trigger(db_session, trigger, policy=policy, source_name=src_name)

    assert len(decisions) == 1
    assert decisions[0].would_accept is True
    assert decisions[0].outcome == "accept"
    assert decisions[0].mode == MODE_OBSERVE
    tasks = (await db_session.execute(select(AgentTask))).scalars().all()
    assert tasks == []  # observe 不执行


async def test_auto_mode_opens_task_with_mandate(db_session) -> None:
    """auto：评估通过即开任务，mandate 记 policy_version + 规则。"""
    policy, _ = await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_AUTO)
    src, src_name = await _seed(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="f-2", thread_key="t:fire-2",
        payload={"fields": {"报警性质": "火警", "原因分类": "现场着火"}},
    ))

    await evaluate_trigger(db_session, trigger, policy=policy, source_name=src_name)

    tasks = (await db_session.execute(select(AgentTask))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].mandate["policy_version"] == policy.version_hash
    assert tasks[0].mandate["rule_id"] == "fire_candidate"
    assert tasks[0].mandate["strength"] == "inferred"  # 机器事件按 inferred 强度


async def test_rule_miss_records_ignore(db_session) -> None:
    """条件不命中（误报）→ outcome=ignore、would_accept=False。"""
    policy, _ = await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_AUTO)
    src, src_name = await _seed(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="f-3", thread_key="t:fire-3",
        payload={"fields": {"报警性质": "误报", "原因分类": "蒸汽引发"}},
    ))
    decisions = await evaluate_trigger(db_session, trigger, policy=policy, source_name=src_name)
    assert decisions[0].outcome == "ignore"
    tasks = (await db_session.execute(select(AgentTask))).scalars().all()
    assert tasks == []


async def test_human_deny_scope_stops_before_rules(db_session) -> None:
    """人消息（名单外未点名）→ Gate deny：规则引擎不再评估（stop）。"""
    policy, _ = await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_AUTO)
    src, src_name = await _seed(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="f-4", thread_key="t:fire-4", human=True, addressed=False,
        actor={"id": "stranger"},
        payload={"fields": {"报警性质": "泄漏报警"}},  # 即使字段命中也不得进入规则
    ))
    decisions = await evaluate_trigger(db_session, trigger, policy=policy, source_name=src_name)
    assert decisions[0].outcome == "stop"
    assert decisions[0].rule_id == "gate"


async def test_policy_change_delivers_input_not_revoke(db_session) -> None:
    """改版：不撤销已开任务，只投 policy_changed Input。"""
    p1, _ = await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_AUTO)
    src, src_name = await _seed(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="f-5", thread_key="t:fire-5",
        payload={"fields": {"报警性质": "火警", "原因分类": "现场着火"}},
    ))
    await evaluate_trigger(db_session, trigger, policy=p1, source_name=src_name)
    task = (await db_session.execute(select(AgentTask))).scalar_one()

    p2, delivered = await apply_new_policy(
        db_session, rules=_RULES + [{"rule_id": "r2"}], accept_mode=MODE_OBSERVE,
    )
    assert p2.version_hash != p1.version_hash
    assert delivered == 1
    task_row = await db_session.get(AgentTask, task.id)
    assert task_row.status == "open"  # 不撤销
    inputs = (
        await db_session.execute(select(AgentInput).where(AgentInput.task_id == task.id))
    ).scalars().all()
    assert any((i.payload or {}).get("type") == "policy_changed" for i in inputs)


async def test_policy_idempotent_same_content(db_session) -> None:
    from app.platform.superagent.models import AgentPolicy

    await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_OBSERVE)
    p2, delivered = await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_OBSERVE)
    assert delivered == 0
    assert (await get_current_policy(db_session)).version_hash == p2.version_hash
    rows = (
        await db_session.execute(
            select(AgentPolicy.id).where(AgentPolicy.version_hash == p2.version_hash)
        )
    ).scalars().all()
    assert len(rows) == 1  # 同内容不重复落版（库中可能有他处播种的其他版本）


async def test_replay_flag_excluded_from_action(db_session) -> None:
    """回放标注：replay=True 只落决策不执行（auto 模式也不开任务）。"""
    policy, _ = await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_AUTO)
    src, src_name = await _seed(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="f-6", thread_key="t:fire-6",
        payload={"fields": {"报警性质": "火警", "原因分类": "现场着火"}},
    ))
    decisions = await evaluate_trigger(
        db_session, trigger, policy=policy, source_name=src_name, replay=True,
    )
    assert decisions[0].replay is True
    tasks = (await db_session.execute(select(AgentTask))).scalars().all()
    assert tasks == []


async def test_off_mode_inferred_no_candidates(db_session) -> None:
    """off：inferred 不产生候选——评估即停（stop），不落 would_accept 不开任务。"""
    policy, _ = await apply_new_policy(db_session, rules=_RULES, accept_mode="off")
    src, src_name = await _seed(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="f-off", thread_key="t:fire-off",
        payload={"fields": {"报警性质": "火警", "原因分类": "现场着火"}},
    ))
    decisions = await evaluate_trigger(db_session, trigger, policy=policy, source_name=src_name)
    assert len(decisions) == 1
    assert decisions[0].outcome == "stop"
    assert decisions[0].would_accept is False
    assert decisions[0].reason.get("mode") == "off"
    tasks = (await db_session.execute(select(AgentTask))).scalars().all()
    assert tasks == []


async def test_decisions_carry_eval_id(db_session) -> None:
    """同批研判共享 eval_id（§5 字段）。"""
    policy, _ = await apply_new_policy(db_session, rules=_RULES, accept_mode=MODE_OBSERVE)
    src, src_name = await _seed(db_session)
    _, trigger = await ingest_draft(db_session, src, TriggerDraft(
        external_id="f-eid", thread_key="t:fire-eid",
        payload={"fields": {"报警性质": "泄漏报警", "原因分类": "氨水引发"}},
    ))
    decisions = await evaluate_trigger(db_session, trigger, policy=policy, source_name=src_name)
    assert decisions[0].eval_id is not None
