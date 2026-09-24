"""消防报警分析 — AI prompt（前缀缓存友好）。

规则：
- system 消息为模块级稳定常量，不含动态数据（DeepSeek prompt_cache 命中前缀）
- 动态数据（记录字段 / 统计 JSON / RAG 法规文本）全部拼在 user 末尾
- chat_parsed 默认 response_format=json_object，AI 只输出 JSON 结构，
  排版由 renderer 完成

月报 prompt（原周报 prompt，2026-09-22 改造）：分析只围绕
重复问题、原因归纳、整改建议三件事，防跑题。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.modules.safety.models import FireAlarmRecord
from app.modules.safety.service.fire_alarm.aggregator import (
    FireAlarmDailyAgg,
    FireAlarmMonthlyAgg,
)

# 月报 prompt 引用的报警清单上限（按报警时间倒序取最近 N 条，防超长 prompt；
# 自然月约 250 起量级，全量覆盖不截断）
MAX_MONTHLY_RECORDS_IN_PROMPT = 250

# ── chat_parsed 校验的顶层字段 ──
EXPECTED_KEYS_PER_RECORD: list[str] = [
    "dimension", "reason_analysis", "rectification_direction",
]
EXPECTED_KEYS_DAILY_SUMMARY: list[str] = [
    "summary", "key_issues", "rectification_suggestions",
]
EXPECTED_KEYS_MONTHLY_SUMMARY: list[str] = [
    "recurring_issues", "cause_summary", "rectification_suggestions",
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

_MONTHLY_SUMMARY_SYSTEM_PROMPT = """你是一名化工企业消防安全管理专家。输入为上一自然月全部消防报警清单、统计分布与重复问题清单。请生成月度分析，内容只允许围绕三件事：
① 重复问题——哪些部位/类型的报警反复发生；
② 原因——反复发生与高发报警的根因归纳；
③ 整改建议——针对上述问题给出可落地的整改措施。
不要输出与这三件事无关的内容（不要写通用安全宣教、不要评价整体安全管理水平、不要编造趋势对比）。

## 输出 JSON 结构
{"recurring_issues": [{"pattern": "部位-报警类型", "count": 3, "cause": "反复发生的根因", "suggestion": "针对性整改措施"}], "cause_summary": "本月报警原因归纳（120-250字）", "rectification_suggestions": [{"issue": "对应的问题", "suggestion": "具体整改动作", "departments": ["建议牵头部门"]}]}

## 要求
- recurring_issues: 只从给定「重复问题清单」和报警明细中提取（count>=2），按 count 降序，至多 5 条；无重复问题时输出空数组 []。每条 count 用整数；cause 必须结合该部位的具体报警原因描述说明为什么会反复发生（如同一部件老化、同一操作环节失误），不允许只复述"多次报警"；suggestion 给出可验证的具体动作（更换/检修/校验/加装/培训等）。
- cause_summary: 归纳上月报警原因的共性规律（按给定的维度分布/类型分布/明细归纳，如"集中于X类设备的Y故障"），只概括数据中出现过的证据；无数据支撑的推断不写。
- rectification_suggestions: 1-5 条，与 recurring_issues 或 cause_summary 中的问题一一对应；issue 点名问题，suggestion 写具体措施与验收标准（做到什么程度算整改完成）；禁止"加强管理""提高意识""落实责任"等无动作空话；departments 填建议牵头部门（从数据涉及部门中选）。
- 所有结论必须能对应到给定数据（部位/次数/部门/原因描述），数据里没有的不写，不编造。

## 示例输出
{"recurring_issues": [{"pattern": "1号装置/压缩机房-火灾报警", "count": 3, "cause": "同一批次可燃气体传感器老化漂移，连续误触发", "suggestion": "整批更换该型传感器，并建立季度标定台账"}], "cause_summary": "上月 28 起报警中误报占 21 起，其中 14 起集中于压缩机房传感器类设备故障，属设备设施维度共性问题。", "rectification_suggestions": [{"issue": "压缩机房传感器批量老化误报", "suggestion": "两周内完成整批更换并逐台标定，此后每季度校验一次并留存记录", "departments": ["动力车间"]}]}"""


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


def build_monthly_summary_messages(agg: FireAlarmMonthlyAgg) -> list[dict[str, str]]:
    """构造月报汇总 messages（重复问题/原因/整改建议三板块）。"""
    stats = {
        "月起止": f"{agg.month_start.isoformat()} ~ {agg.month_end.isoformat()}",
        "报警总数": agg.total,
        "性质分布": agg.nature_distribution,
        "类型分布": agg.type_distribution,
        "部门分布": agg.department_distribution,
        "重复问题清单": agg.recurring_patterns,
    }
    # 记录紧凑摘要（cause_description 截断，供 AI 输入）
    # 条数上限：按报警时间倒序取最近 MAX_MONTHLY_RECORDS_IN_PROMPT 条，超出注明"仅展示部分记录"
    ordered = sorted(
        agg.records,
        key=lambda r: r.alarm_time or datetime(1, 1, 1, tzinfo=UTC),
        reverse=True,
    )
    limited = ordered[:MAX_MONTHLY_RECORDS_IN_PROMPT]
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
    user = f"""请基于以下上月消防报警数据生成月度汇总分析：

{json.dumps(stats, ensure_ascii=False, indent=2)}

全量报警清单（紧凑摘要）{records_note}：
{json.dumps(records_summary, ensure_ascii=False, indent=2)}

请输出 JSON（不要输出其他内容）。"""
    return [
        {"role": "system", "content": _MONTHLY_SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _bj(dt: datetime | None) -> str:
    """UTC → 北京时间字符串（M/D HH:MM）。"""
    if dt is None:
        return "?"
    return (dt + timedelta(hours=8)).strftime("%m/%d %H:%M")
