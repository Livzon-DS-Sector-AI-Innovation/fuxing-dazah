"""研判与策略层 —— Policy 版本化 / Gate 三维准入 / 规则引擎 Assessor / observe-auto。

两级过滤的 Slow Path：Gate（确定性准入）+ Assessment（规则引擎，LLM 留空实现骨架）。

- 版本化：rules+accept_mode+admission 规范化哈希；accept 记录其版本；
  改版不撤销已开任务——只投 policy_changed Input（避免半成品）
- observe/auto/off：observe=默认（只记 would_accept 不执行）；explicit 任何模式
  都受理（对人的承诺，不是对系统的）；observe→auto 切换只能人工改 Policy，
  系统无自动切换路径
- Thread 粒度研判串行锁（pg advisory xact lock）：同 Thread 至多一个 Eval，
  期间到达的合并进下一批；绝不全局锁
- Gate 判定只看结构化 meta（名单/是否点名），永不读 payload 消息文本（红线⑦）
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Protocol

from sqlalchemy import func, select

from app.platform.superagent.models import (
    AgentDecision,
    AgentInput,
    AgentPolicy,
    AgentTask,
    AgentTrigger,
)

logger = logging.getLogger(__name__)

MODE_OFF = "off"
MODE_OBSERVE = "observe"
MODE_AUTO = "auto"
VALID_MODES = (MODE_OFF, MODE_OBSERVE, MODE_AUTO)

# ═══════════════════════════════════════════════════════════════
# 纯函数：版本哈希 / Gate / 规则求值
# ═══════════════════════════════════════════════════════════════

DEFAULT_ADMISSION: dict[str, str] = {
    # 三维准入默认（保守）：在名单+点名=explicit；在名单未点名=inferred；
    # 名单外（点名与否）一律不准入，可按 scope 覆写（如「名单外点名=inferred」
    # 对应跟进场景）
    "in_list_addressed": "explicit",
    "in_list_not_addressed": "inferred",
    "out_list_addressed": "deny",
    "out_list_not_addressed": "deny",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def policy_version_hash(
    rules: list[dict[str, Any]], accept_mode: str, admission: dict[str, Any],
) -> str:
    """内容哈希（同内容恒同哈希；键序无关）。"""
    payload = {
        "rules": rules or [],
        "accept_mode": accept_mode,
        "admission": admission or {},
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def gate_admission(
    admission: dict[str, Any] | None,
    scope_key: str,
    *,
    sender_in_list: bool,
    addressed: bool,
) -> str:
    """三维准入判定：返回 explicit / inferred / deny。

    行=scope（接收范围/群/事件面），列=（在名单未点名/不在名单点名/不在名单未点名）。
    只凭结构化 meta 判定；消息文本永不参与（红线⑦）。
    """
    table = dict(DEFAULT_ADMISSION)
    overrides = ((admission or {}).get("scopes") or {}).get(scope_key) or {}
    table.update({k: v for k, v in overrides.items() if k in table})

    if sender_in_list and addressed:
        return table["in_list_addressed"]
    if sender_in_list and not addressed:
        return table["in_list_not_addressed"]
    if not sender_in_list and addressed:
        return table["out_list_addressed"]
    return table["out_list_not_addressed"]


def resolve_payload_path(payload: dict[str, Any], path: str) -> Any:
    """点路径取值（"fields.报警性质"）；富文本列表扁平化。"""
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    if isinstance(cur, list):
        parts = []
        for item in cur:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return cur


def evaluate_condition(payload: dict[str, Any], cond: dict[str, Any]) -> bool:
    """单条件求值（纯函数）。op ∈ in/not_in/equals/not_equals/is_empty/is_not_empty。"""
    value = resolve_payload_path(payload, cond.get("field", ""))
    op = cond.get("op", "equals")
    values = cond.get("values") or []
    if op == "in":
        return any(_eq(value, v) for v in values)
    if op == "not_in":
        return not any(_eq(value, v) for v in values)
    if op == "equals":
        return bool(values) and _eq(value, values[0])
    if op == "not_equals":
        return not (bool(values) and _eq(value, values[0]))
    if op == "is_empty":
        return value in (None, "", [])
    if op == "is_not_empty":
        return value not in (None, "", [])
    return False


def _eq(a: Any, b: Any) -> bool:
    return str(a if a is not None else "") == str(b if b is not None else "")


def evaluate_rule(rule: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """规则求值：conditions 全部命中 → (True, 证据)；否则 (False, 未命中条件)。

    条件支持嵌套组合：{"any_of": [cond...]} / {"all_of": [cond...]}——
    消防候选规则的「白名单 ∪ 故障子规则」即 any_of。
    """
    conds = rule.get("conditions") or []
    evidence: list[dict[str, Any]] = []
    for cond in conds:
        ok, detail = _eval_cond(payload or {}, cond)
        evidence.append(detail)
        if not ok:
            return False, {"rule_id": rule.get("rule_id"), "missed": detail, "evidence": evidence}
    return True, {"rule_id": rule.get("rule_id"), "evidence": evidence}


def _eval_cond(payload: dict[str, Any], cond: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """单条件（或嵌套组合）求值，返回 (命中, 证据节点)。"""
    if "any_of" in cond:
        sub = [_eval_cond(payload, c) for c in cond["any_of"]]
        hit = any(ok for ok, _ in sub)
        return hit, {"any_of": [d for _, d in sub], "hit": hit}
    if "all_of" in cond:
        sub = [_eval_cond(payload, c) for c in cond["all_of"]]
        hit = all(ok for ok, _ in sub)
        return hit, {"all_of": [d for _, d in sub], "hit": hit}
    ok = evaluate_condition(payload, cond)
    return ok, {
        "field": cond.get("field"), "op": cond.get("op"),
        "values": cond.get("values"),
        "value": resolve_payload_path(payload, cond.get("field", "")),
        "hit": ok,
    }


# ═══════════════════════════════════════════════════════════════
# Assessor 协议（LLM 留空实现骨架）
# ═══════════════════════════════════════════════════════════════


class AssessmentResult(dict):
    """{rule_id: {"outcome": accept/stop/ignore/unavailable, "reason": {...}}}"""


class Assessor(Protocol):
    """研判协议；规则引擎是第一个实现，二期接 LLM（置信度+逐规则判定）。"""

    def assess(
        self, batch: list[dict[str, Any]], thread_snapshot: dict[str, Any],
        policy: dict[str, Any],
    ) -> AssessmentResult: ...


class RuleEngineAssessor:
    """确定性规则引擎：每条启用规则逐一判定（命中与否+证据）。"""

    def assess(
        self, batch: list[dict[str, Any]], thread_snapshot: dict[str, Any],
        policy: dict[str, Any],
    ) -> AssessmentResult:
        rules = [r for r in (policy.get("rules") or []) if r.get("enabled", True)]
        out: AssessmentResult = AssessmentResult()
        for item in batch:
            for rule in rules:
                if rule.get("source") and rule["source"] != item.get("source_name"):
                    continue
                hit, reason = evaluate_rule(rule, item.get("payload") or {})
                out.setdefault(str(item.get("trigger_id")), {})[str(rule.get("rule_id"))] = {
                    "outcome": "accept" if hit else "ignore",
                    "reason": reason,
                }
        return out


class LlmAssessor:
    """LLM 研判空实现骨架（拍板点⑥：一期不接真 LLM，二期随首个应用落实现）。"""

    def assess(
        self, batch: list[dict[str, Any]], thread_snapshot: dict[str, Any],
        policy: dict[str, Any],
    ) -> AssessmentResult:  # pragma: no cover - 骨架
        out = AssessmentResult()
        for item in batch:
            out[str(item.get("trigger_id"))] = {"__llm__": {
                "outcome": "unavailable", "reason": {"note": "LLM assessor 未实现（二期）"}
            }}
        return out


# ═══════════════════════════════════════════════════════════════
# Policy 存取（版本不可变；改版投 policy_changed）
# ═══════════════════════════════════════════════════════════════


async def get_current_policy(session: Any) -> AgentPolicy | None:
    return (
        await session.execute(
            select(AgentPolicy).order_by(AgentPolicy.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def apply_new_policy(
    session: Any,
    *,
    rules: list[dict[str, Any]],
    accept_mode: str,
    admission: dict[str, Any] | None = None,
) -> tuple[AgentPolicy, int]:
    """落新版本（内容不变则幂等返回现行版）；改版只向受影响 open 任务投
    policy_changed Input（不撤销已开任务——避免半成品）。

    Returns: (policy, 投递的 Input 数)
    """
    if accept_mode not in VALID_MODES:
        raise ValueError(f"invalid accept_mode: {accept_mode}")
    vhash = policy_version_hash(rules, accept_mode, admission or {})

    current = await get_current_policy(session)
    if current is not None and current.version_hash == vhash:
        return current, 0

    existing = (
        await session.execute(
            select(AgentPolicy).where(AgentPolicy.version_hash == vhash)
        )
    ).scalar_one_or_none()
    if existing is not None:
        policy = existing
    else:
        policy = AgentPolicy(
            version_hash=vhash, rules=rules or [],
            accept_mode=accept_mode, admission=admission or {},
        )
        session.add(policy)
        await session.flush()

    # 受影响 open 任务（授权依据版本落后）→ policy_changed Input
    delivered = 0
    if current is not None:
        affected = (
            await session.execute(
                select(AgentTask).where(
                    AgentTask.status == "open",
                    AgentTask.mandate["policy_version"].astext != vhash,
                )
            )
        ).scalars().all()
        from datetime import UTC, datetime

        for task in affected:
            session.add(AgentInput(
                task_id=task.id, kind="system",
                payload={
                    "type": "policy_changed",
                    "from": (task.mandate or {}).get("policy_version"),
                    "to": vhash,
                },
                delivered_at=datetime.now(UTC),
            ))
            delivered += 1
    return policy, delivered


# ═══════════════════════════════════════════════════════════════
# 研判管线（Gate → Assessment → Decision → observe/auto 行动）
# ═══════════════════════════════════════════════════════════════


async def acquire_thread_eval_lock(session: Any, thread_key: str) -> None:
    """Thread 粒度研判串行锁（事务级 advisory lock，commit/rollback 自释放）。

    绝不全局锁——防把并发退化成串行（要摆脱的现状）。
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(thread_key)))
    )


async def evaluate_trigger(
    session: Any,
    trigger: AgentTrigger,
    *,
    policy: AgentPolicy,
    source_name: str = "",
    sender_in_list: bool = False,
    scope_key: str = "",
    assessor: Assessor | None = None,
    replay: bool = False,
) -> list[AgentDecision]:
    """对单个 Trigger 跑 Gate+Assessment，落 decisions；observe/auto 行动。

    - explicit 任何模式受理（off 也受理——对人的承诺）
    - inferred：off → 无候选（decision 记 stop）；observe → 只记 would_accept；
      auto → 评估通过即开任务（mandate 记 policy_version）
    - payload 消息文本永不参与授权判定（条件求值只用于规则命中，非授权）
    """
    eval_id = uuid.uuid4()
    await acquire_thread_eval_lock(session, trigger.thread_key)

    mode = policy.accept_mode
    decisions: list[AgentDecision] = []

    def _stop(reason: dict[str, Any]) -> list[AgentDecision]:
        d = AgentDecision(
            trigger_id=trigger.id, rule_id="gate", outcome="stop",
            would_accept=False, reason=reason, eval_id=eval_id,
            policy_version=policy.version_hash, mode=mode, replay=replay,
        )
        session.add(d)
        decisions.append(d)
        return decisions

    if trigger.human:
        gate = gate_admission(
            policy.admission, scope_key or trigger.thread_key,
            sender_in_list=sender_in_list, addressed=trigger.addressed,
        )
    else:
        # 机器事件（cron tick / Bitable 记录）不适用消息准入表：按 inferred
        # 强度走模式管辖（observe 默认只记录；auto 才开工）——规则引擎直接评估
        gate = "inferred"

    if gate == "deny":
        return _stop({"gate": "deny", "scope_key": scope_key})

    # off 模式：inferred 一律不产生候选（§4.2）——评估即停，不落 would_accept
    # （不污染 observe 积压/回放）；explicit 恒受理（对人的承诺）
    if mode == MODE_OFF and gate != "explicit":
        return _stop({"gate": gate, "mode": MODE_OFF, "note": "off: inferred 不产生候选"})

    # 防重复开工（§4.2 口径=该 Thread 现存任务）：同 Thread 已有 open 订阅任务
    # → 各规则 unavailable（正常情况订阅直通已消化此类 Trigger，此处兜
    # 手工建任务等无订阅路径）
    from app.platform.superagent.models import AgentTaskSubscription

    existing_open = (
        await session.execute(
            select(AgentTask.id).where(
                AgentTask.status == "open",
                AgentTask.id.in_(
                    select(AgentTaskSubscription.task_id).where(
                        AgentTaskSubscription.thread_key == trigger.thread_key
                    )
                ),
            )
        )
    ).scalars().all()

    engine = assessor or RuleEngineAssessor()
    batch = [{
        "trigger_id": str(trigger.id),
        "source_name": source_name,
        "payload": dict(trigger.payload or {}),
    }]
    results = engine.assess(batch, {}, {
        "rules": policy.rules, "accept_mode": mode, "admission": policy.admission,
    })
    per_rule = results.get(str(trigger.id), {})

    for rule_id, verdict in per_rule.items():
        outcome = verdict.get("outcome", "ignore")
        if existing_open and outcome == "accept":
            outcome = "unavailable"
            verdict = {**verdict, "dedup": "open task exists for trigger"}

        would = outcome == "accept"
        d = AgentDecision(
            trigger_id=trigger.id, rule_id=rule_id, outcome=outcome,
            would_accept=would, reason=verdict.get("reason", {}), eval_id=eval_id,
            policy_version=policy.version_hash, mode=mode, replay=replay,
        )
        session.add(d)
        decisions.append(d)

        if not would or replay:
            continue
        # 行动：explicit 恒受理；inferred 看 mode
        if gate == "explicit" or mode == MODE_AUTO:
            await _open_task_for_decision(session, trigger, policy, rule_id,
                                          verdict.get("reason", {}), gate)
    return decisions


async def _open_task_for_decision(
    session: Any, trigger: AgentTrigger, policy: AgentPolicy,
    rule_id: str, reason: dict[str, Any], gate: str,
) -> AgentTask:
    from app.platform.superagent.tasks import create_task

    mandate = {
        "policy_version": policy.version_hash,
        "scope": (trigger.payload or {}).get("channel") or {},
        "strength": gate,  # explicit / inferred
        "rule_id": rule_id,
        "origin_actor": trigger.actor or {},
        "reason": reason,
    }
    return await create_task(
        session,
        short_name=f"{rule_id}:{str(trigger.id)[:8]}",
        title=f"规则 {rule_id} 触发任务",
        executor=(policy.rules and next(
            (r.get("executor") for r in policy.rules if r.get("rule_id") == rule_id), "noop_exec"
        )) or "noop_exec",
        origin_trigger_id=trigger.id,
        mandate=mandate,
        origin_thread_key=trigger.thread_key,
    )


# ═══════════════════════════════════════════════════════════════
# observe 回放处置（人工；转正/忽略——切 auto 只能人工改 Policy）
# ═══════════════════════════════════════════════════════════════


async def resolve_decision(
    session: Any,
    decision: AgentDecision,
    *,
    resolution: str,
    resolved_by: str = "",
) -> AgentTask | None:
    """处置一条 Decision：promote（按当时决策开任务）/ dismiss（忽略）。

    - promote：mandate.policy_version 记当时决策版本；strength=promoted（人工转正）
    - 幂等：已处置的决策重复调用直接返回（不再开第二个任务）
    - observe→auto 的切换只能人工改 Policy——本函数不触碰 accept_mode
    """
    if decision.resolution:  # 已处置
        return None

    trigger = await session.get(AgentTrigger, decision.trigger_id)
    task: AgentTask | None = None
    if resolution == "promoted" and trigger is not None:
        from app.platform.superagent.tasks import create_task

        mandate = {
            "policy_version": decision.policy_version,
            "scope": (trigger.payload or {}).get("channel") or {},
            "strength": "promoted",
            "rule_id": decision.rule_id,
            "origin_actor": trigger.actor or {},
            "promoted_from_decision": str(decision.id),
            "reason": decision.reason or {},
        }
        current = await get_current_policy(session)
        executor = "noop_exec"
        if current is not None:
            executor = next(
                (r.get("executor") for r in (current.rules or [])
                 if r.get("rule_id") == decision.rule_id and r.get("executor")),
                "noop_exec",
            )
        task = await create_task(
            session,
            short_name=f"{decision.rule_id}:{str(trigger.id)[:8]}",
            title=f"转正：规则 {decision.rule_id}",
            executor=executor,
            origin_trigger_id=trigger.id,
            mandate=mandate,
            origin_thread_key=trigger.thread_key,
        )

    from datetime import UTC, datetime

    decision.resolution = resolution
    decision.resolved_by = resolved_by or None
    decision.resolved_at = datetime.now(UTC)
    return task
