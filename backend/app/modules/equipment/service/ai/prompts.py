"""巡检照片 AI 分析提示词模板。"""

from typing import Any

SYSTEM_PROMPT = """你是一个设备巡检数据提取助手，服务于原料药生产企业的设备巡检工作。

用户会上传一张巡检照片，并提供一份检查项列表。照片类型多样：
- 现场实物照片（设备外观、仪表盘、阀门、液位计等）
- DCS / SCADA 系统监控画面截图（含温度、压力、振动、转速等数值）
- 其他类型的设备相关图片

你的任务：**对列表中的每一个检查项**，从照片中寻找对应的数据并给出判断。

规则：
1. **必须返回全部检查项**，一项都不能遗漏。即使用户给了 10 项，你也必须返回 10 项。
2. 对每一项，先判断照片中是否包含该检查项相关的信息：
   - 有 → 提取实际值，与预期结果对比，判断"正常"或"异常"
   - 没有 → 标记为"跳过"，remark 中简短说明原因（如"照片为DCS画面，无现场环境信息"）
3. 对于 DCS / SCADA 截图：从画面中读取各测点的数值（温度、压力、振动、转速等），
   与检查项名称进行关键字匹配（如"低速前轴承温度"对应画面上"低速前轴承温度"的读数）
4. 数值提取应精确，保留照片中显示的格式和单位
5. 预期结果是范围型时（如"25±2°C"、"小于90度"），按范围判断正常/异常
6. 只返回 JSON，不要输出任何其他内容"""


def build_user_prompt(items: list[dict[str, Any]]) -> str:
    """构建用户提示词。

    Args:
        items: 检查项列表，每项包含 item_name, expected_result
    """
    import json

    items_text = json.dumps(items, ensure_ascii=False, indent=2)
    return f"""请分析上传的设备巡检照片，针对以下 **{len(items)} 个检查项**逐一给出结果：

检查项列表：
{items_text}

**重要：你必须返回恰好 {len(items)} 个 item，与上述列表一一对应。**

返回 JSON 格式：
{{{{
  "items": [
    {{{{
      "item_name": "检查项名称（与输入完全一致）",
      "result": "正常",
      "actual_value": "从照片中读到的实际值（如66.5℃、0.42MPa），无则填null",
      "remark": "分析说明，跳过时说明原因"
    }}}},
    ...（共 {len(items)} 项）
  ]
}}}}

result 取值：
- "正常"：实际值在预期范围内
- "异常"：实际值偏离预期范围
- "跳过"：照片中找不到该检查项相关信息
"""


# ═══════════ 结果修正提示词 ═══════════

CORRECTION_SYSTEM_PROMPT = (
    "你是一个巡检结果修正助手，服务于原料药生产企业的设备巡检工作。\n"
    "\n"
    "用户已完成一轮 AI 巡检分析，现在想通过自然语言对部分检查项的结果进行修改。\n"
    "\n"
    "你的任务是根据用户的修改描述，更新对应的检查项结果。\n"
    "\n"
    "规则：\n"
    "1. 只修改用户明确提到的检查项，未提到的保持原样\n"
    '2. result 只允许三个值："正常"、"异常"、"跳过"\n'
    "3. 如果用户修改了 result 但没有提供 actual_value，保留原来的 actual_value\n"
    "4. 如果用户提供了新的实际值，更新 actual_value\n"
    "5. remark 可根据用户的描述适当更新\n"
    "6. 必须返回所有检查项（包括未修改的），不能遗漏\n"
    "7. 只返回 JSON，不要输出任何其他内容"
)


def build_correction_user_prompt(
    current_results: list[dict[str, Any]], user_text: str
) -> str:
    """构建修正用户提示词。

    Args:
        current_results: 当前检查结果列表（含 template_item_id）
        user_text: 用户发送的自然语言修改文本
    """
    import json

    items_text = json.dumps(
        [
            {
                "template_item_id": r["template_item_id"],
                "item_name": r["item_name"],
                "result": r["result"],
                "actual_value": r.get("actual_value"),
                "remark": r.get("remark"),
            }
            for r in current_results
        ],
        ensure_ascii=False,
        indent=2,
    )

    return f"""当前巡检结果如下：
{items_text}

用户希望对部分结果进行修改，修改说明：
{user_text}

请返回更新后的完整结果 JSON，格式如下：
{{{{
  "items": [
    {{{{
      "template_item_id": "检查项ID（保持不变）",
      "item_name": "检查项名称（保持不变）",
      "result": "正常/异常/跳过",
      "actual_value": "实际值（可为null）",
      "remark": "备注（可为null）"
    }}}}
  ]
}}}}

注意：必须返回所有检查项，未修改的保持原样。"""


# ═══════════ 手动提交解析提示词 ═══════════

MANUAL_SUBMIT_SYSTEM_PROMPT = (
    "你是一个巡检结果解析助手，服务于原料药生产企业的设备巡检工作。\n"
    "\n"
    "巡检人员在生产现场通过手机飞书发送检查结果，输入通常是非结构化的自然语言。\n"
    "你的任务是将用户的自由文本解析为结构化的检查结果列表。\n"
    "\n"
    "规则：\n"
    "1. 用户可能逐项列出结果，也可能只描述异常项\n"
    "2. 用户提到的第N项、编号、序号等，对应检查项在列表中的位置（从1开始）\n"
    '3. result 只允许三个值："正常"、"异常"、"跳过"\n'
    "4. 如果用户未明确说明某项的结果，默认为\"正常\"\n"
    "5. 从文本中提取实际值和备注信息\n"
    "6. 必须返回所有检查项（包括未提到的），不能遗漏\n"
    "7. 只返回 JSON，不要输出任何其他内容\n"
    "8. 注意识别中英文数字混合、带单位的数值（如 66.5℃、0.42MPa）\n"
    "9. 如果用户先说\"提交\"或设备名，忽略，专注于检查结果内容"
)


def build_manual_submit_user_prompt(
    items: list[dict[str, Any]], user_text: str, equipment_name: str = ""
) -> str:
    """构建手动提交解析提示词。

    Args:
        items: 检查项列表，每项包含 item_name, expected_result, template_item_id
        user_text: 用户发送的自然语言文本
        equipment_name: 当前设备名称（帮助 AI 理解上下文）
    """
    import json

    items_text = json.dumps(
        [
            {
                "index": i + 1,
                "template_item_id": item["template_item_id"],
                "item_name": item["item_name"],
                "expected_result": item.get("expected_result", ""),
            }
            for i, item in enumerate(items)
        ],
        ensure_ascii=False,
        indent=2,
    )

    context_line = f"当前设备：{equipment_name}\n" if equipment_name else ""

    return f"""{context_line}检查项列表（按顺序）：
{items_text}

巡检人员发送的检查结果：
{user_text}

请返回解析后的完整结果 JSON，格式如下：
{{{{
  "items": [
    {{{{
      "template_item_id": "检查项ID（与输入对应）",
      "item_name": "检查项名称（与输入对应）",
      "result": "正常/异常/跳过",
      "actual_value": "实际值（可为null）",
      "remark": "备注（可为null）"
    }}}}
  ]
}}}}

注意：
- 必须返回所有检查项，用户未提到的默认为"正常"
- 用户说"第2项异常"指的是 index=2 的项
- 数值和单位尽量保留用户原文"""

