"""跨模块共享的 SQL 表达式辅助。"""

from __future__ import annotations


def escape_like(value: str) -> str:
    """转义 LIKE/ILIKE 通配符，让用户输入的 % 和 _ 按字面量匹配。

    调用方必须同时传 ``escape="\\\\"``，否则转义符本身也会被当成普通字符：

        pattern = f"%{escape_like(keyword)}%"
        stmt.where(column.ilike(pattern, escape="\\\\"))

    不转义时 ``keyword="%"`` 会退化成 "匹配任意内容"，进而命中全表。
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
