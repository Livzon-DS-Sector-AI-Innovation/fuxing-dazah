"""混装容器业务规则测试。

覆盖：
- 容器 CRUD：创建/列表/更新/删除（有流水拒删）
- 产出混装：选容器入库，line_id 自动取容器产线；类型不匹配拒绝
- 消耗混装：容器库存校验、超耗拦截、类型不匹配拒绝、output_id/container_id 二选一
- 混装与精确共存
- 流水：movement 带容器名、summary 容器余量、容器名筛选
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production import repository as repo
from app.modules.production.models import MixingContainer  # noqa: F401
from app.modules.production.schemas import (
    BatchCreate,
    ExecutionCompleteIn,
    ExecutionStartIn,
    IntermediateConsumptionIn,
    IntermediateOutputIn,
    IntermediateTypeCreate,
    LineCreate,
    MixingContainerCreate,
)
from app.modules.production.service import (
    batch_service,
    container_service,
    execution_service,
    intermediate_service,
    line_service,
)
from app.platform.identity.models import User
from tests.modules.production.conftest import rand_code


async def _make_line(db: AsyncSession) -> Any:
    return await line_service.create_line(
        db, LineCreate(name=rand_code("产线")), None,
    )


async def _make_im_type(db: AsyncSession) -> Any:
    return await intermediate_service.create_intermediate_type(
        db,
        IntermediateTypeCreate(code=rand_code("IM"), name=rand_code("中间体")),
        None,
    )


async def _make_batch(db: AsyncSession, ctx: dict[str, Any]) -> Any:
    return await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ),
        user=None,
    )


async def _make_container(
    db: AsyncSession, im_type: Any, line: Any, name: str | None = None,
) -> Any:
    return await container_service.create_container(
        db,
        MixingContainerCreate(
            name=name or rand_code("容器"),
            intermediate_type_id=im_type.id,
            line_id=line.id,
        ),
        None,
    )


@pytest.fixture(autouse=True)
def _mock_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock 权限查询为管理员，绕开 Redis 依赖。"""

    async def fake_perms(_uid: str, _db: AsyncSession) -> set[str]:
        return {"production:batch:submit"}

    monkeypatch.setattr(execution_service, "get_user_permissions", fake_perms)


class TestContainerCrud:

    async def test_create_and_list(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        im_type = await _make_im_type(db_session)
        line = await _make_line(db_session)
        ct = await _make_container(db_session, im_type, line)
        assert ct.intermediate_type_name == im_type.name
        assert ct.line_name == line.name
        listed = await container_service.list_containers(db_session, im_type.id)
        assert len(listed) == 1 and listed[0].id == ct.id

    async def test_delete_rejected_with_flows(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """已有出入库记录的容器不可删除。"""
        im_type = await _make_im_type(db_session)
        line = await _make_line(db_session)
        await line_service.bind_user_line(
            db_session, user_id=test_user.id, line_id=line.id,
            created_by=test_user.id,
        )
        ct = await _make_container(db_session, im_type, line)
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=test_user,
        )
        await execution_service.complete_execution(
            db_session, ex.id,
            ExecutionCompleteIn(
                intermediate_outputs=[
                    IntermediateOutputIn(
                        intermediate_type_id=im_type.id,
                        quantity=100, unit="L", container_id=ct.id,
                    ),
                ],
            ),
            user=test_user,
        )
        with pytest.raises(AppException) as ei:
            await container_service.delete_container(db_session, ct.id, test_user)
        assert "已有出入库记录" in str(ei.value.message)

    async def test_delete_empty_container_ok(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        im_type = await _make_im_type(db_session)
        line = await _make_line(db_session)
        ct = await _make_container(db_session, im_type, line)
        await container_service.delete_container(db_session, ct.id, None)
        assert await repo.get_mixing_container(db_session, ct.id) is None


class TestMixOutput:

    async def test_complete_with_container_output(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """产出选容器：container_id 落库，line_id 自动取容器产线，无需传 payload.line_id。"""
        im_type = await _make_im_type(db_session)
        line = await _make_line(db_session)
        await line_service.bind_user_line(
            db_session, user_id=test_user.id, line_id=line.id,
            created_by=test_user.id,
        )
        ct = await _make_container(db_session, im_type, line)
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=test_user,
        )
        await execution_service.complete_execution(
            db_session, ex.id,
            ExecutionCompleteIn(
                intermediate_outputs=[
                    IntermediateOutputIn(
                        intermediate_type_id=im_type.id,
                        quantity=100, unit="L", container_id=ct.id,
                    ),
                ],
            ),
            user=test_user,
        )
        outputs = await repo.get_intermediate_outputs_by_batch(db_session, batch.id)
        assert outputs[0].container_id == ct.id
        assert outputs[0].line_id == line.id
        assert await container_service.get_container_stock(db_session, ct.id) == 100

    async def test_output_container_type_mismatch_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        im_type = await _make_im_type(db_session)
        other_type = await _make_im_type(db_session)
        line = await _make_line(db_session)
        await line_service.bind_user_line(
            db_session, user_id=test_user.id, line_id=line.id,
            created_by=test_user.id,
        )
        ct = await _make_container(db_session, other_type, line)
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=test_user,
        )
        with pytest.raises(AppException) as ei:
            await execution_service.complete_execution(
                db_session, ex.id,
                ExecutionCompleteIn(
                    intermediate_outputs=[
                        IntermediateOutputIn(
                            intermediate_type_id=im_type.id,
                            quantity=100, unit="L", container_id=ct.id,
                        ),
                    ],
                ),
                user=test_user,
            )
        assert "类型不匹配" in str(ei.value.message)


class TestMixConsumption:

    async def _setup_stock(
        self, db: AsyncSession, ctx: dict[str, Any], user: User,
        quantity: float = 100,
    ) -> tuple[Any, Any, Any]:
        """准备：类型、产线（用户绑定）、容器、产出落入容器。返回 (im_type, line, ct)。"""
        im_type = await _make_im_type(db)
        line = await _make_line(db)
        await line_service.bind_user_line(
            db, user_id=user.id, line_id=line.id, created_by=user.id,
        )
        ct = await _make_container(db, im_type, line)
        batch = await _make_batch(db, ctx)
        ex = await execution_service.start_execution(
            db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=user,
        )
        await execution_service.complete_execution(
            db, ex.id,
            ExecutionCompleteIn(
                intermediate_outputs=[
                    IntermediateOutputIn(
                        intermediate_type_id=im_type.id,
                        quantity=quantity, unit="L", container_id=ct.id,
                    ),
                ],
            ),
            user=user,
        )
        return im_type, line, ct

    async def test_consume_from_container_ok(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        im_type, _line, ct = await self._setup_stock(db_session, published_route, test_user)
        batch = await _make_batch(db_session, published_route)
        await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id,
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=im_type.id,
                        container_id=ct.id, quantity=40, unit="L",
                    ),
                ],
            ),
            user=test_user,
        )
        consumptions = await repo.get_intermediate_consumptions_by_batch(
            db_session, batch.id,
        )
        assert len(consumptions) == 1
        assert consumptions[0].container_id == ct.id
        assert consumptions[0].output_id is None
        assert await container_service.get_container_stock(db_session, ct.id) == 60

    async def test_consume_over_stock_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        im_type, _line, ct = await self._setup_stock(db_session, published_route, test_user)
        batch = await _make_batch(db_session, published_route)
        with pytest.raises(AppException) as ei:
            await execution_service.start_execution(
                db_session, batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_a"].id,
                    intermediate_consumptions=[
                        IntermediateConsumptionIn(
                            intermediate_type_id=im_type.id,
                            container_id=ct.id, quantity=150, unit="L",
                        ),
                    ],
                ),
                user=test_user,
            )
        assert "超出混装容器" in str(ei.value.message)

    async def test_consume_type_mismatch_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        im_type, _line, ct = await self._setup_stock(db_session, published_route, test_user)
        other_type = await _make_im_type(db_session)
        batch = await _make_batch(db_session, published_route)
        with pytest.raises(AppException) as ei:
            await execution_service.start_execution(
                db_session, batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_a"].id,
                    intermediate_consumptions=[
                        IntermediateConsumptionIn(
                            intermediate_type_id=other_type.id,
                            container_id=ct.id, quantity=10, unit="L",
                        ),
                    ],
                ),
                user=test_user,
            )
        assert "类型不匹配" in str(ei.value.message)

    async def test_consume_requires_exactly_one_source(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        im_type, _line, ct = await self._setup_stock(db_session, published_route, test_user)
        batch = await _make_batch(db_session, published_route)
        # 都不填
        with pytest.raises(AppException) as ei:
            await execution_service.start_execution(
                db_session, batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_a"].id,
                    intermediate_consumptions=[
                        IntermediateConsumptionIn(
                            intermediate_type_id=im_type.id, quantity=10, unit="L",
                        ),
                    ],
                ),
                user=test_user,
            )
        assert "必须且只能" in str(ei.value.message)
        # 都填
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session, batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_a"].id,
                    intermediate_consumptions=[
                        IntermediateConsumptionIn(
                            intermediate_type_id=im_type.id,
                            container_id=ct.id,
                            output_id=uuid.uuid4(),
                            quantity=10, unit="L",
                        ),
                    ],
                ),
                user=test_user,
            )

    async def test_container_output_excluded_from_precise_available(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """混装入库的产出不进入精确批次选择（只能经容器取用，防双重记账）。"""
        im_type, _line, ct = await self._setup_stock(db_session, published_route, test_user)
        available = await intermediate_service.get_available_outputs(
            db_session, im_type.id, user_id=test_user.id,
        )
        assert all(o.container_id is None for o in available)
        # 精确产出的批次仍正常出现
        batch2 = await _make_batch(db_session, published_route)
        ex2 = await execution_service.start_execution(
            db_session, batch2.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=test_user,
        )
        line = await line_service.create_line(db_session, LineCreate(name=rand_code("产线")), None)
        await line_service.bind_user_line(
            db_session, user_id=test_user.id, line_id=line.id,
            created_by=test_user.id,
        )
        await execution_service.complete_execution(
            db_session, ex2.id,
            ExecutionCompleteIn(
                intermediate_outputs=[
                    IntermediateOutputIn(
                        intermediate_type_id=im_type.id,
                        quantity=50, unit="L",
                    ),
                ],
                line_id=line.id,
            ),
            user=test_user,
        )
        available2 = await intermediate_service.get_available_outputs(
            db_session, im_type.id, user_id=test_user.id,
        )
        precise_ids = {o.id for o in available2}
        outputs_b2 = await repo.get_intermediate_outputs_by_batch(db_session, batch2.id)
        assert outputs_b2[0].id in precise_ids
        assert ct.id not in precise_ids  # 容器产出不在批次列表

    async def test_mixed_and_precise_coexist(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """同一批次既从容器混装消耗，也精确消耗独立批次。"""
        im_type, line, ct = await self._setup_stock(db_session, published_route, test_user)
        # 精确批次：另一批次产出（不选容器）
        batch2 = await _make_batch(db_session, published_route)
        ex2 = await execution_service.start_execution(
            db_session, batch2.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=test_user,
        )
        await execution_service.complete_execution(
            db_session, ex2.id,
            ExecutionCompleteIn(
                intermediate_outputs=[
                    IntermediateOutputIn(
                        intermediate_type_id=im_type.id,
                        quantity=50, unit="L",
                    ),
                ],
                line_id=line.id,
            ),
            user=test_user,
        )
        precise = (await repo.get_intermediate_outputs_by_batch(db_session, batch2.id))[0]
        batch3 = await _make_batch(db_session, published_route)
        await execution_service.start_execution(
            db_session, batch3.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id,
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=im_type.id,
                        container_id=ct.id, quantity=20, unit="L",
                    ),
                    IntermediateConsumptionIn(
                        intermediate_type_id=im_type.id,
                        output_id=precise.id, quantity=10, unit="L",
                    ),
                ],
            ),
            user=test_user,
        )
        assert await container_service.get_container_stock(db_session, ct.id) == 80


class TestMovements:

    async def test_movements_container_fields_and_filter(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        im_type, line, ct = await self._setup_stock_for_movements(
            db_session, published_route, test_user,
        )
        result = await intermediate_service.get_material_movements(
            db_session, im_type.id,
        )
        outs = [m for m in result.movements if m.type == "output"]
        assert outs[0].container_name == ct.name
        stocks = {s.container_name: s.available_quantity for s in result.summary.container_stocks}
        assert stocks[ct.name] == 100
        # 按容器名筛选
        filtered = await intermediate_service.get_material_movements(
            db_session, im_type.id, container_name=ct.name,
        )
        assert all(m.container_name == ct.name for m in filtered.movements)
        assert len(filtered.movements) == len(result.movements)
        # 筛选不到
        none_hit = await intermediate_service.get_material_movements(
            db_session, im_type.id, container_name="不存在的容器",
        )
        assert none_hit.movements == []

    async def _setup_stock_for_movements(
        self, db: AsyncSession, ctx: dict[str, Any], user: User,
    ) -> tuple[Any, Any, Any]:
        im_type = await _make_im_type(db)
        line = await _make_line(db)
        await line_service.bind_user_line(
            db, user_id=user.id, line_id=line.id, created_by=user.id,
        )
        ct = await _make_container(db, im_type, line)
        batch = await _make_batch(db, ctx)
        ex = await execution_service.start_execution(
            db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=user,
        )
        await execution_service.complete_execution(
            db, ex.id,
            ExecutionCompleteIn(
                intermediate_outputs=[
                    IntermediateOutputIn(
                        intermediate_type_id=im_type.id,
                        quantity=100, unit="L", container_id=ct.id,
                    ),
                ],
            ),
            user=user,
        )
        return im_type, line, ct
