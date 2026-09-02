"""节点执行：开始/结束/中止工序，来路校验、字段校验、异常判定、偏离判定。"""

import math
import uuid
from collections import defaultdict
from datetime import datetime
from typing import cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.core.time import now
from app.modules.equipment.public_api import get_equipment_briefs
from app.modules.production import repository as repo
from app.modules.production.models import (
    Batch,
    BatchIntermediateConsumption,
    BatchIntermediateOutput,
    MixingContainer,
    NodeExecution,
    NodeExecutionEquipment,
    NodeFieldDef,
    NodeFieldValue,
)
from app.modules.production.schemas import (
    EquipmentSnapshotOut,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
    FieldValueOut,
    MissingFieldOut,
    NodeExecutionListItem,
    ProcessBoardExecutionOut,
    ProcessBoardNodeOut,
    ProcessBoardOut,
    ProcessBoardPlannedItemOut,
)
from app.modules.production.service.assignment_service import require_operator_access
from app.modules.production.service.intermediate_service import (
    get_consumed_quantity_map,
)
from app.modules.production.service.line_service import resolve_user_line_ids
from app.modules.production.service.planning_service import sync_plan_item_status
from app.modules.production.service.reminder_service import (
    schedule_step_completed_notification,
)
from app.modules.production.service.route_service import compute_start_nodes
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User
from app.platform.permission.deps import get_user_permissions


async def _require_operator_permission(
    db: AsyncSession, user: User | None, node_id: uuid.UUID,
    route_id: uuid.UUID, stage_name: str | None,
    batch: "Batch | None" = None,
    execution: "NodeExecution | None" = None,
) -> None:
    """工序执行操作校验：持有 production:batch:submit 或 为该工段/节点负责人 才可操作。

    batch 归属他人时（归属人通常是工段负责人）：
    - 工序级负责人（NodeAssignment）豁免归属限制，可操作自己负责的工序；
    - 单次执行负责人（开始工序时指定的 execution.owner_id）豁免归属限制，
      仅能操作自己这一次执行（结束/补录/中止），无其他批次权限；
    - 工段级负责人（StageAssignment）保持归属隔离（同工段多负责人各自认领批次）。
    管理员权限豁免归属限制。
    """
    from app.core.exceptions import ForbiddenException

    if user is None:
        raise ForbiddenException("未登录，无法执行操作")
    perms = await get_user_permissions(str(user.id), db)
    if "production:batch:submit" in perms:
        return
    await require_operator_access(
        db, user.id, node_id, route_id, stage_name, batch, execution=execution,
    )


def _build_field_values(
    defs: list[NodeFieldDef],
    inputs: list[FieldValueIn],
    phase: str,
    execution_id: uuid.UUID,
    user: User | None,
    enforce_required: bool = True,
) -> list[NodeFieldValue]:
    """校验并构建某一 phase 的字段值行：必填校验、类型校验、is_abnormal 判定。

    enforce_required=False 时跳过必填校验（工序结束阶段允许事后补录，
    必填完整性由 complete_batch 统一把关）。
    """
    defs_by_key = {d.field_key: d for d in defs if d.phase == phase}
    input_map = {v.field_key: v.value for v in inputs}

    unknown = set(input_map) - set(defs_by_key)
    if unknown:
        raise AppException(
            status_code=400, message=f"未定义的字段: {', '.join(sorted(unknown))}"
        )
    if enforce_required:
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
        # 空串视为未填：避免 value='' 生成"已填"行绕过批次完成时的必填门禁
        if value is None or value == "":
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
            filled_at=now(),
            filled_by=user.id if user else None,
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


async def _upsert_field_value_rows(
    db: AsyncSession,
    execution_id: uuid.UUID,
    rows: list[NodeFieldValue],
    user: User | None,
) -> list[NodeFieldValue]:
    """end 阶段字段值 upsert（结束工序与补录共用）：已有行就地更新，新行加入会话。

    返回全部受影响行（已有行 + 新行），供调用方 flush 与返回；rows 为空时直接返回，
    不查询存量行。created_by/created_at 保留首次填报归属，filled_at/filled_by 刷新为本次。
    """
    if not rows:
        return []
    existing = await repo.get_field_values_by_executions(db, [execution_id])
    by_def = {v.field_def_id: v for v in existing}
    for row in rows:
        cur = by_def.get(row.field_def_id)
        if cur:
            cur.value_text = row.value_text
            cur.value_numeric = row.value_numeric
            cur.value_bool = row.value_bool
            cur.is_abnormal = row.is_abnormal
            cur.filled_at = row.filled_at
            cur.filled_by = row.filled_by
            cur.updated_by = user.id if user else None
        else:
            db.add(row)
    return existing + [r for r in rows if r.field_def_id not in by_def]


async def compute_missing_required_fields(
    db: AsyncSession, executions: list[NodeExecution],
) -> dict[uuid.UUID, list[MissingFieldOut]]:
    """已结束工序缺填的必填字段（end 阶段），按 execution_id 分组。

    只统计 completed 执行；同一节点多次执行时以最新一次（execution_seq 最大）为准，
    返工后被覆盖的旧执行缺字段不再永久卡住批次完成。
    空值行（value_text='' 等）不算已填。
    """
    completed = [e for e in executions if e.status == "completed"]
    if not completed:
        return {}
    latest_by_node: dict[uuid.UUID, NodeExecution] = {}
    for e in completed:
        cur = latest_by_node.get(e.node_id)
        if cur is None or e.execution_seq > cur.execution_seq:
            latest_by_node[e.node_id] = e
    latest = list(latest_by_node.values())
    defs = await repo.get_field_defs_by_nodes(db, list({e.node_id for e in latest}))
    required_by_node: dict[uuid.UUID, list[NodeFieldDef]] = {}
    for d in defs:
        if d.phase == "end" and d.required:
            required_by_node.setdefault(d.node_id, []).append(d)
    values = await repo.get_field_values_by_executions(db, [e.id for e in latest])
    filled: set[tuple[uuid.UUID, str]] = {
        (v.execution_id, v.field_key)
        for v in values
        if v.value_text or v.value_numeric is not None or v.value_bool is not None
    }
    missing: dict[uuid.UUID, list[MissingFieldOut]] = {}
    for e in latest:
        m = [
            MissingFieldOut(field_key=d.field_key, field_label=d.field_label)
            for d in required_by_node.get(e.node_id, [])
            if (e.id, d.field_key) not in filled
        ]
        if m:
            missing[e.id] = m
    return missing


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
    if (
        payload.started_at
        and batch.first_started_at
        and payload.started_at < batch.first_started_at
    ):
        raise AppException(status_code=400, message="开始时间不能早于批次首工序开始时间")

    is_legal = await _check_source_legality(db, batch, payload.node_id)
    if not is_legal and not payload.deviation_reason:
        raise AppException(
            status_code=400, message="该流转未在工艺路线中定义，需提供偏离原因"
        )

    # 工段/工序权限校验
    if user:
        route_node = next((n for n in nodes if n.id == payload.node_id), None)
        await _require_operator_permission(
            db, user, payload.node_id, batch.route_id,
            route_node.stage_name if route_node else None,
            batch=batch,
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
        started_at=payload.started_at or now(),
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
    # 中间体消耗记录：精确模式（选产出批次）与混装模式（选容器）二选一
    for c in payload.intermediate_consumptions:
        if (c.output_id is None) == (c.container_id is None):
            raise AppException(
                status_code=400,
                message="每条消耗必须且只能指定产出批次或混装容器之一",
            )

    # 批量查询产出源与容器，避免 N+1；行锁串行化并发余量校验
    output_ids = [
        c.output_id for c in payload.intermediate_consumptions
        if c.output_id is not None
    ]
    output_map: dict[uuid.UUID, BatchIntermediateOutput] = {}
    if output_ids:
        output_map = {
            o.id: o
            for o in await repo.get_intermediate_outputs_by_ids(
                db, output_ids, for_update=True,
            )
        }

    container_ids = list({
        c.container_id for c in payload.intermediate_consumptions
        if c.container_id is not None
    })
    container_map: dict[uuid.UUID, MixingContainer] = {}
    container_stock_map: dict[uuid.UUID, float] = {}
    if container_ids:
        container_map = {
            ct.id: ct
            for ct in await repo.get_mixing_containers_by_ids(db, container_ids)
        }
        missing = set(container_ids) - set(container_map.keys())
        if missing:
            raise NotFoundException("混装容器", ", ".join(str(m) for m in missing))
        # 容器库存 = Σ落入产出 − Σ未中止容器消耗；行锁产出行串行化并发消耗，防超耗
        # （中止执行不计消耗，与精确模式余量口径一致）
        locked_outputs = await repo.get_outputs_by_container_ids(
            db, container_ids, for_update=True,
        )
        consumptions = await repo.get_consumptions_by_container_ids(
            db, container_ids, exclude_aborted=True,
        )
        for ct_id in container_ids:
            container_stock_map[ct_id] = (
                sum(o.quantity for o in locked_outputs if o.container_id == ct_id)
                - sum(c.quantity for c in consumptions if c.container_id == ct_id)
            )

    # 消耗可见产线集合：操作人绑定 → 批次负责人绑定兜底 → 皆无则拒绝产线产出
    visible_line_ids: set[uuid.UUID] | None = None
    if user and (output_ids or container_ids):
        visible_line_ids = set(
            await resolve_user_line_ids(db, user.id, batch.owner_user_id)
        )

    # 混装消耗的单位兜底：容器/消耗行未填单位时用中间体类型默认单位
    container_type_ids = [
        c.intermediate_type_id for c in payload.intermediate_consumptions
        if c.container_id is not None and not c.unit
    ]
    default_unit_map: dict[uuid.UUID, str | None] = {}
    if container_type_ids:
        default_unit_map = {
            t.id: t.default_unit
            for t in await repo.get_intermediate_types_by_ids(db, container_type_ids)
        }

    # 精确模式余量：历史已消耗 + 本次消耗 ≤ 产出数量（硬拦截，防超耗）
    consumed_map = await get_consumed_quantity_map(db, output_ids)
    request_map: defaultdict[uuid.UUID, float] = defaultdict(float)
    container_request_map: defaultdict[uuid.UUID, float] = defaultdict(float)
    for c in payload.intermediate_consumptions:
        if c.output_id is not None:
            request_map[c.output_id] += c.quantity
        else:
            assert c.container_id is not None  # 前面已校验二选一
            container_request_map[c.container_id] += c.quantity

    for c in payload.intermediate_consumptions:
        if c.output_id is not None:
            output = output_map.get(c.output_id)
            if not output:
                raise NotFoundException("中间体产出记录", str(c.output_id))
            if output.container_id is not None:
                raise AppException(
                    status_code=400,
                    message="该产出已混装入容器，请从容器取用",
                )
            if c.intermediate_type_id != output.intermediate_type_id:
                raise AppException(
                    status_code=400,
                    message="消耗的中间体类型与产出源类型不匹配",
                )
            # 产线可见性校验：无产线产出（line_id=None）过渡期放行；其余必须 ∈ 可见产线集合
            if visible_line_ids is not None and output.line_id and output.line_id not in visible_line_ids:
                raise AppException(
                    status_code=400,
                    message="该中间体不在您负责的产线内",
                )
            # 余量校验：按产出汇总（同一产出本次多行合并计算）
            requested = request_map.get(c.output_id, 0.0)
            available = output.quantity - consumed_map.get(c.output_id, 0.0)
            if requested > available + 1e-9:
                raise AppException(
                    status_code=400,
                    message=(
                        f"消耗数量超出该中间体批次的可用余量"
                        f"（余量 {available:g}{output.unit}）"
                    ),
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
        else:
            assert c.container_id is not None  # 前面已校验二选一
            ct = container_map[c.container_id]
            if c.intermediate_type_id != ct.intermediate_type_id:
                raise AppException(
                    status_code=400,
                    message="消耗的中间体类型与容器装存类型不匹配",
                )
            if visible_line_ids is not None and ct.line_id not in visible_line_ids:
                raise AppException(
                    status_code=400,
                    message="该混装容器不在您负责的产线内",
                )
            requested = container_request_map.get(ct.id, 0.0)
            available = container_stock_map.get(ct.id, 0.0)
            unit = c.unit or default_unit_map.get(c.intermediate_type_id) or ""
            if requested > available + 1e-9:
                raise AppException(
                    status_code=400,
                    message=(
                        f"消耗数量超出混装容器 {ct.name} 的可用余量"
                        f"（余量 {available:g}{unit}）"
                    ),
                )
            db.add(
                BatchIntermediateConsumption(
                    batch_id=batch_id,
                    execution_id=execution.id,
                    node_id=payload.node_id,
                    intermediate_type_id=c.intermediate_type_id,
                    container_id=c.container_id,
                    quantity=c.quantity,
                    unit=unit,
                    remark=c.remark,
                    created_by=user.id if user else None,
                )
            )
    # 首个执行推进批次状态 / 记录首工序开始时间
    if batch.status == "pending":
        batch.status = "in_progress"
    if batch.first_started_at is None:
        batch.first_started_at = payload.started_at or now()
    # 无主批次认领：谁先开始归谁
    if batch.owner_user_id is None and user:
        batch.owner_user_id = user.id
        batch.owner_name = user.name
    await db.flush()
    await record_audit_log(
        db,
        action="production.execution.start",
        user=user,
        resource_type="node_execution",
        resource_id=execution.id,
        extra={"batch_no": batch.batch_no, "seq": seq},
    )
    await sync_plan_item_status(db, batch.id)
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
    if payload.finished_at and payload.finished_at < execution.started_at:
        raise AppException(status_code=400, message="结束时间不能早于开始时间")

    # 中间体产出记录
    batch = await repo.get_batch(db, execution.batch_id)
    if not batch:
        raise AppException(status_code=400, message="批次不存在或已删除，无法完成工序")
    if (
        payload.finished_at
        and batch.first_started_at
        and payload.finished_at < batch.first_started_at
    ):
        raise AppException(status_code=400, message="结束时间不能早于批次首工序开始时间")

    # 结束顺序校验：前道未完成则拒绝（allow_overlap 放宽开始但不放宽结束）
    # 跳过 is_batch_boundary 边（前序在父批次完成），与开始校验对齐
    edges = await repo.get_route_edges(db, batch.route_id)
    completed = await repo.completed_node_ids(db, batch.id)
    # 收集未完成的前驱节点 ID，批量查询名称（避免 N+1）
    missing_pred_ids = [
        e.from_node_id
        for e in edges
        if e.to_node_id == execution.node_id
        and e.edge_type == "normal"
        and not e.is_batch_boundary
        and e.from_node_id not in completed
    ]
    if missing_pred_ids:
        pred_nodes = await repo.get_nodes_by_ids(db, list(set(missing_pred_ids)))
        pred_name_map = {n.id: n.name for n in pred_nodes}
        pred_name = pred_name_map.get(missing_pred_ids[0], "前道工序")
        raise AppException(
            status_code=400,
            message=f"请先结束{pred_name}后再结束本工序",
        )

    # 权限校验必须保持在一切写操作之前：后续字段值/产出会向会话加入写操作，
    # 一旦 403 被上层（MCP 工具）吞掉，残留写操作仍可能被会话提交落库
    if user:
        route_node = await repo.get_nodes_by_ids(db, [execution.node_id])
        node = route_node[0] if route_node else None
        await _require_operator_permission(
            db, user, execution.node_id, batch.route_id,
            node.stage_name if node else None,
            batch=batch,
            execution=execution,
        )

    # end 阶段字段值 upsert（与补录共用 _upsert_field_value_rows）：已有行就地更新，
    # 新行才插入。直接插入会在重试/重复提交时撞 (execution_id, field_def_id) 唯一索引
    defs = await repo.get_field_defs_by_nodes(db, [execution.node_id])
    rows = _build_field_values(
        defs, payload.field_values, "end", execution.id, user, enforce_required=False
    )
    await _upsert_field_value_rows(db, execution.id, rows, user)
    # 新增行在 savepoint 内先落库：并发重复提交（双击/重试）撞唯一索引时
    # 在此转 400，避免走到后续查询的 autoflush 时以 500 爆出
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise AppException(
            status_code=400,
            message="提交冲突（并发写入），请刷新后重试",
        ) from None
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

    # 混装容器校验：容器存在且装存的类型与产出类型一致
    container_ids = [o.container_id for o in payload.intermediate_outputs if o.container_id]
    container_map: dict[uuid.UUID, MixingContainer] = {}
    if container_ids:
        container_map = {
            ct.id: ct
            for ct in await repo.get_mixing_containers_by_ids(db, container_ids)
        }
        missing = set(container_ids) - set(container_map.keys())
        if missing:
            raise NotFoundException("混装容器", ", ".join(str(m) for m in missing))
        for o in payload.intermediate_outputs:
            if o.container_id is None:
                continue
            ct = container_map[o.container_id]
            if ct.intermediate_type_id != o.intermediate_type_id:
                raise AppException(
                    status_code=400,
                    message=f"容器 {ct.name} 装存类型与产出物类型不匹配",
                )

    # 产线三级 fallback 校验：操作人绑定 → 批次负责人绑定兜底 → 拒绝。
    # 行级产线 = 混装行取容器所属产线，精确行取 payload.line_id。
    # 仅在有产出且 user 存在时校验——MCP 路径结束工序不传产出，必须豁免；
    # user=None 仅出现在内部调用/测试，跳过校验保持兼容。
    if payload.intermediate_outputs and user:
        has_precise = any(o.container_id is None for o in payload.intermediate_outputs)
        if has_precise and not payload.line_id:
            raise AppException(status_code=400, message="请选择产线")
        allowed_line_ids = set(
            await resolve_user_line_ids(db, user.id, batch.owner_user_id)
        )
        for o in payload.intermediate_outputs:
            if o.container_id is None:
                row_line_id = payload.line_id
            else:
                row_line_id = container_map[o.container_id].line_id
            if row_line_id not in allowed_line_ids:
                raise AppException(
                    status_code=400,
                    message="操作人未绑定该产线，请联系管理员配置",
                )

    # 中间体批号查重：同一提交内互不相同，且不与历史未删除产出重复
    # （留空默认取批次号；DB partial unique index 兜底并发写入）
    batch_nos: set[str] = set()
    for o in payload.intermediate_outputs:
        bno = o.intermediate_batch_no or batch.batch_no
        if bno in batch_nos:
            raise AppException(
                status_code=400,
                message=f"中间体批号 {bno} 重复，请为每个产出填写不重复的批号",
            )
        batch_nos.add(bno)
    if batch_nos:
        dups = await repo.find_duplicate_output_batch_nos(db, list(batch_nos))
        if dups:
            raise AppException(
                status_code=400,
                message=f"中间体批号已存在: {', '.join(sorted(dups))}",
            )
    for o in payload.intermediate_outputs:
        if o.container_id is None:
            row_line_id = payload.line_id
        else:
            row_line_id = container_map[o.container_id].line_id
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
                line_id=row_line_id,
                container_id=o.container_id,
            )
        )
    execution.status = "completed"
    execution.finished_at = payload.finished_at or now()
    execution.finished_by = user.id if user else None
    execution.finished_by_name = user.name if user else None
    if payload.remark:
        execution.remark = payload.remark
    execution.updated_by = user.id if user else None
    # 记录最近一次工序结束时间（末工序结束由 complete_batch 设置）；
    # 手填结束时间可能回退，取单调最大防批次时间线倒挂
    finished_ts = payload.finished_at or now()
    if batch.last_finished_at is None or finished_ts > batch.last_finished_at:
        batch.last_finished_at = finished_ts
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        # 并发写入触发 DB 唯一索引（同批号产出 / 并发重复提交同字段值），转 400 而非 500
        raise AppException(
            status_code=400,
            message="提交冲突（并发写入），请刷新后重试；若再次失败请检查中间体批号是否重复",
        ) from None
    await record_audit_log(
        db,
        action="production.execution.complete",
        user=user,
        resource_type="node_execution",
        resource_id=execution.id,
    )
    refreshed = await repo.get_execution(db, execution_id)
    assert refreshed is not None
    await sync_plan_item_status(db, execution.batch_id)
    # 飞书提醒：下一工序负责人（最后一道工序自动跳过；后台尽力而为）
    schedule_step_completed_notification(batch.id, execution.id, execution.node_id)
    return refreshed


async def backfill_execution_fields(
    db: AsyncSession,
    execution_id: uuid.UUID,
    field_values: list[FieldValueIn],
    user: User | None,
) -> list[NodeFieldValue]:
    """工序结束后补录 end 阶段字段值（upsert）。批次完成后禁止补录。

    filled_at/filled_by 刷新为补录时间与补录人，与首次填报的 created_at/created_by 区分。
    """
    execution = await repo.get_execution(db, execution_id)
    if not execution:
        raise NotFoundException("工序执行", str(execution_id))
    if execution.status != "completed":
        raise AppException(status_code=400, message="仅已结束的工序可补录字段")
    batch = await repo.get_batch(db, execution.batch_id)
    if not batch:
        raise AppException(status_code=400, message="批次不存在或已删除，无法补录")
    if batch.status in ("completed", "cancelled"):
        raise AppException(status_code=400, message="批次已结束后禁止补录")
    if user:
        route_node = await repo.get_nodes_by_ids(db, [execution.node_id])
        node = route_node[0] if route_node else None
        await _require_operator_permission(
            db, user, execution.node_id, batch.route_id,
            node.stage_name if node else None,
            batch=batch,
            execution=execution,
        )
    if not field_values:
        raise AppException(status_code=400, message="没有要补录的字段值")

    defs = await repo.get_field_defs_by_nodes(db, [execution.node_id])
    end_defs = [d for d in defs if d.phase == "end"]
    rows = _build_field_values(
        end_defs, field_values, "end", execution.id, user, enforce_required=False
    )
    values = await _upsert_field_value_rows(db, execution.id, rows, user)
    await db.flush()
    await record_audit_log(
        db,
        action="production.execution.field_backfill",
        user=user,
        resource_type="node_execution",
        resource_id=execution.id,
        extra={"batch_no": batch.batch_no, "fields": [v.field_key for v in field_values]},
    )
    # 已加载的 existing 即返回结果：upsert 就地修改了命中行，新行在 rows 里
    return values


async def abort_execution(
    db: AsyncSession, execution_id: uuid.UUID, user: User | None
) -> NodeExecution:
    execution = await repo.get_execution(db, execution_id)
    if not execution:
        raise NotFoundException("工序执行", str(execution_id))
    if execution.status != "in_progress":
        raise AppException(status_code=400, message="仅进行中的执行可中止")
    if user:
        batch = await repo.get_batch(db, execution.batch_id)
        if batch:
            route_node = await repo.get_nodes_by_ids(db, [execution.node_id])
            node = route_node[0] if route_node else None
            await _require_operator_permission(
                db, user, execution.node_id, batch.route_id,
                node.stage_name if node else None,
                batch=batch,
                execution=execution,
            )
        else:
            # 孤儿执行：批次已删除，回退到纯权限码校验
            # （单次执行负责人豁免与有批次时同口径：可中止自己这一次执行）
            if execution.owner_id != user.id:
                perms = await get_user_permissions(str(user.id), db)
                if "production:batch:submit" not in perms:
                    raise ForbiddenException("缺少 production:batch:submit 权限")
    execution.status = "aborted"
    execution.finished_at = now()
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
    abnormal = _count_abnormal(values)
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


def _count_abnormal(values: list[NodeFieldValue]) -> dict[uuid.UUID, int]:
    """执行 → 异常字段数（仅统计 is_abnormal 的字段值）。"""
    abnormal: dict[uuid.UUID, int] = {}
    for v in values:
        if v.is_abnormal:
            abnormal[v.execution_id] = abnormal.get(v.execution_id, 0) + 1
    return abnormal


async def get_process_board(
    db: AsyncSession, route_id: uuid.UUID
) -> ProcessBoardOut:
    """工序流程看板：路线全部节点 + 计划批次列 + 各节点上"当前位置"的未完成批次。

    工序列按批次当前位置归组：
    - 有 in_progress 执行 → 归入该执行所在节点（正在做）；
    - 无 in_progress 但批次整体未完成 → 归入最近一次已结束执行所在节点（刚做完、等待流转）；
    - 批次整体 completed/cancelled 不展示。
    组内按该节点最近一次活动时间降序。字段/设备随板返回，hover 即时渲染。
    """
    route = await repo.get_route(db, route_id)
    if not route:
        raise NotFoundException("工艺路线", str(route_id))
    nodes = await repo.get_route_nodes(db, route_id)
    node_ids = {n.id for n in nodes}

    batches = await repo.list_active_batches_by_route(db, route_id)
    batch_ids = [b.id for b in batches]

    # 只取本路线节点上的执行（node_id 过滤下推 SQL，避免整表拉取）
    executions = await repo.list_executions_by_batches(
        db, batch_ids, node_ids=list(node_ids),
    )
    execs_by_batch: dict[uuid.UUID, list[NodeExecution]] = defaultdict(list)
    for e in executions:
        execs_by_batch[e.batch_id].append(e)

    # 先在内存中确定各批次锚点执行，再只按锚点查询字段值/设备
    columns: dict[uuid.UUID, list[ProcessBoardExecutionOut]] = {
        n.id: [] for n in nodes
    }
    anchors: list[tuple[Batch, NodeExecution, str]] = []
    for batch in batches:
        bexecs = execs_by_batch.get(batch.id, [])
        if not bexecs:
            continue  # 未到任何工序
        by_node: dict[uuid.UUID, list[NodeExecution]] = defaultdict(list)
        for e in bexecs:
            by_node[e.node_id].append(e)
        # 当前位置：优先取进行中的执行节点；否则取最近一次已结束执行所在节点（等待流转）
        active: dict[uuid.UUID, NodeExecution] = {}
        for nid, es in by_node.items():
            running = [e for e in es if e.status == "in_progress"]
            if running:
                active[nid] = max(running, key=lambda e: e.started_at)
        if active:
            for nid, anchor in active.items():
                anchors.append((batch, anchor, "in_progress"))
        else:
            finished = [e for e in bexecs if e.finished_at is not None]
            if not finished:
                continue
            # finished 已过滤非空，cast 仅为满足 mypy 收窄
            anchor = max(finished, key=lambda e: cast(datetime, e.finished_at))
            state = "aborted" if anchor.status == "aborted" else "waiting"
            anchors.append((batch, anchor, state))

    anchor_ids = [a.id for _, a, _ in anchors]
    values = await repo.get_field_values_by_executions(db, anchor_ids)
    abnormal = _count_abnormal(values)
    equipments = await repo.get_equipments_by_executions(db, anchor_ids)
    eq_map: dict[uuid.UUID, list[EquipmentSnapshotOut]] = defaultdict(list)
    for eq in equipments:
        eq_map[eq.execution_id].append(
            EquipmentSnapshotOut(
                equipment_id=eq.equipment_id,
                equipment_no=eq.equipment_no,
                equipment_name=eq.equipment_name,
            )
        )
    fv_map: dict[uuid.UUID, list[FieldValueOut]] = defaultdict(list)
    for v in values:
        fv_map[v.execution_id].append(FieldValueOut.model_validate(v))

    for batch, anchor, state in anchors:
        columns[anchor.node_id].append(
            ProcessBoardExecutionOut(
                execution_id=anchor.id,
                batch_id=batch.id,
                batch_no=batch.batch_no,
                execution_seq=anchor.execution_seq,
                status=anchor.status,
                board_state=state,
                owner_name=anchor.owner_name,
                started_at=anchor.started_at,
                finished_at=anchor.finished_at,
                is_deviation=anchor.is_deviation,
                abnormal_count=abnormal.get(anchor.id, 0),
                batch_status=batch.status,
                batch_quantity=batch.quantity,
                batch_unit=batch.unit,
                equipments=eq_map.get(anchor.id, []),
                field_values=fv_map.get(anchor.id, []),
            )
        )

    for items in columns.values():
        # 组内按节点最近一次活动时间降序（最新在上）
        items.sort(key=lambda i: i.finished_at or i.started_at, reverse=True)

    planned: list[ProcessBoardPlannedItemOut] = []
    for batch, item, order_no, plan_version in (
        await repo.list_released_plan_batches_by_route(db, route_id)
    ):
        planned.append(
            ProcessBoardPlannedItemOut(
                batch_id=batch.id,
                batch_no=batch.batch_no,
                batch_status=batch.status,
                plan_order_id=item.plan_order_id,
                order_no=order_no,
                plan_version=plan_version,
                item_id=item.id,
                item_no=item.item_no,
                planned_quantity=batch.quantity,
                unit=batch.unit,
                planned_start=item.planned_start,
                planned_end=item.planned_end,
                item_status=item.status,
                priority=item.priority,
                equipment_id=item.equipment_id,
            )
        )

    return ProcessBoardOut(
        route_id=route.id,
        route_name=route.route_name,
        route_status=route.status,
        nodes=[
            ProcessBoardNodeOut(
                id=n.id,
                node_code=n.node_code,
                name=n.name,
                stage_name=n.stage_name,
                sort_order=n.sort_order,
            )
            for n in nodes
        ],
        planned=planned,
        columns=columns,
    )
