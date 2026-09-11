"""数字/日期/批号/规格等关键信息的占位符保护。

翻译前把敏感字面量替换成 ⟦N1⟧、⟦N2⟧ …，译文返回后原样还原，
从机制上保证批号、日期、规格数值、单位不会漏译、错译或被换算。

日期类占位符支持在还原时做确定性格式转换（keep/iso/en/zh），
转换纯程序化完成，不经模型，安全性不变。
"""
from __future__ import annotations

import re

PH_OPEN, PH_CLOSE = "\u27e6", "\u27e7"  # ⟦ ⟧

MONTHS_EN = ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December")

_UNITS = (
    r"(?:EU/mL|EU/ml|CFU/mL|cfu/mL|mol/L|%|℃|°C|°F|mm|cm|km|m|μm|µm|um|nm|"
    r"L|mL|ml|µL|uL|g|mg|μg|µg|ug|kg|"
    r"min|h|hr|kPa|MPa|Pa|mbar|bar|psi|V|mV|kV|A|mA|W|kW|Hz|kHz|MHz|"
    r"rpm|RPM|CFU|cfu|EU|mol|ppm|log)"
)
_NUM = r"\d+(?:\.\d+)?"
_MONTHS_ALT = "|".join(MONTHS_EN)

# 标签词 + 编号（Step 2 / Section 3.4 / Annex 1 / 表2 / 第2阶段…）：
# 编号是引用标记而非数值，掩码只会催生占位符丢失，因此整体免掩码（原样返回）。
_LABEL_WORD = (
    r"(?:\b(?:Step|Section|Sec|Annex|Appendix|Table|Figure|Fig|Part|Phase|Chapter|Page|No)\.?\s*"
    r"|(?:第|节|章|条|附件|附录|页|表|图))"
    r"\d+(?:\.\d+)*"
)

# 单趟正则：按特异性从高到低排列，re 在每个位置取第一个命中的分支，
# 因此不会把 ⟦N1⟧ 里的数字再次掩码（占位符是替换后才插入的）。
# 命名分组名同时作为占位符类别（label 免掩码/date/time/range/numunit/code/longnum/bare）。
_MASK_RE = re.compile(
    r"(?P<label>" + _LABEL_WORD + r")"
    r"|(?P<date>\d{1,2}\s+(?:" + _MONTHS_ALT + r")\s+\d{4}"
    r"|\d{4}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}\s*日?)"
    r"|(?P<time>\d{1,2}:\d{2}(?::\d{2})?)"
    r"|(?P<range>" + _NUM + r"\s*(?:±|~|～|至|-)\s*" + _NUM + r"\s*(?:" + _UNITS + r")(?![A-Za-z]))"
    r"|(?P<numunit>" + _NUM + r"\s*(?:" + _UNITS + r")(?![A-Za-z]))"
    r"|(?P<code>(?<![A-Za-z0-9])[A-Z]{2,6}(?:[-/][A-Za-z0-9]+)+(?![A-Za-z0-9]))"
    r"|(?P<longnum>\d{6,})"
    r"|(?P<bare>" + _NUM + r")"
)

_DATE_PARSE_RE = re.compile(r"(\d{4})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?")
_DATE_PARSE_EN_RE = re.compile(r"(\d{1,2})\s+(" + _MONTHS_ALT + r")\s+(\d{4})", re.IGNORECASE)


def reformat_date(value: str, style: str) -> str:
    """把掩码捕获的日期串转换为指定格式。解析失败时原样返回（宁可保守不错转）。

    keep: 原样；iso: 2026-03-15；en: March 15, 2026；zh: 2026年3月15日
    支持两种输入：2026-03-15 / 2026年3月15日 / March 15, 2026 的反向（15 March 2026）。
    """
    if style == "keep":
        return value
    y = mo = d = None
    m = _DATE_PARSE_RE.fullmatch(value.strip())
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DATE_PARSE_EN_RE.fullmatch(value.strip())
        if m:
            d, month_name, y = int(m.group(1)), m.group(2).capitalize(), int(m.group(3))
            mo = MONTHS_EN.index(month_name) + 1
    if y is None or not (1 <= mo <= 12 and 1 <= d <= 31):
        return value
    if style == "iso":
        return f"{y:04d}-{mo:02d}-{d:02d}"
    if style == "en":
        return f"{MONTHS_EN[mo - 1]} {d}, {y}"
    if style == "zh":
        return f"{y}年{mo}月{d}日"
    return value


class MaskResult:
    def __init__(self, masked: str, mapping: dict[str, tuple[str, str]]):
        self.masked = masked
        self.mapping = mapping  # ⟦N1⟧ -> (原文片段, 类别)

    def restore(self, translated: str, date_style: str = "keep") -> tuple[str, list[str]]:
        """还原占位符。返回 (还原后文本, 异常列表)。异常为空表示完全通过。

        date_style 仅作用于日期类占位符；数字/批号/规格等始终逐字还原。
        """
        anomalies: list[str] = []
        restored = translated
        for ph, (value, category) in self.mapping.items():
            n = restored.count(ph)
            if n == 0:
                anomalies.append(f"占位符 {ph}（{value}）在译文中缺失")
            elif n > 1:
                anomalies.append(f"占位符 {ph}（{value}）在译文中出现 {n} 次")
            else:
                if category == "date":
                    value = reformat_date(value, date_style)
                restored = restored.replace(ph, value)
        if PH_OPEN in restored or PH_CLOSE in restored:
            leftovers = re.findall(re.escape(PH_OPEN) + r"[^" + re.escape(PH_CLOSE) + r"]*" + re.escape(PH_CLOSE), restored)
            anomalies.append(f"译文中出现未知占位符: {', '.join(leftovers[:5])}")
        return restored, anomalies


def mask(text: str) -> MaskResult:
    mapping: dict[str, tuple[str, str]] = {}
    counter = [0]

    def _sub(m: re.Match) -> str:
        if m.lastgroup == "label":
            return m.group(0)  # 标签编号（Step 2 / 表3）免掩码，原样保留
        counter[0] += 1
        ph = f"{PH_OPEN}N{counter[0]}{PH_CLOSE}"
        mapping[ph] = (m.group(0), m.lastgroup or "bare")
        return ph

    return MaskResult(_MASK_RE.sub(_sub, text), mapping)
