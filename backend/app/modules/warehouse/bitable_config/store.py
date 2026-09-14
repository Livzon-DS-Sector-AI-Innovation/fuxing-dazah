"""Bitable 连接配置 store — 表级坐标的运行时大脑。

- **回退链**：base_token = DB 活行（非空）→ env/settings（base_token_setting 键）
  → 空（缺失时适配器按 missing_credentials 报错）；
  table_id = DB 活行（非空）→ bitable_schema 快照。
- **enabled=false**：显式停用该表，适配层报"表未启用"，不回退默认。
- **写（async，API 层传入 session）**：``set_connection`` 校验 → 软删行恢复 →
  before/after 审计（base_token 脱敏）→ flush → re-fetch → invalidate；
  成功后由 API 层 fire-and-forget 刷新字段缓存。
- **测试接缝**：构造函数 ``row_loader`` 注入预设行；生产不传走同步会话工厂。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.bitable_config import registry
from app.modules.warehouse.models import BitableConfigAudit, BitableConnection

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60.0

ConnectionSource = Literal["db", "env", "default"]
ConnectionRowLoader = Callable[[str], Any]


def _mask_token(token: str | None) -> str:
    """展示脱敏：未配置/****后4位（Base token 属半敏感凭据）。"""
    if not token:
        return "未配置"
    if len(token) > 8:
        return f"****{token[-4:]}"
    return "****"


@dataclass(frozen=True)
class ResolvedConnection:
    """解析后的表连接（适配层取用；base_token 可能为空=无处可取）。"""

    table_key: str
    base_token: str
    table_id: str
    enabled: bool
    token_source: ConnectionSource
    table_id_source: ConnectionSource


@dataclass(frozen=True)
class ConnectionView:
    """API 总览视图（base_token 脱敏）。"""

    table_key: str
    base_key: str
    name_cn: str
    base_token: str                       # 脱敏值
    table_id: str
    enabled: bool
    token_source: ConnectionSource
    table_id_source: ConnectionSource


class BitableConfigStore:
    """模块级单例。热路径全同步（内存缓存），写操作 async（DB + 审计 + 失效）。"""

    def __init__(self, row_loader: ConnectionRowLoader | None = None) -> None:
        self._cache: dict[str, ResolvedConnection] = {}
        self._loaded_at: dict[str, float] = {}
        self._ttl_seconds: float = _TTL_SECONDS
        self._row_loader = row_loader

    # ═══════════════════════════════════════════════════════════
    # 读（热路径，同步）
    # ═══════════════════════════════════════════════════════════

    def resolve(self, table_key: str) -> ResolvedConnection:
        """解析某表连接（适配层取用）；未知表抛 ValueError（404 语义）。"""
        registry.get_connection(table_key)  # 未知表抛 ValueError
        return self._view(table_key).resolved

    def get_connection_view(self, table_key: str) -> ConnectionView:
        """某表连接总览视图（脱敏）。"""
        info = registry.get_connection(table_key)
        return self._mask(info, self._view(table_key).resolved)

    def iter_connection_views(self) -> tuple[ConnectionView, ...]:
        """遍历全部表连接（供 GET 总览）。"""
        return tuple(
            self._mask(info, self._view(info.table_key).resolved)
            for info in registry.iter_connections()
        )

    # ═══════════════════════════════════════════════════════════
    # 缓存维护
    # ═══════════════════════════════════════════════════════════

    def invalidate(self, table_key: str | None = None) -> None:
        """失效缓存；None = 全部失效。"""
        if table_key is None:
            self._cache.clear()
            self._loaded_at.clear()
            return
        self._cache.pop(table_key, None)
        self._loaded_at.pop(table_key, None)

    async def warmup(self) -> None:
        """启动预热（失败仅告警，读路径回退 env/快照）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                rows = (
                    await session.execute(
                        select(BitableConnection).where(
                            BitableConnection.is_deleted.is_(False)
                        )
                    )
                ).scalars().all()
                by_key = {r.table_key: r for r in rows}
                now = time.monotonic()
                for info in registry.iter_connections():
                    self._cache[info.table_key] = self._resolve(
                        info, by_key.get(info.table_key)
                    )
                    self._loaded_at[info.table_key] = now
        except Exception:
            logger.exception("Bitable 连接启动预热失败（读路径将以 env/快照兜底）")

    # ═══════════════════════════════════════════════════════════
    # 写（async；API 层传入 session）
    # ═══════════════════════════════════════════════════════════

    async def set_connection(
        self,
        db: AsyncSession,
        table_key: str,
        payload: dict[str, Any],
        operator_name: str | None = None,
    ) -> ConnectionView:
        """更新某表连接坐标（事务 + 审计 + 失效）。

        - 未知表抛 ValueError（404 语义）；
        - base_token/table_id None 或空串 = 清空覆盖（回落 env/快照）；
        - 软删行恢复；before/after 审计（base_token 脱敏）；
        - UPDATE 后 ``flush()`` → ``select`` re-fetch → ``invalidate(table_key)``。
        """
        info = registry.get_connection(table_key)
        values = self._validate_payload(payload)

        row = await self._find_row(db, table_key)
        before = self._compact(row) if row is not None else None
        if row is None:
            row = BitableConnection(table_key=table_key, enabled=True)
            db.add(row)
        if row.is_deleted:
            row.is_deleted = False
        for key, value in values.items():
            setattr(row, key, value)

        after = self._compact(row)
        db.add(
            BitableConfigAudit(
                table_key=table_key,
                action="update",
                before_json=before,
                after_json=after,
                operator_name=operator_name,
            )
        )
        await db.flush()

        fresh = (
            await db.execute(
                select(BitableConnection).where(
                    BitableConnection.table_key == table_key,
                    BitableConnection.is_deleted.is_(False),
                )
            )
        ).scalars().first()
        self.invalidate(table_key)
        return self._mask(
            info, self._view_from_row(info, fresh if fresh is not None else row)
        )

    # ═══════════════════════════════════════════════════════════
    # 内部：解析与缓存
    # ═══════════════════════════════════════════════════════════

    def _view(self, table_key: str) -> _CacheEntry:
        info = registry.get_connection(table_key)
        now = time.monotonic()
        cached = self._cache.get(table_key)
        if cached is not None and now - self._loaded_at.get(table_key, 0.0) < self._ttl_seconds:
            return _CacheEntry(info=info, resolved=cached)
        row = self._fetch_row(table_key)
        resolved = self._resolve(info, row)
        self._cache[table_key] = resolved
        self._loaded_at[table_key] = now
        return _CacheEntry(info=info, resolved=resolved)

    def _view_from_row(self, info: registry.ConnectionInfo, row: Any) -> ResolvedConnection:
        """写路径 re-fetch 后直接按行构建（跳过缓存）。"""
        return self._resolve(info, row)

    def _resolve(self, info: registry.ConnectionInfo, row: Any | None) -> ResolvedConnection:
        """回退链：DB 活行（非空字段）→ env/settings → 快照默认。"""
        from app.core.config import get_settings

        enabled = bool(row.enabled) if row is not None else True
        db_token = (row.base_token or "").strip() if row is not None else ""
        db_table_id = (row.table_id or "").strip() if row is not None else ""

        env_token = str(getattr(get_settings(), info.base_token_setting, "") or "")
        if db_token:
            base_token = db_token
            token_source: ConnectionSource = "db"
        elif env_token:
            base_token = env_token
            token_source = "env"
        else:
            base_token = ""
            token_source = "default"

        if db_table_id:
            table_id = db_table_id
            table_id_source: ConnectionSource = "db"
        else:
            table_id = info.default_table_id
            table_id_source = "default"

        return ResolvedConnection(
            table_key=info.table_key,
            base_token=base_token,
            table_id=table_id,
            enabled=enabled,
            token_source=token_source,
            table_id_source=table_id_source,
        )

    def _mask(self, info: registry.ConnectionInfo, resolved: ResolvedConnection) -> ConnectionView:
        return ConnectionView(
            table_key=info.table_key,
            base_key=info.base_key,
            name_cn=info.name_cn,
            base_token=_mask_token(resolved.base_token),
            table_id=resolved.table_id,
            enabled=resolved.enabled,
            token_source=resolved.token_source,
            table_id_source=resolved.table_id_source,
        )

    # ═══════════════════════════════════════════════════════════
    # 内部：校验与 DB 访问
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, max_len in (("base_token", 128), ("table_id", 64)):
            if key in payload:
                raw = payload[key]
                text = str(raw).strip() if raw is not None else ""
                if len(text) > max_len:
                    raise ValueError(f"{key} 长度不能超过 {max_len}")
                values[key] = text or None  # 空串 = 清空覆盖
        if "note" in payload:
            raw = payload["note"]
            if raw is not None and len(str(raw)) > 255:
                raise ValueError("note 长度不能超过 255")
            values["note"] = str(raw).strip() if raw is not None else None
        if not values:
            raise ValueError("缺少可更新字段（base_token/table_id/note）")
        return values

    @staticmethod
    def _compact(row: BitableConnection) -> dict[str, Any]:
        """审计 before/after（base_token 脱敏，明文不落审计表）。"""
        return {
            "base_token": _mask_token(row.base_token),
            "table_id": row.table_id,
            "enabled": row.enabled,
            "note": row.note,
        }

    def _fetch_row(self, table_key: str) -> BitableConnection | None:
        try:
            if self._row_loader is not None:
                return cast("BitableConnection | None", self._row_loader(table_key))
            from app.modules.warehouse.ai_config._db import make_sync_session_factory

            with make_sync_session_factory()() as session:
                row = session.execute(
                    select(BitableConnection).where(
                        BitableConnection.table_key == table_key,
                        BitableConnection.is_deleted.is_(False),
                    )
                ).scalars().first()
                return row
        except Exception:
            logger.exception(
                "Bitable 连接 DB 读取失败（table_key=%s），回退 env/快照", table_key
            )
            return None

    @staticmethod
    async def _find_row(db: AsyncSession, table_key: str) -> BitableConnection | None:
        stmt = (
            select(BitableConnection)
            .where(BitableConnection.table_key == table_key)
            .order_by(BitableConnection.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()


@dataclass(frozen=True)
class _CacheEntry:
    info: registry.ConnectionInfo
    resolved: ResolvedConnection


bitable_store = BitableConfigStore()

__all__ = [
    "BitableConfigStore",
    "ConnectionView",
    "ResolvedConnection",
    "bitable_store",
]
