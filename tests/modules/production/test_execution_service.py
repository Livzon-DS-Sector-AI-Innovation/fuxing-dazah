"""execution_service 业务规则测试。"""

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
    return await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ),
        user=None,
    )


async def _complete_node_a(db: AsyncSession, ctx: dict[str, Any], batch: Batch) -> None:
    """帮助函数：完成起点节点 A 的一次执行。"""
    ex = await execution_service.start_execution(
        db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None
    )
    await execution_service.complete_execution(
        db, ex.id, ExecutionCompleteIn(), user=None
    )


class TestStart:
    async def test_first_execution_must_be_start_node(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        batch = await _make_batch(db_session, published_route)
        # 首个执行选了非起点 C，且无偏离原因 → 拒绝
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_c"].id),
                user=None,
            )

    async def test_first_execution_at_start_node_flips_batch_status(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        # B 节点有 required 的 start 字段 temp，不传 → 拒绝
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_b"].id),
                user=None,
            )

    async def test_numeric_out_of_range_marks_abnormal(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        batch = await _make_batch(db_session, published_route)
        eq_id = uuid.uuid4()
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id, equipment_ids=[eq_id]
            ),
            user=None,
        )
        snaps = await repo.get_equipments_by_executions(db_session, [ex.id])
        assert len(snaps) == 1
        assert snaps[0].equipment_id == eq_id

    async def test_derived_batch_starts_at_entry_node(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        # 子批次首个执行在入口节点 B（带必填 start 字段）→ 合法非偏离
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
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """流水线边：前道 in_progress 即可开始下游。"""
        batch = await _make_batch(db_session, published_route)
        # 先完成 A（因为 A→B 是批次边界，不允许 overlap）
        await _complete_node_a(db_session, published_route, batch)
        # 开始 B
        ex_b = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        # B 未完成时即可开始 C（allow_overlap=true）
        ex_c = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_c"].id),
            user=None,
        )
        assert ex_c.status == "in_progress"
        assert ex_c.is_deviation is False

    async def test_batch_boundary_edge_requires_completed(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """批次边界边 A→B：A in_progress 时 B 无法开始（需偏离）。"""
        batch = await _make_batch(db_session, published_route)
        # 开始 A 但不完成
        await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        # A→B 是批次边界，A 未完成时 B 无法开始（不含偏离原因 → 拒绝）
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_b"].id),
                user=None,
            )

    async def test_aborted_node_cannot_start_downstream(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        """前道中止后不能用于启动下游。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        # 开始并中止 B
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
        # B 已中止，B→C 的 allow_overlap 无效（中止节点既不在 completed 也不在 in_progress）
        with pytest.raises(AppException):
            await execution_service.start_execution(
                db_session,
                batch.id,
                ExecutionStartIn(node_id=published_route["node_c"].id),
                user=None,
            )


class TestCompleteAndRework:
    async def test_complete_missing_required_end_field_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
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
        # B 的 end 阶段有 required 的 yield_qty → 缺失拒绝
        with pytest.raises(AppException):
            await execution_service.complete_execution(
                db_session, ex.id, ExecutionCompleteIn(), user=None
            )
        done = await execution_service.complete_execution(
            db_session,
            ex.id,
            ExecutionCompleteIn(
                field_values=[FieldValueIn(field_key="yield_qty", value=80)]
            ),
            user=None,
        )
        assert done.status == "completed"
        assert done.finished_at is not None

    async def test_rework_increments_seq(
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)

        async def _run_b() -> None:
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
                    field_values=[FieldValueIn(field_key="yield_qty", value=80)]
                ),
                user=None,
            )

        await _run_b()
        # C 完成后走 rework 边回 B 重做 → seq=2 且非偏离
        ex_c = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_c"].id),
            user=None,
        )
        await execution_service.complete_execution(
            db_session, ex_c.id, ExecutionCompleteIn(), user=None
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
        self, db_session: AsyncSession, published_route: dict[str, Any]
    ) -> None:
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )
        aborted = await execution_service.abort_execution(db_session, ex.id, user=None)
        assert aborted.status == "aborted"
