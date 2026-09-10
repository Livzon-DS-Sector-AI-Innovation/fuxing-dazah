"""消防报警分析 — AI prompt（前缀缓存友好）。

规则：
- system 消息为模块级稳定常量，不含动态数据（DeepSeek prompt_cache 命中前缀）
- 动态数据（记录字段 / 统计 JSON / RAG 法规文本）全部拼在 user 末尾
- chat_parsed 默认 response_format=json_object，AI 只输出 JSON 结构，
  排版由 renderer 完成

周报 prompt 一并建好供 ticket 06 使用（本期日报流程不使用）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.modules.safety.models import FireAlarmRecord
from app.modules.safety.service.fire_alarm.aggregator import (
    FireAlarmDailyAgg,
    FireAlarmWeeklyAgg,
)

# 周报 prompt 引用的报警清单上限（按报警时间倒序取最近 N 条，防超长 prompt）
MAX_WEEKLY_RECORDS_IN_PROMPT = 120

# ── chat_parsed 校验的顶层字段 ──
EXPECTED_KEYS_PER_RECORD: list[str] = [
    "dimension", "reason_analysis", "rectification_direction",
]
EXPECTED_KEYS_DAILY_SUMMARY: list[str] = [
    "summary", "key_issues", "rectification_suggestions",
]
EXPECTED_KEYS_WEEKLY_SUMMARY: list[str] = [
    "summary", "typical_issues", "recurring_issues",
    "systemic_suggestions", "trend",
]

# ── STABLE system prompt（前缀缓存：system 稳定，动态数据放 user 末尾）──
_PER_RECORD_SYSTEM_PROMPT = """你是一名化工企业消防安全管理专家。你将收到一条消防报警记录（人工填写的报警原因），请结合参考法规（如有）做二次理解与归类。

## 输出 JSON 结构
{"dimension": "工艺|人员操作|设备设施|其他", "reason_analysis": "...", "rectification_direction": "..."}

## 字段要求
- dimension: 四选一。工艺=生产过程/工艺参数相关；人员操作=人为误操作/违章；设备设施=设备故障/老化/设计缺陷；其他=上述之外的。
- reason_analysis: 40-120 字自然语言，重写并明确报警根因（不照抄原文，聚焦核心）。
- rectification_direction: 30-80 字，具体可操作的整改方向（不说空话）。

## ⚠️ 重要规则
- 只基于给定数据分析，不编造；字段缺失时如实说明。
- AI 不直接替代现场人员对报警事件的确认，结论仅供参考。"""

_DAILY_SUMMARY_SYSTEM_PROMPT = """你是一名化工企业消防安全管理专家。输入为当日全部消防报警清单与逐条 AI 分析摘要，请生成当日汇总分析。

## 输出 JSON 结构
{"summary": "...", "key_issues": ["..."], "rectification_suggestions": ["..."]}

## 要求
- summary: 80-150 字，概括当日报警态势（部门集中度/类型集中度/维度集中度）。
- key_issues: 1-3 条，每条一句话，突出共性与重点问题。
- rectification_suggestions: 1-3 条，每条一句话，针对共性问题给整改建议。
- 只基于给定数据，不编造。"""

_WEEKLY_SUMMARY_SYSTEM_PROMPT = """你是一名化工企业消防安全管理专家。输入为本周（周一~周日）全部消防报警清单、统计分布与重复问题，请生成周级汇总分析。

## 输出 JSON 结构
{"summary": "...", "typical_issues": [{"title":"...","evidence":"..."}], "recurring_issues": [{"pattern":"...","count":n,"departments":["..."]}], "systemic_suggestions": [{"issue":"...","suggestion":"..."}], "trend": {"summary":"...","trend":"上升|平稳|下降"}}

## 要求
- summary: 100-200 字，概括本周报警态势（总量/部门/类型/维度/重复问题）。
- typical_issues: 1-3 条，突出本周典型与高风险。
- recurring_issues: 从重复问题清单与描述中识别重复模式（count 用整数）。
- systemic_suggestions: 1-3 条系统性整改建议。
- trend: 基于本周数据推导趋势（一句话 + 趋势判断）。
- 只基于给定数据，不编造。

## 示例输出
{"summary": "本周报警集中于A部门设备设施类误报，重复报警 2 起。", "typical_issues": [{"title": "传感器老化误报", "evidence": "1号装置压缩机房发生 2 次"}], "recurring_issues": [{"pattern": "1号装置/压缩机房-火灾报警", "count": 2, "departments": ["A部门"]}], "systemic_suggestions": [{"issue": "同批次传感器老化", "suggestion": "统一更换并建立周期校验台账"}], "trend": {"summary": "总量较上周持平", "trend": "平稳"}}"""


def build_per_record_messages(
    record: FireAlarmRecord, rag_md: str,
) -> list[dict[str, str]]:
    """构造单条记录分析的 messages（system 稳定 + user 动态）。

    前缀缓存规则：system 不变；user 末尾追加动态数据（rag_md + 记录字段）。
    """
    user_lines = [
        "## 报警记录分析",
        f"- 报警时间: {_bj(record.alarm_time)}",
        f"- 报警类型: {record.alarm_type or '?'}",
        f"- 报警部门: {record.department or '?'}",
        f"- 报警楼栋: {record.building or '?'}",
        f"- 报警部位: {record.location or '?'}",
        f"- 报警性质: {record.alarm_nature or '?'}",
        f"- 报警原因分类（人工）: {record.cause_category or '?'}",
        f"- 具体报警原因（人工）: {(record.cause_description or '')[:200]}",
    ]
    if rag_md:
        user_lines.append(f"- 参考法规: {rag_md[:1500]}")
    user_lines.append("请输出 JSON。")
    return [
        {"role": "system", "content": _PER_RECORD_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def build_daily_summary_messages(
    agg: FireAlarmDailyAgg, per_summaries: list[str],
) -> list[dict[str, str]]:
    """构造日报汇总 messages。"""
    stats = {
        "日期": agg.target_date.isoformat(),
        "报警总数": agg.total,
        "性质分布": agg.nature_distribution,
        "类型分布": agg.type_distribution,
        "部门分布": agg.department_distribution,
    }
    user = f"""请基于以下当日消防报警数据（JSON）生成汇总分析：

{json.dumps(stats, ensure_ascii=False, indent=2)}

逐条 AI 分析摘要：
{json.dumps(per_summaries, ensure_ascii=False, indent=2)}

请输出 JSON（不要输出其他内容）。"""
    return [
        {"role": "system", "content": _DAILY_SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_weekly_summary_messages(agg: FireAlarmWeeklyAgg) -> list[dict[str, str]]:
    """构造周报汇总 messages（ticket 06 使用）。"""
    stats = {
        "周起止": f"{agg.week_start.isoformat()} ~ {agg.week_end.isoformat()}",
        "报警总数": agg.total,
        "性质分布": agg.nature_distribution,
        "类型分布": agg.type_distribution,
        "部门分布": agg.department_distribution,
        "重复问题清单": agg.recurring_patterns,
    }
    # 记录紧凑摘要（cause_description 截断，供 AI 输入）
    # 条数上限：按报警时间倒序取最近 MAX_WEEKLY_RECORDS_IN_PROMPT 条，超出注明"仅展示部分记录"
    ordered = sorted(
        agg.records,
        key=lambda r: r.alarm_time or datetime(1, 1, 1, tzinfo=UTC),
        reverse=True,
    )
    limited = ordered[:MAX_WEEKLY_RECORDS_IN_PROMPT]
    records_summary = [
        {
            "alarm_time": _bj(r.alarm_time),
            "department": r.department or "",
            "building": r.building or "",
            "location": r.location or "",
            "alarm_type": r.alarm_type or "",
            "cause_description": (r.cause_description or "")[:120].replace("\n", " "),
            "ai_dimension": r.ai_dimension or "",
        }
        for r in limited
    ]
    records_note = (
        f"（仅展示部分记录：共 {len(ordered)} 条，仅列出最近 {len(limited)} 条）"
        if len(ordered) > len(limited)
        else ""
    )
    user = f"""请基于以下本周消防报警数据生成周级汇总分析：

{json.dumps(stats, ensure_ascii=False, indent=2)}

全量报警清单（紧凑摘要）{records_note}：
{json.dumps(records_summary, ensure_ascii=False, indent=2)}

请输出 JSON（不要输出其他内容）。"""
    return [
        {"role": "system", "content": _WEEKLY_SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _bj(dt: datetime | None) -> str:
    """UTC → 北京时间字符串（M/D HH:MM）。"""
    if dt is None:
        return "?"
    return (dt + timedelta(hours=8)).strftime("%m/%d %H:%M")
