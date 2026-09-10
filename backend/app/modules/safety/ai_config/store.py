"""AI 配置中心 store — 运行时大脑（backend-design §3）。

- **读（热路径，全同步）**：``get_profile`` / ``get_profile_config`` 只读内存缓存，
  零 IO 零锁；缓存 miss / TTL 过期时经同步 psycopg 只读会话重建（每 profile 一次查询）。
- **字段级回退**（与 bitable 行级回退的结构性差异）：起点 = registry.default_config
  深拷贝 → env 层（env_map 非空且 os.getenv 有值 → 覆盖，sources=env）→ DB 层
  （活行 enabled=true 且字段非空 → 覆盖，sources=db）；DB 行 enabled=false → 整行
  回落 env/default，status="disabled"。
- **status 五态**：``db`` / ``env`` / ``default`` / ``disabled`` / ``missing``。
- **写（async，API 层传入 session）**：``set_profile`` 校验 → 软删行恢复 → 应用 →
  before/after 审计（api_key 一律脱敏 ``****``+后4位，明文绝不落审计表）→ flush →
  select re-fetch（CLAUDE.md async 铁律）→ invalidate(profile)。
- **TTL 兜底**：缓存 60s 惰性过期，防御多实例/漏失效（§9 风险 3）。

同步 DB 读取说明：读方法必须同步（读链热路径直接调用），缓存重建使用独立同步
会话（DATABASE_URL asyncpg → psycopg，低频访问 + NullPool + connect_timeout=3）。
DB 读失败仅告警、回退 env/registry 默认值，功能不中断。

循环依赖说明：本模块**不**在模块级 import ``service/``、``knowledge/``、
``event_hooks``；如未来需要「配置变更后触发重订阅/重连」类副作用，一律写成功后
**函数内延迟 import + fire-and-forget**（对齐 bitable ``_trigger_resubscribe``）。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.modules.safety.ai_config import registry
from app.modules.safety.models import AiConfigAudit, AiModelProfile

logger = logging.getLogger(__name__)

# 缓存 TTL 兜底（秒）：写后 invalidate 即时生效；TTL 防御多实例/漏失效
_TTL_SECONDS = 60.0

SourceKind = Literal["db", "env", "default"]
ProfileStatus = Literal["db", "env", "default", "disabled", "missing"]


def _mask_api_key(api_key: str | None) -> str:
    """展示脱敏：与 service/ai_config.py 语义一致（未配置/已配置 · ****后4位）。

    store 内实现同名函数，避免 service 反向 import store 私有函数
    （依赖方向保持 service → store 单向）。
    """
    if not api_key:
        return "未配置"
    if len(api_key) > 8:
        return f"已配置 · ****{api_key[-4:]}"
    return "已配置 · ****"


def _mask_api_key_for_audit(api_key: str | None) -> str:
    """审计专用脱敏：``****``+后4位；空 key 保留真实空态 ``""``，过短 key 全掩码。

    审计表（before_json/after_json）绝不出现明文 api_key（backend-design §9 风险 4）。
    """
    if not api_key:
        return ""
    if len(api_key) > 4:
        return f"****{api_key[-4:]}"
    return "****"


@dataclass(frozen=True)
class ProfileView:
    """单组模型配置视图（字段级回退已展开，含 sources/status 归属）。"""

    profile: str
    label: str
    config: dict[str, Any]                       # 最终合并值（DB→env→registry 默认）
    api_key_masked: str                          # 展示脱敏（未配置/已配置 · ****后4位）
    enabled: bool                                # 活行 enabled（无 DB 行时当 True，回退视为可用）
    status: ProfileStatus                        # db/env/default/disabled/missing
    sources: dict[str, SourceKind]               # 每字段来源："db" | "env" | "default"


class AiConfigStore:
    """模块级单例。热路径全同步（内存缓存），写操作 async（DB + 审计 + 失效）。"""

    def __init__(self) -> None:
        self._profile_cache: dict[str, ProfileView] = {}
        self._loaded_at: dict[str, float] = {}
        self._ttl_seconds: float = _TTL_SECONDS
        self._sync_session_maker: sessionmaker[Session] | None = None  # 惰性创建

    # ═══════════════════════════════════════════════════════════
    # 读（热路径，同步，永不阻塞；缓存 miss 才走一次同步 DB 重建）
    # ═══════════════════════════════════════════════════════════

    def get_profile(self, profile: str) -> ProfileView:
        """某 profile 合并视图；未知 profile 抛 ValueError（「未知 profile」开头，404 语义）。"""
        registry.get_profile(profile)  # 未知 profile 抛 ValueError
        return self._profile_view(profile)

    def get_profile_config(self, profile: str) -> dict[str, Any]:
        """纯 config（供内部读链）：最终合并值副本；含真实 api_key（仅内部使用，不回显）。"""
        return dict(self.get_profile(profile).config)

    # ═══════════════════════════════════════════════════════════
    # 缓存维护
    # ═══════════════════════════════════════════════════════════

    def invalidate(self, profile: str | None = None) -> None:
        """失效缓存条目（不做主动加载，惰性重建）；None = 全部失效。"""
        if profile is None:
            self._profile_cache.clear()
            self._loaded_at.clear()
            return
        self._profile_cache.pop(profile, None)
        self._loaded_at.pop(profile, None)

    async def warmup(self) -> None:
        """启动预热：async_session_factory 全量加载 5 组（失败仅告警，读路径回退 env/默认）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                rows = (
                    await session.execute(
                        select(AiModelProfile).where(AiModelProfile.is_deleted.is_(False))
                    )
                ).scalars().all()
                by_profile = {r.profile: r for r in rows}
                now = time.monotonic()
                for info in registry.iter_profiles():
                    self._profile_cache[info.profile] = self._build_profile_view(
                        info.profile, by_profile.get(info.profile)
                    )
                    self._loaded_at[info.profile] = now
        except Exception:
            logger.exception("AI 配置中心启动预热失败（读路径将以 env/registry 默认兜底）")

    # ═══════════════════════════════════════════════════════════
    # 写（async；API 层传入 session，本模块不自建写会话）
    # ═══════════════════════════════════════════════════════════

    async def set_profile(
        self,
        db: AsyncSession,
        profile: str,
        payload: dict[str, Any],
        operator_name: str | None = None,
    ) -> ProfileView:
        """校验并写入单组模型配置（事务 + 审计 + 失效）。

        - 未知 profile 抛 ValueError（「未知 profile」开头，404 语义）；
        - profile 无关字段 / 越界值抛 ValueError（422 语义，见 _validate_profile_payload）；
        - api_key 空串/None = 不改（保留 DB 现值）；非空覆盖；
        - 软删行恢复（``_find_profile_row`` 含软删行，ORDER BY updated_at DESC LIMIT 1）；
        - before/after 审计：api_key 一律脱敏，明文绝不落审计表；
        - UPDATE 后 ``flush()`` → ``select`` re-fetch（CLAUDE.md SQLAlchemy async 铁律）。
        """
        registry.get_profile(profile)
        values = self._validate_profile_payload(profile, payload)

        row = await self._find_profile_row(db, profile)
        before_enabled = row.enabled if row is not None else None
        before = self._compact_profile(row) if row is not None else None

        if row is None:
            row = AiModelProfile(profile=profile, config={}, enabled=True)  # 首建默认启用
            db.add(row)
        if row.is_deleted:
            row.is_deleted = False
        config = dict(row.config or {})
        for key, value in values.items():
            if key == "enabled":
                row.enabled = value
            elif key == "note":
                row.note = value
            else:
                config[key] = value
        row.config = config
        if row.enabled is None:
            row.enabled = True

        after = self._compact_profile(row)
        db.add(
            AiConfigAudit(
                profile=profile,
                action=self._action_for_enabled(before_enabled, row.enabled),
                before_json=before,
                after_json=after,
                operator_name=operator_name,
            )
        )
        await db.flush()

        # UPDATE 后 select re-fetch（CLAUDE.md SQLAlchemy async 铁律）
        fresh = (
            await db.execute(
                select(AiModelProfile).where(
                    AiModelProfile.profile == profile,
                    AiModelProfile.is_deleted.is_(False),
                )
            )
        ).scalars().first()
        self.invalidate(profile)
        return self._build_profile_view(profile, fresh if fresh is not None else row)

    # ═══════════════════════════════════════════════════════════
    # 内部：缓存重建（读路径）
    # ═══════════════════════════════════════════════════════════

    def _profile_view(self, profile: str) -> ProfileView:
        """某 profile 合并视图，带 TTL 惰性重建。"""
        now = time.monotonic()
        cached = self._profile_cache.get(profile)
        if cached is not None and now - self._loaded_at.get(profile, 0.0) < self._ttl_seconds:
            return cached
        view = self._build_profile_view(profile, self._fetch_profile_row(profile))
        self._profile_cache[profile] = view
        self._loaded_at[profile] = now
        return view

    def _build_profile_view(self, profile: str, row: AiModelProfile | None) -> ProfileView:
        """纯构造：registry 默认深拷贝 → env 层 → DB 层（字段级回退），status/sources 归属。

        读路径（同步重建/warmup）与写路径（re-fetch 返回值）共用。
        """
        info = registry.get_profile(profile)
        config: dict[str, Any] = dict(info.default_config)
        sources: dict[str, SourceKind] = {f: "default" for f in info.field_names}

        # env 层：env_map[field] 非空且 os.getenv 有值 → 覆盖（逐字段回退）
        for field in info.field_names:
            env_name = info.env_map.get(field, "")
            if not env_name:
                continue
            env_value = os.getenv(env_name)
            if env_value is None or env_value == "":
                continue
            config[field] = self._coerce_env_value(field, env_value, info)
            sources[field] = "env"

        # DB 层：仅当活行 enabled=true 且字段非空才覆盖（字段级回退核心）
        if row is not None and row.enabled:
            row_config = row.config or {}
            for field in info.field_names:
                db_value = row_config.get(field)
                if db_value is not None and db_value != "":
                    config[field] = db_value
                    sources[field] = "db"

        # status 归属：DB 行禁用优先（整行回落 env/default）；其次 db/env/default；其余 missing
        if row is not None and not row.enabled:
            status: ProfileStatus = "disabled"
        elif any(v == "db" for v in sources.values()):
            status = "db"
        elif any(v == "env" for v in sources.values()):
            status = "env"
        elif any(v == "default" for v in sources.values()):
            status = "default"
        else:
            status = "missing"

        return ProfileView(
            profile=info.profile,
            label=info.label,
            config=config,
            api_key_masked=_mask_api_key(config.get("api_key")),
            enabled=row.enabled if row is not None else True,
            status=status,
            sources=sources,
        )

    @staticmethod
    def _coerce_env_value(field: str, raw: str, info: registry.ProfileInfo) -> Any:
        """env 值类型对齐 default_config（dims 等 int 字段）；非法值回落默认（来源保持 default）。"""
        default = info.default_config.get(field)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return default
        if isinstance(default, float):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default
        return raw

    # ═══════════════════════════════════════════════════════════
    # 内部：DB 访问（读路径同步会话；测试可替换 _fetch_profile_row 注入 fake）
    # ═══════════════════════════════════════════════════════════

    def _fetch_profile_row(self, profile: str) -> AiModelProfile | None:
        """DB 活行查询（同步只读，低频：缓存 miss/TTL 过期时每 profile 一次）。

        失败仅告警并返回 None（读路径回退 env/registry 默认值）。
        测试通过替换本方法注入 fake rows。
        """
        try:
            with self._sync_session() as session:
                row = session.execute(
                    select(AiModelProfile).where(
                        AiModelProfile.profile == profile,
                        AiModelProfile.is_deleted.is_(False),
                    )
                ).scalars().first()
                return row
        except Exception:
            logger.exception(
                "AI 模型配置 DB 读取失败（profile=%s），回退 env/registry 默认值", profile
            )
            return None

    def _sync_session(self) -> Session:
        """惰性创建同步只读会话（低频重建用，不占 async 连接池）。

        DATABASE_URL 驱动 asyncpg → psycopg（pyproject 已依赖 psycopg[binary]），
        复用共享 helper（``ai_config._db.make_sync_session_factory``）：
        NullPool + pool_pre_ping + connect_timeout=3，行为与二期一致。
        """
        from app.modules.safety.ai_config._db import make_sync_session_factory

        return make_sync_session_factory()()

    # ═══════════════════════════════════════════════════════════
    # 内部：写路径
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _validate_profile_payload(profile: str, payload: dict[str, Any]) -> dict[str, Any]:
        """校验并归一化 set_profile 增量（API 层映射 422）。返回仅含合法键的 dict。

        规则（backend-design §3.4 / §5.2）：
        - 未知 profile 抛 ValueError（「未知 profile」开头，404 语义）；
        - profile 无关字段（不在 field_names/enabled/note 内）→ ValueError（422 语义）；
        - dims >= 1（仅 embedding）；0 <= temperature <= 2（仅 text/vision）；
          1 <= timeout <= 600（仅 text/vision/text_backup）；
        - api_key 空串/None 或 None → 不修改（不进返回）；非空最长 512；
        - base_url 最长 512、model 最长 256、note 最长 255；enabled 必须 bool；
        - 其余字段 None → 不修改（保留 DB 现值）。
        """
        info = registry.get_profile(profile)
        values: dict[str, Any] = {}
        for key, raw in payload.items():
            if key == "enabled":
                if not isinstance(raw, bool):
                    raise ValueError("enabled 必须为布尔值")
                values[key] = raw
                continue
            if key == "note":
                if raw is not None and len(str(raw)) > 255:
                    raise ValueError("note 长度不能超过 255")
                values[key] = str(raw).strip() if raw is not None else None
                continue
            if key not in info.field_names:
                raise ValueError(f"字段 {key} 不适用于 profile {profile}")
            if raw is None:
                continue  # None = 不修改（api_key 空串同样不修改，见下）
            if key == "api_key":
                if str(raw).strip() == "":
                    continue  # 空串 = 不修改（保留 DB 现值）
                if len(str(raw)) > 512:
                    raise ValueError("api_key 长度不能超过 512")
                values[key] = str(raw).strip()
            elif key == "base_url":
                if len(str(raw)) > 512:
                    raise ValueError("base_url 长度不能超过 512")
                values[key] = str(raw).strip()
            elif key == "model":
                if len(str(raw)) > 256:
                    raise ValueError("model 长度不能超过 256")
                values[key] = str(raw).strip()
            elif key == "dims":
                if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
                    raise ValueError("dims 必须为 >=1 的整数（仅 embedding 支持）")
                values[key] = raw
            elif key == "temperature":
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not (0.0 <= float(raw) <= 2.0)
                ):
                    raise ValueError("temperature 必须在 0-2 之间（仅 text/vision 支持）")
                values[key] = float(raw)
            elif key == "timeout":
                if isinstance(raw, bool) or not isinstance(raw, int) or not (1 <= raw <= 600):
                    raise ValueError("timeout 必须在 1-600 之间（仅 text/vision/text_backup 支持）")
                values[key] = raw
            else:  # registry 断言保证 field_names ⊆ default_config，避免字段流失
                values[key] = raw
        return values

    @staticmethod
    async def _find_profile_row(
        db: AsyncSession, profile: str
    ) -> AiModelProfile | None:
        """查找 profile 对应行（含软删行，用于恢复）。"""
        stmt = (
            select(AiModelProfile)
            .where(AiModelProfile.profile == profile)
            .order_by(AiModelProfile.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    def _compact_profile(row: AiModelProfile) -> dict[str, Any]:
        """审计 before/after：config 全量 compact（api_key 脱敏后4位，明文绝不落审计表）。"""
        info = registry.get_profile(row.profile)
        compact: dict[str, Any] = {}
        for field in info.field_names:
            value = (row.config or {}).get(field)
            if field == "api_key":
                compact[field] = _mask_api_key_for_audit(value)
            else:
                compact[field] = value
        compact["enabled"] = row.enabled
        compact["note"] = row.note
        return compact

    @staticmethod
    def _action_for_enabled(before: bool | None, after: bool) -> str:
        """审计 action：按 before.enabled → after.enabled 翻转，取 enable/disable/update。"""
        if before is None:
            return "enable" if after else "disable"
        if after and not before:
            return "enable"
        if before and not after:
            return "disable"
        return "update"


store = AiConfigStore()

__all__ = [
    "ProfileView",
    "AiConfigStore",
    "store",
    "SourceKind",
    "ProfileStatus",
]
