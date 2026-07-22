"""故障三码域(故障现象 / 故障原因 / 维修措施)测试。

覆盖泛型 CRUD 的 service / repository 三层对 FailureSymptom / FailureCause /
FailureAction 三种 model 的行为,以及故障码 REST API。断言以业务规则为准:
- 泛型 CRUD:create / get / list / update / delete(软删)。
- repository exists_by_code(含 exclude_id 排除自身、忽略软删记录)。
- 软删重建:同 code 软删后可再次创建(partial unique `code WHERE is_deleted=false`)。
- API 层:创建 / 修改 / 删除使用 equipment:maintenance:update 权限(conftest autouse 放行)。

本文件从 test_maintenance_service / test_maintenance_api / test_maintenance_repository
中三处高度重复的故障码用例合并去重而来,并补全软删重建等缺口。
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment import service
from app.modules.equipment.models import FailureAction, FailureCause, FailureSymptom
from app.modules.equipment.schemas import FailureCodeCreate, FailureCodeUpdate

FailureModelType = type[FailureSymptom | FailureCause | FailureAction]

# 泛型 CRUD 须对三种 model 一致成立,统一参数化。
_MODELS = pytest.mark.parametrize(
    "model_class",
    [FailureSymptom, FailureCause, FailureAction],
    ids=["symptom", "cause", "action"],
)

# API 路由前缀与三条子路径。
_API_BASE = "/api/v1/equipment/maintenance/failure-codes"
_PATHS = pytest.mark.parametrize(
    "path",
    ["symptoms", "causes", "actions"],
)


def _code(prefix: str = "CODE") -> str:
    """生成带随机后缀的故障码,避免共享 Postgres 唯一键冲突。"""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ==================== Service 层泛型 CRUD ====================


@_MODELS
async def test_service_create_success(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """成功创建故障码,回填 id 与字段。"""
    code = _code("NOISE")
    result = await service.create_failure_code(
        db_session,
        model_class,
        FailureCodeCreate(code=code, name="异响", sort_order=1),
    )
    assert result.id is not None
    assert result.code == code
    assert result.name == "异响"
    assert result.sort_order == 1


@_MODELS
async def test_service_create_duplicate_raises(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """同 code 重复创建应抛 DuplicateException。"""
    code = _code("DUP")
    await service.create_failure_code(
        db_session, model_class, FailureCodeCreate(code=code, name="异响")
    )
    with pytest.raises(DuplicateException):
        await service.create_failure_code(
            db_session, model_class, FailureCodeCreate(code=code, name="异响")
        )


@_MODELS
async def test_service_get_by_id_success(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """按 id 获取已创建的故障码。"""
    code = _code("GET")
    created = await service.create_failure_code(
        db_session, model_class, FailureCodeCreate(code=code, name="异响")
    )
    result = await service.get_failure_code_by_id(
        db_session, model_class, created.id
    )
    assert result.id == created.id
    assert result.code == code


@_MODELS
async def test_service_get_by_id_not_found_raises(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """获取不存在的故障码应抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await service.get_failure_code_by_id(db_session, model_class, uuid.uuid4())


@_MODELS
async def test_service_get_list(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """列表返回全部未删除故障码。"""
    await service.create_failure_code(
        db_session, model_class, FailureCodeCreate(code=_code("A"), name="异响")
    )
    await service.create_failure_code(
        db_session, model_class, FailureCodeCreate(code=_code("B"), name="泄漏")
    )
    codes = await service.get_failure_codes(db_session, model_class)
    assert len(codes) >= 2


@_MODELS
async def test_service_update_success(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """更新 name / sort_order,未传的 code 保持不变。"""
    code = _code("UPD")
    created = await service.create_failure_code(
        db_session, model_class, FailureCodeCreate(code=code, name="异响", sort_order=1)
    )
    updated = await service.update_failure_code(
        db_session,
        model_class,
        created.id,
        FailureCodeUpdate(name="异常噪音", sort_order=2),
    )
    assert updated.name == "异常噪音"
    assert updated.sort_order == 2
    assert updated.code == code


@_MODELS
async def test_service_delete_soft(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """删除为软删:返回 True,随后再查抛 NotFoundException。"""
    created = await service.create_failure_code(
        db_session, model_class, FailureCodeCreate(code=_code("DEL"), name="异响")
    )
    assert await service.delete_failure_code(db_session, model_class, created.id) is True
    with pytest.raises(NotFoundException):
        await service.get_failure_code_by_id(db_session, model_class, created.id)


@_MODELS
async def test_service_soft_delete_then_recreate_same_code(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """软删后同 code 应可重新创建(partial unique 仅约束未删除行)。"""
    code = _code("REBUILD")
    created = await service.create_failure_code(
        db_session, model_class, FailureCodeCreate(code=code, name="旧")
    )
    await service.delete_failure_code(db_session, model_class, created.id)
    recreated = await service.create_failure_code(
        db_session, model_class, FailureCodeCreate(code=code, name="新")
    )
    assert recreated.id != created.id
    assert recreated.code == code
    assert recreated.name == "新"


async def test_service_update_to_existing_code_raises(
    db_session: AsyncSession,
) -> None:
    """把 code 改成另一条已存在故障码的 code 应抛 DuplicateException。"""
    code_a = _code("A")
    code_b = _code("B")
    await service.create_failure_code(
        db_session, FailureSymptom, FailureCodeCreate(code=code_a, name="甲")
    )
    other = await service.create_failure_code(
        db_session, FailureSymptom, FailureCodeCreate(code=code_b, name="乙")
    )
    with pytest.raises(DuplicateException):
        await service.update_failure_code(
            db_session, FailureSymptom, other.id, FailureCodeUpdate(code=code_a)
        )


async def test_service_update_same_code_allowed(
    db_session: AsyncSession,
) -> None:
    """更新时把 code 设为自身原值不算重复(exclude_id 排除自身)。"""
    code = _code("SELF")
    created = await service.create_failure_code(
        db_session, FailureSymptom, FailureCodeCreate(code=code, name="异响")
    )
    updated = await service.update_failure_code(
        db_session,
        FailureSymptom,
        created.id,
        FailureCodeUpdate(code=code, name="异常噪音"),
    )
    assert updated.code == code
    assert updated.name == "异常噪音"


async def test_service_update_not_found_raises(
    db_session: AsyncSession,
) -> None:
    """更新不存在的故障码应抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await service.update_failure_code(
            db_session, FailureSymptom, uuid.uuid4(), FailureCodeUpdate(name="x")
        )


# ==================== Repository 层 ====================


@_MODELS
async def test_repo_create(
    db_session: AsyncSession, model_class: FailureModelType
) -> None:
    """repository 直接以 dict 创建,回填 id。"""
    code = _code("REPO")
    result = await repo.create_failure_code(
        db_session, model_class, {"code": code, "name": "异响", "sort_order": 1}
    )
    assert result.id is not None
    assert result.code == code
    assert result.name == "异响"


async def test_repo_get_by_id_not_found_returns_none(
    db_session: AsyncSession,
) -> None:
    """repository 查不到返回 None(不抛异常)。"""
    result = await repo.get_failure_code_by_id(
        db_session, FailureSymptom, uuid.uuid4()
    )
    assert result is None


async def test_repo_get_list_ordered_by_sort_order(
    db_session: AsyncSession,
) -> None:
    """列表按 sort_order 升序:sort_order 小的排在前。"""
    prefix = uuid.uuid4().hex[:8].upper()
    high = await repo.create_failure_code(
        db_session, FailureSymptom, {"code": f"H-{prefix}", "name": "后", "sort_order": 9}
    )
    low = await repo.create_failure_code(
        db_session, FailureSymptom, {"code": f"L-{prefix}", "name": "前", "sort_order": 1}
    )
    codes = await repo.get_failure_codes(db_session, FailureSymptom)
    ids = [c.id for c in codes]
    assert ids.index(low.id) < ids.index(high.id)


async def test_repo_exists_by_code(
    db_session: AsyncSession,
) -> None:
    """exists_by_code:命中返回 True,未命中返回 False。"""
    code = _code("EXIST")
    await repo.create_failure_code(
        db_session, FailureSymptom, {"code": code, "name": "异响"}
    )
    assert await repo.exists_failure_code_by_code(db_session, FailureSymptom, code) is True
    assert (
        await repo.exists_failure_code_by_code(db_session, FailureSymptom, _code("NONE"))
        is False
    )


async def test_repo_exists_by_code_exclude_id(
    db_session: AsyncSession,
) -> None:
    """exclude_id 排除自身后,仅剩自己那条则视为不存在。"""
    code = _code("EXCL")
    created = await repo.create_failure_code(
        db_session, FailureSymptom, {"code": code, "name": "异响"}
    )
    assert (
        await repo.exists_failure_code_by_code(
            db_session, FailureSymptom, code, exclude_id=created.id
        )
        is False
    )


async def test_repo_exists_ignores_soft_deleted(
    db_session: AsyncSession,
) -> None:
    """软删后 exists_by_code 应返回 False(仅统计未删除行)。"""
    code = _code("SOFT")
    created = await repo.create_failure_code(
        db_session, FailureSymptom, {"code": code, "name": "异响"}
    )
    await repo.delete_failure_code(db_session, FailureSymptom, created.id)
    assert (
        await repo.exists_failure_code_by_code(db_session, FailureSymptom, code) is False
    )


async def test_repo_update(
    db_session: AsyncSession,
) -> None:
    """repository 以 dict 更新字段。"""
    created = await repo.create_failure_code(
        db_session, FailureSymptom, {"code": _code("RU"), "name": "异响"}
    )
    updated = await repo.update_failure_code(
        db_session, FailureSymptom, created.id, {"name": "异常噪音"}
    )
    assert updated is not None
    assert updated.name == "异常噪音"


async def test_repo_delete_soft(
    db_session: AsyncSession,
) -> None:
    """软删返回 True,随后按 id 查为 None。"""
    created = await repo.create_failure_code(
        db_session, FailureSymptom, {"code": _code("RD"), "name": "异响"}
    )
    assert await repo.delete_failure_code(db_session, FailureSymptom, created.id) is True
    assert (
        await repo.get_failure_code_by_id(db_session, FailureSymptom, created.id) is None
    )


async def test_repo_soft_delete_then_recreate_same_code(
    db_session: AsyncSession,
) -> None:
    """repository 层:软删后同 code 可再次插入(partial unique 仅约束未删除行)。"""
    code = _code("RREBUILD")
    created = await repo.create_failure_code(
        db_session, FailureSymptom, {"code": code, "name": "旧"}
    )
    await repo.delete_failure_code(db_session, FailureSymptom, created.id)
    recreated = await repo.create_failure_code(
        db_session, FailureSymptom, {"code": code, "name": "新"}
    )
    assert recreated.id != created.id
    assert recreated.code == code


# ==================== API 层 ====================


@_PATHS
async def test_api_create(client: AsyncClient, path: str) -> None:
    """三条子路径均可创建,回显字段。"""
    code = _code("API")
    response = await client.post(
        f"{_API_BASE}/{path}",
        json={"code": code, "name": "异响", "sort_order": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["data"]["code"] == code
    assert data["data"]["name"] == "异响"


async def test_api_list(client: AsyncClient) -> None:
    """列表接口返回已创建的故障码。"""
    uid = uuid.uuid4().hex[:8].upper()
    await client.post(
        f"{_API_BASE}/symptoms", json={"code": f"NOISE-{uid}", "name": "异响"}
    )
    await client.post(
        f"{_API_BASE}/symptoms", json={"code": f"LEAK-{uid}", "name": "泄漏"}
    )
    response = await client.get(f"{_API_BASE}/symptoms")
    assert response.status_code == 200
    assert len(response.json()["data"]) >= 2


async def test_api_get_one(client: AsyncClient) -> None:
    """按 id 查询单个故障码。"""
    code = _code("ONE")
    created = await client.post(
        f"{_API_BASE}/symptoms", json={"code": code, "name": "异响"}
    )
    code_id = created.json()["data"]["id"]
    response = await client.get(f"{_API_BASE}/symptoms/{code_id}")
    assert response.status_code == 200
    assert response.json()["data"]["code"] == code


async def test_api_update(client: AsyncClient) -> None:
    """修改故障码 name。"""
    created = await client.post(
        f"{_API_BASE}/symptoms", json={"code": _code("UPD"), "name": "异响"}
    )
    code_id = created.json()["data"]["id"]
    response = await client.put(
        f"{_API_BASE}/symptoms/{code_id}", json={"name": "异常噪音"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "异常噪音"


async def test_api_delete(client: AsyncClient) -> None:
    """删除故障码返回成功,再查为 404。"""
    created = await client.post(
        f"{_API_BASE}/symptoms", json={"code": _code("DEL"), "name": "异响"}
    )
    code_id = created.json()["data"]["id"]
    response = await client.delete(f"{_API_BASE}/symptoms/{code_id}")
    assert response.status_code == 200
    assert (await client.get(f"{_API_BASE}/symptoms/{code_id}")).status_code == 404


async def test_api_create_duplicate_returns_409(client: AsyncClient) -> None:
    """同 code 重复创建返回 409。"""
    code = _code("DUP")
    payload = {"code": code, "name": "异响"}
    assert (await client.post(f"{_API_BASE}/symptoms", json=payload)).status_code == 200
    dup = await client.post(f"{_API_BASE}/symptoms", json=payload)
    assert dup.status_code == 409
    assert dup.json()["code"] == 409


async def test_api_get_not_found_returns_404(client: AsyncClient) -> None:
    """查询不存在故障码返回 404。"""
    response = await client.get(f"{_API_BASE}/symptoms/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_api_update_not_found_returns_404(client: AsyncClient) -> None:
    """更新不存在故障码返回 404。"""
    response = await client.put(
        f"{_API_BASE}/symptoms/{uuid.uuid4()}", json={"name": "x"}
    )
    assert response.status_code == 404
