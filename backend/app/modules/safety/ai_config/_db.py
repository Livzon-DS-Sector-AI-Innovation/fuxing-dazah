"""AI 配置共享 DB 基础设施 — 同步只读会话工厂（backend-design §3.2）。

``AiConfigStore._sync_session()`` 与 ``AiScenarioStore._sync_session()`` 共用：
DATABASE_URL 驱动 asyncpg → psycopg（pyproject 已依赖 psycopg[binary]），
低频重建用 + NullPool + pool_pre_ping + connect_timeout=3，不占 async 连接池。
模块级幂等：单个 engine/sessionmaker 全局共享。

本模块零副作用导入（``get_settings`` 在函数内延迟 import）。
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def make_sync_session_factory() -> sessionmaker[Session]:
    """惰性创建同步只读会话工厂（低频重建用）。幂等共享一个 engine。"""
    global _engine, _session_factory
    if _session_factory is None:
        from app.core.config import get_settings

        url = get_settings().DATABASE_URL.replace(
            "postgresql+asyncpg://", "postgresql+psycopg://", 1
        )
        _engine = create_engine(
            url,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _session_factory


__all__ = ["make_sync_session_factory"]
