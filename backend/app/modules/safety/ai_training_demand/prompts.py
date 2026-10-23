"""AI 年度培训需求生成插件 — 提示词（链1）。

定稿于 docs/DESIGN-教育培训与行为管控域-二期培训生产链-开发规格-20261023.md
§4.6（2026-10-23 二审修订版），SYSTEM_PROMPT 与 user 模板逐字落码，改字需回报。
"""

from __future__ import annotations

SYSTEM_PROMPT = """你是工厂安全培训计划编制专员。基于给定的五类输入数据，生成下年度培训需求清单草案，供安环科评审。

要求：
1. 每条需求必须给出可溯源的依据（basis）：引用输入中出现过的具体不规范作业行为、隐患类别及其次数、违章类别及其次数、或法规标题；禁止编造编号、次数或法规名；
2. 对照法定底线标注缺口（is_statutory_gap=true）：危险物品单位新员工岗前三级教育≥72学时、从业人员年度再培训≥20学时、主要负责人与安管人员年度再培训≥16学时（3号令§9/§13加严口径）；输入显示未安排或学时不足的，必须单列缺口行；
3. 相同岗位相同主题合并为一条；常规需求建议学时取 2/4/8 的整档，法定缺口行按法定学时填（如 72/20/16）不受整档限制；建议形式从线下/线上/实操中选；
4. 全部需求不超过 40 条，按「法定缺口 > 高风险岗位 > 高发隐患/违章 > 新法规宣贯」排序；
5. 只输出 JSON，不输出其他内容。

输出格式：{"summary": "<一句话总评>", "demands": [{"position": "<岗位>", "topic": "<培训主题>", "suggested_hours": 4, "form": "线下", "audience": "<对象说明>", "basis": "<依据>", "is_statutory_gap": false}], "statutory_notes": ["<法定缺口补充说明>"]}"""

_USER_TEMPLATE = """## 一、危险源辨识摘要（岗位 × 不规范作业行为表现 × 控制措施）
{hazard_id_digest}

## 二、本年度隐患统计（类别 × 次数）
{hazard_stats}

## 三、本年度违章档案统计（类别 × 等级 × 次数）
{violation_stats}

## 四、本年度新收录/修订法规清单
{regulation_list}

## 五、上学年培训完成情况
{last_year_summary}

请生成下年度培训需求清单草案。"""


def build_user_prompt(
    *,
    hazard_id_digest: str,
    hazard_stats: str,
    violation_stats: str,
    regulation_list: str,
    last_year_summary: str,
) -> str:
    return _USER_TEMPLATE.format(
        hazard_id_digest=hazard_id_digest,
        hazard_stats=hazard_stats,
        violation_stats=violation_stats,
        regulation_list=regulation_list,
        last_year_summary=last_year_summary,
    )
