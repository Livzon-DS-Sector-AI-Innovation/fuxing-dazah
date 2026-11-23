"""《设备设施安全联锁安全附件变更审批》记录解析 —— 纯函数（无 DB 无 IO）。

字段形态实测 2026-11-18（base FGUHbF1DJamdjJskoKhcj7kbngf / tblWlELZ5YiKMB95，49 行）：
- 申请编号：**单 dict 段** {"text": "202611160468", "link": applink, "type": "url"}
  （2026-11-18 raw API 实测；首版误按 list 段实现，致卡面显示 record_id/缺链接）
- 预警状态：公式 dict {"type": 3, "value": ["二级红色报警"]}；
  「二级红色报警」=审批中+过预计恢复（表侧公式维护，本模块不重复判定）
- 部门等单选：list[str] 形态（如 ["提炼工程四部"]）
- 发起人/工艺负责人/安全负责人/当前处理人：人员字段 list[{"id": ou_…, "name": …}]
  （安全应用作用域 open_id，实测 contact 直查姓名对上，可直发私聊）
- 变更时间/预计恢复时间：毫秒时间戳（北京零点对齐）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
_APPLINK_MARK = "applink.feishu.cn"
_MARKDOWN_APPLINK_RE = re.compile(r"\((https?://applink\.feishu\.cn[^)]+)\)")
_LOCATION_MAX_LEN = 80

# ── 人员字段三角色 + 处理人（spec 4.2；发起人=申请人，用户拍板）──
ROLE_APPLICANT = "发起人"
ROLE_PROCESS_OWNER = "工艺负责人"
ROLE_SAFETY_OWNER = "安全负责人"


@dataclass(frozen=True)
class RedRecord:
    """一条红色预警记录解析后的业务事实。"""

    record_id: str
    code: str | None                    # 申请编号
    approval_url: str | None            # 审批详情 applink（缺省卡面略链）
    department: str | None
    facility_type: str | None           # 安全设施类型
    is_critical: bool                   # 是否为关键装置、重点部位=是
    location: str | None                # 岗位及设备设施名称（截 80）
    changed_on: str | None              # 变更时间 YYYY-MM-DD
    expected_recovery_on: str | None    # 预计恢复时间 YYYY-MM-DD
    overdue_days: int | None            # 今日-预计恢复日；预计恢复空 → None
    node: str | None                    # 审批节点
    handler_name: str | None            # 当前处理人（首个姓名，卡面提示用）
    applicants: tuple[tuple[str, str], ...]        # 发起人 (name, open_id)
    process_owners: tuple[tuple[str, str], ...]    # 工艺负责人
    safety_owners: tuple[tuple[str, str], ...]     # 安全负责人


def flat_text(value: Any) -> str | None:
    """Bitable 富文本/公式/单选 → 纯文本；空 → None。

    覆盖：str（单选直值）、段列表 [{"text": …}]、单 dict 段（申请编号
    {"text","link","type":"url"} 形态）、公式 dict {"value": [...]}、
    str 元素列表（select 兜底）。畸形段跳过不炸。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        if "value" in value:
            return flat_text(value["value"])
        text = value.get("text", value.get("name"))
        return text.strip() if isinstance(text, str) and text.strip() else None
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text", item.get("name"))
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip() or None
    return str(value)


def parse_person_list(value: Any) -> tuple[tuple[str, str], ...]:
    """人员字段（multiple）→ ((name, open_id), …)；缺 id 成员跳过。"""
    if not isinstance(value, list):
        return ()
    out: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        open_id = (item.get("id") or "").strip()
        if name and open_id:
            out.append((name, open_id))
    return tuple(out)


def extract_applink(value: Any) -> str | None:
    """申请编号富文本 → applink 审批详情 URL；无链接 → None。

    覆盖形态：单 dict 段/段列表内 dict 带 "link" 键（raw API 实测）；
    或整列扁平后含 markdown 链接 [x](url)。
    """
    segments: list[Any] = value if isinstance(value, list) else [value]
    for item in segments:
        if isinstance(item, dict):
            link = item.get("link")
            if isinstance(link, str) and _APPLINK_MARK in link:
                return link
    flat = flat_text(value)
    if flat:
        m = _MARKDOWN_APPLINK_RE.search(flat)
        if m:
            return m.group(1)
    return None


def ms_to_date(value: Any) -> str | None:
    """毫秒时间戳 → 北京时区 YYYY-MM-DD；非数值 → None。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return (
            datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            .astimezone(_TZ_SHANGHAI)
            .date()
            .isoformat()
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def overdue_days(today: date, expected_recovery_on: str | None) -> int | None:
    """今日 − 预计恢复日（天）；预计恢复空 → None（不参与 ⚠️ 判定）。"""
    if not expected_recovery_on:
        return None
    try:
        expected = date.fromisoformat(expected_recovery_on)
    except ValueError:
        return None
    return (today - expected).days


def _is_critical(value: Any) -> bool:
    return flat_text(value) == "是"


def parse_red_record(
    record_id: str, fields: dict[str, Any], today: date
) -> RedRecord:
    """整条记录 fields → RedRecord（filter_red_records 的单条版）。"""
    location = flat_text(fields.get("岗位及设备设施名称"))
    expected_on = ms_to_date(fields.get("预计恢复时间"))
    handler = parse_person_list(fields.get("当前处理人"))
    return RedRecord(
        record_id=record_id,
        code=flat_text(fields.get("申请编号")),
        approval_url=extract_applink(fields.get("申请编号")),
        department=flat_text(fields.get("部门")),
        facility_type=flat_text(fields.get("安全设施类型")),
        is_critical=_is_critical(fields.get("是否为关键装置、重点部位")),
        location=(location[:_LOCATION_MAX_LEN] if location else None),
        changed_on=ms_to_date(fields.get("变更时间")),
        expected_recovery_on=expected_on,
        overdue_days=overdue_days(today, expected_on),
        node=flat_text(fields.get("审批节点")),
        handler_name=(handler[0][0] if handler else None),
        applicants=parse_person_list(fields.get(ROLE_APPLICANT)),
        process_owners=parse_person_list(fields.get(ROLE_PROCESS_OWNER)),
        safety_owners=parse_person_list(fields.get(ROLE_SAFETY_OWNER)),
    )


def filter_red_records(
    rows: list[dict[str, Any]], *, today: date
) -> list[RedRecord]:
    """全表行 → 红色记录列表（预警状态扁平化含「红色」；判定逻辑表侧公式维护）。"""
    out: list[RedRecord] = []
    for row in rows:
        fields = row.get("fields") or {}
        warn_state = flat_text(fields.get("预警状态")) or ""
        if "红色" not in warn_state:
            continue
        out.append(parse_red_record(row.get("record_id") or "", fields, today))
    return out
