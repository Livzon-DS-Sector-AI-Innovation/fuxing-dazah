# 生产工序流水线重叠流转 — 设计文档

**日期**: 2026-07-20
**状态**: 设计中

## 背景

当前生产模块的工序流转约束为：工序 X 必须 `completed` 后才能开始 X+1。但原料药生产中产品为液体，工艺流程更接近流水线——前道工序开始产出后，后道即可开始接收物料继续加工，无需等待前道完全结束。

## 需求

在工艺路线边层级支持"流水线模式"：允许前道工序未完成时开始下一道工序。

### 核心规则

1. 边 `X → X+1` 的 `allow_overlap=true` 时，X 处于 `in_progress` 或 `completed` 即可开始 X+1
2. `is_batch_boundary=true` 的边不允许 `allow_overlap=true`，批次边界必须等待前道完成
3. X 被中止后，不能基于已中止的 X 启动新下游，但已在进行中的下游不受影响
4. 同批次同工序不允许多个并行执行（现有 `has_in_progress_execution` 约束保持不变）
5. `allow_overlap` 作为路线图的一部分，发布时冻结

## 变更设计

### 1. 数据模型 — RouteEdge 加字段

**文件**: `app/modules/production/models/route.py`

```python
# RouteEdge 新增
allow_overlap: Mapped[bool] = mapped_column(
    default=False, comment="允许前道工序未完成时开始本工序（流水线模式）"
)
```

**Migration**: `ALTER TABLE production.route_edges ADD COLUMN allow_overlap BOOLEAN NOT NULL DEFAULT FALSE`

### 2. 核心逻辑 — _check_source_legality 改造

**文件**: `app/modules/production/service/execution_service.py`

```python
async def _check_source_legality(
    db: AsyncSession, batch: Batch, node_id: uuid.UUID
) -> bool:
    nodes = await repo.get_route_nodes(db, batch.route_id)
    edges = await repo.get_route_edges(db, batch.route_id)
    completed = await repo.completed_node_ids(db, batch.id)
    in_progress = await repo.in_progress_node_ids(db, batch.id)

    if not completed and not in_progress:
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
```

**文件**: `app/modules/production/repository/execution.py`

新增 `in_progress_node_ids` 查询（与 `completed_node_ids` 同模式，filter `status='in_progress'`）。

### 3. 边界校验 — 路线图保存

**文件**: `app/modules/production/service/route_service.py`

在 `_validate_graph` 或图保存逻辑中增加：

```python
# is_batch_boundary 边禁止 allow_overlap
for e in edges:
    if e.is_batch_boundary and e.allow_overlap:
        raise AppException(
            status_code=400,
            message=f"批次边界边不允许开启流水线模式",
        )
```

### 4. Schema

**文件**: `app/modules/production/schemas/route.py`

`EdgeOut` 和对应的输入 schema 加 `allow_overlap: bool` 字段。

### 5. 前端

- 路线编辑器边上加 `allow_overlap` Switch
- `is_batch_boundary=true` 时禁用
- Tooltip: "允许前道工序未完成时开始本工序"

## 影响范围

| 文件 | 操作 | 说明 |
|------|------|------|
| `models/route.py` | 修改 | RouteEdge 加 allow_overlap |
| Alembic migration | 新增 | 加列 |
| `repository/execution.py` | 修改 | 新增 in_progress_node_ids |
| `service/execution_service.py` | 修改 | _check_source_legality 改造 |
| `service/route_service.py` | 修改 | 图保存时校验互斥 |
| `schemas/route.py` | 修改 | EdgeOut/EdgeIn 加字段 |

**不涉及**: 批次、中间体、审计等模块。

## 向后兼容

- `allow_overlap` 默认 `false`，现有路线行为不变
- 前端路线编辑器旧数据加载时，缺失字段默认为 `false`
