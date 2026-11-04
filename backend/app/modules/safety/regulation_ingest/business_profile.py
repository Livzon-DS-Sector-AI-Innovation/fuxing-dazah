"""企业业务画像聚合：静态基线（app_config 可改）+ safety 库轻量事实。

供 AI 判定（批量相关性）与适用性深度分析注入企业背景，替代原 prompt
硬编码画像。进程内 TTL 缓存；任何聚合失败降级为静态基线文本，绝不阻断
收录链（每条事实查询独立 SAVEPOINT，失败不污染外层事务）。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.app_config.store import store as app_config_store

logger = logging.getLogger(__name__)

PROFILE_TEXT_KEY = "SAFETY_BUSINESS_PROFILE_TEXT"
_CACHE_TTL_SECONDS = 3600.0

# 静态基线（原 ASSESS/BATCH prompt 硬编码内容，作为 DB 未配置时的默认）
DEFAULT_PROFILE_TEXT = (
    "- 行业：医药制造业（化学药品原料药制造）\n"
    "- 涉及领域：安全生产、职业健康、环境保护、消防安全、危化品管理、特种设备\n"
    "- 工厂位于福建省福州市"
)

# 各事实段条数上限（画像总长可控，避免 prompt 膨胀）
_MAX_CHEMICALS = 40
_MAX_EQUIPMENT = 30
_MAX_REGULATIONS = 30

_cache: dict[str, Any] = {"ts": 0.0, "text": ""}


def _static_text() -> str:
    return (app_config_store.get_str(PROFILE_TEXT_KEY, "") or DEFAULT_PROFILE_TEXT).strip()


def reset_profile_cache() -> None:
    """清空画像缓存（测试用；运营改画像配置后也无需等 TTL）。"""
    _cache.update(ts=0.0, text="")


async def get_business_profile(session: AsyncSession) -> str:
    """画像文本 = 静态基线 + 动态事实；动态段整体失败静默降级。"""
    now = time.monotonic()
    if _cache["text"] and now - _cache["ts"] < _CACHE_TTL_SECONDS:
        return _cache["text"]

    parts = [_static_text()]
    try:
        facts = await _collect_facts(session)
    except Exception:
        logger.warning("画像事实聚合整体失败（降级静态基线）", exc_info=True)
        facts = {}
    if facts.get("chemicals"):
        parts.append("- 在册危化品（示例）：" + "、".join(facts["chemicals"]))
    if facts.get("equipment"):
        parts.append("- 主要设备（示例）：" + "、".join(facts["equipment"]))
    if facts.get("hazard_factors"):
        parts.append("- 职业病危害因素：" + "、".join(facts["hazard_factors"]))
    if facts.get("operation_regulations"):
        parts.append("- 内部操作规程（示例）：" + "、".join(facts["operation_regulations"]))

    text = "\n".join(parts)
    _cache.update(ts=now, text=text)
    return text


async def _collect_facts(session: AsyncSession) -> dict[str, list[str]]:
    """四路轻量事实聚合，逐路独立容错（SAVEPOINT 防事务污染）。"""
    facts: dict[str, list[str]] = {}

    async def _safe_query(label: str, stmt) -> list[str]:
        try:
            async with session.begin_nested():
                rows = (await session.execute(stmt)).scalars().all()
            return [str(r).strip() for r in rows if r and str(r).strip()]
        except Exception:
            logger.warning("画像事实聚合失败（降级跳过）：%s", label, exc_info=True)
            return []

    from app.modules.safety.models.chemical_inventory import ChemicalInventoryRecord
    from app.modules.safety.models.occupational_health import OhHazardFactor
    from app.modules.safety.models.regulations import OperationRegulation

    facts["chemicals"] = sorted(await _safe_query(
        "chemicals",
        select(ChemicalInventoryRecord.material_name)
        .where(ChemicalInventoryRecord.is_deleted.is_(False))
        .distinct().limit(_MAX_CHEMICALS),
    ))
    facts["hazard_factors"] = sorted(await _safe_query(
        "hazard_factors",
        select(OhHazardFactor.factor_name)
        .where(OhHazardFactor.is_deleted.is_(False))
        .distinct(),
    ))
    facts["operation_regulations"] = await _safe_query(
        "operation_regulations",
        select(OperationRegulation.regulation_name)
        .where(OperationRegulation.is_deleted.is_(False))
        .limit(_MAX_REGULATIONS),
    )

    try:
        from app.modules.equipment.models.equipment import Equipment

        facts["equipment"] = await _safe_query(
            "equipment",
            select(Equipment.name)
            .where(Equipment.is_deleted.is_(False))
            .distinct().limit(_MAX_EQUIPMENT),
        )
    except ImportError:
        facts["equipment"] = []

    return facts
