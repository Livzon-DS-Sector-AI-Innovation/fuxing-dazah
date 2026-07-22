# 生产工序流水线重叠流转 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 RouteEdge 上新增 `allow_overlap` 字段，允许前道工序进行中时开始下一道工序。

**Architecture:** 最小改动——1 个 ORM 字段 + 1 个迁移 + 1 个 repository 查询 + 2 处 service 逻辑 + 1 处 schema。默认 `false`，不影响现有行为。

**Tech Stack:** Python 3.12+, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest

## Global Constraints

- `allow_overlap` 默认 `false`，向后兼容
- `is_batch_boundary=true` 的边禁止 `allow_overlap=true`
- X 中止后不能基于 X 启动新下游，但已在进行中的下游不受影响
- 同批次同工序不允许多个并行执行（现有约束保持不变）

---

### Task 1: Repository — 新增 `in_progress_node_ids` 查询

**Files:**
- Modify: `app/modules/production/repository/execution.py`

**Interfaces:**
- Produces: `async def in_progress_node_ids(db: AsyncSession, batch_id: uuid.UUID) -> set[uuid.UUID]`

`_check_source_legality` 需要知道哪些节点有 `in_progress` 的执行，与已有的 `completed_node_ids` 模式一致。

- [ ] **Step 1: 在 `__all__` 和函数体中添加**

`app/modules/production/repository/execution.py`:

在 `__all__` 列表中加入 `"in_progress_node_ids"`，在 `completed_node_ids` 函数后面添加：

```python
async def in_progress_node_ids(
    db: AsyncSession, batch_id: uuid.UUID
) -> set[uuid.UUID]:
    stmt = select(NodeExecution.node_id).where(
        NodeExecution.batch_id == batch_id,
        NodeExecution.status == "in_progress",
        NodeExecution.is_deleted == False,  # noqa: E712
    )
    return set((await db.execute(stmt)).scalars())
```

- [ ] **Step 2: 验证**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run ruff check app/modules/production/repository/execution.py
```

- [ ] **Step 3: Commit**

```bash
git add app/modules/production/repository/execution.py
git commit -m "feat: 新增 in_progress_node_ids 查询"
```

---

### Task 2: Model — RouteEdge 新增 `allow_overlap` 字段

**Files:**
- Modify: `app/modules/production/models/route.py`

**Interfaces:**
- Produces: `RouteEdge.allow_overlap: Mapped[bool]`

- [ ] **Step 1: 在 RouteEdge 类中添加字段**

在 `RouteEdge` 的 `remark` 字段下方添加：

```python
allow_overlap: Mapped[bool] = mapped_column(
    default=False, comment="允许前道工序未完成时开始本工序（流水线模式）"
)
```

- [ ] **Step 2: 验证**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run ruff check app/modules/production/models/route.py
```

- [ ] **Step 3: Commit**

```bash
git add app/modules/production/models/route.py
git commit -m "feat: RouteEdge 新增 allow_overlap 字段"
```

---

### Task 3: Alembic Migration

**Files:**
- Create: `alembic/versions/<revision>_add_allow_overlap_to_route_edges.py`

- [ ] **Step 1: 拉取最新代码并检查 heads**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && git pull
```

```bash
uv run alembic heads
```

如果多于一个 head，执行：
```bash
uv run alembic merge heads -m "merge heads"
```

- [ ] **Step 2: 升级本地数据库**

```bash
uv run alembic upgrade head
```

- [ ] **Step 3: 生成迁移**

```bash
uv run alembic revision --autogenerate -m "add allow_overlap to route_edges"
```

- [ ] **Step 4: 检查迁移文件**

确认生成的 migration 只包含 `ALTER TABLE production.route_edges ADD COLUMN allow_overlap`，没有其他无关变更。手动清理不需要的 DDL。

`upgrade()` 应类似：
```python
def upgrade() -> None:
    op.add_column(
        'route_edges',
        sa.Column('allow_overlap', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        schema='production'
    )
```

`downgrade()` 应类似：
```python
def downgrade() -> None:
    op.drop_column('route_edges', 'allow_overlap', schema='production')
```

- [ ] **Step 5: 验证迁移可执行**

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

- [ ] **Step 6: 确认只有一个 head**

```bash
uv run alembic heads
```

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/<revision>_add_allow_overlap_to_route_edges.py
git commit -m "feat: 迁移 — route_edges 表新增 allow_overlap 列"
```

---

### Task 4: Schema — EdgeIn / EdgeOut 新增 `allow_overlap`

**Files:**
- Modify: `app/modules/production/schemas/route.py`

**Interfaces:**
- Consumes: `RouteEdge.allow_overlap` from model
- Produces: `EdgeIn.allow_overlap: bool`, `EdgeOut.allow_overlap: bool`

- [ ] **Step 1: EdgeIn 添加字段**

```python
class EdgeIn(BaseModel):
    from_node_code: str
    to_node_code: str
    edge_type: Literal["normal", "rework"] = "normal"
    is_batch_boundary: bool = False
    allow_overlap: bool = False  # 新增
    remark: str | None = Field(default=None, max_length=200)
```

- [ ] **Step 2: EdgeOut 添加字段**

```python
class EdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_node_id: uuid.UUID
    to_node_id: uuid.UUID
    edge_type: str
    is_batch_boundary: bool
    allow_overlap: bool  # 新增
    remark: str | None
```

- [ ] **Step 3: 验证**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run ruff check app/modules/production/schemas/route.py && uv run python -c "from app.modules.production.schemas.route import EdgeIn, EdgeOut; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add app/modules/production/schemas/route.py
git commit -m "feat: EdgeIn/EdgeOut schema 新增 allow_overlap 字段"
```

---

### Task 5: Route Service — save_graph 写入 allow_overlap + 互斥校验

**Files:**
- Modify: `app/modules/production/service/route_service.py:178-189`（边创建）
- Modify: `app/modules/production/service/route_service.py:128-135`（保存前校验）
- Modify: `app/modules/production/service/route_service.py:276-278`（_validate_graph）

**Interfaces:**
- Consumes: `EdgeIn.allow_overlap`
- Produces: `RouteEdge.allow_overlap` persisted

- [ ] **Step 1: save_graph 中边创建时写入 allow_overlap**

将 `save_graph` 中约第 179-189 行的 `RouteEdge(...)` 创建改为：

```python
    for e in graph.edges:
        db.add(
            RouteEdge(
                route_id=route_id,
                from_node_id=node_by_code[e.from_node_code].id,
                to_node_id=node_by_code[e.to_node_code].id,
                edge_type=e.edge_type,
                is_batch_boundary=e.is_batch_boundary,
                allow_overlap=e.allow_overlap,
                remark=e.remark,
                created_by=user.id if user else None,
            )
        )
```

- [ ] **Step 2: save_graph 中添加互斥校验**

在 `save_graph` 现有的 `if e.edge_type == "rework" and e.is_batch_boundary:` 校验后面（约第 135 行后），添加：

```python
        if e.is_batch_boundary and e.allow_overlap:
            raise AppException(
                status_code=400, message="批次边界边不允许开启流水线模式"
            )
```

- [ ] **Step 3: _validate_graph 添加互斥校验**

在 `_validate_graph` 现有的 `if e.edge_type == "rework" and e.is_batch_boundary:` 校验后面（约第 278 行后），添加：

```python
        if e.is_batch_boundary and e.allow_overlap:
            raise AppException(status_code=400, message="批次边界边不允许开启流水线模式")
```

- [ ] **Step 4: 验证**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run ruff check app/modules/production/service/route_service.py
```

- [ ] **Step 5: Commit**

```bash
git add app/modules/production/service/route_service.py
git commit -m "feat: save_graph 写入 allow_overlap 并校验批次边界互斥"
```

---

### Task 6: Route Service — new_version 克隆 allow_overlap

**Files:**
- Modify: `app/modules/production/service/route_service.py:390-401`（边克隆）

- [ ] **Step 1: new_version 边克隆加入 allow_overlap**

将 `new_version` 中约第 390-401 行的边克隆改为：

```python
    for e in edges:
        db.add(
            RouteEdge(
                route_id=new_route.id,
                from_node_id=id_map[e.from_node_id],
                to_node_id=id_map[e.to_node_id],
                edge_type=e.edge_type,
                is_batch_boundary=e.is_batch_boundary,
                allow_overlap=e.allow_overlap,
                remark=e.remark,
                created_by=user.id if user else None,
            )
        )
```

- [ ] **Step 2: 验证**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run ruff check app/modules/production/service/route_service.py
```

- [ ] **Step 3: Commit**

```bash
git add app/modules/production/service/route_service.py
git commit -m "feat: new_version 克隆边时保留 allow_overlap"
```

---

### Task 7: Execution Service — _check_source_legality 核心逻辑

**Files:**
- Modify: `app/modules/production/service/execution_service.py:105-121`

**Interfaces:**
- Consumes: `repo.in_progress_node_ids`, `RouteEdge.allow_overlap`

- [ ] **Step 1: 改写 `_check_source_legality`**

```python
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
```

- [ ] **Step 2: 验证 ruff + mypy**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run ruff check app/modules/production/service/execution_service.py && uv run mypy app/modules/production/service/execution_service.py
```

- [ ] **Step 3: Commit**

```bash
git add app/modules/production/service/execution_service.py
git commit -m "feat: 工序允许前道未完成时流转（allow_overlap）"
```

---

### Task 8: 测试

**Files:**
- Modify: `tests/modules/production/conftest.py`
- Modify: `tests/modules/production/test_execution_service.py`

- [ ] **Step 1: conftest — build_graph_in 加入 allow_overlap 示例边**

在 `conftest.py` 的 `build_graph_in()` 中，将 `B→C` 边改为 `allow_overlap=True`：

```python
edges=[
    EdgeIn(from_node_code="A", to_node_code="B", is_batch_boundary=True),
    EdgeIn(from_node_code="B", to_node_code="C", allow_overlap=True),  # 流水线边
    EdgeIn(from_node_code="C", to_node_code="B", edge_type="rework"),
],
```

- [ ] **Step 2: 添加测试 — allow_overlap 允许 in_progress 前道时开始下游**

在 `test_execution_service.py` 的 `TestStart` 类中添加：

```python
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
```

- [ ] **Step 3: 添加测试 — is_batch_boundary 边不允许 overlap**

```python
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
```

- [ ] **Step 4: 添加测试 — 已中止节点不能启动新下游**

```python
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
```

- [ ] **Step 5: 添加测试 — save_graph 拒绝 is_batch_boundary + allow_overlap**

在 `test_route_service.py` 中添加（先检查该文件内容）：

```python
    async def test_batch_boundary_with_allow_overlap_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """批次边界边不允许开启流水线模式。"""
        product = await route_service.create_product(
            db_session,
            ProductCreate(product_name="测试", product_code=rand_code("P")),
            user=None,
        )
        route = await route_service.create_route(
            db_session, RouteCreate(product_id=product.id, name="V1"), user=None
        )
        graph = build_graph_in()
        # 修改 A→B 边：is_batch_boundary=True + allow_overlap=True
        graph.edges[0].allow_overlap = True
        with pytest.raises(AppException, match="批次边界边不允许"):
            await route_service.save_graph(db_session, route.id, graph, user=None)
```

- [ ] **Step 6: 运行全部生产模块测试**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run pytest tests/modules/production/ -v
```

全部通过。

- [ ] **Step 7: Commit**

```bash
git add tests/modules/production/conftest.py tests/modules/production/test_execution_service.py tests/modules/production/test_route_service.py
git commit -m "test: 流水线重叠流转测试用例"
```

---

### Task 9: 全量验证

- [ ] **Step 1: ruff**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run ruff check .
```

- [ ] **Step 2: mypy**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run mypy app tests
```

- [ ] **Step 3: 全部测试**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run pytest
```

- [ ] **Step 4: alembic heads 确认**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run alembic heads
```

- [ ] **Step 5: 应用启动验证**

```bash
cd /Volumes/NVME/DevProjects/dazah/dazah-backend && uv run python -c "from app.main import app; print(app.title)"
```

- [ ] **Step 6: Commit（如有修复）**
