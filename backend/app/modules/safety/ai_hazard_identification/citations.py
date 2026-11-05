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
_STANDARD_NO = (
    rf"(?:GB(?:{_STANDARD_SEP}?[TZ])?|AQ(?:{_STANDARD_SEP}?T)?|"
    rf"HG(?:{_STANDARD_SEP}?T)?|SH(?:{_STANDARD_SEP}?T)?|"
    rf"JGJ(?:{_STANDARD_SEP}?T)?|TSG(?:\s*[A-Z]{{1,3}})?|DL(?:{_STANDARD_SEP}?T)?|"
    rf"JB(?:{_STANDARD_SEP}?T)?|CJJ(?:{_STANDARD_SEP}?T)?|"
    rf"(?:T{_STANDARD_SEP})?CCSAS|DB\d{{2}}(?:{_STANDARD_SEP}?T)?)"
    rf"\s*\d+(?:\.\d+)*(?:\s*[-—–－]\s*\d{{2,4}})?"
)

CITATION_RE: re.Pattern[str] = re.compile(
    # 1) 书名号：《安全生产法》《重大隐患判定标准（试行）》等
    r"《[^》\n]{1,80}》"
    # 2) 标准号：GB 30871-2022 / GB/T 38429.2-2019 / JGJT46-2024 / TCCSAS005-2019
    rf"|{_STANDARD_NO}"
    # 3) 〔YYYY〕N号（国家部委/集团发文号）
    r"|〔(?:19|20)\d{2}〕\s*\d+\s*号"
    # 4) [YYYY]N号
    r"|\[(?:19|20)\d{2}\]\s*\d+\s*号"
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
    内容的变体不命中，由 `has_citation` 的正向引用判定兜底。

    Args:
        text: 待判定文本（通常为 AI 输出的 `major_hazard_basis`）

    Returns:
        True 表示命中任一占位文案。
    """
    if not text:
        return False
    return any(marker in text for marker in PLACEHOLDER_BASIS_MARKERS)
