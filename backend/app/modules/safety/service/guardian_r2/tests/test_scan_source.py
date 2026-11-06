"""R2 持证扫描源 —— Trigger 分型/月度键/草稿构建 纯函数单测（T03）。

拍板⑧：每日扫描按月触发——提醒月=「截止月-3/-2/-1」三个自然月（精确封顶
3 次，不随剩余天数漂移）；external_id 月度键不含全字段指纹（防成绩写回
引发重复提醒）。一次性键：逾期（按节点）、不合格（按考核日期）、恢复
（按考核日期）。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.guardian_r2.scan_source import (
    build_cert_drafts,
    remind_month_keys,
)

_TODAY = date(2026, 11, 4)


def _fields(
    name: str = "张三",
    issue: str = "2026-01-10",
) -> dict:
    """监护人 A 证 Bitable fields 替身。

    日期列毫秒按 UTC 零点构造（与 cert 既有映射链 _ms_to_datetime 同口径）；
    三截止列由 issue 按 1/2/3 年推导（脏数据场景另测）。
    """
    import datetime as dt

    def ms(s: str) -> int:
        d = dt.date.fromisoformat(s)
        return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
                   .timestamp() * 1000)

    def plus_years(s: str, n: int) -> str:
        d = dt.date.fromisoformat(s)
        try:
            return d.replace(year=d.year + n).isoformat()
        except ValueError:
            return dt.date(d.year + n, 2, 28).isoformat()

    return {
        "姓名": [{"id": "ou_demo", "name": name}],
        "部门": ["提炼工程一部"],
        "取证日期": ms(issue),
        "第一次复审截止日期": ms(plus_years(issue, 1)),
        "第二次复审截止日期": ms(plus_years(issue, 2)),
        "应换证日期": ms(plus_years(issue, 3)),
    }


def _record(rid: str = "rec1", **kw) -> dict:
    return {"record_id": rid, "kind": "guardian_a", "fields": _fields(**kw)}


def _links(**kw) -> dict:
    base = dict(
        qualification_status="active", remind_count=0,
        last_reminded_month=None, exam_history=[],
        last_score_event=None,
    )
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════
# 提醒月窗口（拍板⑧）
# ═══════════════════════════════════════════════════════════


def test_remind_month_keys_three_calendar_months() -> None:
    """截止月 M → 恰好 M-3/M-2/M-1 三个自然月（跨年正确）。"""
    assert remind_month_keys(date(2027, 1, 10)) == [
        "2026-10", "2026-11", "2026-12",
    ]
    assert remind_month_keys(date(2026, 12, 31)) == [
        "2026-09", "2026-10", "2026-11",
    ]


# ═══════════════════════════════════════════════════════════
# Trigger 分型
# ═══════════════════════════════════════════════════════════


def _one(records, links_map=None, today=_TODAY):
    return build_cert_drafts(records, links_map or {}, today=today)


def test_remind_trigger_in_window_month() -> None:
    """第一次复审截止 2027-01 → 2026-11 在提醒窗内 → remind Trigger（发送月键）。"""
    drafts = _one([_record("rec1")])
    assert len(drafts) == 1
    d = drafts[0]
    assert d.external_id == "guardian:rec1:first_review:remind:2026-11"
    assert d.payload["_derived"]["trigger_type"] == "remind"
    assert d.payload["_derived"]["node_key"] == "first_review"
    assert d.payload["_derived"]["deadline"] == "2027-01-10"
    assert d.payload["_derived"]["person_name"] == "张三"
    assert d.payload["_derived"]["guardian_open_id"] == "ou_demo"
    assert d.payload["_derived"]["cert_category"] == "guardian_a"
    assert d.thread_key == "guardian_cert:rec1"


def test_no_trigger_outside_window() -> None:
    """截止月-3 之前（2026-09 扫 2027-06 截止）→ 无 Trigger。"""
    drafts = _one([_record("rec1", issue="2026-03-01")], today=date(2026, 9, 4))
    # issue 2026-03-01 → first 2027-03-01，提醒窗 2026-12/2027-01/02；9月不在窗内
    assert drafts == []


def test_month_key_dedup_within_month() -> None:
    """同月内字段变化（成绩写回）不产生新提醒键——external_id 不含指纹，
    两轮扫描产出相同键（DB Trigger 唯一约束据此去重）；跨月换键（每月一次）。"""
    r1 = _record("rec1")
    r2 = _record("rec1")
    r2["fields"]["已换证日期"] = None
    d1 = _one([r1])
    d2 = _one([r2])  # 同月第二轮扫描（字段已变）
    assert [d.external_id for d in d1] == ["guardian:rec1:first_review:remind:2026-11"]
    assert [d.external_id for d in d2] == [d1[0].external_id]  # 同键 → DB 去重
    # 下月扫描 → 新键（第 2 次）
    d3 = _one([_record("rec1")], today=date(2026, 12, 4))
    assert [d.external_id for d in d3] == ["guardian:rec1:first_review:remind:2026-12"]


def test_remind_capped_by_count() -> None:
    """links remind_count 已 3 → 不再产提醒（第二道封顶）。"""
    drafts = _one([_record("rec1")], {"rec1": _links(remind_count=3)})
    assert drafts == []


def test_overdue_silent_no_trigger() -> None:
    """节点逾期 → 静默（2026-11-06 拍板④：不催办不展示，存量不产 Trigger）。"""
    drafts = _one([_record("rec1", issue="2024-01-10")])  # first=2025-01 已逾期
    assert drafts == []


def test_failed_trigger_keyed_by_exam_date() -> None:
    """最新考核不合格 → failed Trigger（键含考核日期，再考再败可再触发）。"""
    rec = _record("rec1")
    rec["fields"]["考核成绩"] = "不合格"
    rec["fields"]["考核日期"] = 1770000000000
    drafts = _one([rec])
    assert [d.external_id for d in drafts] == ["guardian:rec1:failed:2026-02-02"]
    assert drafts[0].payload["_derived"]["trigger_type"] == "failed"


def test_failed_suppressed_when_revoked() -> None:
    """已 revoked → 不合格/逾期/提醒全静默（只剩恢复路径）。"""
    rec = _record("rec1", issue="2024-01-10")
    rec["fields"]["考核成绩"] = "不合格"
    drafts = _one([rec], {"rec1": _links(qualification_status="revoked")})
    assert drafts == []


def test_restore_trigger_on_new_pass() -> None:
    """revoked + 最新考核事件合格 → restore Trigger（键=考核日期）。"""
    drafts = _one(
        [_record("rec1")],
        {"rec1": _links(
            qualification_status="revoked",
            last_score_event={"exam_type": "复审", "passed": "合格",
                              "exam_date": "2026-11-20"},
        )},
    )
    assert [d.external_id for d in drafts] == ["guardian:rec1:restore:2026-11-20"]
    assert drafts[0].payload["_derived"]["trigger_type"] == "restore"


def test_revoked_without_new_pass_silent() -> None:
    """revoked 且无新合格事件 → 静默。"""
    drafts = _one(
        [_record("rec1", issue="2024-01-10")],
        {"rec1": _links(qualification_status="revoked")},
    )
    assert drafts == []


def test_failed_still_triggers_when_overdue_silent() -> None:
    """逾期静默不影响不合格触发：逾期者考核不合格仍进取消资格链。"""
    rec = _record("rec1", issue="2024-01-10")
    rec["fields"]["考核成绩"] = "不合格"
    rec["fields"]["考核日期"] = 1793462400000
    drafts = _one([rec])
    assert [d.payload["_derived"]["trigger_type"] for d in drafts] == ["failed"]


def test_node_passed_by_history_moves_remind_target() -> None:
    """links 历史一次复审合格 → 第一次复审被消费，提醒落在第二次复审窗口。"""
    # issue 2024-12-01：first=2025-12（已过但被合格消费）、second=2026-12（窗口内：
    # 2026-09/10/11，today=2026-11-04 命中）
    drafts = _one(
        [_record("rec1", issue="2024-12-01")],
        {"rec1": _links(exam_history=[
            {"exam_type": "复审", "passed": "合格", "exam_date": "2025-06-01"},
        ])},
    )
    assert [d.external_id for d in drafts] == [
        "guardian:rec1:second_review:remind:2026-11"
    ]


def test_no_date_record_skipped() -> None:
    """无姓名/无日期脏数据 → 跳过不产 Trigger。"""
    rec = _record("rec1")
    rec["fields"] = {"部门": ["提炼工程一部"]}
    drafts = _one([rec])
    assert drafts == []


def test_remind_payload_carries_count_for_nth_label() -> None:
    """_derived 带提醒计数与月份（执行器文案「第 N 次（共 3 次）」依据）。"""
    drafts = _one([_record("rec1")], {"rec1": _links(remind_count=1)})
    assert drafts[0].payload["_derived"]["remind_count"] == 1
    assert drafts[0].payload["_derived"]["remind_seq"] == 2  # 本次是第 2 次


def test_three_months_three_keys_then_window_closes() -> None:
    """完成标准核心：截止月前 3 个自然月各恰一键，截止当月/之后不再提醒。"""
    # issue 2025-11-10 → first=2026-11-10；提醒窗 = 2026-08/09/10
    keys = []
    for day in (date(2026, 8, 4), date(2026, 9, 4), date(2026, 10, 4),
                date(2026, 11, 4)):
        drafts = _one([_record("rec1", issue="2025-11-10")], today=day)
        keys.append([d.external_id for d in drafts])
    assert keys[0] == ["guardian:rec1:first_review:remind:2026-08"]
    assert keys[1] == ["guardian:rec1:first_review:remind:2026-09"]
    assert keys[2] == ["guardian:rec1:first_review:remind:2026-10"]
    # 截止当月（11-04 扫 11-10 截止）：已出提醒窗（窗=前 3 个自然月）且未逾期
    # → 无 Trigger；截止后（12 月）才转 overdue
    # 截止后同样静默（拍板④：逾期不产 Trigger；恢复走成绩映射链）
    assert keys[3] == []
    late = _one([_record("rec1", issue="2025-11-10")], today=date(2026, 12, 4))
    assert late == []
