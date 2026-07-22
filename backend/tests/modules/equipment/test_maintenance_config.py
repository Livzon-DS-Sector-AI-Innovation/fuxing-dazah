"""维护配置域(抢单超时 / 计划提前天数)测试。

覆盖 service 层(get/update claim-timeout、advance-days)、repository 层
(get_configs / upsert_configs)以及 HTTP API。断言以业务规则为准,而非照抄
app 现有实现。

共享 Postgres 说明:maintenance_config.config_key 是硬唯一约束;所有用例走
db_session / client(均在测试结束回滚),不落库。repository 裸测用随机 key
额外规避冲突。
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment import repository as repo
from app.modules.equipment import service
from app.modules.equipment.models.maintenance_config import MaintenanceConfig
from app.modules.equipment.schemas import (
    AdvanceDaysUpdateRequest,
    ClaimTimeoutUpdateRequest,
)

CLAIM_TIMEOUT_URL = "/api/v1/equipment/maintenance/config/claim-timeout"
ADVANCE_DAYS_URL = "/api/v1/equipment/maintenance/config/advance-days"

_TIMEOUT_KEYS = [
    "claim_timeout_emergency",
    "claim_timeout_high",
    "claim_timeout_medium",
    "claim_timeout_low",
]


ADVANCE_DAYS_KEY = "maintenance_plan_advance_days"
AUTO_EXECUTE_KEY = "maintenance_plan_auto_execute"


def _rand_key() -> str:
    """生成随机配置键,避免共享库硬唯一约束冲突。"""
    return f"test_cfg_{uuid.uuid4().hex[:12]}"


async def _clear_keys(db: AsyncSession, keys: list[str]) -> None:
    """在当前事务内清除指定配置键(硬删),模拟空库。

    共享 Postgres 可能已有他人提交的配置行,直接断言"空库默认值"会被污染。
    事务级删除仅在本用例可见,db_session/client 回滚后原数据完好。
    """
    await db.execute(
        delete(MaintenanceConfig).where(MaintenanceConfig.config_key.in_(keys))
    )
    await db.flush()


# ----------------------------- service: claim-timeout -----------------------


async def test_get_claim_timeout_returns_defaults_on_empty_db(
    db_session: AsyncSession,
) -> None:
    """空库时抢单超时返回默认:紧急15/高30/中60/低120(分钟)。"""
    await _clear_keys(db_session, _TIMEOUT_KEYS)
    config = await service.get_claim_timeout_config(db_session)

    assert config.emergency == 15
    assert config.high == 30
    assert config.medium == 60
    assert config.low == 120


async def test_update_claim_timeout_partial_keeps_defaults_for_unset(
    db_session: AsyncSession,
) -> None:
    """空库上只更新 emergency,其余字段应回落到各自默认值。"""
    await _clear_keys(db_session, _TIMEOUT_KEYS)
    result = await service.update_claim_timeout_config(
        db_session, ClaimTimeoutUpdateRequest(emergency=10)
    )

    assert result.emergency == 10
    assert result.high == 30
    assert result.medium == 60
    assert result.low == 120


async def test_update_claim_timeout_partial_preserves_existing(
    db_session: AsyncSession,
) -> None:
    """先写入四项,再仅更新 emergency,其余三项须保持原有值而非默认。"""
    await service.update_claim_timeout_config(
        db_session,
        ClaimTimeoutUpdateRequest(emergency=11, high=22, medium=33, low=44),
    )

    result = await service.update_claim_timeout_config(
        db_session, ClaimTimeoutUpdateRequest(emergency=99)
    )

    assert result.emergency == 99
    assert result.high == 22
    assert result.medium == 33
    assert result.low == 44


async def test_update_claim_timeout_roundtrip(
    db_session: AsyncSession,
) -> None:
    """更新四项后重新读回,数值应完全一致(往返一致)。"""
    await service.update_claim_timeout_config(
        db_session,
        ClaimTimeoutUpdateRequest(emergency=5, high=25, medium=50, low=100),
    )

    reread = await service.get_claim_timeout_config(db_session)

    assert (reread.emergency, reread.high, reread.medium, reread.low) == (
        5,
        25,
        50,
        100,
    )


async def test_update_claim_timeout_all_none_is_noop(
    db_session: AsyncSession,
) -> None:
    """全 None 请求不应写入任何行,返回值等于默认。"""
    await _clear_keys(db_session, _TIMEOUT_KEYS)
    result = await service.update_claim_timeout_config(
        db_session, ClaimTimeoutUpdateRequest()
    )

    assert (result.emergency, result.high, result.medium, result.low) == (
        15,
        30,
        60,
        120,
    )
    count = await db_session.scalar(
        select(func.count())
        .select_from(MaintenanceConfig)
        .where(MaintenanceConfig.config_key.in_(_TIMEOUT_KEYS))
    )
    assert count == 0


# ----------------------------- service: advance-days ------------------------


async def test_get_advance_days_defaults_to_zero(
    db_session: AsyncSession,
) -> None:
    """空库时维护计划提前创建天数默认 0，自动执行默认 True。"""
    await _clear_keys(db_session, [ADVANCE_DAYS_KEY, AUTO_EXECUTE_KEY])
    config = await service.get_advance_days_config(db_session)

    assert config.advance_days == 0
    assert config.auto_execute is True


async def test_update_advance_days_roundtrip(
    db_session: AsyncSession,
) -> None:
    """更新提前天数后读回应一致(upsert + 往返一致)。"""
    await service.update_advance_days_config(
        db_session, AdvanceDaysUpdateRequest(advance_days=7)
    )

    reread = await service.get_advance_days_config(db_session)

    assert reread.advance_days == 7


async def test_update_auto_execute_roundtrip(
    db_session: AsyncSession,
) -> None:
    """关闭自动执行后读回应为 False，再开启读回 True。"""
    await service.update_advance_days_config(
        db_session, AdvanceDaysUpdateRequest(advance_days=0, auto_execute=False)
    )
    assert (await service.get_advance_days_config(db_session)).auto_execute is False

    await service.update_advance_days_config(
        db_session, AdvanceDaysUpdateRequest(advance_days=0, auto_execute=True)
    )
    assert (await service.get_advance_days_config(db_session)).auto_execute is True


async def test_update_advance_days_upsert_overwrites(
    db_session: AsyncSession,
) -> None:
    """二次更新提前天数应覆盖旧值,而非新增另一行。"""
    await service.update_advance_days_config(
        db_session, AdvanceDaysUpdateRequest(advance_days=3)
    )
    result = await service.update_advance_days_config(
        db_session, AdvanceDaysUpdateRequest(advance_days=9)
    )

    assert result.advance_days == 9
    count = await db_session.scalar(
        select(func.count())
        .select_from(MaintenanceConfig)
        .where(MaintenanceConfig.config_key == "maintenance_plan_advance_days")
    )
    assert count == 1


# ----------------------------- repository -----------------------------------


async def test_get_configs_missing_keys_returns_empty_dict(
    db_session: AsyncSession,
) -> None:
    """查询不存在的键返回空 dict。"""
    result = await repo.get_configs(db_session, [_rand_key(), _rand_key()])

    assert result == {}


async def test_upsert_configs_inserts_new_keys(
    db_session: AsyncSession,
) -> None:
    """upsert 新键后 get_configs 应能读到对应字符串值。"""
    key_a, key_b = _rand_key(), _rand_key()

    await repo.upsert_configs(db_session, {key_a: "100", key_b: "200"})
    result = await repo.get_configs(db_session, [key_a, key_b])

    assert result == {key_a: "100", key_b: "200"}


async def test_upsert_configs_updates_existing_without_duplicate(
    db_session: AsyncSession,
) -> None:
    """对已存在键 upsert 应原地更新值,不产生重复行。"""
    key = _rand_key()
    await repo.upsert_configs(db_session, {key: "1"})

    await repo.upsert_configs(db_session, {key: "2"})

    result = await repo.get_configs(db_session, [key])
    assert result == {key: "2"}
    count = await db_session.scalar(
        select(func.count())
        .select_from(MaintenanceConfig)
        .where(MaintenanceConfig.config_key == key)
    )
    assert count == 1


async def test_upsert_configs_only_touches_given_keys(
    db_session: AsyncSession,
) -> None:
    """upsert 部分键不应影响 dict 之外的既有键。"""
    key_keep, key_new = _rand_key(), _rand_key()
    await repo.upsert_configs(db_session, {key_keep: "keep"})

    await repo.upsert_configs(db_session, {key_new: "new"})

    result = await repo.get_configs(db_session, [key_keep, key_new])
    assert result == {key_keep: "keep", key_new: "new"}


# ----------------------------- API ------------------------------------------


async def test_api_get_claim_timeout_returns_defaults(
    client: AsyncClient,
    _equipment_session: AsyncSession,
) -> None:
    """GET /claim-timeout 空库返回默认配置。"""
    await _clear_keys(_equipment_session, _TIMEOUT_KEYS)
    response = await client.get(CLAIM_TIMEOUT_URL)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {"emergency": 15, "high": 30, "medium": 60, "low": 120}


async def test_api_put_claim_timeout_partial_merges(
    client: AsyncClient,
) -> None:
    """PUT /claim-timeout 部分字段更新,返回合并后的完整配置。"""
    response = await client.put(CLAIM_TIMEOUT_URL, json={"high": 45})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["high"] == 45
    assert data["emergency"] == 15
    assert data["medium"] == 60
    assert data["low"] == 120


async def test_api_put_claim_timeout_out_of_range_rejected(
    client: AsyncClient,
) -> None:
    """PUT /claim-timeout 超出 1-1440 范围应被校验拒绝(422)。"""
    response = await client.put(CLAIM_TIMEOUT_URL, json={"emergency": 0})

    assert response.status_code == 422


async def test_api_get_advance_days_returns_default_zero(
    client: AsyncClient,
    _equipment_session: AsyncSession,
) -> None:
    """GET /advance-days 空库返回默认 0。"""
    await _clear_keys(_equipment_session, [ADVANCE_DAYS_KEY])
    response = await client.get(ADVANCE_DAYS_URL)

    assert response.status_code == 200
    assert response.json()["data"]["advance_days"] == 0


async def test_api_put_advance_days_updates(
    client: AsyncClient,
) -> None:
    """PUT /advance-days 更新后返回新值。"""
    response = await client.put(ADVANCE_DAYS_URL, json={"advance_days": 14})

    assert response.status_code == 200
    assert response.json()["data"]["advance_days"] == 14


async def test_api_put_advance_days_zero_allowed(
    client: AsyncClient,
) -> None:
    """advance_days=0（当天触发）是合法可设置值，PUT 0 应 200 往返一致。"""
    response = await client.put(ADVANCE_DAYS_URL, json={"advance_days": 0})

    assert response.status_code == 200
    assert response.json()["data"]["advance_days"] == 0
