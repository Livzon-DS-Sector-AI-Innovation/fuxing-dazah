"""Bitable 配置中心 store — 运行时大脑（backend-design §3.2）。

- **读（热路径，全同步）**：``get_connections`` / ``get_connection`` /
  ``get_domain_view`` / ``is_enabled`` / ``table_id_for`` 只读内存缓存，
  零 IO 零锁；缓存 miss / TTL 过期时经同步只读会话重建（每域一次查询）。
- **fallback 链**：``ConnectionView = DB 活行 → registry.default_connection``；
  mapping = ``DB 行 → registry.default_mappings[kind]``；DB 行 ``enabled=false``
  不回退默认（显式停用），``get_connections`` 剔除之，``get_connection`` 返回
  ``status="disabled"`` 视图供配置页展示。
- **status 四态**：``db``（DB 活行）/ ``default``（DB 无行，用 registry 值）/
  ``disabled``（DB 行停用）/ ``missing``（registry 无默认连接且 DB 无行）。
- **写（async，API 层传入 session）**：``set_connection`` / ``set_mappings``
  校验 → 查活行（含软删恢复）→ 应用变更 → ``db.add(audit)`` → ``flush`` →
  ``invalidate(domain)`` → ``create_task(resubscribe_domain(domain))``。
- **TTL 兜底**：缓存 60s 惰性过期，防御多实例/漏失效（§7.1 R3）。

同步 DB 读取说明：读方法必须同步（被 async 事件 handler 热路径直接调用），
故缓存重建使用独立同步会话（DATABASE_URL 的 asyncpg 驱动替换为 psycopg，
低频访问 + NullPool，不占 async 连接池）。DB 读失败仅告警、回退 registry
默认值，功能不中断（§7.1 R4）。

循环依赖说明：本模块**不**在模块级 import ``event_hooks``（handler → store
→ event_hooks 链），``set_connection`` 在函数内延迟 import 并 fire-and-forget。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal, get_args

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.modules.safety.bitable_config import registry
from app.modules.safety.models import (
    BitableConfigAudit,
    BitableConnection,
    BitableFieldMapping,
)

logger = logging.getLogger(__name__)

# 缓存 TTL 兜底（秒）：写后 invalidate 即时生效；TTL 防御多实例/漏失效
_TTL_SECONDS = 60.0

ConnectionStatus = Literal["db", "default", "disabled", "missing"]


@dataclass(frozen=True)
class ConnectionView:
    """单表连接视图（fallback 已展开，含 status 归属）。"""

    domain: str
    kind: str
    app_token: str
    table_id: str
    extra_table_ids: tuple[str, ...]
    enabled: bool
    note: str | None
    status: ConnectionStatus  # db=DB 行 / default=registry 默认 / disabled=停用 / missing=无配置


@dataclass(frozen=True)
class DomainConfigView:
    """单域合并视图（连接 + 映射，配置页与 API 用）。"""

    domain: str
    connections: dict[str, ConnectionView]
    mappings: dict[str, list[dict[str, Any]]]


class BitableConfigStore:
    """模块级单例。热路径全同步（内存缓存），写操作 async（DB + 审计 + 失效 + 重订阅）。"""

    def __init__(self) -> None:
        self._conn_cache: dict[str, dict[str, ConnectionView]] = {}
        self._map_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._conn_loaded_at: dict[str, float] = {}
        self._map_loaded_at: dict[tuple[str, str], float] = {}
        self._ttl_seconds: float = _TTL_SECONDS
        self._sync_session_maker: sessionmaker[Session] | None = None  # 惰性创建

    # ═══════════════════════════════════════════════════════════
    # 读（热路径，同步，永不阻塞；缓存 miss 才走一次同步 DB 重建）
    # ═══════════════════════════════════════════════════════════

    def get_connections(self, domain: str) -> list[ConnectionView]:
        """域内全部**启用**的连接视图（剔除 disabled；未知域名抛 ValueError）。"""
        registry.get_domain(domain)
        return [v for v in self._conn_views(domain).values() if v.enabled]

    def get_connection(self, domain: str, kind: str) -> ConnectionView | None:
        """单表连接视图。

        - disabled 行返回视图（status="disabled"，配置页展示，handler 经
          ``is_enabled``/``enabled`` 判断）；
        - missing（registry 无默认且 DB 无行）或未知 kind 返回 None
          （handler 走现有降级分支，§5.1）。
        """
        registry.get_domain(domain)
        view = self._conn_views(domain).get(kind)
        if view is None or view.status == "missing":
            return None
        return view

    def get_domain_view(self, domain: str) -> DomainConfigView:
        """域合并视图：全部 kind 连接（含 disabled/missing）+ 映射（含 fallback）。"""
        domain_info = registry.get_domain(domain)
        mappings: dict[str, list[dict[str, Any]]] = {}
        for kind_info in domain_info.kinds:
            mappings[kind_info.kind] = self._mappings_for(domain, kind_info.kind)
        return DomainConfigView(
            domain=domain,
            connections=self._conn_views(domain),
            mappings=mappings,
        )

    def is_enabled(self, domain: str, kind: str) -> bool:
        """该表连接是否可用（disabled/missing/未知 → False）。"""
        view = self.get_connection(domain, kind)
        return bool(view is not None and view.enabled)

    def table_id_for(self, domain: str, kind: str) -> str | None:
        """启用连接的 table_id；未启用/缺失返回 None。"""
        view = self.get_connection(domain, kind)
        if view is None or not view.enabled:
            return None
        return view.table_id

    # ═══════════════════════════════════════════════════════════
    # 缓存维护
    # ═══════════════════════════════════════════════════════════

    def invalidate(self, domain: str | None = None) -> None:
        """失效缓存条目（不做主动加载，惰性重建）；None = 全部失效。"""
        if domain is None:
            self._conn_cache.clear()
            self._map_cache.clear()
            self._conn_loaded_at.clear()
            self._map_loaded_at.clear()
            return
        self._conn_cache.pop(domain, None)
        self._conn_loaded_at.pop(domain, None)
        for key in [k for k in self._map_cache if k[0] == domain]:
            self._map_cache.pop(key, None)
            self._map_loaded_at.pop(key, None)

    async def warmup(self) -> None:
        """启动预热：async_session_factory 全量加载连接+映射缓存（每域一次查询）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                conn_rows = (
                    await session.execute(
                        select(BitableConnection).where(
                            BitableConnection.is_deleted.is_(False)
                        )
                    )
                ).scalars().all()
                by_domain: dict[str, list[BitableConnection]] = {}
                for row in conn_rows:
                    by_domain.setdefault(row.domain, []).append(row)
                now = time.monotonic()
                for domain, rows in by_domain.items():
                    self._conn_cache[domain] = self._build_connection_views(domain, rows)
                    self._conn_loaded_at[domain] = now

                map_rows = (
                    await session.execute(
                        select(BitableFieldMapping).where(
                            BitableFieldMapping.is_deleted.is_(False)
                        )
                    )
                ).scalars().all()
                for mapping_row in map_rows:
                    self._map_cache[(mapping_row.domain, mapping_row.kind)] = list(mapping_row.mappings)
                    self._map_loaded_at[(mapping_row.domain, mapping_row.kind)] = now
        except Exception:
            logger.exception("Bitable 配置中心启动预热失败（读路径将以 registry 默认兜底）")

    # ═══════════════════════════════════════════════════════════
    # 写（async；API 层传入 session，本模块不自建写会话）
    # ═══════════════════════════════════════════════════════════

    async def set_connection(
        self,
        db: AsyncSession,
        domain: str,
        kind: str,
        payload: dict[str, Any],
        operator_name: str | None = None,
    ) -> ConnectionView:
        """校验并写入单表连接（事务 + 审计 + 失效 + 触发重订阅）。

        - 未知域名/未知 kind 抛 ValueError（「未知域名」/「未知表类型」开头）；
        - app_token/table_id 非空；extra_table_ids 仅 central_alarm 域支持，
          且每项 tbl 前缀、非空、去重、不含主表；
        - 软删行恢复（参照 scheduler ``_find_config_row`` 恢复语义）。
        """
        domain_info = registry.get_domain(domain)
        domain_info.get_kind(kind)  # 未知表类型抛 ValueError
        values = self._validate_connection_payload(domain, payload)

        row = await self._find_connection_row(db, domain, kind)
        before = self._compact_connection(row) if row is not None else None

        if row is None:
            row = BitableConnection(domain=domain, kind=kind)
            db.add(row)
        if row.is_deleted:
            row.is_deleted = False
        for key, value in values.items():
            setattr(row, key, value)
        if "enabled" not in values and row.enabled is None:
            row.enabled = True

        after = self._compact_connection(row)
        db.add(
            BitableConfigAudit(
                domain=domain,
                kind=kind,
                action="update",
                before_json=before,
                after_json=after,
                operator_name=operator_name,
            )
        )
        await db.flush()

        # UPDATE 后 select re-fetch（CLAUDE.md SQLAlchemy async 铁律）
        fresh = (
            await db.execute(
                select(BitableConnection).where(
                    BitableConnection.domain == domain,
                    BitableConnection.kind == kind,
                    BitableConnection.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        view = self._view_from_row(fresh) if fresh is not None else self._view_from_row(row)

        self.invalidate(domain)
        self._trigger_resubscribe(domain)
        return view

    async def set_mappings(
        self,
        db: AsyncSession,
        domain: str,
        kind: str,
        mappings: list[dict[str, Any]],
        operator_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """全量替换字段映射（事务 + 审计 + 失效；不触发重订阅，§4.1）。"""
        domain_info = registry.get_domain(domain)
        domain_info.get_kind(kind)
        normalized = self._validate_mappings(mappings)

        row = await self._find_mapping_row(db, domain, kind)
        before = list(row.mappings) if row is not None else None

        if row is None:
            row = BitableFieldMapping(domain=domain, kind=kind)
            db.add(row)
        if row.is_deleted:
            row.is_deleted = False
        row.mappings = normalized

        db.add(
            BitableConfigAudit(
                domain=domain,
                kind=kind,
                action="update",
                before_json=before,
                after_json=list(normalized),
                operator_name=operator_name,
            )
        )
        await db.flush()
        self.invalidate(domain)
        return list(normalized)

    async def test_connection(self, app_token: str, table_id: str) -> dict[str, Any]:
        """校验 app_token/table_id：只读拉表/字段，不写库不写审计。

        成功返回 ``{"ok": True, "meta": {"table_name": ..., "field_count": N}}``；
        失败抛 ValueError（消息含飞书错误码语义，由 API 层映射 400/502）。
        """
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        client = SafetyBitableClient(app_token=app_token, table_id=table_id)
        tables = await client.list_tables()
        table = next((t for t in tables if t.get("table_id") == table_id), None)
        if table is None:
            raise ValueError(f"table_id 不存在或无权限: {table_id}")
        fields = await client.list_fields(table_id)
        return {
            "ok": True,
            "meta": {
                "table_name": table.get("name"),
                "field_count": len(fields),
            },
        }

    # ═══════════════════════════════════════════════════════════
    # 内部：缓存重建（读路径）
    # ═══════════════════════════════════════════════════════════

    def _conn_views(self, domain: str) -> dict[str, ConnectionView]:
        """域内全部 kind 连接视图（含 disabled/missing），带 TTL 惰性重建。"""
        now = time.monotonic()
        cached = self._conn_cache.get(domain)
        if cached is not None and now - self._conn_loaded_at.get(domain, 0.0) < self._ttl_seconds:
            return cached
        views = self._build_connection_views(domain, self._fetch_connection_rows(domain))
        self._conn_cache[domain] = views
        self._conn_loaded_at[domain] = now
        return views

    def _mappings_for(self, domain: str, kind: str) -> list[dict[str, Any]]:
        """单 kind 映射（DB 行 → registry 默认），带 TTL 惰性重建。"""
        key = (domain, kind)
        now = time.monotonic()
        cached = self._map_cache.get(key)
        if cached is not None and now - self._map_loaded_at.get(key, 0.0) < self._ttl_seconds:
            return cached
        row_mappings = self._fetch_mapping_row(domain, kind)
        if row_mappings is not None:
            mappings = row_mappings
        else:
            kind_info = registry.get_domain(domain).get_kind(kind)
            mappings = [dict(m) for m in kind_info.default_mappings]
        self._map_cache[key] = mappings
        self._map_loaded_at[key] = now
        return list(mappings)  # 独立拷贝：调用方改动不污染缓存/registry 默认

    def _build_connection_views(
        self, domain: str, rows: list[BitableConnection]
    ) -> dict[str, ConnectionView]:
        """纯构造：DB 活行 → registry 默认展开（warmup 与同步读共用）。"""
        domain_info = registry.get_domain(domain)
        rows_by_kind = {r.kind: r for r in rows}
        views: dict[str, ConnectionView] = {}
        for kind_info in domain_info.kinds:
            row = rows_by_kind.get(kind_info.kind)
            if row is not None:
                views[kind_info.kind] = self._view_from_row(row)
                continue
            default = kind_info.default_connection
            if default is None:
                views[kind_info.kind] = ConnectionView(
                    domain=domain,
                    kind=kind_info.kind,
                    app_token="",
                    table_id="",
                    extra_table_ids=(),
                    enabled=False,
                    note=None,
                    status="missing",
                )
            else:
                views[kind_info.kind] = ConnectionView(
                    domain=domain,
                    kind=kind_info.kind,
                    app_token=default.app_token,
                    table_id=default.table_id,
                    extra_table_ids=default.extra_table_ids,
                    enabled=True,
                    note=default.note,
                    status="default",
                )
        return views

    @staticmethod
    def _view_from_row(row: BitableConnection) -> ConnectionView:
        return ConnectionView(
            domain=row.domain,
            kind=row.kind,
            app_token=row.app_token,
            table_id=row.table_id,
            extra_table_ids=tuple(row.extra_table_ids or []),
            enabled=row.enabled,
            note=row.note,
            status="disabled" if not row.enabled else "db",
        )

    # ═══════════════════════════════════════════════════════════
    # 内部：DB 访问（读路径同步会话；测试可替换 _fetch_* 注入 fake）
    # ═══════════════════════════════════════════════════════════

    def _fetch_connection_rows(self, domain: str) -> list[BitableConnection]:
        """DB 活行查询（同步只读，低频：缓存 miss/TTL 过期时每域一次）。

        失败仅告警并返回 []（读路径回退 registry 默认，§7.1 R4）。
        测试通过替换本方法注入 fake rows。
        """
        try:
            with self._sync_session() as session:
                rows = session.execute(
                    select(BitableConnection).where(
                        BitableConnection.domain == domain,
                        BitableConnection.is_deleted.is_(False),
                    )
                ).scalars().all()
                return list(rows)
        except Exception:
            logger.exception(
                "Bitable 连接配置 DB 读取失败（domain=%s），回退 registry 默认值", domain
            )
            return []

    def _fetch_mapping_row(self, domain: str, kind: str) -> list[dict[str, Any]] | None:
        """DB 映射行查询（同步只读）；无行/失败返回 None（走 registry 默认）。"""
        try:
            with self._sync_session() as session:
                row = session.execute(
                    select(BitableFieldMapping).where(
                        BitableFieldMapping.domain == domain,
                        BitableFieldMapping.kind == kind,
                        BitableFieldMapping.is_deleted.is_(False),
                    )
                ).scalars().first()
                return list(row.mappings) if row is not None else None
        except Exception:
            logger.exception(
                "Bitable 映射配置 DB 读取失败（domain=%s kind=%s），回退 registry 默认",
                domain, kind,
            )
            return None

    def _sync_session(self) -> Session:
        """惰性创建同步只读会话（低频重建用，不占 async 连接池）。

        DATABASE_URL 驱动 asyncpg → psycopg（pyproject 已依赖 psycopg[binary]）。
        """
        if self._sync_session_maker is None:
            from sqlalchemy import create_engine
            from sqlalchemy.pool import NullPool

            from app.core.config import get_settings

            url = get_settings().DATABASE_URL.replace(
                "postgresql+asyncpg://", "postgresql+psycopg://", 1
            )
            engine = create_engine(
                url,
                poolclass=NullPool,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 3},
            )
            self._sync_session_maker = sessionmaker(
                bind=engine, expire_on_commit=False
            )
        return self._sync_session_maker()

    # ═══════════════════════════════════════════════════════════
    # 内部：写路径
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _validate_connection_payload(
        domain: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        app_token = payload.get("app_token")
        table_id = payload.get("table_id")
        if app_token is None or not str(app_token).strip():
            raise ValueError("app_token 不能为空")
        if table_id is None or not str(table_id).strip():
            raise ValueError("table_id 不能为空")
        values["app_token"] = str(app_token).strip()
        values["table_id"] = str(table_id).strip()

        if "enabled" in payload:
            if not isinstance(payload["enabled"], bool):
                raise ValueError("enabled 必须为布尔值")
            values["enabled"] = payload["enabled"]

        if "extra_table_ids" in payload:
            extra = payload["extra_table_ids"]
            if extra is None:
                values["extra_table_ids"] = None
            else:
                if domain != "central_alarm":
                    raise ValueError("extra_table_ids 仅 central_alarm 域支持")
                if not isinstance(extra, list) or not extra:
                    raise ValueError("extra_table_ids 必须为非空列表")
                normalized = [str(t).strip() for t in extra]
                for t in normalized:
                    if not t.startswith("tbl"):
                        raise ValueError(f"extra_table_ids 表 ID 必须以 tbl 开头: {t}")
                if values["table_id"] in normalized:
                    raise ValueError("extra_table_ids 不能包含主表 table_id")
                seen: set[str] = set()
                deduped: list[str] = []
                for t in normalized:
                    if t not in seen:
                        seen.add(t)
                        deduped.append(t)
                values["extra_table_ids"] = deduped

        if "note" in payload:
            note = payload["note"]
            values["note"] = str(note).strip() if note is not None else None
        return values

    @staticmethod
    def _validate_mappings(mappings: Any) -> list[dict[str, Any]]:
        if not isinstance(mappings, list):
            raise ValueError("mappings 必须为列表")
        valid_field_types = get_args(registry.FieldType)
        normalized: list[dict[str, Any]] = []
        for item in mappings:
            if not isinstance(item, dict):
                raise ValueError("mappings 每项必须为 dict")
            target = item.get("target_field")
            if not target or not str(target).strip():
                raise ValueError("target_field 不能为空")
            field_type = item.get("field_type")
            if field_type not in valid_field_types:
                raise ValueError(f"未知字段类型: {field_type}")
            value_map = item.get("value_map")
            if value_map is not None and not isinstance(value_map, dict):
                raise ValueError(f"value_map 必须为 dict（target_field={target}）")
            optional = item.get("optional")
            if optional is not None and not isinstance(optional, bool):
                raise ValueError(f"optional 必须为布尔值（target_field={target}）")
            normalized.append(dict(item))
        return normalized

    @staticmethod
    async def _find_connection_row(
        db: AsyncSession, domain: str, kind: str
    ) -> BitableConnection | None:
        """查找 (domain, kind) 对应连接行（含软删行，用于恢复）。"""
        stmt = (
            select(BitableConnection)
            .where(BitableConnection.domain == domain, BitableConnection.kind == kind)
            .order_by(BitableConnection.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    async def _find_mapping_row(
        db: AsyncSession, domain: str, kind: str
    ) -> BitableFieldMapping | None:
        """查找 (domain, kind) 对应映射行（含软删行，用于恢复）。"""
        stmt = (
            select(BitableFieldMapping)
            .where(BitableFieldMapping.domain == domain, BitableFieldMapping.kind == kind)
            .order_by(BitableFieldMapping.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    def _compact_connection(row: BitableConnection) -> dict[str, Any]:
        """审计 before/after：连接全量 compact（§7.2 回滚 = 用 before 反向 PUT）。"""
        return {
            "app_token": row.app_token,
            "table_id": row.table_id,
            "enabled": row.enabled,
            "extra_table_ids": list(row.extra_table_ids) if row.extra_table_ids else None,
            "note": row.note,
        }

    @staticmethod
    def _trigger_resubscribe(domain: str) -> None:
        """写成功后 fire-and-forget 重订阅（不阻塞 API 响应，§4.3）。

        延迟 import ``event_hooks`` 避免循环依赖（handler → store → event_hooks）。
        无运行中事件循环（如单元测试）时记日志即可，API 可手动 POST 兜底。
        """
        try:
            from app.modules.safety.bitable_config.event_hooks import resubscribe_domain

            asyncio.create_task(resubscribe_domain(domain))
        except Exception:
            logger.exception("触发域 %s 重订阅失败（可手动 POST /resubscribe 兜底）", domain)


store = BitableConfigStore()


def resolve_connection(domain: str, kind: str) -> tuple[str, str]:
    """脚本/CLI 用的同步便捷读取：返回 ``(app_token, table_id)``。

    - 优先 DB 配置（store 缓存），缺失/停用回退 registry 默认值；
    - 未知域名/kind 或无任何配置时返回空元组（调用方走现有降级分支）。
    """
    try:
        view = store.get_connection(domain, kind)
        if view and view.status != "disabled":
            return view.app_token, view.table_id
    except ValueError:
        return "", ""
    try:
        kind_info = registry.get_domain(domain).get_kind(kind)
    except ValueError:
        return "", ""
    default = kind_info.default_connection
    if default is not None:
        return default.app_token, default.table_id
    return "", ""


__all__ = [
    "ConnectionView",
    "DomainConfigView",
    "BitableConfigStore",
    "store",
    "resolve_connection",
]
