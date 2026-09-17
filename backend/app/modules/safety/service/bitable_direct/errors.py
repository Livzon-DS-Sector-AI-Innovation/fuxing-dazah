"""公共直读底座异常层级。

域包异常应继承 ``BitableDirectError``，保证调用方既有的 ``except`` 语义
继续成立（收敛前的 ``SpecialOpDirectError`` 等仍是 ``RuntimeError`` 子类）。
"""

from __future__ import annotations


class BitableDirectError(RuntimeError):
    """底座异常基类（可读失败、写失败、配置缺失的共同父类）。"""


class BitableQueryError(BitableDirectError):
    """批量读取失败（接口报错、分页异常等）。"""


class BitableWriteError(BitableDirectError):
    """回写失败（字段不存在、并发写冲突等）。"""


class BitableConfigError(BitableDirectError):
    """Bitable 连接未配置或已停用。"""
