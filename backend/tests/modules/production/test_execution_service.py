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
from app.modules.production.models import (
    Batch,
    BatchIntermediateConsumption,
    BatchIntermediateOutput,
)
from app.modules.production.schemas import (
    BatchCreate,
    ChildBatchIn,
    DeriveIn,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
    IntermediateConsumptionIn,
    IntermediateOutputIn,
    LineCreate,
)
from app.modules.production.service import (
    batch_service,
    execution_service,
    line_service,
)
from app.platform.identity.models import User
from tests.modules.production.conftest import make_raw_output, rand_code


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
    async def test_complete_without_required_end_field_allowed(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """B 节点 end 阶段 required 字段 yield_qty 缺失时仍可结束工序（批次结束前可补录）。"""
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
        done = await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        assert done.status == "completed"
        assert done.finished_at is not None

    async def test_complete_batch_rejected_until_backfill(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """批次完成时必填字段未上报被拒；补录后批次可完成。"""
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
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        with pytest.raises(AppException, match="yield_qty|产出量"):
            await batch_service.complete_batch(db_session, batch.id, user=None)
        # 补录后批次可完成
        await execution_service.backfill_execution_fields(
            db_session,
            ex.id,
            [FieldValueIn(field_key="yield_qty", value=80)],
            user=None,
        )
        done = await batch_service.complete_batch(db_session, batch.id, user=None)
        assert done.status == "completed"

    async def test_backfill_rejected_after_batch_completed(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """批次完成后禁止补录。"""
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
        await execution_service.complete_execution(
            db_session,
            ex.id,
            ExecutionCompleteIn(
                field_values=[FieldValueIn(field_key="yield_qty", value=80)],
            ),
            user=None,
        )
        await batch_service.complete_batch(db_session, batch.id, user=None)
        with pytest.raises(AppException, match="批次已结束"):
            await execution_service.backfill_execution_fields(
                db_session,
                ex.id,
                [FieldValueIn(field_key="yield_qty", value=90)],
                user=None,
            )

    async def test_backfill_records_filled_at(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """补录写入 filled_at/filled_by，覆盖更新已有行。"""
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
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=None,
        )
        values = await execution_service.backfill_execution_fields(
            db_session,
            ex.id,
            [FieldValueIn(field_key="yield_qty", value=80)],
            user=None,
        )
        row = next(v for v in values if v.field_key == "yield_qty")
        assert row.filled_at is not None
        assert row.value_numeric == 80

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


async def _make_line(db: AsyncSession) -> Any:
    """辅助：创建一条测试产线。"""
    return await line_service.create_line(
        db, LineCreate(name=rand_code("产线")), None,
    )


async def _make_im_type(db: AsyncSession) -> Any:
    """辅助：创建真实中间体类型（complete 的类型存在性校验需要）。"""
    from app.modules.production.schemas import IntermediateTypeCreate
    from app.modules.production.service import intermediate_service

    return await intermediate_service.create_intermediate_type(
        db,
        IntermediateTypeCreate(code=rand_code("IM"), name=rand_code("中间体")),
        None,
    )


async def _make_raw_output(
    db: AsyncSession, ctx: dict[str, Any], batch: Batch,
    *, line_id: Any = None, creator: Any = None, quantity: float = 100,
) -> BatchIntermediateOutput:
    """辅助：手造一条产出记录，精确控制 line_id、归属人与数量。

    薄封装 conftest.make_raw_output，保持本文件调用点不变。
    """
    return await make_raw_output(
        db,
        batch_id=batch.id,
        node_id=ctx["node_a"].id,
        line_id=line_id,
        created_by=creator,
        quantity=quantity,
    )


class TestLineVisibility:
    """产线标记与消耗可见性校验。"""

    @pytest.fixture(autouse=True)
    def _mock_permissions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock 权限查询为管理员，绕开 Redis 依赖，聚焦产线校验逻辑。"""

        async def fake_perms(_uid: str, _db: AsyncSession) -> set[str]:
            return {"production:batch:submit"}

        monkeypatch.setattr(execution_service, "get_user_permissions", fake_perms)

    async def test_complete_with_outputs_requires_line_id(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """有产出但未传产线 → 拒绝。"""
        im_type = await _make_im_type(db_session)
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=test_user,
        )
        with pytest.raises(AppException) as ei:
            await execution_service.complete_execution(
                db_session, ex.id,
                ExecutionCompleteIn(intermediate_outputs=[
                    IntermediateOutputIn(
                        intermediate_type_id=im_type.id, quantity=10, unit="L",
                    ),
                ]),
                user=test_user,
            )
        assert "请选择产线" in str(ei.value.message)

    async def test_complete_line_not_bound_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """产线存在但操作人未绑定（批次负责人也无绑定）→ 拒绝。"""
        im_type = await _make_im_type(db_session)
        line = await _make_line(db_session)
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
                            quantity=10, unit="L",
                        ),
                    ],
                    line_id=line.id,
                ),
                user=test_user,
            )
        assert "未绑定该产线" in str(ei.value.message)

    async def test_complete_batch_owner_fallback_allows(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """执行人未绑定产线，批次负责人绑定 → 兜底通过，产出行落产线。"""
        im_type = await _make_im_type(db_session)
        line = await _make_line(db_session)
        await line_service.bind_user_line(
            db_session, user_id=test_user.id, line_id=line.id,
            created_by=test_user.id,
        )
        executor = User(name="执行人", employee_no=rand_code("E"))
        db_session.add(executor)
        await db_session.flush()

        batch = await _make_batch(db_session, published_route)
        # 批次负责人 = test_user（首次开始认领）
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
                        intermediate_type_id=im_type.id, quantity=10, unit="L",
                    ),
                ],
                line_id=line.id,
            ),
            user=executor,
        )
        outputs = await repo.get_intermediate_outputs_by_batch(db_session, batch.id)
        assert outputs[0].line_id == line.id

    async def test_complete_no_outputs_skips_line_check(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """无产出结束不校验产线（MCP 路径回归守护）。"""
        batch = await _make_batch(db_session, published_route)
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=test_user,
        )
        await execution_service.complete_execution(
            db_session, ex.id, ExecutionCompleteIn(), user=test_user,
        )

    async def test_start_consumption_same_line_ok(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """消耗产出属于操作人绑定产线 → 通过。"""
        line = await _make_line(db_session)
        await line_service.bind_user_line(
            db_session, user_id=test_user.id, line_id=line.id,
            created_by=test_user.id,
        )
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        out = await _make_raw_output(
            db_session, published_route, batch,
            line_id=line.id, creator=uuid.uuid4(),
        )
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=out.intermediate_type_id,
                        output_id=out.id, quantity=5, unit="L",
                    ),
                ],
            ),
            user=test_user,
        )
        assert ex.status == "in_progress"

    async def test_start_consumption_other_line_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """消耗产出属其他产线 → 拒绝。"""
        line1 = await _make_line(db_session)
        line2 = await _make_line(db_session)
        await line_service.bind_user_line(
            db_session, user_id=test_user.id, line_id=line2.id,
            created_by=test_user.id,
        )
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        out = await _make_raw_output(
            db_session, published_route, batch,
            line_id=line1.id, creator=uuid.uuid4(),
        )
        with pytest.raises(AppException) as ei:
            await execution_service.start_execution(
                db_session, batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_b"].id,
                    field_values=[FieldValueIn(field_key="temp", value=25)],
                    intermediate_consumptions=[
                        IntermediateConsumptionIn(
                            intermediate_type_id=out.intermediate_type_id,
                            output_id=out.id, quantity=5, unit="L",
                        ),
                    ],
                ),
                user=test_user,
            )
        assert "不在您负责的产线" in str(ei.value.message)

    async def test_start_consumption_null_line_ok(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """历史产出无产线标记 → 放行（过渡期）。"""
        line = await _make_line(db_session)
        await line_service.bind_user_line(
            db_session, user_id=test_user.id, line_id=line.id,
            created_by=test_user.id,
        )
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        out = await _make_raw_output(
            db_session, published_route, batch,
            line_id=None, creator=uuid.uuid4(),
        )
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=out.intermediate_type_id,
                        output_id=out.id, quantity=5, unit="L",
                    ),
                ],
            ),
            user=test_user,
        )
        assert ex.status == "in_progress"

    async def test_start_consumption_no_binding_ok(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """操作人与批次负责人均未绑定产线 → 放行（过渡期全量）。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        out = await _make_raw_output(
            db_session, published_route, batch,
            line_id=None, creator=uuid.uuid4(),
        )
        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=out.intermediate_type_id,
                        output_id=out.id, quantity=5, unit="L",
                    ),
                ],
            ),
            user=test_user,
        )
        assert ex.status == "in_progress"

    async def _make_history_consumption(
        self, db_session: AsyncSession, out: BatchIntermediateOutput,
        quantity: float,
    ) -> None:
        """辅助：手造一条历史消耗记录，模拟该产出已被部分消耗。"""
        db_session.add(
            BatchIntermediateConsumption(
                batch_id=uuid.uuid4(),
                execution_id=uuid.uuid4(),
                node_id=out.node_id,
                intermediate_type_id=out.intermediate_type_id,
                output_id=out.id,
                quantity=quantity,
                unit=out.unit,
                remark=None,
                created_by=uuid.uuid4(),
            )
        )
        await db_session.flush()

    async def test_start_consumption_exceeds_available_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """消耗数量超出产出余量 → 硬拦截。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        out = await _make_raw_output(
            db_session, published_route, batch,
            line_id=None, creator=uuid.uuid4(), quantity=100,
        )
        with pytest.raises(AppException) as ei:
            await execution_service.start_execution(
                db_session, batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_b"].id,
                    field_values=[FieldValueIn(field_key="temp", value=25)],
                    intermediate_consumptions=[
                        IntermediateConsumptionIn(
                            intermediate_type_id=out.intermediate_type_id,
                            output_id=out.id, quantity=150, unit="L",
                        ),
                    ],
                ),
                user=test_user,
            )
        assert "超出" in str(ei.value.message)

    async def test_start_consumption_with_history_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """历史已消耗 80 后再耗 30（余量 20）→ 拒绝。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        out = await _make_raw_output(
            db_session, published_route, batch,
            line_id=None, creator=uuid.uuid4(), quantity=100,
        )
        await self._make_history_consumption(db_session, out, 80)

        with pytest.raises(AppException) as ei:
            await execution_service.start_execution(
                db_session, batch.id,
                ExecutionStartIn(
                    node_id=published_route["node_b"].id,
                    field_values=[FieldValueIn(field_key="temp", value=25)],
                    intermediate_consumptions=[
                        IntermediateConsumptionIn(
                            intermediate_type_id=out.intermediate_type_id,
                            output_id=out.id, quantity=30, unit="L",
                        ),
                    ],
                ),
                user=test_user,
            )
        assert "余量" in str(ei.value.message)

    async def test_start_consumption_edge_quantity_ok(
        self, db_session: AsyncSession, published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """历史已消耗 80 后刚好耗完余量 20 → 通过（边界）。"""
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, published_route, batch)
        out = await _make_raw_output(
            db_session, published_route, batch,
            line_id=None, creator=uuid.uuid4(), quantity=100,
        )
        await self._make_history_consumption(db_session, out, 80)

        ex = await execution_service.start_execution(
            db_session, batch.id,
            ExecutionStartIn(
                node_id=published_route["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
                intermediate_consumptions=[
                    IntermediateConsumptionIn(
                        intermediate_type_id=out.intermediate_type_id,
                        output_id=out.id, quantity=20, unit="L",
                    ),
                ],
            ),
            user=test_user,
        )
        assert ex.status == "in_progress"
