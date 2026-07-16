"""trace_service 溯源测试：分裂 + 合并的 DAG 双向追溯。"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.schemas import (
    BatchCreate,
    ChildBatchIn,
    DeriveIn,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
    MergeIn,
    MergeParentIn,
)
from app.modules.production.service import (
    batch_service,
    execution_service,
    trace_service,
)
from tests.modules.production.conftest import rand_code


async def _build_lineage(db: AsyncSession, ctx: dict[str, Any]) -> dict[str, Any]:
    """构建谱系：root --derive(边界边)--> c1, c2 --merge(偏离)--> merged。

    子批次先各自完成入口工序 B（merge 要求父批次非 pending）。
    """
    root = await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("ROOT"),
            product_id=ctx["product"].id,
            route_id=ctx["route"].id,
        ),
        user=None,
    )
    ex = await execution_service.start_execution(
        db, root.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None
    )
    await execution_service.complete_execution(
        db, ex.id, ExecutionCompleteIn(), user=None
    )
    children = await batch_service.derive_batches(
        db,
        root.id,
        DeriveIn(
            edge_id=ctx["edge_ab"].id,
            children=[
                ChildBatchIn(batch_no=rand_code("C1"), quantity=40),
                ChildBatchIn(batch_no=rand_code("C2"), quantity=60),
            ],
        ),
        user=None,
    )
    for child in children:
        ex_c = await execution_service.start_execution(
            db,
            child.id,
            ExecutionStartIn(
                node_id=ctx["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        await execution_service.complete_execution(
            db,
            ex_c.id,
            ExecutionCompleteIn(
                field_values=[FieldValueIn(field_key="yield_qty", value=30)]
            ),
            user=None,
        )
    merged = await batch_service.merge_batches(
        db,
        MergeIn(
            parents=[
                MergeParentIn(batch_id=children[0].id),
                MergeParentIn(batch_id=children[1].id),
            ],
            deviation_reason="测试合并",
            batch_no=rand_code("M"),
        ),
        user=None,
    )
    return {"root": root, "children": children, "merged": merged}


async def test_trace_upstream_from_merged(
    db_session: AsyncSession, published_route: dict[str, Any]
) -> None:
    lineage = await _build_lineage(db_session, published_route)
    trace = await trace_service.get_trace(db_session, lineage["merged"].id)
    batch_ids = {b.id for b in trace.batches}
    assert lineage["root"].id in batch_ids  # 向上穿透两层
    assert len(trace.links) == 4  # root->c1, root->c2, c1->m, c2->m


async def test_trace_downstream_from_root(
    db_session: AsyncSession, published_route: dict[str, Any]
) -> None:
    lineage = await _build_lineage(db_session, published_route)
    trace = await trace_service.get_trace(db_session, lineage["root"].id)
    batch_ids = {b.id for b in trace.batches}
    assert lineage["merged"].id in batch_ids  # 向下穿透两层
    root_batch = next(b for b in trace.batches if b.id == lineage["root"].id)
    assert len(root_batch.executions) == 1  # 带执行摘要
