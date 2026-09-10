"""消防报警日报/周报 — Markdown 渲染（纯函数，无 DB / 环境依赖）。

排版约定（飞书卡片 markdown + 前端 <pre> 双端兼容，不用表格 / # 标题 / HTML）：
- 分区标题：emoji + **加粗**，上下用 ━ 分隔线
- 统计行：`·` 项目符号，关键数字 **加粗**
- 报警明细：**按部门分组**（部门标题 @负责人一次，条目内不重复），每条含
  ① 报警原因(Cause)、② 原因分析(AI)、③ 整改建议，并附多维表格「查看记录」链接
- 日报/周报均不渲染 AI 汇总分析，无文末整改提醒（用户要求）

结构（对接督办通报 hazard_supervision.build_bulletin_content 的分组风格）：
- 日报：标题 → 生成时间 → 📊 当日报警统计（报警类型/性质合并为「报警类型」、
  涉及部门）→ 部门分组报警明细（每部门分隔线 + @负责人）
- 周报：标题 → 周起止 → 📊 本周报警统计 → 部门分组明细（含重复报警提示/
  @负责人跟进）

用户定制（2026-08-18）：
- 「人工原因」→「报警原因」；「AI 分析」→「原因分析（AI）」；「整改方向」→「整改建议」
- 删除「（待现场确认）」判定与备注标记 → prompt 与渲染均移除
- 删除 AI 汇总分析；删除文末整改提醒（改为每部门明细内呈现）
- 明细按部门分类（不按 AI 维度），各部门用分隔线分开 → 部门负责人直观看到本部门情况
- 每条记录附「查看记录」原文链接（参考督办通报 _record_link）
- 统计：报警性质+报警类型合并为「报警类型」，删 AI 维度，部门分布改「涉及部门」
- 周报重点：同一地点重复报警未采取措施 + @负责人及时跟进
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.modules.safety.service.fire_alarm.aggregator import (
    FireAlarmDailyAgg,
    FireAlarmWeeklyAgg,
)

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

# AI 维度英文枚举 → 中文（仅用于明细行前缀，不做统计）
_DIMENSION_CN = {
    "process": "工艺",
    "operation": "人员操作",
    "equipment": "设备设施",
    "other": "其他",
}

# 序号样式：1~20 用 ①~⑳，超出回退 "N."
_NUM_MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

TITLE = "🔥 **消防报警日报**"
TITLE_WEEKLY = "🔥 **消防报警周报**"

# 消防报警多维表格（配置中心 store 覆盖；未启用/缺失时回退以下历史硬编码值，
# 与 bitable_config/registry.py fire_alarm/alarm 默认连接一致）
_FIRE_APP_TOKEN = "MGX1bLhasaRx6usKOodcVpXGnTb"
_FIRE_TABLE_ID = "tblgtwoBn4SMBSGj"
_BASE_URL = "https://j0eukrlohu.feishu.cn/base"


def _at(name: str | None, person_open_id: dict[str, str]) -> str:
    """部门负责人 → @mention 或纯文本（无安全应用 open_id 时纯文本）。"""
    from app.modules.safety.feishu import mention

    if not name:
        return "待维护"
    return mention.at_tag(name, person_open_id.get(name, ""))


def _dimension_tag(dimension: str | None) -> str:
    """AI 维度 → 中文；未分析显示「未分析」。"""
    return _DIMENSION_CN.get(dimension or "", "未分析")


def _fmt_dist(dist: dict[str, int]) -> str:
    """分布 dict → "A×n、B×m" 文本；空显示「-」。"""
    if not dist:
        return "-"
    return "、".join(f"{k}×{v}" for k, v in dist.items())


def _bj(dt: datetime | None) -> str:
    """UTC → 北京时间字符串（M/D HH:MM）。"""
    if dt is None:
        return "-"
    return (dt + timedelta(hours=8)).strftime("%m/%d %H:%M")


def _seq(i: int) -> str:
    """序号：①..⑳（1..20），超出回退 "N."。"""
    return _NUM_MARKS[i - 1] if 1 <= i <= len(_NUM_MARKS) else f"{i}."


def _ai_items(ai: dict[str, Any], key: str) -> tuple[bool, list[dict[str, Any]]]:
    """AI 板块字段守卫：非 list 视为格式异常（降级省略），list 内非 dict 条目跳过。

    Returns:
        (格式异常, dict 条目列表)；key 缺失/空列表 → (False, [])。
    """
    val = ai.get(key)
    if val is None or val == []:
        return False, []
    if not isinstance(val, list):
        return True, []
    return False, [it for it in val if isinstance(it, dict)]


def _stat_block(title: str, rows: list[str]) -> list[str]:
    """分区模板：分隔线 + 加粗标题 + 分隔线 + `·` 统计行。"""
    return [DIVIDER, f"**{title}**", DIVIDER, *[f"· {row}" for row in rows], ""]


def _fire_conn_tokens() -> tuple[str, str]:
    """当前配置中心连接 app_token/table_id（函数内读 store，保持模块纯函数可导入）。

    配置中心未启用/缺失（读失败/未配置）时回退历史硬编码值（= registry 默认）。
    """
    from app.modules.safety.bitable_config.store import store

    conn = store.get_connection("fire_alarm", "alarm")
    if conn is not None and conn.enabled:
        return conn.app_token, conn.table_id
    return _FIRE_APP_TOKEN, _FIRE_TABLE_ID


def _record_link(r) -> str:
    """多维表格「查看记录」链接（feishu_record_id 非空才有）。"""
    rid = r.feishu_record_id or ""
    if not rid:
        return "　🔗 查看记录（无原表链接）"
    app_token, table_id = _fire_conn_tokens()
    url = f"{_BASE_URL}/{app_token}?table={table_id}&record={rid}"
    return f"　🔗 [查看记录]({url})"


def _group_records_by_dept(records) -> list[tuple[str, list]]:
    """按部门分组（部门为空的归「部门待确认」组；部门排序按首现顺序稳定）。"""
    groups: dict[str, list] = defaultdict(list)
    for r in records:
        dept = r.department or "部门待确认"
        groups[dept].append(r)
    return list(groups.items())


def _render_record(r, person_open_id: dict[str, str], idx: int) -> list[str]:
    """渲染单条报警明细：序号 + 时间 + 维度/类型/性质 + 报警原因/原因分析/整改建议 + 链接。"""
    dim = _dimension_tag(r.ai_dimension)
    building = r.building or ""
    location = r.location or ""
    place = f"{building}{location}" or "部位待确认"
    lines: list[str] = [
        f"{_seq(idx)} {_bj(r.alarm_time)} · **{dim}**｜{r.alarm_type or '?'}｜{r.alarm_nature or '?'}",
        f"　📍 {place}",
        f"　① **报警原因**：{(r.cause_description or '无')[:100]}",
    ]
    if r.ai_reason_analysis:
        lines.append(f"　② **原因分析（AI）**：{r.ai_reason_analysis[:120]}")
    if r.ai_rectification_direction:
        lines.append(f"　③ **整改建议**：{r.ai_rectification_direction[:80]}")
    lines.append(_record_link(r))
    return lines


def _render_dept_blocks(
    grouped: list[tuple[str, list]],
    person_open_id: dict[str, str],
    dept_leader_names: dict[str, str] | None = None,
) -> list[str]:
    """按部门渲染（部门标题 @负责人一次，条目内不重复）；部门之间用分隔线分开。

    负责人解析优先聚合映射 ``dept_leader_names``（department → leader_name）；
    映射缺失时回退记录自带的 ``department_leader_name``。
    负责人 presence：有 open_id 显示 @提及，无 open_id 显示纯文本姓名（_at 兜底）；
    完全无负责人信息时组头追加占位提示。
    """
    parts: list[str] = []
    for dept, items in grouped:
        count_str = f"（{len(items)}条）" if len(items) > 1 else ""
        leader_name: str | None = None
        if isinstance(dept_leader_names, dict):
            leader_name = dept_leader_names.get(dept)
        if not isinstance(leader_name, str) or not leader_name:
            # 兼容记录自带负责人（过滤 MagicMock/非 str 占位）
            leader_name = next(
                (getattr(r, "department_leader_name", "") for r in items
                 if isinstance(getattr(r, "department_leader_name", None), str)
                 and getattr(r, "department_leader_name", "")),
                None,
            )
        leaders = [leader_name] if isinstance(leader_name, str) and leader_name else []
        head: str = f"**{dept}{count_str}**"
        if leaders:
            mentions = "　".join(_at(name, person_open_id) for name in leaders)
            head += f"　{mentions}"
        elif not dept_leader_names:
            head += "　（无部门负责人信息，请各责任部门自行跟进）"
        parts.append(head)
        for idx, r in enumerate(items, 1):
            parts.extend(_render_record(r, person_open_id, idx))
        parts.append(DIVIDER)
    return parts


def render_daily_report(
    agg: FireAlarmDailyAgg,
    person_open_id: dict[str, str],
    ai_summary: dict[str, Any] | None = None,
    *,
    window_start_utc: datetime | None = None,
    window_end_utc: datetime | None = None,
) -> str:
    """渲染日报 Markdown。

    结构: 标题 → 生成时间 → 📊 当日报警统计（报警类型合并、涉及部门）
    → 部门分组报警明细（参照督办通报：部门标题 @负责人，条目内含原因/分析/建议/链接）。

    Args:
        agg: 日报聚合结果
        person_open_id: 部门负责人姓名 → feishu open_id（@提及用；空 dict 纯文本）
        ai_summary: 保留以兼容调用方签名；按需求不再渲染（AI 汇总分析已删除）
        window_start_utc: 滚动窗口起始 UTC（前日17:00~当日17:00）；None=自然日
        window_end_utc: 滚动窗口结束 UTC
    """
    if window_start_utc is not None and window_end_utc is not None:
        period = (
            f"{(window_start_utc + timedelta(hours=8)).strftime('%m/%d 17:00')}"
            f" ~ {(window_end_utc + timedelta(hours=8)).strftime('%m/%d 17:00')}"
        )
    else:
        period = agg.target_date.isoformat()
    parts: list[str] = [
        f"{TITLE} · {period}",
        f"🕒 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    # 统计：报警类型合并（性质+类型）、涉及部门（不显示 AI 维度）
    parts.extend(_stat_block("📊 当日报警统计", [
        f"报警总数：**{agg.total} 起**",
        f"报警类型：{_fmt_dist(agg.type_distribution)}、{_fmt_dist(agg.nature_distribution)}",
        f"涉及部门：{_fmt_dist(agg.department_distribution)}",
    ]))

    grouped = _group_records_by_dept(agg.records)
    parts.extend(_render_dept_blocks(grouped, person_open_id, agg.dept_leader_names))
    parts.append("")
    parts.append(DIVIDER)
    parts.append("**各部门负责人请核实报警原因并落实整改措施。**")
    return "\n".join(parts)


def render_weekly_report(
    agg: FireAlarmWeeklyAgg,
    person_open_id: dict[str, str],
    ai_summary: dict[str, Any] | None = None,
) -> str:
    """渲染周报 Markdown。

    结构: 标题 → 周起止 → 📊 本周报警统计 → 部门分组明细（含重复报警重点提示）。

    Args:
        agg: 周报聚合结果
        person_open_id: 部门负责人姓名 → feishu open_id
        ai_summary: 保留以兼容调用方签名；周级 AI 汇总已删除
    """
    parts: list[str] = [
        f"{TITLE_WEEKLY} · {agg.week_start.isoformat()} ~ {agg.week_end.isoformat()}",
        "📅 周一~周日",
        "",
    ]
    analyzed = sum(1 for r in agg.records if r.ai_analyzed_at is not None)
    stat_rows = [
        f"报警总数：**{agg.total} 起**",
        f"报警类型：{_fmt_dist(agg.type_distribution)}、{_fmt_dist(agg.nature_distribution)}",
        f"涉及部门：{_fmt_dist(agg.department_distribution)}",
    ]
    if agg.total:
        unanalyzed = agg.total - analyzed
        stat_rows.append(
            f"AI 分析覆盖：{analyzed}/{agg.total} 条已分析（**{unanalyzed} 条未分析**）"
            if unanalyzed else f"AI 分析覆盖：{analyzed}/{agg.total} 条已分析"
        )
    parts.extend(_stat_block("📊 本周报警统计", stat_rows))

    # 周报重点：同一地点重复报警未措施 + @负责人跟进
    if agg.recurring_patterns:
        parts.extend([
            DIVIDER,
            "**🔁 重复/集中问题**",
            DIVIDER,
        ])
        for i, p in enumerate(agg.recurring_patterns, 1):
            depts = "、".join(p.get("departments") or []) or "部门待确认"
            mention = "　".join(
                _at(leader_name, person_open_id)
                for dept in p.get("departments") or []
                for leader_name in [agg.dept_leader_names.get(dept, "")]
                if isinstance(leader_name, str) and leader_name
            )
            parts.append(
                f"· {_seq(i)} {p.get('pattern', '?')}（**{p.get('count', 0)} 次**）涉及：{depts}"
                + (f"　{mention}" if mention else "")
            )
        parts.append("")
    else:
        # 无重复/集中问题：不显示重复块标题，仅提示一行
        parts.extend([
            DIVIDER,
            "（本周暂无明显重复/集中问题）",
            "",
        ])

    # 周级 AI 分析（ai_summary 非空才渲染：典型问题/系统性建议/趋势）
    if ai_summary:
        parts.extend([
            DIVIDER,
            "🧠 **AI 周级分析**",
            DIVIDER,
        ])
        # AI 字段守卫：非 list 或条目非 dict 视为格式异常 → 降级省略该板块
        malformed = False
        typical_bad, typical = _ai_items(ai_summary, "typical_issues")
        malformed |= typical_bad
        if typical:
            parts.extend(["", "**🔠 典型问题（高风险）**", ""])
            for i, issue in enumerate(typical, 1):
                parts.append(f"{i}. {issue.get('title', '?')}：{issue.get('evidence', '')}")
            parts.append("")
        systemic_bad, systemic = _ai_items(ai_summary, "systemic_suggestions")
        malformed |= systemic_bad
        if systemic:
            parts.append("**✅ 系统性整改建议**")
            for i, sug in enumerate(systemic, 1):
                parts.append(f"{i}. {sug.get('issue', '?')}：{sug.get('suggestion', '')}")
            parts.append("")
        trend = ai_summary.get("trend")
        if isinstance(trend, dict) and trend:
            parts.append(f"**📈 趋势**：{trend.get('summary', '')}；趋势：**{trend.get('trend', '')}**")
            parts.append("")
        elif trend not in (None, {}, ""):
            malformed = True
        if malformed:
            parts.append("（AI 输出格式异常，该板块已省略）")
            parts.append("")
    else:
        # 无 AI 汇总时不显示该块（需求：周报重点仅当有重复报警才提示）
        pass

    parts.extend([
        DIVIDER,
        "**各部门报警明细与整改要求**",
    ])
    grouped = _group_records_by_dept(agg.records)
    parts.extend(_render_dept_blocks(grouped, person_open_id, agg.dept_leader_names))
    parts.append("")
    parts.append(DIVIDER)
    parts.append("**各部门负责人请及时跟进并落实整改措施。**")
    return "\n".join(parts)
