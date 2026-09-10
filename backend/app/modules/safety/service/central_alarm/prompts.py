"""中控报警分析 — AI prompt（前缀缓存友好）。

规则：
- system 消息为模块级稳定常量，不含动态数据（DeepSeek prompt_cache 命中前缀）
- 动态数据（记录字段 / 历史上下文 / 统计 JSON）全部拼在 user 末尾
- chat_parsed 默认 response_format=json_object，AI 只输出 JSON 结构，
  排版由 renderer 完成
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from app.modules.safety.models import CentralAlarmRecord
from app.modules.safety.service.central_alarm.aggregator import CentralAlarmDailyAgg

# ── chat_parsed 校验的顶层字段 ──
EXPECTED_KEYS_PER_RECORD: list[str] = [
    "alarm_type", "equipment", "pattern", "dimension", "reason_analysis", "rectification_direction",
]
EXPECTED_KEYS_DAILY_SUMMARY: list[str] = [
    "summary", "key_issues", "rectification_suggestions",
]

# ── STABLE system prompt（前缀缓存：system 稳定，动态数据放 user 末尾）──
_PER_RECORD_SYSTEM_PROMPT = """你是一名化工企业生产安全/中控报警分析专家。你将收到一条中控报警记录（自由文本「报警情况说明」）及其历史趋势上下文，请做结构化抽取与异常模式识别。

## 输出 JSON 结构
{"alarm_type": "高液位|低液位|高温|低温|空罐|误报|联锁|其他", "equipment": "...", "pattern": "normal_transient|repeated|false_alarm|anomalous", "dimension": "工艺|操作|设备|其他", "reason_analysis": "...", "rectification_direction": "..."}

## 字段要求
- alarm_type: 从报警说明提炼的报警类型（高液位/低液位/高温/低温/空罐/误报/联锁/其他）。
- equipment: 报警涉及的设备/部位（如 R19150B 层析上柱罐）；无法确认留空。
- pattern: normal_transient=正常瞬报（一次性、已处置）；repeated=同设备/同岗位重复报警；false_alarm=误报；anomalous=异常依赖（如联锁、频发、跨岗位扩散）。
- dimension: 工艺=生产过程/工艺参数；操作=人为误操作/违章；设备=设备故障/老化/设计缺陷；其他=上述之外。
- reason_analysis: 40-120 字自然语言，明确根因（不照抄原文）。
- rectification_direction: 30-80 字，具体可操作的整改方向。

## ⚠️ 重要规则
- 只基于给定数据，不编造；信息不足时如实说明。
- pattern 需参考「历史趋势上下文」（同设备/同岗位上周同期、本周重复计数）判断，不能仅凭单条文本臆断。
- 结论仅供参考，不替代现场确认。"""

_DAILY_SUMMARY_SYSTEM_PROMPT = """你是一名化工企业中控报警分析专家。输入为当日全部中控报警记录与逐条 AI 分析摘要，请生成当日全厂汇总分析。

## 输出 JSON 结构
{"summary": "...", "key_issues": ["..."], "rectification_suggestions": ["..."]}

## 要求
- summary: 80-150 字，概括当日报警态势（车间集中度/报警类型集中度/异常模式/维度集中度）。
- key_issues: 1-3 条，突出共性与异常（重复报警、误报群、频发设备/岗位）。
- rectification_suggestions: 1-3 条，针对共性问题给整改建议；每条建议必须包含涉及的车间/岗位/设备名称，指向具体对象。
- 只基于给定数据，不编造。"""


def build_per_record_messages(
    record: CentralAlarmRecord, history_context: str | None = None,
) -> list[dict[str, str]]:
    """构造单条记录分析的 messages（system 稳定 + user 动态 + 历史上下文在 user 末尾）。"""
    user_lines = [
        "## 报警记录分析",
        f"- 日期: {_bj(record.alarm_date)}",
        f"- 车间: {record.workshop or '?'}",
        f"- 产线: {record.line or '?'}",
        f"- 岗位: {record.post or '?'}",
        f"- 报警情况说明: {(record.alarm_description or '')[:300]}",
        f"- 特殊情况说明: {(record.special_note or '')[:200]}",
    ]
    if history_context:
        user_lines.append(f"- 历史趋势上下文: {history_context[:800]}")
    user_lines.append("请输出 JSON。")
    return [
        {"role": "system", "content": _PER_RECORD_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def build_daily_summary_messages(
    agg: CentralAlarmDailyAgg, per_summaries: list[str],
) -> list[dict[str, str]]:
    """构造日报汇总 messages。"""
    stats = {
        "日期": agg.target_date.isoformat(),
        "报警总数": agg.total,
        "车间分布": agg.workshop_distribution,
        "岗位分布": agg.post_distribution,
        "报警类型分布": agg.alarm_type_distribution,
        "异常模式分布": agg.pattern_distribution,
        "维度分布": agg.dimension_distribution,
    }
    user = f"""请基于以下当日中控报警数据（JSON）生成汇总分析：

{json.dumps(stats, ensure_ascii=False, indent=2)}

逐条 AI 分析摘要：
{json.dumps(per_summaries, ensure_ascii=False, indent=2)}

请输出 JSON（不要输出其他内容）。"""
    return [
        {"role": "system", "content": _DAILY_SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _bj(dt: datetime | None) -> str:
    """UTC → 北京时间字符串。"""
    if dt is None:
        return "?"
    return (dt + timedelta(hours=8)).strftime("%m/%d %H:%M")
