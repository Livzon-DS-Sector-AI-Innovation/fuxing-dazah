"""中间体物料台账业务逻辑测试。

覆盖业务场景：
- 批次产出查询：空批次返回空列表；产出记录含节点名、批号、中间体类型名
- 可用产出列表：按中间体类型过滤
- 批次消耗查询：消耗记录含来源批号；空批次返回空列表；
  消耗类型与产出源类型不匹配时拒绝（AppException）
- 中间体溯源：产出记录 + 下游消耗记录；不存在的产出记录抛 NotFoundException
- 出入库流水：产出物维度的全局出入库汇总（total_output/consumed/stock）；
  不存在的产出物抛 NotFoundException
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.production.schemas import (
    BatchCreate,
    ExecutionCompleteIn,
    ExecutionStartIn,
    IntermediateConsumptionIn,
    IntermediateOutputIn,
    IntermediateTypeCreate,
)
from app.modules.production.service import (
    batch_service,
    execution_service,
    intermediate_service,
)
from tests.modules.production.conftest import rand_code


async def _setup_output_chain(
    db: AsyncSession, ctx: dict[str, Any]
) -> dict[str, Any]:
    """辅助：创建中间体类型→批次→执行→产出记录，返回链条中各对象。"""
    im_type = await intermediate_service.create_intermediate_type(
        db,
        IntermediateTypeCreate(
            code=rand_code("IM"), name="发酵液", category="中间体",
            default_unit="L",
        ),
        user=None,
    )
    batch = await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ),
        user=None,
    )
    ex_a = await execution_service.start_execution(
        db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db, ex_a.id, ExecutionCompleteIn(
            intermediate_outputs=[
                IntermediateOutputIn(
                    intermediate_type_id=im_type.id, quantity=100, unit="L",
                ),
            ],
        ), user=None,
    )
    outputs = await intermediate_service.get_batch_outputs(db, batch.id)
    return {
        "im_type": im_type,
        "batch": batch,
        "execution": ex_a,
        "output": outputs[0],
    }


class TestBatchOutputs:
    async def test_empty_batch_returns_empty(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """无产出的批次查询产出记录返回空列表。"""
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )
        outputs = await intermediate_service.get_batch_outputs(
            db_session, batch.id,
        )
        assert outputs == []

    async def test_output_has_node_info(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """产出记录中 node_name、batch_no、intermediate_type_name 均正确填充。"""
        chain = await _setup_output_chain(db_session, published_route)
        assert chain["output"].node_name is not None
        assert chain["output"].batch_no is not None
        assert chain["output"].intermediate_type_name == "发酵液"

    async def test_available_outputs_filtered(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """按中间体类型过滤可用产出列表，所有返回记录的 intermediate_type_id 一致。"""
        chain = await _setup_output_chain(db_session, published_route)
        available = await intermediate_service.get_available_outputs(
            db_session, intermediate_type_id=chain["im_type"].id,
        )
        assert len(available) >= 1
        assert all(
            o.intermediate_type_id == chain["im_type"].id for o in available
        )


class TestBatchConsumptions:
    async def test_consumption_flow(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """开始执行时消耗上游产出，查询消耗记录含数量和来源批号。"""
        chain = await _setup_output_chain(db_session, published_route)
        batch2 = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )
        ex = await execution_service.start_execution(
            db_session,
            batch2.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id,
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=chain["im_type"].id,
                        output_id=chain["output"].id,
                        quantity=50,
                    ),
                ],
            ),
            user=None,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        consumptions = await intermediate_service.get_batch_consumptions(
            db_session, batch2.id,
        )
        assert len(consumptions) == 1
        assert consumptions[0].quantity == 50
        assert consumptions[0].output_batch_no is not None

    async def test_empty_consumptions(self, db_session: AsyncSession) -> None:
        """不存在的批次查询消耗记录返回空列表。"""
        result = await intermediate_service.get_batch_consumptions(
            db_session, uuid.uuid4(),
        )
        assert result == []

    async def test_consumption_type_mismatch_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """消耗类型 ID 与产出源的类型不匹配时抛出 AppException。"""
        chain = await _setup_output_chain(db_session, published_route)
        other_type = await intermediate_service.create_intermediate_type(
            db_session,
            IntermediateTypeCreate(
                code=rand_code("IM"), name="结晶粉", default_unit="kg",
            ),
            user=None,
        )
        batch2 = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )
        from app.core.exceptions import AppException
        with pytest.raises(AppException, match="类型不匹配"):
            await execution_service.start_execution(
                db_session,
                batch2.id,
                ExecutionStartIn(
                    node_id=published_route["node_a"].id,
                    intermediate_consumptions=[
                        IntermediateConsumptionIn(
                            intermediate_type_id=other_type.id,
                            output_id=chain["output"].id,
                            quantity=50,
                        ),
                    ],
                ),
                user=None,
            )


class TestMaterialTrace:
    async def test_trace_output_with_consumptions(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """追溯产出记录时返回产出信息及其下游消耗列表。"""
        chain = await _setup_output_chain(db_session, published_route)
        batch2 = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )
        ex = await execution_service.start_execution(
            db_session,
            batch2.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id,
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=chain["im_type"].id,
                        output_id=chain["output"].id,
                        quantity=30,
                    ),
                ],
            ),
            user=None,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        trace = await intermediate_service.trace_intermediate_output(
            db_session, chain["output"].id,
        )
        assert trace["output"].id == chain["output"].id
        assert len(trace["consumptions"]) >= 1

    async def test_trace_nonexistent_output_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """追溯不存在的产出记录抛出 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await intermediate_service.trace_intermediate_output(
                db_session, uuid.uuid4(),
            )


class TestMaterialMovements:
    async def test_movements_summary(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """出入库流水含汇总信息，total_output 和 current_stock 正确。"""
        chain = await _setup_output_chain(db_session, published_route)
        movements = await intermediate_service.get_material_movements(
            db_session, chain["im_type"].id,
        )
        assert movements.summary.total_output >= 100
        assert movements.summary.current_stock >= 100
        assert len(movements.movements) >= 1

    async def test_movements_nonexistent_material_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """不存在的产出物查询出入库流水抛出 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await intermediate_service.get_material_movements(
                db_session, uuid.uuid4(),
            )
