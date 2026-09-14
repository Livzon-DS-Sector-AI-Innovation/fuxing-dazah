"""Bitable 连接注册表 — 表级连接默认值的代码唯一事实源。

从 ``bitable_schema.TABLES`` **单向导出**（禁止手抄 table_id，防双份漂移）：
10 张核心表的 base_key / env token 键名 / 测试版 table_id / 中文名。

回退链（store 实现，票 05）：DB 活行 → env（按 base_token_setting 取 settings 键）
→ 本注册表默认（= 代码快照）。DB 行 ``enabled=false`` = 显式停用该表，不回退默认。
本模块仅 import bitable_schema（纯常量模块），零副作用，migration 可直接引用。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.warehouse.bitable_schema import TABLES


@dataclass(frozen=True)
class ConnectionInfo:
    """单张表的连接默认值（table_key 是稳定标识，DB 只能改值不能新增表）。"""

    table_key: str
    base_key: str                       # MATERIAL / GMP / PROD / SALES
    base_token_setting: str             # env/settings 键名（Base token 兜底来源）
    default_table_id: str               # 测试版 table_id（代码快照）
    name_cn: str


def iter_connections() -> tuple[ConnectionInfo, ...]:
    """按 TABLES 顺序导出全部表连接（供 migration 播种 + 遍历视图）。"""
    return tuple(
        ConnectionInfo(
            table_key=key,
            base_key=meta.base_key,
            base_token_setting=meta.base_token_setting,
            default_table_id=meta.table_id,
            name_cn=meta.name_cn,
        )
        for key, meta in TABLES.items()
    )


CONNECTION_REGISTRY: dict[str, ConnectionInfo] = {c.table_key: c for c in iter_connections()}
assert len(CONNECTION_REGISTRY) == len(TABLES), "Bitable 连接注册表与 TABLES 数量不一致"


def get_connection(table_key: str) -> ConnectionInfo:
    """未知表抛 ValueError（消息以「未知表」开头，404 语义）。"""
    info = CONNECTION_REGISTRY.get(table_key)
    if info is None:
        raise ValueError(f"未知表: {table_key}")
    return info
