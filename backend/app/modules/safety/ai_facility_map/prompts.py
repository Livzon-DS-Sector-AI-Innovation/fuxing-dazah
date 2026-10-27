"""AI 地点→分区建议映射插件 — 提示词（#2）。

设计口径 docs/DESIGN-3x平台关联-…-20261026.md §12.1：64 分区清单 +
待映射文本批（≤20 条/批），输出逐条建议，允许 null 不硬配。
"""

from __future__ import annotations

from app.modules.safety.service.facility_map.district_names import (
    format_district_list,
)

SYSTEM_PROMPT = """你是制药厂区的地点匹配专员。给定全厂风险分区清单（distId=名称）和一批来自作业票/消防报警/中控报警的地点文本，逐条判断每个文本最可能指向的分区，供安环科人工确认。

要求：
1. 按厂区常识与分区名近义判断：设备级写法（罐号/冻干机型/机台编号等）归入其所在建筑或产线的分区；「楼栋+部位」写法取楼栋对应分区；「车间+产线」写法匹配同名分区或其短形（如「车间二达托」对应含「达托」的分区）；
2. 无法可靠判断时 dist_id 填 null，不硬配——宁缺勿错，错误映射会把当日作业/报警落到错误分区；
3. confidence：high=文本与分区名直接对应或厂区常识唯一；mid=设备/短写法但归属基本明确；low=牵强或 dist_id 为 null；
4. reason 一句话说明判断依据（引用所配分区名或设备所在建筑）；
5. 每条 text 必须原样回显输入文本，不得改写、合并或拆分；只输出 JSON，不输出其他内容。

输出格式：{"suggestions": [{"text": "<原文本>", "dist_id": "64" 或 null, "confidence": "high", "reason": "<一句话>"}]}"""


def build_user_prompt(items: list[tuple[str, int]]) -> str:
    """items = [(location_text, count), …]（≤20 条/批）。

    频次不拼进条目行——模型会整行回显 text 字段，混入计数后缀会破坏
    解析侧的原文精确匹配（2026-10-27 实测 443 条全丢弃的根因）。
    """
    lines = [f"{i + 1}. {text}" for i, (text, _) in enumerate(items)]
    numbered = "\n".join(lines)
    return (
        f"## 全厂风险分区清单（distId=名称）\n{format_district_list()}\n\n"
        f"## 待映射地点文本（共 {len(items)} 条，每条各输出一行建议，全部输出不得省略）\n"
        f"{numbered}\n\n请逐条给出建议。"
    )
