"""工序视角跨批次执行记录查询测试。

覆盖业务场景：
- 跨批次列出某节点的全部执行记录，含批号和异常字段计数
- 按状态过滤（aborted 无结果）
- 查询不存在的节点抛出 NotFoundException
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.production.schemas import (
    BatchCreate,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
)
from app.modules.production.service import batch_service, execution_service
from tests.modules.production.conftest import rand_code


async def _run_node_b(db: AsyncSession, ctx: dict[str, Any]) -> None:
    """辅助：新建批次并完成 node_b 的一次执行（temp=99 超限→1 个异常字段）。"""
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
        db, ex_a.id, ExecutionCompleteIn(), user=None,
    )
    ex_b = await execution_service.start_execution(
        db,
        batch.id,
        ExecutionStartIn(
            node_id=ctx["node_b"].id,
            field_values=[FieldValueIn(field_key="temp", value=99)],
        ),
        user=None,
    )
    await execution_service.complete_execution(
        db,
        ex_b.id,
        ExecutionCompleteIn(
            field_values=[FieldValueIn(field_key="yield_qty", value=10)],
        ),
        user=None,
    )


async def test_list_by_node_across_batches(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """node_b 上两次执行（两个批次），列表返回 2 条，均含批号和 1 个异常字段。"""
    await _run_node_b(db_session, published_route)
    await _run_node_b(db_session, published_route)
    items, total = await execution_service.list_node_executions(
        db_session, published_route["node_b"].id, None, 1, 20,
    )
    assert total == 2
    assert len(items) == 2
    assert all(i.batch_no for i in items)
    assert all(i.abnormal_count == 1 for i in items)


async def test_status_filter_and_unknown_node(
    db_session: AsyncSession, published_route: dict[str, Any],
) -> None:
    """按 aborted 状态过滤返回 0 条；不存在的节点查询抛出 NotFoundException。"""
    await _run_node_b(db_session, published_route)
    items, total = await execution_service.list_node_executions(
        db_session, published_route["node_b"].id, "aborted", 1, 20,
    )
    assert total == 0
    with pytest.raises(AppException):
        await execution_service.list_node_executions(
            db_session, uuid.uuid4(), None, 1, 20,
        )
