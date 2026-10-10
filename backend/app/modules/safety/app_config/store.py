"""应用配置中心 store — env→DB 迁移的运行时读写层。

- **读（热路径，全同步）**：``get_raw`` / ``get_bool`` / ``get_int`` / ``get_str``
  只读内存缓存，零 IO；缓存 miss / TTL 过期时经同步 psycopg 只读会话一次查询
  全量活行（复用 ``ai_config._db.make_sync_session_factory``）。
- **生效优先级（刻意设计，与 ai_config 的 DB>env 相反）**：
  进程 env（非空）> DB 活行（enabled 且 value 非空）> registry 代码默认。
  理由：① 既有测试以 monkeypatch.setenv 隔离推送（误发事故教训），env 优先
  保证 DB 行永远压不过测试显式设置；② env 保留为运维应急通道；
  ③ 「迁移到 DB」通过清空 .env 中对应键达成。DB 行与 env 同设且值不同时，
  warmup / 列表 API 打 WARNING（防残留 env 静默遮蔽 DB）。
- **读路径对未注册键宽容**：``get_raw`` 不查 registry（gates 拼名调用，历史
  上任何 env 名都可读）；registry 仅约束**写**与列表展示。
- **写（async，API 层传入 session）**：校验（未知键「未知配置键」→404；值
  非法→422）→ 软删行恢复 → 审计（secret 值脱敏 ****后4位）→ flush →
  select re-fetch（CLAUDE.md async 铁律）→ invalidate。
- **播种**：``seed_from_env`` 只补「无活行且 env 有值」的键（幂等；复刻
  scheduler_config.seed_default_task_targets 惯例），供启动一次性调用。

同步 DB 读取说明：读方法必须同步（gates/常量读取链热路径直接调用），缓存重建
使用独立同步会话（DATABASE_URL asyncpg → psycopg，NullPool + connect_timeout=3）。
DB 读失败仅告警、回退 env/registry 默认，功能不中断。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Literal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.modules.safety.app_config import registry
from app.modules.safety.models import AppConfigAudit, AppConfigEntry

logger = logging.getLogger(__name__)

# 缓存 TTL（秒）：写后 invalidate 即时生效；TTL 防御多实例/漏失效。
# 30s 对齐调度器「配置修改 30s 内生效」口径（gates 类开关改动 ≤30s 生效，
# restart_required 键除外——它们只在启动时读取）。
_TTL_SECONDS = 30.0

# 与 service/bitable_direct/gates.py 的真值集合保持一致（单一定义点在 gates，
# 此处复制常量集合并注释来源；避免 store → service 反向依赖）
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

SourceKind = Literal["env", "db", "default"]


def _mask_secret(value: str | None) -> str:
    """展示/审计脱敏：空保留空态；过长取后 4 位，过短全掩码。"""
    if not value:
        return ""
    if len(value) > 4:
        return f"****{value[-4:]}"
    return "****"


class AppConfigStore:
    """模块级单例。热路径全同步（内存缓存），写操作 async（DB + 审计 + 失效）。"""

    def __init__(self) -> None:
        self._rows: dict[str, str] = {}
        self._loaded_at: float = 0.0
        self._ttl_seconds: float = _TTL_SECONDS

    # ═══════════════════════════════════════════════════════════
    # 读（热路径，同步；env > DB 活行 > None）
    # ═══════════════════════════════════════════════════════════

    def get_raw(self, key: str) -> str | None:
        """原始字符串值；env 非空优先，其次 DB 活行；两层皆无 → None。

        不查 registry（读路径宽容：gates 拼名调用，任意 env 名可读）。
        """
        env_value = os.getenv(key)
        if env_value is not None and env_value != "":
            return env_value
        row_value = self._rows_view().get(key)
        if row_value is not None and row_value != "":
            return row_value
        return None

    def get_bool(self, key: str, default: bool | None = None) -> bool:
        """布尔值：raw 缺省时用 default（None = registry 默认，未注册为 False）。"""
        if default is None:
            default = self._registry_default(key, False)
            if not isinstance(default, bool):
                default = bool(default)
        raw = self.get_raw(key)
        if raw is None:
            return default
        return raw.strip().lower() in _TRUE

    def get_int(self, key: str, default: int | None = None, *, minimum: int = 1) -> int:
        """整数值：解析失败/缺省回退 default 并按 minimum 兜底（gates.int_env 同款）。"""
        if default is None:
            default = self._registry_default(key, 0)
            if not isinstance(default, int) or isinstance(default, bool):
                default = 0
        raw = self.get_raw(key)
        if raw is None:
            return max(minimum, default)
        try:
            return max(minimum, int(raw.strip()))
        except ValueError:
            return max(minimum, default)

    def get_str(self, key: str, default: str | None = None) -> str:
        """字符串值：raw 缺省时用 default（None = registry 默认，未注册为空串）。"""
        if default is None:
            default = self._registry_default(key, "")
            if not isinstance(default, str):
                default = str(default)
        raw = self.get_raw(key)
        return raw.strip() if raw is not None else default

    # ═══════════════════════════════════════════════════════════
    # 列表视图（API/前端 + env-DB 冲突告警）
    # ═══════════════════════════════════════════════════════════

    def effective_items(self) -> list[dict[str, Any]]:
        """全部注册项的生效视图（值/来源/类型化展示/冲突标记）。

        来源：env > db > default（与读路径一致）。secret 值展示脱敏。
        env 与 DB 同设且值不同 → ``env_overrides_db=true`` + WARNING
        （提示清掉 .env 残留键，否则 DB 改动不生效）。
        """
        rows = self._rows_view()
        items: list[dict[str, Any]] = []
        for info in registry.iter_items():
            env_value = (os.getenv(info.key) or "").strip()
            db_value = rows.get(info.key)
            conflict = bool(env_value and db_value and env_value != db_value)
            if conflict:
                logger.warning(
                    "应用配置 %s 同时存在 env(%r) 与 DB(%r)：env 优先生效，"
                    "如需 DB 生效请清除 .env 中该键",
                    info.key, env_value, _mask_secret(db_value) if info.secret else db_value,
                )
            if env_value:
                value, source = env_value, "env"
            elif db_value:
                value, source = db_value, "db"
            else:
                value, source = self._default_display(info), "default"
            items.append({
                "key": info.key,
                "category": info.category,
                "category_label": registry.CATEGORY_LABELS.get(info.category, info.category),
                "type": info.type,
                "value": _mask_secret(value) if info.secret else value,
                "source": source,
                "default": self._default_display(info),
                "description": info.description,
                "restart_required": info.restart_required,
                "secret": info.secret,
                "allow_off": info.allow_off,
                "env_overrides_db": conflict,
            })
        return items

    # ═══════════════════════════════════════════════════════════
    # 缓存维护
    # ═══════════════════════════════════════════════════════════

    def invalidate(self) -> None:
        """失效缓存（不做主动加载，惰性重建）。"""
        self._rows.clear()
        self._loaded_at = 0.0

    async def warmup(self) -> None:
        """启动预热：async_session_factory 全量加载（失败仅告警，读路径回退 env/默认）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                rows = (
                    await session.execute(self._active_rows_stmt())
                ).scalars().all()
                self._rows = {r.key: r.value for r in rows if r.value}
                self._loaded_at = time.monotonic()
        except Exception:
            logger.exception("应用配置中心启动预热失败（读路径将以 env/registry 默认兜底）")

    # ═══════════════════════════════════════════════════════════
    # 写（async；API 层传入 session）+ 播种
    # ═══════════════════════════════════════════════════════════

    async def set_value(
        self,
        db: AsyncSession,
        key: str,
        value: str,
        *,
        enabled: bool | None = None,
        note: str | None = None,
        operator_name: str | None = None,
    ) -> dict[str, Any]:
        """校验并写入单个配置键（事务 + 审计 + 失效），返回该键生效视图。

        - 未知键抛 ValueError（「未知配置键」开头，API 层映射 404）；
        - 值非法抛 ValueError（422 语义，见 _validate_value）；
        - 软删行恢复；UPDATE 后 flush → select re-fetch（async 铁律）。
        """
        info = registry.get_item(key)
        normalized = self._validate_value(info, value)

        row = await self._find_row(db, key)
        before = self._compact_row(row) if row is not None else None
        before_enabled = row.enabled if row is not None else None

        if row is None:
            row = AppConfigEntry(key=key, value=normalized, enabled=True)
            db.add(row)
        if row.is_deleted:
            row.is_deleted = False
        row.value = normalized
        if enabled is not None:
            row.enabled = enabled
        if note is not None:
            row.note = note.strip()[:255] if note.strip() else None
        if row.enabled is None:
            row.enabled = True

        after = self._compact_row(row)
        db.add(
            AppConfigAudit(
                key=key,
                action=self._action_for(before_enabled, row.enabled),
                before_json=before,
                after_json=after,
                operator_name=operator_name,
            )
        )
        await db.flush()

        # UPDATE 后 select re-fetch（CLAUDE.md SQLAlchemy async 铁律）
        fresh = (
            await db.execute(
                select(AppConfigEntry).where(
                    AppConfigEntry.key == key,
                    AppConfigEntry.is_deleted.is_(False),
                )
            )
        ).scalars().first()
        self.invalidate()
        view = self._single_effective(key, fresh)
        return view

    async def seed_from_env(
        self,
        db: AsyncSession | None = None,
        operator_name: str = "system",
    ) -> int:
        """为「无活行且 env 有值」的注册键播种 DB 行（幂等、only-missing）。

        复刻 scheduler_config.seed_default_task_targets 惯例：启动调用一次
        （db=None 自建会话并 commit），每环境自动带走自己 .env 的当前值；
        此后清空 .env 键即完成 DB 切换。测试可传 db 走调用方事务（回滚隔离）。
        """
        if db is not None:
            return await self._seed_in_session(db, operator_name)
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            created = await self._seed_in_session(session, operator_name)
            if created:
                await session.commit()
                self.invalidate()
            return created

    async def _seed_in_session(
        self, session: AsyncSession, operator_name: str
    ) -> int:
        # 已存在 = 任意非软删行（含 enabled=false 停用行——部分唯一索引只排除
        # 软删行，停用行仍占用键位；停用语义 = 整行不生效、回落 env/默认）
        rows = (
            await session.execute(
                select(AppConfigEntry).where(AppConfigEntry.is_deleted.is_(False))
            )
        ).scalars().all()
        existing = {r.key for r in rows}
        created = 0
        for info in registry.iter_items():
            env_value = (os.getenv(info.key) or "").strip()
            if not env_value or info.key in existing:
                continue
            session.add(
                AppConfigEntry(
                    key=info.key,
                    value=env_value,
                    enabled=True,
                    note="启动播种自 env（迁移基线）",
                )
            )
            session.add(
                AppConfigAudit(
                    key=info.key,
                    action="seed",
                    before_json=None,
                    after_json={
                        "value": _mask_secret(env_value) if info.secret else env_value,
                        "enabled": True,
                    },
                    operator_name=operator_name,
                )
            )
            created += 1
        if created:
            await session.flush()
            logger.info("应用配置中心播种 %d 键（env → DB 迁移基线）", created)
        return created

    # ═══════════════════════════════════════════════════════════
    # 内部：缓存重建 / 校验 / compact
    # ═══════════════════════════════════════════════════════════

    def _rows_view(self) -> dict[str, str]:
        """全量活行视图（TTL 惰性重建；失败返回空 dict 回退 env/默认）。"""
        now = time.monotonic()
        if self._loaded_at and now - self._loaded_at < self._ttl_seconds:
            return self._rows
        self._rows = self._fetch_rows()
        self._loaded_at = now
        return self._rows

    def _fetch_rows(self) -> dict[str, str]:
        """DB 活行查询（同步只读，TTL 过期时一次）。

        失败仅告警并返回空 dict（读路径回退 env/registry 默认值）。
        测试通过替换本方法注入 fake rows。
        """
        try:
            from app.modules.safety.ai_config._db import make_sync_session_factory

            factory: sessionmaker[Session] = make_sync_session_factory()
            with factory() as session:
                rows = session.execute(self._active_rows_stmt()).scalars().all()
                return {r.key: r.value for r in rows if r.value}
        except Exception:
            logger.exception("应用配置 DB 读取失败，回退 env/registry 默认值")
            return {}

    @staticmethod
    def _active_rows_stmt() -> Select[tuple[AppConfigEntry]]:
        return select(AppConfigEntry).where(
            AppConfigEntry.is_deleted.is_(False),
            AppConfigEntry.enabled.is_(True),
        )

    @staticmethod
    async def _find_row(db: AsyncSession, key: str) -> AppConfigEntry | None:
        """查找 key 对应行（含软删行，用于恢复）。"""
        stmt = (
            select(AppConfigEntry)
            .where(AppConfigEntry.key == key)
            .order_by(AppConfigEntry.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    def _validate_value(info: registry.ConfigItem, raw: str) -> str:
        """校验并归一化写入值；非法抛 ValueError（422 语义）。

        - bool：接受 _TRUE/_FALSE 集合，归一化为 true/false；空串非法；
        - int：十进制整数且 >= minimum；空串非法；
        - str：strip 后 ≤1024；空串合法（语义 = 清除覆盖，回落 env/默认）；
          chat_id/open_id/notify_users 按后缀约定校验前缀（off 哨兵仅 allow_off）。
        """
        value = (raw or "").strip()
        if info.type == "bool":
            lowered = value.lower()
            if lowered in _TRUE:
                return "true"
            if lowered in _FALSE:
                return "false"
            raise ValueError("布尔值仅接受 true/false/1/0/yes/no/on/off")
        if info.type == "int":
            try:
                parsed = int(value)
            except ValueError:
                raise ValueError("必须为整数") from None
            if parsed < info.minimum:
                raise ValueError(f"不能小于 {info.minimum}")
            return str(parsed)
        # str
        if len(value) > 1024:
            raise ValueError("长度不能超过 1024")
        if not value:
            return ""  # 空串 = 清除覆盖（回落 env/registry 默认）
        key = info.key
        lowered = value.lower()
        if key.endswith(("_CHAT_ID", "_GROUP_ID")):
            if lowered in ("off", "false", "none"):
                if not info.allow_off:
                    raise ValueError("该配置不支持 off 停用哨兵")
                return "off"
            if not (value.startswith("oc_") or value.startswith("ou_")):
                raise ValueError("目标必须以 oc_（群聊）或 ou_（个人）开头")
        elif key.endswith("_OPEN_ID"):
            if not value.startswith("ou_"):
                raise ValueError("open_id 必须以 ou_ 开头")
        elif key.endswith("_NOTIFY_USERS"):
            for item in value.split(","):
                if item.strip() and not item.strip().startswith("ou_"):
                    raise ValueError("通知人列表每项必须以 ou_ 开头（逗号分隔）")
        return value

    def _single_effective(self, key: str, row: AppConfigEntry | None) -> dict[str, Any]:
        """写路径返回的单键生效视图（复用 effective_items 的合并口径）。"""
        info = registry.get_item(key)
        env_value = (os.getenv(key) or "").strip()
        db_value = row.value if (row is not None and row.enabled and row.value) else None
        conflict = bool(env_value and db_value and env_value != db_value)
        if env_value:
            value, source = env_value, "env"
        elif db_value:
            value, source = db_value, "db"
        else:
            value, source = self._default_display(info), "default"
        return {
            "key": key,
            "category": info.category,
            "category_label": registry.CATEGORY_LABELS.get(info.category, info.category),
            "type": info.type,
            "value": _mask_secret(value) if info.secret else value,
            "source": source,
            "default": self._default_display(info),
            "description": info.description,
            "restart_required": info.restart_required,
            "secret": info.secret,
            "allow_off": info.allow_off,
            "env_overrides_db": conflict,
            "enabled": row.enabled if row is not None else None,
            "note": row.note if row is not None else None,
        }

    @staticmethod
    def _default_display(info: registry.ConfigItem) -> str:
        """默认值的展示形态（bool → true/false；int → 十进制；str 原样）。"""
        return str(info.default).lower() if info.type == "bool" else str(info.default)

    @staticmethod
    def _registry_default(key: str, fallback: Any) -> Any:
        item = registry.REGISTRY.get(key)
        return item.default if item is not None else fallback

    @staticmethod
    def _compact_row(row: AppConfigEntry) -> dict[str, Any]:
        """审计 before/after compact（secret 值脱敏，明文绝不落审计表）。"""
        info = registry.REGISTRY.get(row.key)
        value = row.value or ""
        return {
            "value": _mask_secret(value) if (info is not None and info.secret) else value,
            "enabled": row.enabled,
            "note": row.note,
        }

    @staticmethod
    def _action_for(before: bool | None, after: bool) -> str:
        if before is None:
            return "enable" if after else "disable"
        if after and not before:
            return "enable"
        if before and not after:
            return "disable"
        return "update"


store = AppConfigStore()

__all__ = ["AppConfigStore", "store"]
