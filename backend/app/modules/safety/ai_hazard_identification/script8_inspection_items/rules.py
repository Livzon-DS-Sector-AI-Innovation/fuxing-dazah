"""脚本8 排查内容生成 — 输出规则验证器。

验证 AI 生成的现场排查检查项质量（对应标准文件「现有控制措施转现场排查检查项」）：
1. 输入为空 → 对应输出必须为「无」（规则9）
2. 每条检查项以「检查」开头 + 全角（N）序号编号（规则4/输出格式）
3. 禁止新增/整改式表述（禁止事项2）
4. 每类至少 3 条（规则10）
5. 不混写（个人防护字段不含工程类描述，规则2）
"""

from __future__ import annotations

import logging
import re

from app.modules.safety.ai_hazard_identification.script8_inspection_items.schemas import (
    InspectionItemsInput,
    InspectionItemsOutput,
)

logger = logging.getLogger(__name__)

NO_ITEMS = "无"
UNCONFIRMED = "待人工确认"

# 输入视为「无相关措施」的表述
EMPTY_INPUT_PHRASES = ("无", "未填写", "无相关措施", "待人工确认")

# 禁止在排查内容中出现的新增/整改式表述（标准文件禁止事项2）
# 拆成两档：
#   HARD  — 明确整改/新增措辞，无论是否处于「是否…」核查问句一律拦截（如「必须增加」）
#   SOFT  — 可能作核查问句用词（如「检查…是否配备到位」是合规检查项），
#           仅当不处于「是否/有无」核查语境时才视为整改式表述
HARD_REMEDIATION = ["必须增加", "需补充", "有待加强"]
SOFT_REMEDIATION = ["应当", "增设", "建立", "建议", "需要", "加强", "完善", "配备"]

# 核查问句标志：词前/后 ±window 内出现这些标志 → 视为「检查…是否…」合规问句
_CHECK_QUESTION_MARKERS = ("是否", "有无", "有否", "是否有")
_CHECK_QUESTION_WINDOW = 20

# 每类最少条数
MIN_ITEMS = 3

# 行编号格式：全角括号数字，如（1）
NUMBERED_LINE_RE = re.compile(r"^\s*（(\d+)）\s*(.*)$", re.MULTILINE)

# 任意位置的（N）序号（用于按编号计数，兼容「单行拼接」输出）
_NUMBERED_TOKEN_RE = re.compile(r"（\d+）")

# 个人防护字段不应出现的工程类关键词（不混写检查）
ENGINEERING_KEYWORDS = ["联锁", "报警器", "通风机", "安全阀", "爆破片", "DCS", "SIS"]


def is_empty_input(value: str) -> bool:
    """输入字段是否视为无相关措施。"""
    v = (value or "").strip()
    if not v:
        return True
    return v in EMPTY_INPUT_PHRASES


def _is_check_question_usage(text: str, word: str) -> bool:
    """判断 SOFT 档禁语是否用于「检查…是否…」核查问句（合规）而非整改式表述。

    以词位置为中心取 ±_CHECK_QUESTION_WINDOW 的短窗口，窗口内出现
    「是否/有无/有否/是否有」之一 → 判定为核查问句用法 → 放行。

    例：「检查防毒面具是否配备到位」→ 配备 邻接 是否 → 放行
    例：「建议配备防毒面具」       → 配备 附近无 是否 → 拦截
    例：「检查应急物资配备是否齐全」→ 配备 后随 是否 → 放行
    """
    idx = text.find(word)
    if idx < 0:
        return False
    start = max(0, idx - _CHECK_QUESTION_WINDOW)
    end = min(len(text), idx + len(word) + _CHECK_QUESTION_WINDOW)
    window = text[start:end]
    return any(m in window for m in _CHECK_QUESTION_MARKERS)


def _banned_remediation_hits(value: str) -> list[str]:
    """返回文本中命中的整改式表述清单（按语境判断）。"""
    hits: list[str] = []
    for phrase in HARD_REMEDIATION:
        if phrase in value:
            hits.append(phrase)
    for phrase in SOFT_REMEDIATION:
        if phrase in value and not _is_check_question_usage(value, phrase):
            hits.append(phrase)
    return hits


def count_numbered_items(text: str) -> int:
    """统计文本中（N）编号条目的数量。

    按任意位置的（N）序号计数（不要求每行一个），兼容 AI 偶发的「单行拼接」输出，
    如「（1）…。（2）…。（3）…」记为 3 条。
    """
    if not text or text.strip() == NO_ITEMS:
        return 0
    return len(_NUMBERED_TOKEN_RE.findall(text))


def _validate_field(
    errors: list[str],
    label: str,
    input_value: str,
    output_value: str,
) -> None:
    """校验单个输入/输出字段对。"""
    input_empty = is_empty_input(input_value)
    value = (output_value or "").strip()

    # 规则9：输入为空 → 输出必须为「无」
    if input_empty:
        if value != NO_ITEMS:
            errors.append(
                f"{label}：输入无相关控制措施，输出必须为「无」，但实际为「{value[:20]}」"
            )
        return

    # 输入非空时输出不能为「无」
    if value == NO_ITEMS:
        errors.append(
            f"{label}：输入存在控制措施，但输出为「无」，请生成现场排查检查项"
        )
        return

    # 归一化：AI 偶发把多条检查项合并到一行（用「。（N）」拼接，无换行）。
    # 在「。/；」后紧跟（N）处补换行，使「单行拼接」也能逐条校验格式。
    normalized = re.sub(r"(?<=[。；])\s*(?=（\d+）)", "\n", value)
    lines = [ln for ln in normalized.split("\n") if ln.strip()]
    if not lines:
        errors.append(f"{label}：输出为空，请输入排查检查项")
        return

    for idx, line in enumerate(lines, 1):
        m = NUMBERED_LINE_RE.match(line)
        if not m:
            errors.append(
                f"{label} 第{idx}行：未使用（N）全角序号编号，格式应为（1）检查……"
            )
            continue
        content = m.group(2).strip()
        if not content.startswith("检查"):
            errors.append(
                f"{label} 第{idx}行：排查内容必须以「检查」开头，实际为「{content[:20]}」"
            )

    # 条数：按（N）编号计数（修复「单行拼接被误判为1条」）
    count = count_numbered_items(value)
    if count < MIN_ITEMS:
        errors.append(f"{label}：排查检查项至少 {MIN_ITEMS} 条，实际 {count} 条")

    # 禁止新增/整改式表述（语境判断：核查问句「是否配备/是否需要」放行）
    for phrase in _banned_remediation_hits(value):
        errors.append(
            f"{label}：包含整改式表述「{phrase}」，排查内容禁止新增/整改建议"
        )


class InspectionRuleEngine:
    """脚本8 输出规则验证器。"""

    def validate(
        self,
        input_data: InspectionItemsInput,
        output: InspectionItemsOutput,
    ) -> list[str]:
        errors: list[str] = []

        fields: list[tuple[str, str, str]] = [
            ("工程措施排查内容", input_data.engineering_controls, output.engineering_items),
            ("管理措施排查内容", input_data.management_controls, output.management_items),
            ("个人防护措施排查内容", input_data.ppe, output.ppe_items),
            ("应急措施排查内容", input_data.emergency_measures, output.emergency_items),
        ]
        for label, input_value, output_value in fields:
            _validate_field(errors, label, input_value, output_value)

        # 不混写：个人防护字段不应含工程类描述（规则2）
        if output.ppe_items and output.ppe_items.strip() != NO_ITEMS:
            for kw in ENGINEERING_KEYWORDS:
                if kw in output.ppe_items:
                    errors.append(
                        f"个人防护措施排查内容 不应包含工程类描述（检测到「{kw}」），"
                        "请移至工程措施排查内容"
                    )
                    break

        return errors


def auto_correct(
    output: InspectionItemsOutput,
    input_data: InspectionItemsInput,
) -> InspectionItemsOutput:
    """自动修正 AI 输出（携带输入以落实「空输入→无」规则9）。"""
    pairs = [
        ("engineering_items", "engineering_controls"),
        ("management_items", "management_controls"),
        ("ppe_items", "ppe"),
        ("emergency_items", "emergency_measures"),
    ]
    for out_field, in_field in pairs:
        value = getattr(output, out_field)
        input_value = getattr(input_data, in_field)
        if is_empty_input(input_value):
            setattr(output, out_field, NO_ITEMS)
        elif value is None or not (value or "").strip():
            setattr(output, out_field, UNCONFIRMED)
        else:
            setattr(output, out_field, value.strip())

    return output
