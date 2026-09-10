"""统一输出格式要求：脚本4/6/8 的 OUTPUT_FORMAT 必须包含【输出格式要求】规范，
FEWSHOT 输出必须使用全角（N）编号；脚本2 多条内容以「；」分隔不得使用（N）编号。

防止回归：任何人移除/改写格式要求，或把 FEWSHOT 编号改回半角 "1. "，都会在此失败。
"""

import re

from app.modules.safety.ai_hazard_identification.script2_hazard_id import (
    prompts as p2,
)
from app.modules.safety.ai_hazard_identification.script4_controls import (
    prompts as p4,
)
from app.modules.safety.ai_hazard_identification.script6_recommendations import (
    prompts as p6,
)
from app.modules.safety.ai_hazard_identification.script8_inspection_items import (
    prompts as p8,
)

# 用户要求的 5 点规范原文（逐条，取稳定子串避免引号格式差异）
# 注：脚本4/6/8 多条内容使用（1）（2）（3）编号；脚本2 已改为「；」分隔（见下方专项测试）
REQUIRED_POINTS = [
    "各输出字段均需按条目分点、分行生成",
    "每条检查项单独成行，使用中文序号格式编号",
    "编号格式统一为：（1）……（2）……（3）……",
    "等其他编号格式",
    "不要将多条检查项合并在同一行输出",
]

SCRIPTS = {
    "script4": p4,
    "script6": p6,
    "script8": p8,
}


def test_output_format_contains_required_block():
    for name, mod in SCRIPTS.items():
        fmt = mod.OUTPUT_FORMAT
        assert "【输出格式要求】" in fmt, f"{name}: 缺少【输出格式要求】段"
        for point in REQUIRED_POINTS:
            assert point in fmt, f"{name}: OUTPUT_FORMAT 缺少规范「{point}」"


def test_script2_output_format_requires_semicolon_separator():
    """脚本2 多条内容以「；」分隔：不得使用（1）（2）（3）编号，不得换行分隔。

    脚本2 的 possible_accident/unsafe_behavior 由脚本4 按「、」/「；」拆分消费，
    输出必须为单行「；」连接文本，防止 AI 输出（N）编号行文本。
    """
    fmt = p2.OUTPUT_FORMAT
    assert "【输出格式要求】" in fmt
    assert "多条内容以「；」分隔" in fmt, "缺少「；」分隔要求"
    assert "不得使用（1）（2）（3）编号" in fmt, "缺少不得使用（N）编号要求"
    assert "不得换行分隔" in fmt, "缺少不得换行分隔要求"
    # 禁止回归：不得再要求（1）（2）（3）编号格式
    assert "编号格式统一为：（1）" not in fmt, "脚本2 不应再要求（1）（2）（3）编号"


def test_script2_fewshot_uses_semicolon_separator():
    """脚本2 FEWSHOT 输出必须与「；」分隔契约一致（无（N）编号/无换行）。"""
    for ex in p2.FEWSHOT_EXAMPLES:
        for key in ("possible_accident", "unsafe_behavior"):
            value = ex["output"][key]
            assert "；" in value, f"script2 FEWSHOT {key} 缺少「；」分隔"
            assert "\n" not in value, f"script2 FEWSHOT {key} 不得换行分隔"
            assert not re.search(r"（\d+）", value), (
                f"script2 FEWSHOT {key} 不得使用（N）编号"
            )


def test_fewshot_uses_fullwidth_numbering():
    """多行 FEWSHOT 输出必须用全角（N）编号，不得使用半角 1. 编号。

    单行取值字段（如 hazard_type、needs_recommendation 等）无需编号，跳过。
    """
    line_num = re.compile(r"^\d+\.", re.MULTILINE)
    for name, mod in SCRIPTS.items():
        for ex in mod.FEWSHOT_EXAMPLES:
            for value in ex["output"].values():
                if not isinstance(value, str) or "\n" not in value:
                    continue
                first_line = value.splitlines()[0]
                assert not line_num.search(value), (
                    f"{name}: FEWSHOT 输出存在半角编号行「{first_line!r}」"
                )
                assert "（1）" in value, (
                    f"{name}: FEWSHOT 多行输出缺少全角（1）编号（首行「{first_line!r}」）"
                )


def test_fewshot_multiselect_uses_valid_presets():
    """FEWSHOT 示例的多选字段值必须命中 Bitable 预设（防止预设漂移）。

    脚本2 hazard_type、脚本6 recommendation_type 为 Bitable 多选字段，
    FEWSHOT 中的示例值若跑出预设，会让模型模仿输出非法选项，回写 Bitable 失败。
    """
    from app.modules.safety.ai_hazard_identification.script2_hazard_id import (
        VALID_HAZARD_TYPES_BITABLE,
    )
    from app.modules.safety.ai_hazard_identification.script6_recommendations import (
        VALID_RECOMMENDATION_TYPES,
    )

    for ex in p2.FEWSHOT_EXAMPLES:
        for t in ex["output"]["hazard_type"].split("、"):
            assert t.strip() in VALID_HAZARD_TYPES_BITABLE, (
                f"script2 FEWSHOT hazard_type 含非预设值: {t}"
            )

    for ex in p6.FEWSHOT_EXAMPLES:
        for t in ex["output"]["recommendation_type"].split("、"):
            assert t.strip() in VALID_RECOMMENDATION_TYPES, (
                f"script6 FEWSHOT recommendation_type 含非预设值: {t}"
            )


def test_script2_work_rules_cover_identification_quality_dimensions():
    """脚本2 工作规则必须覆盖辨识质量四缺口：人-不安全行为 / 操规操作 / 安全操作 / 物-不安全状态。

    防止回归：任何人在重写 WORK_RULES 时删掉这些辨识清单，导致辨识输出退回
    泛泛结论（无具体防护用品/带压操作/投料顺序/氮气置换/静电/设备接地/安全附件）。
    """
    rules = p2.WORK_RULES
    # ① 人的不安全行为：防护用品佩戴 + 带压危险操作
    assert "防护用品佩戴" in rules, "缺少防护用品佩戴辨识清单"
    assert "带压" in rules, "缺少带压/带液危险操作辨识（如带压开盖）"
    assert "面屏" in rules, "缺少具体 PPE 示例（面屏）"
    # ② 操规中的操作辨识：开盖加料等具体操作动作
    assert "开盖" in rules, "缺少开盖/加料类操作辨识"
    # ③ 安全操作辨识：投料顺序 / 氮气置换 / 静电消除
    assert "投料顺序" in rules, "缺少投料顺序辨识"
    assert "氮气置换" in rules, "缺少氮气置换辨识"
    assert "静电" in rules, "缺少静电消除辨识"
    # ④ 物的不安全状态：设备接地 / 安全附件有效性 / 联锁 / 报警
    assert "接地" in rules, "缺少设备接地辨识"
    assert "安全阀" in rules, "缺少安全附件（安全阀）有效性辨识"
    assert "联锁" in rules, "缺少联锁/报警辨识"
    assert "报警" in rules, "缺少报警系统辨识"
