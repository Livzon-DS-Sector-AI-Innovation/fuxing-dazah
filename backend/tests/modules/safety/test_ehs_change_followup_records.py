"""EHS 变更周度督办 — 记录解析/验收归属/关闭判定/周一分类（纯函数单测）。

数据形态实测 2026-11-24（scripts-tmp/probe_ehs_change_status.py）：
申请编号=单 dict 段（text+link applink）、富文本段列表、multi-select
list[str]、单选 str、毫秒时间戳。关闭判定覆盖定稿口径关键用例：
FX-T6-20260724 双行审批单（按编号对、不逐行对）与两条关联路径。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.ehs_change_followup import records

_APPLINK = (
    "https://applink.feishu.cn/client/mini_program/open?appId=cli_9cb844403dbb9108"
    "&mode=appCenter&path_pc=pc/pages/in-process/index%3FinstanceId%3D7708668647694339073"
)


def _approval_fields(
    change_no: str = "FX-D4-2026-0826",
    code: str = "202611200123",
    dept: str = "提炼工程四部",
    status: str = "已通过",
    change_status: str = "待验收",
    progress: str = "已完工待验收收集资料中",
    expected_ms: int | None = 1767196800000,  # 2026-01-01 北京
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "申请编号": {"text": code, "link": _APPLINK, "type": "url"},
        "变更申请编号": [{"type": "text", "text": change_no}],
        "变更名称": [{"type": "text", "text": "二期围堰改造"}],
        "变更申请部门": [dept],
        "申请状态": status,
        "变更状态": change_status,
        "变更最新具体进展": [{"type": "text", "text": progress}],
    }
    if expected_ms is not None:
        fields["预计实施日期"] = expected_ms
    return fields


def _approval(**kw: Any) -> dict[str, Any]:
    return {"record_id": f"rec_{kw.get('code', 'x')}", "fields": _approval_fields(**kw)}


def _acceptance(
    status: str = "已通过",
    related: str = "",
    change_no: str = "",
    record_id: str = "recAcc1",
) -> dict[str, Any]:
    fields: dict[str, Any] = {"申请状态": status}
    if related:
        fields["关联审批"] = related
    if change_no:
        fields["变更编号"] = [{"type": "text", "text": change_no}]
    return {"record_id": record_id, "fields": fields}


def _parse(rows: list[dict[str, Any]]) -> list:
    return [a for a in (records.parse_approval_row(r) for r in rows) if a]


# ═══════════════════════════════════════════════════════════
# 解析与归一
# ═══════════════════════════════════════════════════════════

class TestParse:
    def test_normalize_change_no(self):
        assert records.normalize_change_no("FX-D4-2026-002") == "FXD42026002"
        assert records.normalize_change_no(" fx t5 20260424 ") == "FXT520260424"
        assert records.normalize_change_no("FXD1-2026-07-01") == "FXD120260701"
        assert records.normalize_change_no(None) == ""

    def test_flat_text_variants(self):
        assert records.flat_text("待验收") == "待验收"
        assert records.flat_text([{"type": "text", "text": "FX-A"}]) == "FX-A"
        assert records.flat_text({"text": "123", "link": "u", "type": "url"}) == "123"
        assert records.flat_text(["提炼工程四部"]) == "提炼工程四部"
        assert records.flat_text(None) == ""
        assert records.flat_text(1767196800000) == "1767196800000"

    def test_parse_approval_row_full_shape(self):
        row = _approval()
        change = records.parse_approval_row(row)
        assert change is not None
        assert change.change_no == "FX-D4-2026-0826"
        assert change.approval_code == "202611200123"
        assert change.approval_url == _APPLINK
        assert change.department == "提炼工程四部"
        assert change.status == "已通过"
        assert change.change_status == "待验收"
        assert change.progress == "已完工待验收收集资料中"
        assert change.expected_start == "2026-01-01"
        assert change.departments == ["提炼工程四部"]
        assert records.parse_approval_row({"fields": {}}) is None

    def test_multi_select_departments_comma_joined(self):
        """multi-select list[str] 逗号连接（无缝拼接会把多部门粘成一串）。"""
        assert records.flat_text(["提炼工程四部", "环保工程中心"]) == "提炼工程四部,环保工程中心"
        row = _approval()
        row["fields"]["变更申请部门"] = ["提炼工程四部", "环保工程中心"]
        change = records.parse_approval_row(row)
        assert change.departments == ["提炼工程四部", "环保工程中心"]

    def test_parse_acceptance_row(self):
        acc = records.parse_acceptance_row(
            _acceptance(related="202611200001-验收单", change_no="FX-D4-2026-0826")
        )
        assert acc.related_code == "202611200001"
        assert acc.change_no == "FX-D4-2026-0826"
        assert acc.status == "已通过"
        # 关联审批开头非 12 位数字 → related_code 空
        acc2 = records.parse_acceptance_row(
            _acceptance(related="FX-验收-关联")
        )
        assert acc2.related_code == ""


# ═══════════════════════════════════════════════════════════
# 验收归属（DESIGN §2.2 两条路径 + FX-T6 双行用例）
# ═══════════════════════════════════════════════════════════

class TestAcceptedNumbers:
    def test_path_related_code(self):
        """路径①：关联审批 12 位 → 审批行 → 变更申请编号。"""
        approvals = _parse([_approval(change_no="FX-A-1", code="202601010001")])
        accs = [records.parse_acceptance_row(
            _acceptance(related="202601010001-验收")
        )]
        assert records.accepted_change_numbers(accs, approvals) == {"FXA1"}

    def test_path_own_change_no(self):
        """路径②：验收单自己的变更编号（关联审批空）。"""
        approvals = _parse([_approval(change_no="FX-B-2", code="202601010002")])
        accs = [records.parse_acceptance_row(
            _acceptance(related="", change_no="FX-B-2")
        )]
        assert records.accepted_change_numbers(accs, approvals) == {"FXB2"}

    def test_only_approved_counts(self):
        approvals = _parse([_approval(change_no="FX-C-3", code="202601010003")])
        accs = [
            records.parse_acceptance_row(
                _acceptance(related="202601010003-x", record_id="r1")
            ),
            records.parse_acceptance_row(
                _acceptance(status="审批中", change_no="FX-C-3", record_id="r2")
            ),
        ]
        assert records.accepted_change_numbers(accs, approvals) == {"FXC3"}

    def test_fx_t6_double_row_by_number(self):
        """FX-T6-20260724 双行已通过审批单：验收单只挂一行，按编号对两行都关。"""
        approvals = _parse([
            _approval(change_no="FX-T6-20260724", code="202607240001"),
            _approval(change_no="FX-T6-20260724", code="202607240002"),
        ])
        accs = [records.parse_acceptance_row(
            _acceptance(related="202607240001-验收")
        )]
        accepted = records.accepted_change_numbers(accs, approvals)
        assert records.normalize_change_no("FX-T6-20260724") in accepted
        # 逐行对会把 202607240002 误判未验收；编号归属两行都关
        facts = records.split_followup(approvals, accs, set())
        assert facts.todo == []
        assert len(facts.closed_accepted) == 2


# ═══════════════════════════════════════════════════════════
# 筛分（关闭判定定稿口径）
# ═══════════════════════════════════════════════════════════

class TestSplitFollowup:
    def test_four_buckets(self):
        approvals = _parse([
            _approval(change_no="FX-OK-1", code="202601010101"),        # 验收单已通过
            _approval(change_no="FX-STOP-1", code="202601010102",
                      change_status="变更中止"),                          # 中止关闭
            _approval(change_no="FX-TODO-1", code="202601010103"),      # 待督办
            _approval(change_no="FX-WD-1", code="202601010104",
                      status="已撤回"),                                   # 撤回天然不进
            _approval(change_no="FX-ING-1", code="202601010105",
                      status="审批中"),                                   # 非已通过不进
        ])
        accs = [records.parse_acceptance_row(
            _acceptance(related="202601010101-验收")
        )]
        facts = records.split_followup(approvals, accs, set())
        assert [c.change_no for c in facts.todo] == ["FX-TODO-1"]
        assert [c.change_no for c in facts.closed_accepted] == ["FX-OK-1"]
        assert [c.change_no for c in facts.closed_terminated] == ["FX-STOP-1"]
        assert facts.excluded == []

    def test_terminated_variants(self):
        approvals = _parse([
            _approval(change_no="FX-S1", code="202601010201", change_status="变更中止"),
            _approval(change_no="FX-S2", code="202601010202", change_status="中止"),
        ])
        facts = records.split_followup(approvals, [], set())
        assert len(facts.closed_terminated) == 2
        assert facts.todo == []

    def test_excluded_with_note_derivation(self):
        """排除项标注四型：审批中/已撤回可推导，-002 兄弟覆盖预置，其余未找到。"""
        approvals = _parse([
            _approval(change_no="FXSC-2026001", code="202601010301"),   # 名下验收单审批中
            _approval(change_no="FXQA-20260728", code="202601010302"),  # 名下验收单已撤回
            _approval(change_no="FX-D4-2026-002", code="202601010303"), # 兄弟覆盖（预置）
            _approval(change_no="FSAS-2025-003", code="202601010304"),  # 未找到
        ])
        accs = [
            records.parse_acceptance_row(
                _acceptance(status="审批中", change_no="FXSC-2026001", record_id="a1")
            ),
            records.parse_acceptance_row(
                _acceptance(status="已撤回", change_no="FXQA-20260728", record_id="a2")
            ),
        ]
        excluded = {records.normalize_change_no(x) for x in
                    ("FXSC-2026001", "FXQA-20260728", "FX-D4-2026-002", "FSAS-2025-003")}
        facts = records.split_followup(approvals, accs, excluded)
        notes = {c.change_no: note for c, note in facts.excluded}
        assert notes["FXSC-2026001"] == records.NOTE_IN_REVIEW
        assert notes["FXQA-20260728"] == records.NOTE_WITHDRAWN
        assert notes["FX-D4-2026-002"] == records.NOTE_SIBLING_COVERED
        assert notes["FSAS-2025-003"] == records.NOTE_NOT_FOUND
        assert facts.todo == []

    def test_excluded_matches_normalized(self):
        """排除清单比较走归一化（带连字符/空格差异也能剔）。"""
        approvals = _parse([_approval(change_no="FX-T5-20260424", code="202601010401")])
        facts = records.split_followup(
            approvals, [], {"FXT5202604 24".replace(" ", "")},
        )
        assert facts.todo == []
        assert len(facts.excluded) == 1

    def test_status_stale_accepted_hint(self):
        """验收单已通过但状态没改成已验收 → 进速递提示桶，不督办。"""
        approvals = _parse([
            _approval(change_no="FX-ST-1", code="202601010501", change_status="实施中"),
            _approval(change_no="FX-ST-2", code="202601010502", change_status="已验收"),
        ])
        accs = [
            records.parse_acceptance_row(
                _acceptance(related="202601010501-x", record_id="a1")
            ),
            records.parse_acceptance_row(
                _acceptance(related="202601010502-x", record_id="a2")
            ),
        ]
        facts = records.split_followup(approvals, accs, set())
        assert facts.status_stale_accepted == ["FX-ST-1"]
        assert facts.todo == []


# ═══════════════════════════════════════════════════════════
# 周一分类与复查关闭（DESIGN §5 顺序命中即止）
# ═══════════════════════════════════════════════════════════

class TestClassify:
    def test_order_closed_first(self):
        assert records.classify_item(
            closed_now=True,
            progress_friday="a", progress_monday="b",
            status_friday="待验收", status_monday="实施中",
            unchanged_clicked=True,
        ) == "closed"

    def test_progress_changed_wins_over_button(self):
        assert records.classify_item(
            closed_now=False,
            progress_friday="施工中", progress_monday="施工中\n\n【卡片提交·x】完工",
            status_friday="待验收", status_monday="待验收",
            unchanged_clicked=True,
        ) == "updated"

    def test_status_changed_is_updated(self):
        assert records.classify_item(
            closed_now=False,
            progress_friday="a", progress_monday="a",
            status_friday="待实施", status_monday="实施中",
            unchanged_clicked=False,
        ) == "updated"

    def test_button_is_unchanged(self):
        assert records.classify_item(
            closed_now=False,
            progress_friday="a", progress_monday="a",
            status_friday="待验收", status_monday="待验收",
            unchanged_clicked=True,
        ) == "unchanged"

    def test_nothing_is_not_updated(self):
        assert records.classify_item(
            closed_now=False,
            progress_friday="a", progress_monday="a",
            status_friday="待验收", status_monday="待验收",
            unchanged_clicked=False,
        ) == "not_updated"

    def test_whitespace_only_progress_change_not_updated(self):
        """纯空白差异不算更新（两侧 strip 后比对）。"""
        assert records.classify_item(
            closed_now=False,
            progress_friday="a", progress_monday=" a ",
            status_friday="待验收", status_monday="待验收",
            unchanged_clicked=False,
        ) == "not_updated"


class TestIsClosedNow:
    def _change(self, **kw: Any):
        row = _approval(**kw)
        return records.parse_approval_row(row)

    def test_row_deleted(self):
        assert records.is_closed_now(None, set()) is True

    def test_withdrawn(self):
        assert records.is_closed_now(self._change(status="已撤回"), set()) is True

    def test_accepted(self):
        change = self._change(change_no="FX-Z-9")
        accepted = {records.normalize_change_no("FX-Z-9")}
        assert records.is_closed_now(change, accepted) is True

    def test_terminated(self):
        assert records.is_closed_now(
            self._change(change_status="变更中止"), set()
        ) is True

    def test_open(self):
        assert records.is_closed_now(self._change(), set()) is False
