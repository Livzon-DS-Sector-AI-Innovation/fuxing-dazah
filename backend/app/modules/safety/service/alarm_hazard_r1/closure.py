"""R1 闭环分类器 —— 消防报警「处理情况」文本 → 五值闭环分类（纯函数）。

口径=R1 设计 §1.2 闭环盘点（2026-10-20 修订版）：
- 屏蔽（含未记录恢复）按闭环处理，不计未闭环（用户拍板）
- 未闭环 = 移交无回执（pending_handover）/ 明示待办（explicit_todo）/ 空（empty）
- F 类「其他描述」不算未闭环
- 文本规范化必须处理形近字与截断句式（修订版复盘点名的分类假阳性根因：
  「烣复系统」错别字曾致 2 条误分类）

判定优先级（§1.2 真实样本验证）：empty → closed（恢复词最权威——
「已通知仪表更换探头，22:50恢复系统」是闭环）→ explicit_todo →
pending_handover → other。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

CLOSURE_CLOSED = "closed"
CLOSURE_PENDING_HANDOVER = "pending_handover"
CLOSURE_EXPLICIT_TODO = "explicit_todo"
CLOSURE_EMPTY = "empty"
CLOSURE_OTHER = "other"

#: 未闭环三值（规则引擎 closure 子规则的命中集合）
CLOSURE_OPEN_CLASSES = (CLOSURE_PENDING_HANDOVER, CLOSURE_EXPLICIT_TODO, CLOSURE_EMPTY)

#: 形近字修正（修订版复盘实见：「烣复系统」→「恢复系统」）
_TYPO_FIXES = {"烣": "恢"}

#: E 类闭环词（含 B 类屏蔽拍板口径、F 类列举的实为闭环项）
_CLOSED_WORDS = (
    "恢复", "复位", "正常", "已更换", "已报备", "无异常",
    "误报", "屏蔽", "点位已拆除",
)

#: D 类明示待办词（§1.2 F4 实见形态）
_TODO_WORDS = ("未处理", "跟进处理", "采购中", "待处理", "待更换", "待维修", "待校准")
#: D 类开放形态：待…(更换/维修/处理/校准/采购/到货)
_TODO_PATTERN = re.compile(r"待[^，。；,.\s]{0,12}?(更换|维修|处理|校准|采购|到货)")

#: C 类移交无回执词
_HANDOVER_WORDS = ("已通知", "移交")


def plain_text(value: Any) -> str:
    """Bitable 富文本/结构值扁平化为纯文本（R1 公共实现；包内各模块统一用它）。"""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "")
    return str(value)


#: 兼容旧名（模块内历史引用）
_flatten = plain_text


def _normalize(text: str) -> str:
    """规范化：NFKC 全半角统一 + 形近字修正 + 去空白。"""
    fixed = unicodedata.normalize("NFKC", text)
    for wrong, right in _TYPO_FIXES.items():
        fixed = fixed.replace(wrong, right)
    return re.sub(r"\s+", "", fixed)


def classify_closure(value: Any) -> str:
    """处理情况（富文本/str/None）→ closed/pending_handover/explicit_todo/empty/other。"""
    text = _normalize(plain_text(value))
    if not text:
        return CLOSURE_EMPTY
    if any(w in text for w in _CLOSED_WORDS):
        return CLOSURE_CLOSED
    if any(w in text for w in _TODO_WORDS) or _TODO_PATTERN.search(text):
        return CLOSURE_EXPLICIT_TODO
    if any(w in text for w in _HANDOVER_WORDS):
        return CLOSURE_PENDING_HANDOVER
    return CLOSURE_OTHER
