"""A3/A4 共用引用判定唯一事实源。

本模块只做纯文本判定，无任何 IO/网络/数据库依赖，供两处共用：
- A3 质量闸门（`service/hazard_direct/quality_gate.py`）：写回前判定
  「占位依据 / 无任何法规引用」；
- A4 规则引擎（`ai_hazard_identification/rules.py`）：`_validate_basis`
  判定依据是否包含真实引用。

口径依据 2026-11-05 的 197 条历史重跑 ground truth（140 success / 57 failed）：
「占位文案 + 引用正则」组合对两类判定 0 误判（本地只读校验）。其中引用正则
必须覆盖历史成功输出里真实出现的写法，包括 `GBT 16483-2008`、`SHT3097-2017`、
`T/CCSAS 005-2019`、`GB 4053.3—2025`（全角破折号）、`〔2014〕70号`、
仅条号（`第二十八条`）等——不要把「标准号带不带斜杠」当成引用有无的分界。
"""

from __future__ import annotations

import re

# ═══════════════════════════════════════════════════════════════════════════
# 占位文案（与历史重跑脚本口径一致，勿改文案）
# ═══════════════════════════════════════════════════════════════════════════

PLACEHOLDER_BASIS_MARKERS: tuple[str, ...] = (
    "知识库中无相应条文",
    "知识库信息不足",
)

# ═══════════════════════════════════════════════════════════════════════════
# 引用正则
# ═══════════════════════════════════════════════════════════════════════════

# 标准号前缀（GB/AQ/HG/SH/JGJ/TSG/DL/JB/CJJ/TCCSAS/DBxx 等）。
# `/T`、`T`、全角斜杠（／∕）、下划线都是同一标准的真实书写变体，统一接受；
# 编号部分支持 `GB 3836.1-2010`、`GB 4053.3—2025`（全角破折号）等写法。
# TSG（特种设备安全技术规范）编号可带字母代号（TSG D7005 / TSG T5002 /
# TSG ZF001 / TSG 08 等），故允许 1~3 位大写字母后再接编号。
_STANDARD_SEP = r"[/／∕⁄_]"
# 前缀与类型字母之间允许空白：历史真实写法既有 `GB/T 30871`、`SH/T3007`，
# 也有 `SH T3007-2014`、`GB T 37140-2018`（空格代替斜杠）——共享语法全部覆盖。
_STANDARD_JOIN = rf"(?:\s*{_STANDARD_SEP}?\s*)"
# 标准号语法片段：CITATION_RE（引用有无判定）与 citation_evidence
#（引用可验证匹配）共用，避免两套正则漂移（扩写法只需改这一处）。
STANDARD_NO_PATTERN: str = (
    rf"(?:GB(?:{_STANDARD_JOIN}[TZ])?|AQ(?:{_STANDARD_JOIN}T)?|"
    rf"HG(?:{_STANDARD_JOIN}T)?|SH(?:{_STANDARD_JOIN}T)?|"
    rf"JGJ(?:{_STANDARD_JOIN}T)?|TSG(?:\s*[A-Z]{{1,3}})?|DL(?:{_STANDARD_JOIN}T)?|"
    rf"JB(?:{_STANDARD_JOIN}T)?|CJJ(?:{_STANDARD_JOIN}T)?|"
    rf"(?:T{_STANDARD_SEP})?CCSAS|DB\d{{2}}(?:{_STANDARD_JOIN}T)?)"
    rf"\s*\d+(?:\.\d+)*(?:\s*[-—–－]\s*\d{{2,4}})?"
)

# 发文号语法片段〔YYYY〕N号 / [YYYY]N号（与 citation_evidence 共用）
DOC_NUMBER_PATTERN: str = (
    r"〔(?:19|20)\d{2}〕\s*\d+\s*号|\[(?:19|20)\d{2}\]\s*\d+\s*号"
)

CITATION_RE: re.Pattern[str] = re.compile(
    # 1) 书名号：《安全生产法》《重大隐患判定标准（试行）》等
    r"《[^》\n]{1,80}》"
    # 2) 标准号：GB 30871-2022 / GB/T 38429.2-2019 / JGJT46-2024 / TCCSAS005-2019
    rf"|{STANDARD_NO_PATTERN}"
    # 3) 〔YYYY〕N号 / [YYYY]N号（国家部委/集团发文号）
    rf"|{DOC_NUMBER_PATTERN}"
    # 5) 第X条 / 第X.X条 / 第X节（中文数字与阿拉伯数字混排）
    r"|第[一二三四五六七八九十百千零〇两\d]+(?:\.\d+)*\s*[条章节]"
    # 6) X.X条 / X.X.X条（不带「第」的简写条号）
    r"|\d+\.\d+(?:\.\d+)*\s*条"
)


def has_citation(text: str) -> bool:
    """判定文本是否包含至少一处可识别的法规/标准/条文引用。

    Args:
        text: 待判定文本（通常为 AI 输出的 `major_hazard_basis`）

    Returns:
        True 表示命中任一引用格式；空文本/纯泛化表述返回 False。
    """
    if not text:
        return False
    return CITATION_RE.search(text) is not None


def is_placeholder_basis(text: str) -> bool:
    """判定文本是否为「知识库无条文」类占位依据。

    仅做精确子串判定（与历史重跑脚本口径一致）：占位标记中间插入书名号等
    内容的变体不命中（P0-A 遗留漏判，见 ``is_placeholder_variant``），由
    `has_citation` 的正向引用判定兜底。

    Args:
        text: 待判定文本（通常为 AI 输出的 `major_hazard_basis`）

    Returns:
        True 表示命中任一占位文案。
    """
    if not text:
        return False
    return any(marker in text for marker in PLACEHOLDER_BASIS_MARKERS)


# 占位文案变体：模型把法规名插进占位句（如「知识库中无《重大隐患判定标准
# （试行）》相应条文，待人工补充」），P0-A 的精确子串判定会漏判并写回台账
# （2026-11-05 重跑窗口实际发生 1 条）。变体判定在 P0-C 纳入质量闸门。
_PLACEHOLDER_VARIANT_RE = re.compile(
    r"知识库\s*(?:中|信息)?[^。\n]{0,20}?(?:无|没有|不足|未找到|暂无)"
    r"[^。\n]{0,20}?(?:条文|信息)"
)


def is_placeholder_variant(text: str) -> bool:
    """判定文本是否为「知识库无条文」占位（含 P0-A 精确口径漏掉的变体）。

    在 ``is_placeholder_basis`` 精确子串口径之上增加变体正则：
    「知识库〔中/信息〕…无/没有/不足/未找到/暂无…条文/信息」，
    以及「含『知识库』且含『待人工补充』」的兜底。

    注意：本函数只判文案形态，**是否阻断写回由引用可验证报告决定**
    （依据里有可验证引用时，占位注记只是补充说明，可放行）。

    Args:
        text: 待判定文本（通常为 AI 输出的 `major_hazard_basis`）

    Returns:
        True 表示占位/占位变体文案。
    """
    if not text:
        return False
    if is_placeholder_basis(text):
        return True
    if "知识库" in text and "待人工补充" in text:
        return True
    return _PLACEHOLDER_VARIANT_RE.search(text) is not None
