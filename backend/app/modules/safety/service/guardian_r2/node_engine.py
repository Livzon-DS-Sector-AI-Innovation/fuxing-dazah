"""监护人资格节点引擎与考核类型辨别 —— 纯函数（无 DB 无 IO）。

周期口径（2026-11-04 拍板①）：年审+三年换证——
  第一次复审 = 取证日期 + 1 年；第二次复审 = + 2 年；应换证 = + 3 年。
  已换证日期（renewed_date）非空 → 以其为新取证日重算下一周期（成功延期换证）。

节点义务是**顺序消费**的（拍板③辨别的正确性根基）：
  第一次复审未通过不能跳到第二次/换证——当前节点 = 第一个未被合格成绩
  覆盖的节点（已过期则该节点逾期，逾期后的补考仍辨别为该节点类型）。
  合格事件按次数消费：第 N 次复审合格覆盖第 N 个复审节点；
  换证合格（或 renewed_date 回填）覆盖换证节点并开启新周期。

合格事件来源（duck-typing 属性，优先级从高到低）：
  1. ``exam_history``：[{"exam_type": 复审|换证|取证, "passed": 合格|不合格,
     "exam_date": date}, ...]——links 留痕的考核事件流（扫描源注入）；
  2. 回退「考核三列」（exam_score/exam_date/exam_type，机器人写回的最新一次）：
     视为单条事件。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.safety.service.guardian_r2.score_parse import ScoreFacts

# 周期常量（年）——拍板①；cert_warning._GUARDIAN_PERIODS 同步校准
PERIOD_YEARS: dict[str, int] = {
    "first_review": 1,
    "second_review": 2,
    "renew": 3,
}

NODE_LABELS: dict[str, str] = {
    "first_review": "第一次复审",
    "second_review": "第二次复审",
    "renew": "换证",
}
# 节点 → 考核类型（辨别语义/写回列值）
NODE_EXAM_KINDS: dict[str, str] = {
    "first_review": "复审",
    "second_review": "复审",
    "renew": "换证",
}

REVIEW_NODES = ("first_review", "second_review")
RENEW_NODE = "renew"


@dataclass(frozen=True)
class NodeState:
    """当前节点判定结果（提醒/逾期/辨别共用）。"""

    node_key: str | None        # first_review/second_review/renew；无节点=None
    label: str | None           # 第一次复审/第二次复审/换证
    exam_kind: str | None       # 复审/换证（考核类型语义）
    deadline: date | None
    remaining_days: int | None  # deadline - ref_date；负=逾期；None=无法计算


def add_years(d: date, years: int) -> date:
    """周年推导（2月29日 → 平年落在2月28日，不抛错）。"""
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 2/29 遇平年
        return date(d.year + years, 2, 28)


def derive_nodes(issue: date) -> dict[str, date]:
    """取证日期 → 三节点截止日（+1/+2/+3 年）。"""
    return {
        "first_review": add_years(issue, PERIOD_YEARS["first_review"]),
        "second_review": add_years(issue, PERIOD_YEARS["second_review"]),
        "renew": add_years(issue, PERIOD_YEARS["renew"]),
    }


def _exam_events(record: Any) -> list[dict[str, Any]]:
    """合格事件列表归一：exam_history 优先，回退考核三列单事件。

    只保留 passed=="合格" 且 exam_date 非 None 的事件（不合格不消费节点，
    走取消资格链路）。
    """
    history = getattr(record, "exam_history", None)
    events: list[dict[str, Any]] = []
    if history:
        for e in history:
            if not isinstance(e, dict):
                continue
            if e.get("passed") == "合格" and e.get("exam_date") is not None:
                events.append(e)
        return events
    # 回退：考核三列（最新一次写回）
    if (
        getattr(record, "exam_score", None) == "合格"
        and getattr(record, "exam_date", None) is not None
        and getattr(record, "exam_type", None) in ("复审", "换证")
    ):
        events.append({
            "exam_type": record.exam_type,
            "passed": "合格",
            "exam_date": record.exam_date,
        })
    return events


def _event_date(value: Any) -> date | None:
    """考核事件日期归一：date | ISO 字符串（JSONB 往返）→ date。"""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _cycle_start(record: Any) -> date | None:
    """当前周期起点（renewed_date 优先；换证后旧周期事件不再消费新节点）。"""
    renewed = getattr(record, "renewed_date", None)
    if renewed is not None:
        return renewed
    return getattr(record, "issue_date", None)


def _node_passed(record: Any, node_key: str, ref_date: date) -> bool:
    """顺序消费判定：第 N 个复审节点需要第 N 次复审合格；换证需换证合格。

    事件须在**当前周期内**（> 周期起点=取证/换证日，严格晚于——开启本周期
    的换证事件不消费新周期节点）且 ≤ ref_date——换证重开周期后，上一周期
    的合格事件不再消费新周期节点（跨周期防泄漏）。
    """
    start = _cycle_start(record)
    events = [
        e for e in _exam_events(record)
        if (_event_date(e.get("exam_date")) or date.max) <= ref_date
        and (start is None or (_event_date(e.get("exam_date")) or date.min) > start)
    ]
    if node_key in REVIEW_NODES:
        need = REVIEW_NODES.index(node_key) + 1
        review_passes = [e for e in events if e["exam_type"] == "复审"]
        return len(review_passes) >= need
    if node_key == RENEW_NODE:
        return any(e["exam_type"] == "换证" for e in events)
    return False


def current_node(record: Any, *, ref_date: date) -> NodeState:
    """当前节点判定（提醒用 ref_date=today；辨别用 ref_date=考核日期）。

    当前节点 = 第一个「有截止日期且未被合格事件消费」的节点（顺序义务，
    过期不跳过——逾期补考仍属该节点）；全部被消费或无日期 → NodeState(None)。
    renewed_date 回填 → 新周期推导候选覆盖显式列（换证已完成）。
    """
    if getattr(record, "renewed_date", None) is not None:
        derived = derive_nodes(record.renewed_date)
        candidates: list[tuple[date | None, str]] = [
            (derived["first_review"], "first_review"),
            (derived["second_review"], "second_review"),
            (derived["renew"], "renew"),
        ]
    else:
        candidates = [
            (getattr(record, "first_review_deadline", None), "first_review"),
            (getattr(record, "second_review_deadline", None), "second_review"),
            (getattr(record, "should_renew_date", None), "renew"),
        ]
        # 显式截止列缺失（脏数据）→ 按取证日期推导兜底（周期常量为权威口径）
        if all(d is None for d, _ in candidates):
            issue = getattr(record, "issue_date", None)
            if issue is not None:
                fallback = derive_nodes(issue)
                candidates = [
                    (fallback["first_review"], "first_review"),
                    (fallback["second_review"], "second_review"),
                    (fallback["renew"], "renew"),
                ]

    has_any_date = any(d is not None for d, _ in candidates)
    if not has_any_date:
        return NodeState(None, None, None, None, None)
    for deadline, key in candidates:
        if deadline is None or _node_passed(record, key, ref_date):
            continue
        return NodeState(
            node_key=key,
            label=NODE_LABELS[key],
            exam_kind=NODE_EXAM_KINDS[key],
            deadline=deadline,
            remaining_days=(deadline - ref_date).days,
        )
    return NodeState(None, None, None, None, None)


# ═══════════════════════════════════════════════════════════
# 考核类型辨别（拍板③）
# ═══════════════════════════════════════════════════════════


def _match_cert_records(
    facts: ScoreFacts, cert_records: list[Any]
) -> list[Any]:
    """按 姓名 + A/B 类别（报名考试类型路由）匹配持证记录。"""
    if not facts.person_name:
        return []
    same_name = [
        r for r in cert_records
        if (getattr(r, "person_name", None) or "").strip() == facts.person_name
    ]
    if facts.cert_category is None:
        return same_name
    return [
        r for r in same_name
        if getattr(r, "cert_category", None) == facts.cert_category
    ]


def _disambiguate(facts: ScoreFacts, records: list[Any]) -> list[Any]:
    """多命中 → 成绩表部门消歧（仍多 → 原样返回，调用方判异常）。"""
    if len(records) <= 1 or not facts.department:
        return records
    narrowed = [
        r for r in records
        if facts.department in (getattr(r, "department", None) or "")
        or (getattr(r, "department", None) or "") in facts.department
    ]
    return narrowed or records


def discriminate(
    facts: ScoreFacts, cert_records: list[Any]
) -> tuple[str, str | None, Any]:
    """辨别考核类型：取证 / 复审 / 换证 / 无需处理 / 异常。

    Returns:
        (result, detail, matched_record)：result 语义——
        - 取证：合格且不在名单 → 执行器 create_record 进名单（matched=None）
        - 复审/换证：在名单且按考核日期当天的当前节点类型（matched=命中记录）
        - 无需处理：不在名单且非合格（无资格可取消）
        - 异常：无姓名 / 同名无法消歧 / 记录无日期（不映射不猜测）
    """
    if not facts.person_name:
        return "异常", "成绩记录无姓名", None
    routed = _match_cert_records(facts, cert_records)
    if not routed:
        if facts.passed == "合格":
            return "取证", "合格且不在持证名单", None
        return "无需处理", "非合格且不在持证名单", None

    matched = _disambiguate(facts, routed)
    if len(matched) != 1:
        return "异常", f"姓名匹配 {len(matched)} 条且部门无法消歧", None
    record = matched[0]

    ref = facts.exam_date or date.today()
    state = current_node(record, ref_date=ref)
    if state.node_key is None:
        return "异常", "持证记录无节点日期，无法辨别", record
    return state.exam_kind, state.label, record
