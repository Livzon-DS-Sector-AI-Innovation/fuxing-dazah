"""AI+安全日报 Bitable 存取层——四表 CRUD（daily_report 域）。

唯一写入者是机器人；「一人一天一条」的唯一性约束由本层查重保证
（Bitable 无唯一索引，查重键 = 日期键 + 员工OpenID，日期键过滤后客户端匹配）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.modules.safety.feishu.bitable_client import SafetyBitableClient

from . import config

# ═══════════════════════════════════════════════════════════
# 字段名（与 seed_daily_report.py 建表定义同源，改必同步）
# ═══════════════════════════════════════════════════════════

# 员工日报表
F_DATE = "日报日期"
F_DATE_KEY = "日期键"
F_NAME = "员工姓名"
F_OPEN_ID = "员工OpenID"
F_WORK = "今日重点工作"
F_DONE = "完成情况"
F_ISSUE = "问题与协调"
F_PLAN = "明日计划"
F_AI = "AI评价与建议"
F_STATUS = "日报状态"
F_FIRST_AT = "首次提交时间"
F_FINAL_AT = "完成提交时间"
# 汇总表
FS_DATE = "汇总日期"
FS_DATE_KEY = F_DATE_KEY
FS_REPORT = "负责人日报"
FS_PUBLISHED_AT = "发布时间"
# 名单表
FR_MEMBER = "成员"
FR_ROLE = "角色"
# 历史表
FH_OPEN_ID = F_OPEN_ID
FH_NAME = F_NAME
FH_STAGE = "阶段"
FH_CONTENT = "内容"

# 状态/枚举
ST_PENDING = "待补充"
ST_DONE = "已完成"
ST_EVAL_ERROR = "评价异常"
ROLE_MEMBER = "员工"
ROLE_LEADER = "负责人"
HIST_FIRST = "首次提交"
HIST_FINAL = "最终提交"
HIST_EVAL = "AI评价"

#: 四段内部键 → 表字段
SECTION_FIELDS: dict[str, str] = {
    "work": F_WORK,
    "done": F_DONE,
    "issue": F_ISSUE,
    "plan": F_PLAN,
}


def _ts(dt: datetime) -> int:
    """datetime → Bitable 日期字段毫秒时间戳。"""
    return int(dt.timestamp() * 1000)


def _ms_str(value: Any) -> str:
    """日期字段读值（毫秒时间戳/富文本段/str）→ 'MM-DD HH:MM' 展示串（BJ 时区）。"""
    text = plain(value)
    if text.isdigit() and len(text) >= 13:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        return _dt.fromtimestamp(
            int(text) / 1000, tz=ZoneInfo("Asia/Shanghai"),
        ).strftime("%m-%d %H:%M")
    return text[:16].replace("T", " ")


def date_key_filter(date_key: str, field: str = F_DATE_KEY) -> dict[str, Any]:
    """日期键精确匹配的结构化过滤（search body 只认 filter_info）。"""
    return {
        "conjunction": "and",
        "conditions": [{"field_name": field, "operator": "is", "value": [date_key]}],
    }


def plain(value: Any) -> str:
    """Bitable 字段值 → 纯文本（str 直取；富文本 list 拼接）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or ""))
            elif item is not None:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "")
    return str(value)


def _parse_person(value: Any) -> tuple[str, str]:
    """人员字段 → (name, open_id)；解析失败 → ("", "")。"""
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return (
                (first.get("name") or "").strip(),
                (first.get("id") or "").strip(),
            )
    return "", ""


@dataclass(frozen=True)
class RosterMember:
    """名单成员。"""

    open_id: str
    name: str
    role: str  # 员工 / 负责人


@dataclass(frozen=True)
class ReportRecord:
    """员工日报记录（读路径视图）。"""

    record_id: str
    open_id: str
    name: str
    status: str
    sections: dict[str, str]
    ai_advice: str
    first_at: str
    final_at: str


def client_for(kind: str) -> SafetyBitableClient | None:
    """按 kind 构造客户端；连接缺失/停用 → None（调用方走降级）。"""
    conn = config.connection(kind)
    if conn is None:
        return None
    return SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)


def _parse_report(item: dict[str, Any]) -> ReportRecord:
    f = item.get("fields", {})
    return ReportRecord(
        record_id=item.get("record_id", ""),
        open_id=plain(f.get(F_OPEN_ID)),
        name=plain(f.get(F_NAME)),
        status=plain(f.get(F_STATUS)) or ST_PENDING,
        sections={k: plain(f.get(v)) for k, v in SECTION_FIELDS.items()},
        ai_advice=plain(f.get(F_AI)),
        first_at=_ms_str(f.get(F_FIRST_AT)),
        final_at=_ms_str(f.get(F_FINAL_AT)),
    )


async def list_reports(date_key: str) -> list[ReportRecord]:
    """拉取某日全部日报记录（按日期键过滤；单日 ≤ 名单规模，量小）。"""
    client = client_for(config.KIND_REPORTS)
    if client is None:
        return []
    items = await client.list_all_records(
        filter_info=date_key_filter(date_key),
        strict=False,
    )
    return [_parse_report(it) for it in items]


async def find_report(date_key: str, open_id: str) -> ReportRecord | None:
    """一人一天一条：按 (日期键, open_id) 查重。"""
    for rec in await list_reports(date_key):
        if rec.open_id == open_id:
            return rec
    return None


async def upsert_report(
    date_key: str,
    open_id: str,
    name: str,
    sections: dict[str, str],
    now: datetime,
) -> tuple[str, bool]:
    """写入四段内容并推进状态机，返回 (record_id, created)。

    状态推进规则（service 层提交语义落地在此）：
    - 新记录 → 首次提交：置首次提交时间，状态=待补充（AI 评价在途）
    - 已有记录且处于 待补充/评价异常（未完成）→ 最终提交：完成时间+状态=已完成
    - 已是已完成 → 内容修订：只更新四段与完成时间（不再触发 AI 评价）
    """
    client = client_for(config.KIND_REPORTS)
    if client is None:
        return "", False
    existing = await find_report(date_key, open_id)

    section_fields = {SECTION_FIELDS[k]: (sections.get(k) or "") for k in SECTION_FIELDS}
    if existing is None:
        fields: dict[str, Any] = {
            F_DATE: _ts(now),
            F_DATE_KEY: date_key,
            F_NAME: name or open_id[-8:],
            F_OPEN_ID: open_id,
            F_STATUS: ST_PENDING,
            F_FIRST_AT: _ts(now),
            **section_fields,
        }
        created = await client.create_record(fields)
        return ((created or {}).get("record_id", ""), True)

    fields = dict(section_fields)
    if existing.status == ST_DONE:
        fields[F_FINAL_AT] = _ts(now)  # 已完成后的内容修订
    else:
        fields[F_STATUS] = ST_DONE
        fields[F_FINAL_AT] = _ts(now)
    await client.update_record(existing.record_id, fields)
    return existing.record_id, False


async def write_evaluation(record_id: str, advice: str, *, error: bool = False) -> bool:
    """AI 评价结果回填（评价异常也写状态，建议字段留旧值/空）。"""
    client = client_for(config.KIND_REPORTS)
    if client is None:
        return False
    fields: dict[str, Any] = {F_STATUS: ST_EVAL_ERROR if error else ST_PENDING}
    if not error:
        fields[F_AI] = advice
    return await client.update_record(record_id, fields)


async def append_history(
    date_key: str,
    open_id: str,
    name: str,
    stage: str,
    content: dict[str, Any],
) -> bool:
    """提交历史追加一行（初稿快照/AI建议留痕，append-only 不查重）。"""
    client = client_for(config.KIND_HISTORY)
    if client is None:
        return False
    fields = {
        F_DATE_KEY: date_key,
        FH_OPEN_ID: open_id,
        FH_NAME: name or "",
        FH_STAGE: stage,
        FH_CONTENT: json.dumps(content, ensure_ascii=False),
    }
    return bool(await client.create_record(fields))


async def load_roster() -> list[RosterMember]:
    """应提交名单（全部行；请假=直接从表中移除，不做按天豁免）。"""
    client = client_for(config.KIND_ROSTER)
    if client is None:
        return []
    items = await client.list_all_records(strict=False)
    members: list[RosterMember] = []
    for item in items:
        f = item.get("fields", {})
        name, open_id = _parse_person(f.get(FR_MEMBER))
        role = plain(f.get(FR_ROLE)) or ROLE_MEMBER
        if open_id:
            members.append(RosterMember(open_id=open_id, name=name, role=role))
    return members


async def get_summary(date_key: str) -> tuple[str, str, str] | None:
    """汇总记录 → (record_id, report_markdown, published_at)。"""
    client = client_for(config.KIND_SUMMARY)
    if client is None:
        return None
    items = await client.list_all_records(
        filter_info=date_key_filter(date_key),
        strict=False,
    )
    for item in items:
        f = item.get("fields", {})
        return (
            item.get("record_id", ""),
            plain(f.get(FS_REPORT)),
            _ms_str(f.get(FS_PUBLISHED_AT)),
        )
    return None


async def upsert_summary(date_key: str, report_markdown: str, now: datetime) -> str:
    """写入/覆盖汇总草稿（未发布），返回 record_id。"""
    client = client_for(config.KIND_SUMMARY)
    if client is None:
        return ""
    existing = await get_summary(date_key)
    if existing is None:
        created = await client.create_record({
            FS_DATE: _ts(now),
            FS_DATE_KEY: date_key,
            FS_REPORT: report_markdown,
        })
        return str((created or {}).get("record_id") or "")
    await client.update_record(existing[0], {FS_REPORT: report_markdown})
    return existing[0]


async def mark_summary_published(record_id: str, now: datetime) -> bool:
    """发布：写发布时间。"""
    client = client_for(config.KIND_SUMMARY)
    if client is None:
        return False
    return await client.update_record(record_id, {FS_PUBLISHED_AT: _ts(now)})
