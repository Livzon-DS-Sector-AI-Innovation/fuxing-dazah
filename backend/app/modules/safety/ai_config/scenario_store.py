"""AI 场景配置 store — 场景级开关与模型绑定运行时大脑（backend-design §3）。

- **读（热路径，全同步）**：``get_scenario_view`` 只读内存缓存，零 IO 零锁；
  缓存 miss / TTL 过期时经同步 psycopg 只读会话重建（每场景一次查询）。
- **场景视图解析**：enabled 缺省 true；model_profile 缺省 NULL（空串视为 None）
  → ``effective_profile`` 按该场景默认（绑定 ∈ 白名单时取绑定，否则回退默认）；
  未注册场景/无 DB 行 → default-enabled（不抛，熔断层默认放行）。
- **status/source 归属**：``source`` = db（有活行）/ default（无行）/ disabled
  （活行 enabled=false）；``status`` = enabled/disabled。停用仅保留 store 视图
  （供 API 展示），不拦截读。
- **写（async，API 层传入 session）**：``set_scenario`` 校验（enabled bool、
  model_profile 白名单、note 长度）→ 软删行恢复 → before/after 压缩审计
  （相位无密钥，不脱敏）→ flush → select re-fetch（CLAUDE.md async 铁律）→
  invalidate(scenario)。
- **TTL 兜底**：缓存 60s 惰性过期，防御多实例/漏失效。

同步 DB 读取说明：读方法必须同步（读链热路径直接调用），缓存重建使用独立同步
会话（``ai_config._db.make_sync_session_factory``，与二期 AiConfigStore 共用）。
DB 读失败仅告警、回退 registry 默认——默认开启，功能不中断。

循环依赖说明：本模块**不**在模块级 import ``service/``、``knowledge/``、
``event_hooks``；只 import ``scenario_registry`` + ``models``（+ 共享 sync helper）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.safety.ai_config import scenario_registry
from app.modules.safety.models import AiScenarioConfig, AiScenarioConfigAudit

logger = logging.getLogger(__name__)

# 缓存 TTL 兜底（秒）：写后 invalidate 即时生效；TTL 防御多实例/漏失效
_TTL_SECONDS = 60.0

ScenarioSource = Literal["db", "default", "disabled"]
ScenarioStatus = Literal["enabled", "disabled"]


@dataclass(frozen=True)
class ScenarioView:
    """单场景合并视图（注册元信息 + 配置状态，字段级回退已展开）。"""

    scenario: str
    label: str
    description: str
    model_type: str
    channel: str
    deprecated: bool
    enabled: bool                       # 活行 enabled；无 DB 行＝True
    model_profile: str | None           # raw 绑定值；NULL/空串=按默认
    effective_profile: str              # 场景绑定 > 场景默认（已解析）
    allowed_profiles: tuple[str, ...]   # 白名单（前端下拉 & 校验来源）
    source: ScenarioSource              # db / default / disabled
    status: ScenarioStatus              # enabled / disabled


class AiScenarioStore:
    """模块级单例。热路径全同步（内存缓存），写操作 async（DB + 审计 + 失效）。"""

    def __init__(self) -> None:
        self._scenario_cache: dict[str, ScenarioView] = {}
        self._loaded_at: dict[str, float] = {}
        self._ttl_seconds: float = _TTL_SECONDS

    # ═══════════════════════════════════════════════════════════
    # 读（热路径，同步，永不阻塞；缓存 miss 才走一次同步 DB 重建）
    # ═══════════════════════════════════════════════════════════

    def get_scenario_view(self, scenario: str) -> ScenarioView:
        """某场景合并视图；未注册场景/无 DB 行 → default-enabled（不抛异常，熔断层据此放行）。"""
        now = time.monotonic()
        cached = self._scenario_cache.get(scenario)
        if cached is not None and now - self._loaded_at.get(scenario, 0.0) < self._ttl_seconds:
            return cached
        view = self._build_scenario_view(
            scenario, scenario_registry.get_scenario(scenario), self._fetch_scenario_row(scenario)
        )
        self._scenario_cache[scenario] = view
        self._loaded_at[scenario] = now
        return view

    def get_scenario(self, scenario: str) -> ScenarioView:
        """ticket 别名：与 get_scenario_view 同义。"""
        return self.get_scenario_view(scenario)

    def iter_scenario_views(self) -> tuple[ScenarioView, ...]:
        """遍历 registry 全部场景，逐场景合并视图（供 GET ai-scenarios 全量，含 deprecated）。"""
        return tuple(
            self.get_scenario_view(info.scenario) for info in scenario_registry.iter_scenarios()
        )

    def is_enabled(self, scenario: str) -> bool:
        """熔断层专用：只判断 enabled。未注册场景返回 True（默认放行）。"""
        return self.get_scenario_view(scenario).enabled

    def get_effective_profile(self, scenario: str) -> str:
        """熔断层专用：绑定生效 profile（场景绑定 > 场景默认）。"""
        return self.get_scenario_view(scenario).effective_profile

    def effective_profile(self, scenario: str) -> str:
        """ticket 别名：与 get_effective_profile 同义。"""
        return self.get_effective_profile(scenario)

    # ═══════════════════════════════════════════════════════════
    # 缓存维护
    # ═══════════════════════════════════════════════════════════

    def invalidate(self, scenario: str | None = None) -> None:
        """失效缓存条目（不做主动加载，惰性重建）；None = 全部失效。"""
        if scenario is None:
            self._scenario_cache.clear()
            self._loaded_at.clear()
            return
        self._scenario_cache.pop(scenario, None)
        self._loaded_at.pop(scenario, None)

    async def warmup(self) -> None:
        """启动预热：async_session_factory 全量加载场景行（失败仅告警，读路径回退默认开启）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                rows = (
                    await session.execute(
                        select(AiScenarioConfig).where(AiScenarioConfig.is_deleted.is_(False))
                    )
                ).scalars().all()
                by_scenario = {r.scenario: r for r in rows}
                now = time.monotonic()
                self._scenario_cache.clear()
                self._loaded_at.clear()
                for info in scenario_registry.iter_scenarios():
                    self._scenario_cache[info.scenario] = self._build_scenario_view(
                        info.scenario, info, by_scenario.get(info.scenario)
                    )
                    self._loaded_at[info.scenario] = now
        except Exception:
            logger.exception("AI 场景配置启动预热失败（读路径将以 registry 默认兜底）")

    # ═══════════════════════════════════════════════════════════
    # 写（async；API 层传入 session，本模块不自建写会话）
    # ═══════════════════════════════════════════════════════════

    async def set_scenario(
        self,
        db: AsyncSession,
        scenario: str,
        payload: dict[str, Any],
        operator_name: str | None = None,
    ) -> ScenarioView:
        """校验并写入单场景配置（事务 + 审计 + 失效）。

        - 未知场景抛 ValueError（「未知场景」开头，API 映射 404）；
        - 白名单外绑定抛 ValueError（「不适用绑定」开头，API 映射 422）；
        - ``enabled`` 必须 bool；``model_profile`` 可为 None/空串（清绑定）；
          ``note`` ≤255；
        - 首建/软删恢复/字段更新 → ``flush()`` → ``select`` re-fetch →
          ``invalidate(scenario)``（CLAUDE.md SQLAlchemy async 铁律）。
        """
        info = scenario_registry.get_scenario_info(scenario)  # 未知场景抛 ValueError
        values = self._validate_scenario_payload(scenario, payload, info)

        row = await self._find_scenario_row(db, scenario)
        before_enabled = row.enabled if row is not None else None
        before = self._compact_scenario(row) if row is not None else None

        if row is None:
            row = AiScenarioConfig(scenario=scenario, enabled=True)  # 首建默认启用
            db.add(row)
        if row.is_deleted:
            row.is_deleted = False
        if "enabled" in values:
            row.enabled = values["enabled"]
        if "model_profile" in values:
            row.model_profile = values["model_profile"]
        if "note" in values:
            row.note = values["note"]
        if row.enabled is None:
            row.enabled = True

        after = self._compact_scenario(row)
        db.add(
            AiScenarioConfigAudit(
                scenario=scenario,
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
                select(AiScenarioConfig).where(
                    AiScenarioConfig.scenario == scenario,
                    AiScenarioConfig.is_deleted.is_(False),
                )
            )
        ).scalars().first()
        self.invalidate(scenario)
        return self._build_scenario_view(scenario, info, fresh if fresh is not None else row)

    # ═══════════════════════════════════════════════════════════
    # 内部：缓存重建（读路径）
    # ═══════════════════════════════════════════════════════════

    def _build_scenario_view(
        self,
        scenario: str,
        info: scenario_registry.ScenarioInfo | None,
        row: AiScenarioConfig | None,
    ) -> ScenarioView:
        """纯构造：注册元信息 + DB 行合并（缺行=默认开启；空串绑定视为 None）。"""
        if info is None:
            # 未注册场景：合成 default 视图（默认放行，熔断层只看 enabled）
            label, description, model_type, channel, deprecated = (
                scenario, "", "text", "unknown", False,
            )
            allowed: tuple[str, ...] = ("text", "text_backup")
            default_profile = "text"
        else:
            label = info.label
            description = info.description
            model_type = info.model_type
            channel = info.channel
            deprecated = info.deprecated
            allowed = scenario_registry.allowed_profiles_for(info.scenario)
            default_profile = scenario_registry.default_profile_for(info.scenario)

        enabled = row.enabled if row is not None else True
        model_profile = row.model_profile if row is not None else None
        if model_profile == "":  # 劣化数据防御：空字符串绑定视为 None
            model_profile = None
        # 绑定非空且不在白名单 → 写路径已拦；读路径防御性回退场景默认
        effective_profile = (
            model_profile
            if model_profile is not None and model_profile in allowed
            else default_profile
        )
        if row is not None and not row.enabled:
            source: ScenarioSource = "disabled"
        elif row is not None:
            source = "db"
        else:
            source = "default"
        status: ScenarioStatus = "disabled" if not enabled else "enabled"

        return ScenarioView(
            scenario=scenario,
            label=label,
            description=description,
            model_type=model_type,
            channel=channel,
            deprecated=deprecated,
            enabled=enabled,
            model_profile=model_profile,
            effective_profile=effective_profile,
            allowed_profiles=allowed,
            source=source,
            status=status,
        )

    # ═══════════════════════════════════════════════════════════
    # 内部：DB 访问（读路径同步会话；测试可替换 _fetch_scenario_row 注入 fake）
    # ═══════════════════════════════════════════════════════════

    def _fetch_scenario_row(self, scenario: str) -> AiScenarioConfig | None:
        """DB 活行查询（同步只读，低频：缓存 miss/TTL 过期时每场景一次）。

        失败仅告警并返回 None（读路径回退默认开启）。
        测试通过替换本方法注入 fake rows。
        """
        try:
            with self._sync_session() as session:
                row = session.execute(
                    select(AiScenarioConfig).where(
                        AiScenarioConfig.scenario == scenario,
                        AiScenarioConfig.is_deleted.is_(False),
                    )
                ).scalars().first()
                return row
        except Exception:
            logger.exception(
                "AI 场景配置 DB 读取失败（scenario=%s），回退 registry 默认", scenario
            )
            return None

    def _sync_session(self) -> Session:
        """惰性创建同步只读会话（复用共享 helper，与二期 AiConfigStore 同源）。"""
        from app.modules.safety.ai_config._db import make_sync_session_factory

        return make_sync_session_factory()()

    # ═══════════════════════════════════════════════════════════
    # 内部：写路径
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _validate_scenario_payload(
        scenario: str,
        payload: dict[str, Any],
        info: scenario_registry.ScenarioInfo,
    ) -> dict[str, Any]:
        """校验并归一化 set_scenario 增量（API 层映射 400/422）。返回仅含合法键的 dict。

        规则（backend-design §3.5）：
        - 未知场景抛 ValueError（「未知场景」开头，404 语义，由 get_scenario_info 预先抛）；
        - 白名单外绑定抛 ValueError（「不适用绑定」开头，422 语义）；
        - enabled 必须 bool；model_profile 非空 ≤32 且必须 ∈ allowed_profiles；
          None/空串 = 清绑定；note ≤255；其余字段抛 ValueError（不适用于此场景）。
        """
        allowed = scenario_registry.allowed_profiles_for(info.scenario)
        values: dict[str, Any] = {}
        for key, raw in payload.items():
            if key == "enabled":
                if not isinstance(raw, bool):
                    raise ValueError("enabled 必须为布尔值")
                values[key] = raw
                continue
            if key == "model_profile":
                if raw is None or (isinstance(raw, str) and raw.strip() == ""):
                    values[key] = None  # 空串/None = 清绑定
                    continue
                raw_str = str(raw).strip()
                if len(raw_str) > 32:
                    raise ValueError("model_profile 长度不能超过 32")
                if raw_str not in allowed:
                    raise ValueError(f"场景 {scenario} 不适用绑定 profile {raw_str}")
                values[key] = raw_str
                continue
            if key == "note":
                if raw is not None and len(str(raw)) > 255:
                    raise ValueError("note 长度不能超过 255")
                values[key] = str(raw).strip() if raw is not None else None
                continue
            raise ValueError(f"字段 {key} 不适用于场景 {scenario}")
        return values

    @staticmethod
    async def _find_scenario_row(
        db: AsyncSession, scenario: str
    ) -> AiScenarioConfig | None:
        """查找场景对应行（含软删行，用于恢复；ORDER BY updated_at DESC LIMIT 1）。"""
        stmt = (
            select(AiScenarioConfig)
            .where(AiScenarioConfig.scenario == scenario)
            .order_by(AiScenarioConfig.updated_at.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    def _compact_scenario(row: AiScenarioConfig) -> dict[str, Any]:
        """审计 before/after：{enabled, model_profile, note} compact（相位无密钥，不脱敏）。"""
        return {
            "enabled": row.enabled,
            "model_profile": row.model_profile,
            "note": row.note,
        }

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


scenario_store = AiScenarioStore()

__all__ = [
    "ScenarioView",
    "AiScenarioStore",
    "scenario_store",
    "ScenarioSource",
    "ScenarioStatus",
]
