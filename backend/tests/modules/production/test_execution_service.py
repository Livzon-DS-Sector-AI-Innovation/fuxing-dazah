"""节点执行业务规则测试。

覆盖业务场景：
- 开始执行：首次执行必须在起点/入口节点；起点执行推进批次状态为 in_progress；
  偏离执行标记 is_deviation；缺失必填字段拒绝；超范围数值标记 is_abnormal；
  非有限数值拒绝；中止后重做非偏离且 seq+1；同节点并行拒绝；
  设备快照写入；衍生批次可在 entry_node 开始
- 流水线重叠：allow_overlap 边允许前道 in_progress 时开始下游；
  批次边界边强制 completed；前道中止不可启动下游
- 完成/回流：缺失结束必填字段拒绝；回流边重做 seq 递增且非偏离
- 中止：进行中执行可中止，状态变为 aborted
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production import repository as repo
from app.modules.production.models import Batch
from app.modules.production.schemas import (
    BatchCreate,
    ChildBatchIn,
    DeriveIn,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
)
from app.modules.production.service import batch_service, execution_service
from tests.modules.production.conftest import rand_code


async def _make_batch(db: AsyncSession, ctx: dict[str, Any]) -> Batch:
    """辅助：在已发布路线上下文中创建测试批次。"""
    return await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ),
        user=None,
    )


async def _complete_node_a(
    db: AsyncSession, ctx: dict[str, Any], batch: Batch,
) -> None:
    """辅助：完成起点节点 A 的一次执行。"""
    ex = await execution_service.start_execution(
        db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None,
    )
    await execution_service.complete_execution(
        db, ex.id, ExecutionCompleteIn(), user=None,
    )


class TestStart:
    async def test_first_execution_must_be_start_node(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """首次执行选非起点节点 C 且无偏离原因时被拒。"""
        batch = await _make_batch(db_session, published_route)
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_c"].id),
                user=None,
            )

    async def test_first_execution_at_start_node_flips_batch_status(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """在起点开始首个执行后批次状态从 pending 翻转为 in_progress，seq=1。"""
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        assert ex.status == "in_progress"
        assert ex.execution_seq == 1
        refreshed = await repo.get_batch(db_session, batch.id)
        assert refreshed is not None and refreshed.status == "in_progress"

    async def test_deviation_start_with_reason_is_marked(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """带偏离原因在非合法来路节点开始时 is_deviation 标记为 True。"""
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_c"].id,
                deviation_reason="特殊情况直接精制",
            ),
            user=None,
        )
        assert ex.is_deviation is True

    async def test_missing_required_start_field_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """B 节点 start 阶段有 required 字段 temp，不传时开始被拒。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_b"].id),
                user=None,
            )

    async def test_numeric_out_of_range_marks_abnormal(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """数值字段超出 min/max 范围时 is_abnormal 标记为 True。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=35)],  # max=30
            ),
            user=None,
        )
        values = await repo.get_field_values_by_executions(db_session, [ex.id])
        temp = next(v for v in values if v.field_key == "temp")
        assert temp.is_abnormal is True
        assert temp.value_numeric == 35

    async def test_numeric_non_finite_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """NaN 等非有限数值字段值被拒绝。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_b"].id,
                    field_values=[FieldValueIn(field_key="temp", value="nan")],
                ),
                user=None,
            )

    async def test_restart_after_abort_is_not_deviation(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """中止执行后在同一节点重新开始，非偏离且 seq 递增到 2。"""
        batch = await _make_batch(db_session, published_route)
        ex1 = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        await execution_service.abort_execution(db_session, ex1.id, user=None)
        ex2 = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        assert ex2.is_deviation is False
        assert ex2.execution_seq == 2

    async def test_parallel_same_node_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """同一批次同一节点已有进行中执行时不可重复开始。"""
        batch = await _make_batch(db_session, published_route)
        await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_a"].id),
                user=None,
            )

    async def test_equipment_snapshot_written(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """指定设备 ID 时开始执行会写入设备快照关联记录。"""
        batch = await _make_batch(db_session, published_route)
        eq_id = uuid.uuid4()
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id, equipment_ids=[eq_id],
            ),
            user=None,
        )
        snaps = await repo.get_equipments_by_executions(db_session, [ex.id])
        assert len(snaps) == 1
        assert snaps[0].equipment_id == eq_id

    async def test_derived_batch_starts_at_entry_node(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """衍生批次在 entry_node（B 节点）上首次开始执行，非偏离且带必填字段通过。"""
        parent = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, parent)
        children = await batch_service.derive_batches(
            db_session,
            parent.id,
            DeriveIn(
                edge_id=published_route["edge_ab"].id,
                children=[ChildBatchIn(batch_no=rand_code("B"))],
            ),
            user=None,
        )
        child = children[0]
        assert child.entry_node_id == published_route["node_b"].id
        ex = await execution_service.start_execution(
            db_session,
            child.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        assert ex.is_deviation is False

    async def test_allow_overlap_starts_when_prev_in_progress(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """流水线边（allow_overlap）：前道 B 进行中即可开始下游 C，且非偏离。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        ex_b = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        assert ex_b.status == "in_progress"
        ex_c = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_c"].id),
            user=None,
        )
        assert ex_c.status == "in_progress"
        assert ex_c.is_deviation is False

    async def test_batch_boundary_edge_requires_completed(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """批次边界边 A→B：A 未完成时不能开始 B（需偏离原因）。"""
        batch = await _make_batch(db_session, published_route)
        await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_b"].id),
                user=None,
            )

    async def test_aborted_node_cannot_start_downstream(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """前道 B 已中止，即便是 allow_overlap 边也不能启动下游 C。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        ex_b = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        await execution_service.abort_execution(db_session, ex_b.id, user=None)
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_c"].id),
                user=None,
            )


class TestCompleteAndRework:
    async def test_complete_missing_required_end_field_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """B 节点 end 阶段有 required 字段 yield_qty，缺失时完成被拒；补齐后完成成功。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        with pytest.raises(AppException):
            await execution_service.complete_execution(
                db_session, ex.id, ExecutionCompleteIn(), user=None,
            )
        done = await execution_service.complete_execution(
            db_session,
            ex.id,
            ExecutionCompleteIn(
                field_values=[FieldValueIn(field_key="yield_qty", value=80)],
            ),
            user=None,
        )
        assert done.status == "completed"
        assert done.finished_at is not None

    async def test_rework_increments_seq(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """C 完成后沿 rework 边回到 B 重做，seq=2 且非偏离。"""

        async def _run_b() -> None:
            """辅助：完成 B 节点的一次执行。"""
            ex_b = await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_b"].id,
                    field_values=[FieldValueIn(field_key="temp", value=25)],
                ),
                user=None,
            )
            await execution_service.complete_execution(
                db_session,
                ex_b.id,
                ExecutionCompleteIn(
                    field_values=[FieldValueIn(field_key="yield_qty", value=80)],
                ),
                user=None,
            )

        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        await _run_b()
        ex_c = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_c"].id),
            user=None,
        )
        await execution_service.complete_execution(
            db_session, ex_c.id, ExecutionCompleteIn(), user=None,
        )
        ex_b2 = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        assert ex_b2.execution_seq == 2
        assert ex_b2.is_deviation is False

    async def test_abort(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """进行中的执行可中止，状态变为 aborted。"""
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        aborted = await execution_service.abort_execution(
            db_session, ex.id, user=None,
        )
        assert aborted.status == "aborted"
