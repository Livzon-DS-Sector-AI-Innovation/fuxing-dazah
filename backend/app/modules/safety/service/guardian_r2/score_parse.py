"""成绩表《理论考试分数表》字段解析 —— 纯函数（无 DB 无 IO）。

字段形态实测 2026-11-04（base OKxib32E5apWgUs0dYBcObH4nNe / tblJ7mW0OrgxwXfA，353 行）：
- 姓名：人员字段（含安全应用 open_id，私信直取链第一层）
- 报名考试类型：单选 监护人A证/监护人B证 → A/B 持证表路由
- 考试分数：数字 0-100（缺考为 0 或空）
- 是否合格：**公式列** → {"type": 1, "value": [{"text": "合格"|"不合格"}]}；
  缺考记录无该键（公式空值）——None ≠ 不合格
- 考试日期：**公式列** → {"type": 5, "value": [<毫秒>]}；回退「参加考试日期」
  单选文本（yyyy年M月d日）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

# 飞书日期公式值为北京时间零点毫秒（实测 1763308800000=2025-11-17 北京）
_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

_SELECT_DATE_RE = re.compile(
    r"(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"
)


@dataclass(frozen=True)
class ScoreFacts:
    """一条成绩记录解析后的业务事实（辨别算法输入）。"""

    person_name: str | None
    open_id: str | None          # 安全应用 open_id（人员字段直取）
    department: str | None
    cert_category: str | None    # guardian_a / guardian_b（报名考试类型路由）
    passed: str | None           # "合格" / "不合格" / None（缺考/空）
    exam_date: date | None       # 考试日期公式优先，单选文本回退
    score_value: float | None    # 考试分数原始值


def _flat_text(value: Any) -> str | None:
    """Bitable 富文本/公式富文本 → 纯文本；空 → None。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        inner = value.get("value", value)
        return _flat_text(inner)
    if isinstance(value, list):
        parts = [
            str(item.get("text") or item.get("name") or "")
            for item in value
            if isinstance(item, dict)
        ]
        return "".join(parts).strip() or None
    return str(value)


def parse_pass(value: Any) -> str | None:
    """「是否合格」公式列 → 合格/不合格/None（缺考空值不误判）。"""
    text = _flat_text(value)
    if text == "合格":
        return "合格"
    if text == "不合格":
        return "不合格"
    return None


def parse_exam_date(fields: dict[str, Any]) -> date | None:
    """考试日期：公式列（type 5 毫秒）优先；回退「参加考试日期」单选文本。"""
    formula = fields.get("考试日期")
    if isinstance(formula, dict):
        values = formula.get("value")
        if isinstance(values, list) and values:
            try:
                ms = int(values[0])
                return datetime.fromtimestamp(
                    ms / 1000, tz=timezone.utc
                ).astimezone(_TZ_SHANGHAI).date()
            except (TypeError, ValueError, OSError):
                pass
    text = _flat_text(fields.get("参加考试日期"))
    if text:
        m = _SELECT_DATE_RE.search(text)
        if m:
            try:
                return date(int(m["y"]), int(m["m"]), int(m["d"]))
            except ValueError:
                return None
    return None


def parse_person(value: Any) -> tuple[str | None, str | None]:
    """人员字段 → (name, open_id)；空 → (None, None)。"""
    if not isinstance(value, list) or not value:
        return None, None
    first = value[0]
    if not isinstance(first, dict):
        return None, None
    name = (first.get("name") or "").strip() or None
    open_id = (first.get("id") or "").strip() or None
    return name, open_id


def parse_exam_type_ab(value: Any) -> str | None:
    """「报名考试类型」→ guardian_a/guardian_b（A/B 持证表路由）。"""
    text = _flat_text(value)
    if text == "监护人A证":
        return "guardian_a"
    if text == "监护人B证":
        return "guardian_b"
    return None


def parse_score_number(value: Any) -> float | None:
    """「考试分数」数字列 → float（0 分是有效值，None 才是空）。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_score_record(fields: dict[str, Any]) -> ScoreFacts:
    """整条成绩记录 fields → ScoreFacts（辨别算法统一入口）。"""
    name, open_id = parse_person(fields.get("姓名"))
    dept = _flat_text(fields.get("部门"))
    return ScoreFacts(
        person_name=name,
        open_id=open_id,
        department=dept,
        cert_category=parse_exam_type_ab(fields.get("报名考试类型")),
        passed=parse_pass(fields.get("是否合格")),
        exam_date=parse_exam_date(fields),
        score_value=parse_score_number(fields.get("考试分数")),
    )
