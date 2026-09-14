"""Agent 运行参数 store — 运营可调参数的运行时大脑。

- **读（热路径，全同步）**：``get_value`` / ``get_view`` 只读内存缓存；缓存 miss /
  TTL 过期时经同步只读会话重建（每键一次查询）。
- **回退链**：DB 活行（软删行视同缺行）→ env（registry.env_var）→ registry 默认；
  值按注册表 value_type 收敛（int/float/str）。
- **写（async，API 层传入 session）**：``set_key`` 按注册表类型/范围校验 →
  软删行恢复 → before/after 审计 → flush → re-fetch → invalidate。
- **测试接缝**：构造函数 ``row_loader`` 注入预设行；生产不传走同步会话工厂。
DB 读失败仅告警并回退默认——配置中心故障不中断业务。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.models import RuntimeConfig, RuntimeConfigAudit
from app.modules.warehouse.ops_config import runtime_registry

logger = logging.getLogger(__name__)

_TTL_SECONDS = 60.0

RuntimeSource = Literal["db", "env", "default"]
RuntimeRowLoader = Callable[[str], Any]


@dataclass(frozen=True)
class RuntimeView:
    """单参数合并视图（含来源归属，供 API 展示）。"""

    key: str
    label: str
    group: str
    value: Any
    default: Any
    source: RuntimeSource
    value_type: str
    min_value: float | None
    max_value: float | None
    max_length: int | None
    description: str


class RuntimeConfigStore:
    """模块级单例。热路径全同步（内存缓存），写操作 async（DB + 审计 + 失效）。"""

    def __init__(self, row_loader: RuntimeRowLoader | None = None) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_sources: dict[str, RuntimeSource] = {}
        self._loaded_at: dict[str, float] = {}
        self._ttl_seconds: float = _TTL_SECONDS
        self._row_loader = row_loader

    # ═══════════════════════════════════════════════════════════
    # 读（热路径，同步）
    # ═══════════════════════════════════════════════════════════

    def get_value(self, key: str) -> Any:
        """某参数最终值（DB → env → registry 默认）；未知 key 抛 ValueError。"""
        runtime_registry.get_runtime_key(key)  # 未知参数抛 ValueError
        return self._view(key).value

    def get_view(self, key: str) -> RuntimeView:
        """某参数合并视图（供 GET 总览）。"""
        runtime_registry.get_runtime_key(key)
        return self._view(key)

    def iter_views(self) -> tuple[RuntimeView, ...]:
        """遍历 registry 全部参数（供 GET 总览）。"""
        return tuple(self._view(info.key) for info in runtime_registry.iter_runtime_keys())

    # ═══════════════════════════════════════════════════════════
    # 缓存维护
    # ═══════════════════════════════════════════════════════════

    def invalidate(self, key: str | None = None) -> None:
        """失效缓存；None = 全部失效。"""
        if key is None:
            self._cache.clear()
            self._cache_sources.clear()
            self._loaded_at.clear()
            return
        self._cache.pop(key, None)
        self._cache_sources.pop(key, None)
        self._loaded_at.pop(key, None)

    async def warmup(self) -> None:
        """启动预热（失败仅告警，读路径回退 env/默认）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                rows = (
                    await session.execute(
                        select(RuntimeConfig).where(RuntimeConfig.is_deleted.is_(False))
                    )
                ).scalars().all()
                by_key = {r.key: r for r in rows}
                now = time.monotonic()
                for info in runtime_registry.iter_runtime_keys():
                    value, source = self._resolve(info, by_key.get(info.key))
                    self._cache[info.key] = value
                    self._cache_sources[info.key] = source
                    self._loaded_at[info.key] = now
        except Exception:
            logger.exception("运行参数启动预热失败（读路径将以 env/registry 默认兜底）")

    # ═══════════════════════════════════════════════════════════
    # 写（async；API 层传入 session）
    # ═══════════════════════════════════════════════════════════

    async def set_key(
        self,
        db: AsyncSession,
        key: str,
        value: Any,
        operator_name: str | None = None,
    ) -> RuntimeView:
        """按注册表校验并写入单参数（事务 + 审计 + 失效）。

        - 未知 key 抛 ValueError（404 语义）；类型/范围不合法抛 ValueError（422 语义）；
        - 软删行恢复；before/after 审计（action=update）；
        - UPDATE 后 ``flush()`` → ``select`` re-fetch → ``invalidate(key)``。
        """
        info = runtime_registry.get_runtime_key(key)
        normalized = self._validate_value(info, value)

        row = await self._find_row(db, key)
        before = {"value": row.value} if row is not None else None
        if row is None:
            row = RuntimeConfig(key=key, value=normalized)
            db.add(row)
        else:
            row.is_deleted = False
            row.value = normalized

        db.add(
            RuntimeConfigAudit(
                key=key,
                action="update",
                before_json=before,
                after_json={"value": normalized},
                operator_name=operator_name,
            )
        )
        await db.flush()

        # UPDATE 后 select re-fetch（CLAUDE.md SQLAlchemy async 铁律）
        fresh = (
            await db.execute(
                select(RuntimeConfig).where(
                    RuntimeConfig.key == key,
                    RuntimeConfig.is_deleted.is_(False),
                )
            )
        ).scalars().first()
        self.invalidate(key)
        row = fresh if fresh is not None else row
        value = self._coerce(info, row.value) if row is not None else info.default
        return self._build_view(info, forced_value=value, forced_source="db")

    # ═══════════════════════════════════════════════════════════
    # 内部：缓存重建（读路径）
    # ═══════════════════════════════════════════════════════════

    def _view(self, key: str) -> RuntimeView:
        info = runtime_registry.get_runtime_key(key)
        now = time.monotonic()
        if key in self._cache and now - self._loaded_at.get(key, 0.0) < self._ttl_seconds:
            return self._build_view(
                info,
                forced_value=self._cache[key],
                forced_source=self._cache_sources[key],
            )
        row = self._fetch_row(key)
        if row is not None and row.is_deleted:
            row = None
        value, source = self._resolve(info, row)
        self._cache[key] = value
        self._cache_sources[key] = source
        self._loaded_at[key] = now
        return self._build_view(info, forced_value=value, forced_source=source)

    def _build_view(
        self,
        info: runtime_registry.RuntimeKeyInfo,
        *,
        forced_value: Any,
        forced_source: RuntimeSource,
    ) -> RuntimeView:
        return RuntimeView(
            key=info.key,
            label=info.label,
            group=info.group,
            value=forced_value,
            default=info.default,
            source=forced_source,
            value_type=info.value_type,
            min_value=info.min_value,
            max_value=info.max_value,
            max_length=info.max_length,
            description=info.description,
        )

    def _resolve(
        self, info: runtime_registry.RuntimeKeyInfo, row: Any | None
    ) -> tuple[Any, RuntimeSource]:
        """回退链解析：DB 活行（值非空）→ env → registry 默认。"""
        if row is not None and not row.is_deleted and row.value is not None:
            return self._coerce(info, row.value), "db"
        if info.env_var:
            env_value = getattr(get_settings(), info.env_var, None)
            if env_value is not None and env_value != "":
                return self._coerce(info, env_value), "env"
        return info.default, "default"

    def _coerce(self, info: runtime_registry.RuntimeKeyInfo, raw: Any) -> Any:
        """按注册表 value_type 收敛值类型；非法值回落默认。"""
        try:
            if info.value_type == "int":
                return int(raw)
            if info.value_type == "float":
                return float(raw)
            return str(raw)[: (info.max_length or 8000)]
        except (TypeError, ValueError):
            logger.warning("运行参数 %s 值 %r 类型不合法，回落默认", info.key, raw)
            return info.default

    def _validate_value(self, info: runtime_registry.RuntimeKeyInfo, value: Any) -> Any:
        """写路径校验：类型 + 范围/长度（422 语义）。"""
        if info.value_type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{info.label} 必须为整数")
            if info.min_value is not None and value < info.min_value:
                raise ValueError(f"{info.label} 不能小于 {int(info.min_value)}")
            if info.max_value is not None and value > info.max_value:
                raise ValueError(f"{info.label} 不能大于 {int(info.max_value)}")
            return value
        if info.value_type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{info.label} 必须为数值")
            value = float(value)
            if info.min_value is not None and value < info.min_value:
                raise ValueError(f"{info.label} 不能小于 {info.min_value}")
            if info.max_value is not None and value > info.max_value:
                raise ValueError(f"{info.label} 不能大于 {info.max_value}")
            return value
        text = str(value)
        if info.max_length is not None and len(text) > info.max_length:
            raise ValueError(f"{info.label} 长度不能超过 {info.max_length}")
        return text

    # ═══════════════════════════════════════════════════════════
    # 内部：DB 访问
    # ═══════════════════════════════════════════════════════════

    def _fetch_row(self, key: str) -> RuntimeConfig | None:
        try:
            if self._row_loader is not None:
                return cast("RuntimeConfig | None", self._row_loader(key))
            from app.modules.warehouse.ai_config._db import make_sync_session_factory

            with make_sync_session_factory()() as session:
                row = session.execute(
                    select(RuntimeConfig).where(
                        RuntimeConfig.key == key,
                        RuntimeConfig.is_deleted.is_(False),
                    )
                ).scalars().first()
                return row
        except Exception:
            logger.exception("运行参数 DB 读取失败（key=%s），回退 env/registry 默认", key)
            return None

    @staticmethod
    async def _find_row(db: AsyncSession, key: str) -> RuntimeConfig | None:
        stmt = (
            select(RuntimeConfig)
            .where(RuntimeConfig.key == key)
            .order_by(RuntimeConfig.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()


runtime_store = RuntimeConfigStore()

__all__ = ["RuntimeConfigStore", "RuntimeView", "runtime_store"]
