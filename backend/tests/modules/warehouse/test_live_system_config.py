"""系统配置地基 live 冒烟：迁移播种 + store 真实库读取（票 01 验收）。

依赖：e5c4d8a91b72 迁移已在本地 dev 库执行。
断言播种行数（registry 数量一致）、store 真实库合并读取、warmup 不抛错。
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.ai_config import registry as ai_registry
from app.modules.warehouse.ai_config import scenario_registry
from app.modules.warehouse.ai_config.resolver import get_profile_config
from app.modules.warehouse.ai_config.scenario_store import scenario_store
from app.modules.warehouse.ai_config.store import store as ai_store
from app.modules.warehouse.bitable_config import registry as bitable_registry
from app.modules.warehouse.models import (
    AiModelProfile,
    AiScenarioConfig,
    BitableConnection,
    RuntimeConfig,
    SchedulerTaskConfig,
)
from app.modules.warehouse.ops_config import runtime_registry, scheduler_registry


async def _count(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


@pytest.mark.live
async def test_seeded_row_counts_match_registries(db_session: AsyncSession) -> None:
    assert await _count(db_session, AiModelProfile) == len(ai_registry.PROFILE_KEYS)
    assert await _count(db_session, AiScenarioConfig) == len(scenario_registry.SCENARIO_REGISTRY)
    assert await _count(db_session, RuntimeConfig) == len(runtime_registry.RUNTIME_REGISTRY)
    assert await _count(db_session, BitableConnection) == len(bitable_registry.CONNECTION_REGISTRY)
    assert await _count(db_session, SchedulerTaskConfig) == len(scheduler_registry.SCHEDULER_REGISTRY)


@pytest.mark.live
async def test_seeded_profile_model_matches_db_row(db_session: AsyncSession) -> None:
    """store 真实库合并读取：resolver 返回的 model 与 DB 播种行一致。"""
    row = (
        await db_session.execute(
            select(AiModelProfile).where(AiModelProfile.profile == "agent")
        )
    ).scalars().one()
    config = get_profile_config("agent")
    assert config["model"] == row.config["model"]
    assert config["base_url"]  # 网关非空


@pytest.mark.live
async def test_scenario_stores_enabled_and_warmup_ok() -> None:
    """两个场景默认启用；warmup 真实库预热不抛错。"""
    await ai_store.warmup()
    await scenario_store.warmup()
    for info in scenario_registry.iter_scenarios():
        assert scenario_store.is_enabled(info.scenario) is True
        assert scenario_store.get_effective_profile(info.scenario) == "agent"
