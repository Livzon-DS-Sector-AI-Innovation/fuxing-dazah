"""EHS 变更审批/验收记录解析与关闭判定 —— 纯函数（无 DB 无 IO）。

字段形态实测 2026-11-24（Base X7mEbClq3asgrlsofZJczNiCnwb，
审批表 tblt0Rv0UaXZT4AK 312 行 / 验收表 tblaNPRi14i8CgS5 262 行，
scripts-tmp/probe_ehs_change_status.py）：
- 审批表「申请编号」：单 dict 段 {"text","link","type":"url"}（applink 卡面直达）；
- 「变更申请编号」/「变更名称」/「变更最新具体进展」：富文本段列表；
- 「变更申请部门」：multi-select list[str]；
- 「变更状态」：单选 str；「预计实施日期」：毫秒时间戳（北京零点对齐）；
- 验收表「关联审批」：文本，开头 12 位数字=审批表「申请编号」；
- 验收表「变更编号」：仅 14 行有值。

关闭判定（DESIGN §2，2026-11-24 定稿）：只认「已通过」验收单（按变更编号
归属，两条路径都认），不看人工填的「变更状态」；变更中止两种都算关闭；
排除清单剔除。周一复查时申请被撤回/删除也算关闭。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# 变更编号归一：去连字符/空格（含全角），大写（probe_ehs_change_rule.py 同款）
_CHANGE_NO_STRIP = re.compile(r"[-\s　]")
# 验收单「关联审批」开头 12 位审批编号
_RELATED_CODE_RE = re.compile(r"^(\d{12})")

# 中止取值（「变更状态」列参与判定的唯一地方）
TERMINATED_STATUSES = ("变更中止", "中止")

APPROVED = "已通过"


def normalize_change_no(value: str | None) -> str:
    """变更编号归一：去连字符/空格、大写（两条关联路径比较前的统一口径）。"""
    return _CHANGE_NO_STRIP.sub("", value or "").strip().upper()


def flat_text(value: Any) -> str:
    """Bitable 字段值 → 纯文本（str 直取；空=空串）。

    两种列表形态分开处理（probe txt 同款）：富文本段列表无缝拼接；
    multi-select 的 list[str] 逗号连接（否则多部门会粘成一串）。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        if "value" in value:
            return flat_text(value["value"])
        text = value.get("text", value.get("name"))
        return text.strip() if isinstance(text, str) else ""
    if isinstance(value, list):
        if value and all(isinstance(item, str) for item in value):
            return ",".join(value).strip()      # select 兜底 / multi-select
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text", item.get("name"))
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()           # 富文本段无缝
    return str(value)


def _ms_to_date(value: Any) -> str | None:
    """毫秒时间戳 → YYYY-MM-DD（北京时间）；非数值返回 None。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return datetime.fromtimestamp(value / 1000, _TZ_SHANGHAI).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class ApprovalChange:
    """一条审批单解析后的业务事实（督办范围筛选用）。"""

    record_id: str
    change_no: str                      # 变更申请编号（原始）
    approval_code: str                  # 申请编号（12 位审批码）
    approval_url: str                   # 审批详情 applink（缺省空）
    title: str
    department: str                     # 多部门逗号分隔
    status: str                         # 申请状态
    change_status: str                  # 「变更状态」原样（仅展示/中止判定）
    progress: str                       # 变更最新具体进展全文
    expected_start: str | None          # 预计实施日期 YYYY-MM-DD

    @property
    def change_no_norm(self) -> str:
        return normalize_change_no(self.change_no)

    @property
    def departments(self) -> list[str]:
        return [d for d in (x.strip() for x in self.department.split(",")) if d]


@dataclass(frozen=True)
class AcceptanceRef:
    """一条验收单的关联事实（归属判定用）。"""

    record_id: str
    status: str                         # 申请状态
    related_code: str                   # 「关联审批」开头 12 位（可空）
    change_no: str                      # 「变更编号」（可空）


# ── 排除项标注（DESIGN §2.4 四型）──

NOTE_IN_REVIEW = "验收单审批中"
NOTE_WITHDRAWN = "验收单已撤回"
NOTE_NOT_FOUND = "未找到验收单"
NOTE_SIBLING_COVERED = "疑似已由兄弟变更验收单覆盖，请核实补挂"

# 深查结论覆盖（2026-11-24 §2.4 逐项核查）：-002 的覆盖关系只有人工深查能定
# （兄弟变更名下有验收单），代码不可推导，按编号预置；业务补挂后自然失效
# （随排除清单一起移除）。
_NOTE_OVERRIDES: dict[str, str] = {
    normalize_change_no("FX-D4-2026-002"): NOTE_SIBLING_COVERED,
}


def parse_approval_row(rec: dict[str, Any]) -> ApprovalChange | None:
    """审批表原始行 → ApprovalChange（record_id 缺失返回 None）。"""
    record_id = str(rec.get("record_id") or "")
    if not record_id:
        return None
    f = rec.get("fields") or {}
    code_field = f.get("申请编号")
    approval_url = ""
    if isinstance(code_field, dict):
        link = code_field.get("link")
        if isinstance(link, str):
            approval_url = link
    return ApprovalChange(
        record_id=record_id,
        change_no=flat_text(f.get("变更申请编号")),
        approval_code=flat_text(code_field),
        approval_url=approval_url,
        title=flat_text(f.get("变更名称")),
        department=flat_text(f.get("变更申请部门"))
        .replace("，", ",")
        .strip(", "),
        status=flat_text(f.get("申请状态")),
        change_status=flat_text(f.get("变更状态")),
        progress=flat_text(f.get("变更最新具体进展")),
        expected_start=_ms_to_date(f.get("预计实施日期")),
    )


def parse_acceptance_row(rec: dict[str, Any]) -> AcceptanceRef | None:
    """验收表原始行 → AcceptanceRef。"""
    record_id = str(rec.get("record_id") or "")
    if not record_id:
        return None
    f = rec.get("fields") or {}
    related = flat_text(f.get("关联审批"))
    mo = _RELATED_CODE_RE.match(related)
    return AcceptanceRef(
        record_id=record_id,
        status=flat_text(f.get("申请状态")),
        related_code=mo.group(1) if mo else "",
        change_no=flat_text(f.get("变更编号")),
    )


def accepted_change_numbers(
    acceptances: list[AcceptanceRef],
    approvals: list[ApprovalChange],
) -> set[str]:
    """「已通过」验收单覆盖的变更编号集合（归一化；DESIGN §2.2 两条路都认）。

    路径① 验收单「关联审批」开头 12 位 → 审批行 → 其「变更申请编号」；
    路径② 验收单自己的「变更编号」。
    """
    by_code = {a.approval_code: a for a in approvals if a.approval_code}
    numbers: set[str] = set()
    for acc in acceptances:
        if acc.status != APPROVED:
            continue
        if acc.related_code:
            row = by_code.get(acc.related_code)
            if row is not None:
                numbers.add(row.change_no_norm)
        own = normalize_change_no(acc.change_no)
        if own:
            numbers.add(own)
    numbers.discard("")
    return numbers


def acceptance_note_for(
    change: ApprovalChange,
    acceptances: list[AcceptanceRef],
    approvals: list[ApprovalChange],
) -> str:
    """排除项标注：从该变更名下验收单的申请状态推导（§2.4 四型）。

    名下有审批中 → 验收单审批中；有已撤回 → 验收单已撤回；
    兄弟覆盖特例预置覆盖；其余 → 未找到验收单。
    """
    overridden = _NOTE_OVERRIDES.get(change.change_no_norm)
    if overridden:
        return overridden
    by_code = {a.approval_code: a for a in approvals if a.approval_code}
    own_norm = change.change_no_norm
    statuses: list[str] = []
    for acc in acceptances:
        hit = False
        if acc.related_code:
            row = by_code.get(acc.related_code)
            if row is not None and row.change_no_norm == own_norm:
                hit = True
        if not hit and normalize_change_no(acc.change_no) == own_norm:
            hit = True
        if hit:
            statuses.append(acc.status)
    if "审批中" in statuses:
        return NOTE_IN_REVIEW
    if "已撤回" in statuses:
        return NOTE_WITHDRAWN
    return NOTE_NOT_FOUND


@dataclass(frozen=True)
class FollowupFacts:
    """周五口径筛分结果（DESIGN §2.3 的四桶 + 提示桶）。"""

    todo: list[ApprovalChange] = field(default_factory=list)          # 待督办
    closed_accepted: list[ApprovalChange] = field(default_factory=list)  # 验收单已通过（关闭）
    closed_terminated: list[ApprovalChange] = field(default_factory=list)  # 变更中止（关闭）
    excluded: list[tuple[ApprovalChange, str]] = field(default_factory=list)  # (变更, 标注)
    # 验收单已通过但「变更状态」没改成已验收（已关闭，速递格提示用，§2.4 末段）
    status_stale_accepted: list[str] = field(default_factory=list)


def split_followup(
    approvals: list[ApprovalChange],
    acceptances: list[AcceptanceRef],
    excluded_numbers: set[str],
) -> FollowupFacts:
    """筛分：已通过审批单 → 关闭/排除/待督办（撤回/拒绝/审批中天然不进）。"""
    accepted = accepted_change_numbers(acceptances, approvals)
    facts = FollowupFacts()
    for change in approvals:
        if change.status != APPROVED:
            continue
        if change.change_no_norm in accepted:
            facts.closed_accepted.append(change)
            if change.change_status != "已验收":
                facts.status_stale_accepted.append(change.change_no)
            continue
        if change.change_status in TERMINATED_STATUSES:
            facts.closed_terminated.append(change)
            continue
        if change.change_no_norm in {normalize_change_no(x) for x in excluded_numbers if x}:
            facts.excluded.append(
                (change, acceptance_note_for(change, acceptances, approvals))
            )
            continue
        facts.todo.append(change)
    return facts


# ── 周一三类判定（DESIGN §5，顺序命中即止）──

def classify_item(
    *,
    closed_now: bool,
    progress_friday: str | None,
    progress_monday: str | None,
    status_friday: str | None,
    status_monday: str | None,
    unchanged_clicked: bool,
) -> str:
    """单项周一判定：closed → ③更新（进展或状态变）→ ②按钮 → ①未更新。"""
    if closed_now:
        return "closed"
    if (progress_monday or "").strip() != (progress_friday or "").strip():
        return "updated"
    if (status_monday or "").strip() != (status_friday or "").strip():
        return "updated"
    if unchanged_clicked:
        return "unchanged"
    return "not_updated"


def is_closed_now(
    change: ApprovalChange | None,
    accepted: set[str],
) -> bool:
    """周一复查单项是否已关闭：行被删（None）/申请非已通过（撤回等）/
    验收单已通过/变更中止，都算关闭。"""
    if change is None:
        return True
    if change.status != APPROVED:
        return True
    if change.change_no_norm in accepted:
        return True
    if change.change_status in TERMINATED_STATUSES:
        return True
    return False
