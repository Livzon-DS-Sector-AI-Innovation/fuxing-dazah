"""节点执行：开始/结束/中止工序，来路校验、字段校验、异常判定、偏离判定。"""

import math
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment.public_api import get_equipment_briefs
from app.modules.production import repository as repo
from app.modules.production.models import (
    Batch,
    BatchIntermediateConsumption,
    BatchIntermediateOutput,
    NodeExecution,
    NodeExecutionEquipment,
    NodeFieldDef,
    NodeFieldValue,
)
from app.modules.production.schemas import (
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
    NodeExecutionListItem,
)
from app.modules.production.service.route_service import compute_start_nodes
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User


def _build_field_values(
    defs: list[NodeFieldDef],
    inputs: list[FieldValueIn],
    phase: str,
    execution_id: uuid.UUID,
    user: User | None,
) -> list[NodeFieldValue]:
    """校验并构建某一 phase 的字段值行：必填校验、类型校验、is_abnormal 判定。"""
    defs_by_key = {d.field_key: d for d in defs if d.phase == phase}
    input_map = {v.field_key: v.value for v in inputs}

    unknown = set(input_map) - set(defs_by_key)
    if unknown:
        raise AppException(
            status_code=400, message=f"未定义的字段: {', '.join(sorted(unknown))}"
        )
    missing = [
        d.field_key
        for d in defs_by_key.values()
        if d.required and input_map.get(d.field_key) is None
    ]
    if missing:
        raise AppException(
            status_code=400, message=f"缺少必填字段: {', '.join(sorted(missing))}"
        )

    rows: list[NodeFieldValue] = []
    for key, value in input_map.items():
        if value is None:
            continue
        d = defs_by_key[key]
        row = NodeFieldValue(
            execution_id=execution_id,
            field_def_id=d.id,
            field_key=d.field_key,
            field_label=d.field_label,
            unit=d.unit,
            phase=d.phase,
            created_by=user.id if user else None,
        )
        if d.data_type == "numeric":
            if isinstance(value, bool) or not isinstance(value, int | float | str):
                raise AppException(status_code=400, message=f"字段 {key} 需为数值")
            try:
                num = float(value)
            except ValueError:
                raise AppException(
                    status_code=400, message=f"字段 {key} 需为数值"
                ) from None
            if not math.isfinite(num):
                raise AppException(
                    status_code=400, message=f"字段 {key} 需为有限数值"
                )
            row.value_numeric = num
            row.is_abnormal = (d.min_value is not None and num < d.min_value) or (
                d.max_value is not None and num > d.max_value
            )
        elif d.data_type == "boolean":
            if not isinstance(value, bool):
                raise AppException(status_code=400, message=f"字段 {key} 需为布尔值")
            row.value_bool = value
        elif d.data_type == "select":
            if d.options and str(value) not in d.options:
                raise AppException(
                    status_code=400, message=f"字段 {key} 的值不在选项范围内"
                )
            row.value_text = str(value)
        else:  # text
            row.value_text = str(value)
        rows.append(row)
    return rows


async def _check_source_legality(
    db: AsyncSession, batch: Batch, node_id: uuid.UUID
) -> bool:
    """来路校验：completed 节点始终合法；allow_overlap 边允许 in_progress 前道。"""
    nodes = await repo.get_route_nodes(db, batch.route_id)
    edges = await repo.get_route_edges(db, batch.route_id)
    completed = await repo.completed_node_ids(db, batch.id)
    in_progress = await repo.in_progress_node_ids(db, batch.id)

    if not completed and not in_progress:
        # 无任何执行记录：仅起点/入口节点合法
        if batch.entry_node_id:
            return node_id == batch.entry_node_id
        return node_id in compute_start_nodes(nodes, edges)

    for e in edges:
        if e.to_node_id != node_id:
            continue
        if e.from_node_id in completed:
            return True
        if e.allow_overlap and not e.is_batch_boundary and e.from_node_id in in_progress:
            return True
    return False


async def start_execution(
    db: AsyncSession, batch_id: uuid.UUID, payload: ExecutionStartIn, user: User | None
) -> NodeExecution:
    batch = await repo.get_batch(db, batch_id)
    if not batch:
        raise NotFoundException("批次", str(batch_id))
    if batch.status not in ("pending", "in_progress"):
        raise AppException(
            status_code=400, message="仅 pending/in_progress 的批次可开始工序"
        )
    nodes = await repo.get_route_nodes(db, batch.route_id)
    if payload.node_id not in {n.id for n in nodes}:
        raise NotFoundException("工序节点", str(payload.node_id))
    if await repo.has_in_progress_execution(db, batch_id, payload.node_id):
        raise AppException(
            status_code=400, message="该工序已有进行中的执行，不能重复开始"
        )

    is_legal = await _check_source_legality(db, batch, payload.node_id)
    if not is_legal and not payload.deviation_reason:
        raise AppException(
            status_code=400, message="该流转未在工艺路线中定义，需提供偏离原因"
        )

    # 设备校验 + 快照
    briefs = await get_equipment_briefs(db, payload.equipment_ids)
    found_ids = {b.id for b in briefs}
    missing_eq = set(payload.equipment_ids) - found_ids
    if missing_eq:
        raise NotFoundException("设备", ", ".join(str(i) for i in missing_eq))

    seq = await repo.max_execution_seq(db, batch_id, payload.node_id) + 1
    execution = NodeExecution(
        batch_id=batch_id,
        node_id=payload.node_id,
        execution_seq=seq,
        status="in_progress",
        owner_id=payload.owner_id,
        owner_name=payload.owner_name,
        started_at=datetime.now(UTC),
        started_by=user.id if user else None,
        started_by_name=user.name if user else None,
        is_deviation=not is_legal,
        deviation_reason=payload.deviation_reason if not is_legal else None,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(execution)
    await db.flush()

    # start 阶段字段
    defs = await repo.get_field_defs_by_nodes(db, [payload.node_id])
    for row in _build_field_values(
        defs, payload.field_values, "start", execution.id, user
    ):
        db.add(row)
    for brief in briefs:
        db.add(
            NodeExecutionEquipment(
                execution_id=execution.id,
                equipment_id=brief.id,
                equipment_no=brief.equipment_no,
                equipment_name=brief.name,
                created_by=user.id if user else None,
            )
        )
    # 中间体消耗记录
    for c in payload.intermediate_consumptions:
        output = await repo.get_intermediate_output(db, c.output_id)
        if not output:
            raise NotFoundException("中间体产出记录", str(c.output_id))
        if c.intermediate_type_id != output.intermediate_type_id:
            raise AppException(
                status_code=400,
                message="消耗的中间体类型与产出源类型不匹配",
            )
        db.add(
            BatchIntermediateConsumption(
                batch_id=batch_id,
                execution_id=execution.id,
                node_id=payload.node_id,
                intermediate_type_id=c.intermediate_type_id,
                output_id=c.output_id,
                quantity=c.quantity,
                unit=c.unit or output.unit,
                remark=c.remark,
                created_by=user.id if user else None,
            )
        )
    # 首个执行推进批次状态
    if batch.status == "pending":
        batch.status = "in_progress"
    await db.flush()
    await record_audit_log(
        db,
        action="production.execution.start",
        user=user,
        resource_type="node_execution",
        resource_id=execution.id,
        extra={"batch_no": batch.batch_no, "seq": seq},
    )
    return execution


async def complete_execution(
    db: AsyncSession,
    execution_id: uuid.UUID,
    payload: ExecutionCompleteIn,
    user: User | None,
) -> NodeExecution:
    execution = await repo.get_execution(db, execution_id)
    if not execution:
        raise NotFoundException("工序执行", str(execution_id))
    if execution.status != "in_progress":
        raise AppException(status_code=400, message="仅进行中的执行可结束")
    defs = await repo.get_field_defs_by_nodes(db, [execution.node_id])
    for row in _build_field_values(
        defs, payload.field_values, "end", execution.id, user
    ):
        db.add(row)
    # 中间体产出记录
    batch = await repo.get_batch(db, execution.batch_id)
    if not batch:
        raise AppException(status_code=400, message="批次不存在或已删除，无法完成工序")
    # 从产出物类型配置读取 is_product（批量查询，不走全表扫描）
    output_type_ids = [o.intermediate_type_id for o in payload.intermediate_outputs]
    is_product_map: dict[uuid.UUID, bool] = {}
    if output_type_ids:
        types = await repo.get_intermediate_types_by_ids(db, output_type_ids)
        is_product_map = {t.id: t.is_product for t in types}
        # 校验所有中间体类型均存在且未被软删除
        missing = set(output_type_ids) - set(is_product_map.keys())
        if missing:
            raise NotFoundException("中间体类型", ", ".join(str(m) for m in missing))
    for o in payload.intermediate_outputs:
        db.add(
            BatchIntermediateOutput(
                batch_id=execution.batch_id,
                execution_id=execution.id,
                node_id=execution.node_id,
                intermediate_type_id=o.intermediate_type_id,
                intermediate_batch_no=o.intermediate_batch_no or batch.batch_no,
                quantity=o.quantity,
                unit=o.unit or "",
                is_product=is_product_map.get(o.intermediate_type_id, False),
                remark=o.remark,
                created_by=user.id if user else None,
            )
        )
    execution.status = "completed"
    execution.finished_at = datetime.now(UTC)
    execution.finished_by = user.id if user else None
    execution.finished_by_name = user.name if user else None
    if payload.remark:
        execution.remark = payload.remark
    execution.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="production.execution.complete",
        user=user,
        resource_type="node_execution",
        resource_id=execution.id,
    )
    refreshed = await repo.get_execution(db, execution_id)
    assert refreshed is not None
    return refreshed


async def abort_execution(
    db: AsyncSession, execution_id: uuid.UUID, user: User | None
) -> NodeExecution:
    execution = await repo.get_execution(db, execution_id)
    if not execution:
        raise NotFoundException("工序执行", str(execution_id))
    if execution.status != "in_progress":
        raise AppException(status_code=400, message="仅进行中的执行可中止")
    execution.status = "aborted"
    execution.finished_at = datetime.now(UTC)
    execution.finished_by = user.id if user else None
    execution.finished_by_name = user.name if user else None
    execution.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_execution(db, execution_id)
    assert refreshed is not None
    return refreshed


async def list_node_executions(
    db: AsyncSession,
    node_id: uuid.UUID,
    status: str | None,
    page: int,
    page_size: int,
    order_by: str = "started_at",
    order: str = "desc",
) -> tuple[list[NodeExecutionListItem], int]:
    """工序视角：某节点的全部执行记录（跨批次），带批号与异常字段计数。"""
    nodes = await repo.get_nodes_by_ids(db, [node_id])
    if not nodes:
        raise NotFoundException("工序节点", str(node_id))
    executions, total = await repo.list_executions_by_node(
        db, node_id, status, page, page_size, order_by, order
    )
    batches = await repo.get_batches_by_ids(db, list({e.batch_id for e in executions}))
    batch_no_map = {b.id: b.batch_no for b in batches}
    values = await repo.get_field_values_by_executions(db, [e.id for e in executions])
    abnormal: dict[uuid.UUID, int] = {}
    for v in values:
        if v.is_abnormal:
            abnormal[v.execution_id] = abnormal.get(v.execution_id, 0) + 1
    items = [
        NodeExecutionListItem(
            id=e.id,
            batch_id=e.batch_id,
            batch_no=batch_no_map.get(e.batch_id, ""),
            execution_seq=e.execution_seq,
            status=e.status,
            owner_name=e.owner_name,
            started_at=e.started_at,
            finished_at=e.finished_at,
            is_deviation=e.is_deviation,
            abnormal_count=abnormal.get(e.id, 0),
        )
        for e in executions
    ]
    return items, total
