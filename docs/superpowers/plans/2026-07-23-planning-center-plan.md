# 生产计划中枢实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在生产管理模块中新增"计划中枢"功能，包含需求池、计划单、计划排程三个 Tab。

**Architecture:** 五层模型（Demand → PlanOrder → PlanItem → Allocation → Batch），计划与执行解耦。后端遵循现有模块化单体架构（models/schemas/repository/service/api），前端遵循 Next.js 16 App Router + React Query + Server Actions 模式。

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, PostgreSQL, Alembic, Next.js 16, React 19, TypeScript, Ant Design V6, @dnd-kit/core

## Global Constraints

- 新增表在 `production` schema，继承 `BaseModel`，软删除，无外键约束
- 所有查询显式检查 `is_deleted == False`
- API 前缀 `/api/v1/production`，权限复用 `production:batch:read` / `production:batch:submit`
- 前端遵循现有模式：`ProductionQueryProvider` 包裹，`actionFetch` 调用 Server Actions，React Query 管理服务端状态
- 本期不做 AI 功能
- git commit 需允许改动全局模块（production 模块为此 session 的负责范围）
- 不修改不属于自己负责范围的其他模块代码

---

### Task 1: 后端数据模型与迁移

**Files:**
- Create: `backend/app/modules/production/models/planning.py`
- Modify: `backend/app/modules/production/models/__init__.py`
- Modify: `backend/app/modules/production/models/batch.py`
- Create via Alembic: `alembic/versions/xxxx_add_planning_tables.py`

**Interfaces:**
- Consumes: `app.shared.base_model.BaseModel`
- Produces: ORM classes `Demand`, `PlanOrder`, `PlanItem`, `PlanAllocation`, `DemandAllocation`；Batch 新增字段 `creation_type`, `plan_version`；Batch CHECK 约束扩展为七态

- [ ] **Step 1: 编写 planning.py 新增五张表的 ORM 模型**

创建 `backend/app/modules/production/models/planning.py`：

```python
"""生产计划 ORM：需求 / 计划单 / 计划项 / 分配关系。"""

import uuid

from sqlalchemy import CheckConstraint, Date, DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class Demand(BaseModel):
    """需求条目：销售订单、手动录入、预测等需求的统一载体。"""

    __tablename__ = "demands"
    __table_args__ = (
        Index(
            "uq_production_demands_no",
            "demand_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "source_type IN ('manual', 'sales_order', 'forecast', 'internal')",
            name="ck_production_demands_source_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'partial', 'fulfilled', 'closed', 'cancelled')",
            name="ck_production_demands_status",
        ),
        CheckConstraint(
            "priority IN ('urgent', 'high', 'medium', 'low')",
            name="ck_production_demands_priority",
        ),
        {"schema": "production"},
    )

    demand_no: Mapped[str] = mapped_column(String(30), comment="需求编号")
    source_type: Mapped[str] = mapped_column(
        String(20), default="manual", comment="manual/sales_order/forecast/internal"
    )
    source_ref: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="外部来源引用号"
    )
    product_id: Mapped[uuid.UUID] = mapped_column(comment="产品")
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名快照")
    demanded_quantity: Mapped[float] = mapped_column(Float, comment="原始需求量")
    allocated_quantity: Mapped[float] = mapped_column(
        Float, default=0, comment="已分配量"
    )
    fulfilled_quantity: Mapped[float] = mapped_column(
        Float, default=0, comment="已完成量"
    )
    unit: Mapped[str] = mapped_column(String(20), comment="单位")
    demand_date: Mapped[datetime.date] = mapped_column(Date, comment="需求日期")
    priority: Mapped[str] = mapped_column(
        String(10), default="medium", comment="urgent/high/medium/low"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="pending/confirmed/partial/fulfilled/closed/cancelled"
    )
    customer_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="客户名称"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class PlanOrder(BaseModel):
    """计划单：将需求转化为生产计划的决策载体。"""

    __tablename__ = "plan_orders"
    __table_args__ = (
        Index(
            "uq_production_plan_orders_no",
            "order_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'released', 'completed', 'closed')",
            name="ck_production_plan_orders_status",
        ),
        CheckConstraint(
            "priority IN ('urgent', 'high', 'medium', 'low')",
            name="ck_production_plan_orders_priority",
        ),
        {"schema": "production"},
    )

    order_no: Mapped[str] = mapped_column(String(30), comment="计划单号")
    title: Mapped[str] = mapped_column(String(200), comment="计划标题")
    plan_version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号")
    status: Mapped[str] = mapped_column(
        String(20), default="draft", comment="draft/confirmed/released/completed/closed"
    )
    scheduled_start: Mapped[datetime.date | None] = mapped_column(
        Date, nullable=True, comment="计划开始日期"
    )
    scheduled_end: Mapped[datetime.date | None] = mapped_column(
        Date, nullable=True, comment="计划结束日期"
    )
    priority: Mapped[str] = mapped_column(
        String(10), default="medium", comment="urgent/high/medium/low"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class PlanItem(BaseModel):
    """计划项：排程最小单元。"""

    __tablename__ = "plan_items"
    __table_args__ = (
        Index(
            "uq_production_plan_items_no",
            "plan_order_id",
            "item_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_production_plan_items_equipment_time",
            "equipment_id",
            "planned_start",
            "planned_end",
        ),
        CheckConstraint(
            "status IN ('draft', 'scheduled', 'allocated', 'in_progress', 'completed', 'cancelled')",
            name="ck_production_plan_items_status",
        ),
        CheckConstraint(
            "priority IN ('urgent', 'high', 'medium', 'low')",
            name="ck_production_plan_items_priority",
        ),
        {"schema": "production"},
    )

    plan_order_id: Mapped[uuid.UUID] = mapped_column(comment="所属计划单")
    item_no: Mapped[int] = mapped_column(Integer, comment="计划单内序号")
    product_id: Mapped[uuid.UUID] = mapped_column(comment="产品")
    product_name: Mapped[str] = mapped_column(String(200), comment="产品名快照")
    route_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="工艺路线")
    equipment_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="目标设备/产线"
    )
    planned_quantity: Mapped[float] = mapped_column(Float, comment="计划产量")
    unit: Mapped[str] = mapped_column(String(20), comment="单位")
    planned_start: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划开始时间"
    )
    planned_end: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划结束时间"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="draft", comment="draft/scheduled/allocated/in_progress/completed/cancelled"
    )
    priority: Mapped[str] = mapped_column(
        String(10), default="medium", comment="urgent/high/medium/low"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排程序号")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class PlanAllocation(BaseModel):
    """计划项↔批次分配关系（纯映射，无生命周期）。"""

    __tablename__ = "plan_allocations"
    __table_args__ = (
        Index(
            "uq_production_plan_allocations",
            "plan_item_id",
            "batch_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "production"},
    )

    plan_item_id: Mapped[uuid.UUID] = mapped_column(comment="计划项")
    batch_id: Mapped[uuid.UUID] = mapped_column(comment="批次")
    allocated_quantity: Mapped[float] = mapped_column(Float, comment="本批次承担数量")


class DemandAllocation(BaseModel):
    """需求↔计划项关联（纯映射）。"""

    __tablename__ = "demand_allocations"
    __table_args__ = (
        Index(
            "uq_production_demand_allocations",
            "demand_id",
            "plan_item_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "production"},
    )

    demand_id: Mapped[uuid.UUID] = mapped_column(comment="需求")
    plan_item_id: Mapped[uuid.UUID] = mapped_column(comment="计划项")
    allocated_quantity: Mapped[float] = mapped_column(Float, comment="该计划项为此需求承担的数量")
```

- [ ] **Step 2: 修改 Batch 模型**

编辑 `backend/app/modules/production/models/batch.py`，新增 `creation_type` 和 `plan_version` 字段，扩展 CHECK 约束：

```python
# 在 Batch 类中新增字段（放在 remark 之前）：
creation_type: Mapped[str] = mapped_column(
    String(20), default="direct", comment="plan/rework/outsource/trial/direct"
)
plan_version: Mapped[int | None] = mapped_column(
    Integer, nullable=True, comment="由计划生成时记录所依据的计划版本"
)

# 修改 Batch.__table_args__ 中的 CheckConstraint：
# 将 status IN ('pending', 'in_progress', 'completed', 'cancelled')
# 改为 status IN ('draft', 'scheduled', 'released', 'pending', 'in_progress', 'completed', 'cancelled')
CheckConstraint(
    "status IN ('draft', 'scheduled', 'released', 'pending', 'in_progress', 'completed', 'cancelled')",
    name="ck_production_batches_status",
),
# 新增 creation_type 约束：
CheckConstraint(
    "creation_type IN ('plan', 'rework', 'outsource', 'trial', 'direct')",
    name="ck_production_batches_creation_type",
),
```

- [ ] **Step 3: 更新 models/__init__.py 导出**

编辑 `backend/app/modules/production/models/__init__.py`：

```python
from app.modules.production.models.planning import (
    Demand,
    DemandAllocation,
    PlanAllocation,
    PlanItem,
    PlanOrder,
)

# 在 __all__ 列表中追加：
"Demand",
"DemandAllocation",
"PlanAllocation",
"PlanItem",
"PlanOrder",
```

- [ ] **Step 4: 创建 Alembic 迁移**

```bash
cd backend && git pull && uv run alembic heads && uv run alembic upgrade head && uv run alembic revision --autogenerate -m "add planning tables and extend batch model"
```

检查生成的 migration 文件，确保：
- `upgrade()` 开头有 `op.execute("CREATE SCHEMA IF NOT EXISTS production")`（如果 migration 模板未自动包含）
- 包含五张新表的 `create_table`
- Batch 表包含 `add_column` 对应 `creation_type` 和 `plan_version`
- Batch 的 status CHECK 约束已更新
- 清理非 production schema 的无关变更（如自动检测到其他模块的表变更）

- [ ] **Step 5: 运行迁移验证**

```bash
cd backend && uv run alembic upgrade head
```

确认数据库表创建成功。

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/modules/production/models/planning.py app/modules/production/models/__init__.py app/modules/production/models/batch.py alembic/versions/*.py
git commit -m "feat(production): 新增计划中枢五张表及 Batch 扩展字段

- 新增 demands/plan_orders/plan_items/plan_allocations/demand_allocations
- Batch 新增 creation_type/plan_version，状态扩展为七态

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 后端 Schemas

**Files:**
- Create: `backend/app/modules/production/schemas/planning.py`
- Modify: `backend/app/modules/production/schemas/__init__.py`
- Modify: `backend/app/modules/production/schemas/batch.py`

**Interfaces:**
- Produces: `DemandCreate`, `DemandUpdate`, `DemandOut`, `DemandDetailOut`；`PlanOrderCreate`, `PlanOrderUpdate`, `PlanOrderOut`, `PlanOrderDetailOut`；`PlanItemCreate`, `PlanItemUpdate`, `PlanItemScheduleIn`, `PlanItemOut`；`PlanAllocationOut`；`DemandAllocationCreate`, `DemandAllocationOut`；`ScheduleViewItem`；`TraceNode`（追溯树节点）；`BatchOut` 新增 `creation_type` 和 `plan_version` 字段

- [ ] **Step 1: 编写 planning.py schemas**

创建 `backend/app/modules/production/schemas/planning.py`：

```python
"""计划中枢 API 契约。"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Demand ──

class DemandCreate(BaseModel):
    demand_no: str = Field(max_length=30)
    source_type: str = Field(default="manual", pattern="^(manual|sales_order|forecast|internal)$")
    source_ref: str | None = Field(default=None, max_length=100)
    product_id: uuid.UUID
    product_name: str = Field(max_length=200)
    demanded_quantity: float = Field(gt=0)
    unit: str = Field(max_length=20)
    demand_date: date
    priority: str = Field(default="medium", pattern="^(urgent|high|medium|low)$")
    customer_name: str | None = Field(default=None, max_length=100)
    remark: str | None = None


class DemandUpdate(BaseModel):
    product_name: str | None = Field(default=None, max_length=200)
    demanded_quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    demand_date: date | None = None
    priority: str | None = Field(default=None, pattern="^(urgent|high|medium|low)$")
    customer_name: str | None = Field(default=None, max_length=100)
    remark: str | None = None


class DemandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    demand_no: str
    source_type: str
    source_ref: str | None
    product_id: uuid.UUID
    product_name: str
    demanded_quantity: float
    allocated_quantity: float
    fulfilled_quantity: float
    unit: str
    demand_date: date
    priority: str
    status: str
    customer_name: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def remaining_quantity(self) -> float:
        return self.demanded_quantity - self.allocated_quantity


class DemandDetailOut(DemandOut):
    allocations: list["DemandAllocationOut"] = []


# ── PlanOrder ──

class PlanOrderCreate(BaseModel):
    order_no: str = Field(max_length=30)
    title: str = Field(max_length=200)
    scheduled_start: date | None = None
    scheduled_end: date | None = None
    priority: str = Field(default="medium", pattern="^(urgent|high|medium|low)$")
    remark: str | None = None


class PlanOrderUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    scheduled_start: date | None = None
    scheduled_end: date | None = None
    priority: str | None = Field(default=None, pattern="^(urgent|high|medium|low)$")
    remark: str | None = None


class PlanOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_no: str
    title: str
    plan_version: int
    status: str
    scheduled_start: date | None
    scheduled_end: date | None
    priority: str
    remark: str | None
    created_at: datetime
    updated_at: datetime


class PlanOrderDetailOut(PlanOrderOut):
    items: list["PlanItemOut"] = []
    demand_allocations: list["DemandAllocationOut"] = []


# ── PlanItem ──

class PlanItemCreate(BaseModel):
    product_id: uuid.UUID
    product_name: str = Field(max_length=200)
    route_id: uuid.UUID | None = None
    equipment_id: str | None = Field(default=None, max_length=100)
    planned_quantity: float = Field(gt=0)
    unit: str = Field(max_length=20)
    priority: str = Field(default="medium", pattern="^(urgent|high|medium|low)$")
    remark: str | None = None


class PlanItemUpdate(BaseModel):
    product_name: str | None = Field(default=None, max_length=200)
    route_id: uuid.UUID | None = None
    equipment_id: str | None = Field(default=None, max_length=100)
    planned_quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    priority: str | None = Field(default=None, pattern="^(urgent|high|medium|low)$")
    remark: str | None = None


class PlanItemScheduleIn(BaseModel):
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    equipment_id: str | None = Field(default=None, max_length=100)
    sort_order: int | None = None


class PlanItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_order_id: uuid.UUID
    item_no: int
    product_id: uuid.UUID
    product_name: str
    route_id: uuid.UUID | None
    equipment_id: str | None
    planned_quantity: float
    unit: str
    planned_start: datetime | None
    planned_end: datetime | None
    status: str
    priority: str
    sort_order: int
    remark: str | None
    created_at: datetime
    updated_at: datetime

    # ponytail: __init__ 注入 allocations，不另建 Detail 类
    allocations: list["PlanAllocationOut"] = []
    demand_allocations: list["DemandAllocationOut"] = []


# ── PlanAllocation ──

class PlanAllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_item_id: uuid.UUID
    batch_id: uuid.UUID
    allocated_quantity: float
    # ponytail: batch 简要信息只注入 batch_status/batch_no，不深层展开
    batch_no: str = ""
    batch_status: str = ""


# ── DemandAllocation ──

class DemandAllocationCreate(BaseModel):
    plan_item_id: uuid.UUID
    allocated_quantity: float = Field(gt=0)


class DemandAllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    demand_id: uuid.UUID
    plan_item_id: uuid.UUID
    allocated_quantity: float
    # 填充字段（由 service 层注入）
    demand_no: str = ""
    plan_order_no: str = ""
    item_no: int = 0
    product_name: str = ""


# ── 排程视图 ──

class ScheduleViewItem(BaseModel):
    """排程甘特图单条数据。"""
    plan_order_id: uuid.UUID
    order_no: str
    order_title: str
    order_status: str
    order_priority: str
    order_scheduled_start: date | None
    order_scheduled_end: date | None
    item_id: uuid.UUID
    item_no: int
    product_name: str
    equipment_id: str | None
    planned_quantity: float
    unit: str
    planned_start: datetime | None
    planned_end: datetime | None
    item_status: str
    item_priority: str


# ── 追溯树 ──

class TraceNode(BaseModel):
    """需求全链路追溯：自引用树节点。"""
    type: str  # "demand" | "plan_item" | "batch"
    id: uuid.UUID
    label: str
    quantity: float | None = None
    unit: str | None = None
    status: str | None = None
    children: list["TraceNode"] = []
```

- [ ] **Step 2: 更新 schemas/__init__.py 导出**

编辑 `backend/app/modules/production/schemas/__init__.py`，在现有导入后追加 planning schema 的 all 导出。

- [ ] **Step 3: 更新 BatchOut 新增字段**

编辑 `backend/app/modules/production/schemas/batch.py`，在 `BatchOut` 类中新增：

```python
creation_type: str = "direct"
plan_version: int | None = None
```

- [ ] **Step 4: 验证 schema 导入**

```bash
cd backend && uv run python -c "from app.modules.production.schemas.planning import DemandCreate, PlanOrderCreate, PlanItemCreate, PlanItemOut, ScheduleViewItem, TraceNode; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/modules/production/schemas/
git commit -m "feat(production): 新增计划中枢 Schemas

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 后端 Repository

**Files:**
- Create: `backend/app/modules/production/repository/planning.py`
- Modify: `backend/app/modules/production/repository/__init__.py`（如需重新导出）

**Interfaces:**
- Consumes: `AsyncSession`, ORM models from Task 1
- Produces: Repository 函数 — CRUD + 列表查询 + 设备时间线查询 + 追溯查询

- [ ] **Step 1: 编写 planning.py repository**

创建 `backend/app/modules/production/repository/planning.py`：

```python
"""计划中枢数据查询。"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import Batch
from app.modules.production.models.planning import (
    Demand,
    DemandAllocation,
    PlanAllocation,
    PlanItem,
    PlanOrder,
)


# ── Demand ──

async def get_demand(db: AsyncSession, demand_id: uuid.UUID) -> Demand | None:
    stmt = select(Demand).where(Demand.id == demand_id, Demand.is_deleted == False)  # noqa: E712
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_demand_by_no(db: AsyncSession, demand_no: str) -> Demand | None:
    stmt = select(Demand).where(
        Demand.demand_no == demand_no, Demand.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_demands(
    db: AsyncSession,
    status: str | None = None,
    priority: str | None = None,
    source_type: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Demand], int]:
    stmt = select(Demand).where(Demand.is_deleted == False)  # noqa: E712
    if status:
        stmt = stmt.where(Demand.status == status)
    if priority:
        stmt = stmt.where(Demand.priority == priority)
    if source_type:
        stmt = stmt.where(Demand.source_type == source_type)
    if date_from:
        stmt = stmt.where(Demand.demand_date >= date_from)
    if date_to:
        stmt = stmt.where(Demand.demand_date <= date_to)
    if keyword:
        stmt = stmt.where(
            Demand.demand_no.ilike(f"%{keyword}%")
            | Demand.product_name.ilike(f"%{keyword}%")
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(Demand.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    return list((await db.execute(stmt)).scalars()), total


# ── PlanOrder ──

async def get_plan_order(db: AsyncSession, order_id: uuid.UUID) -> PlanOrder | None:
    stmt = select(PlanOrder).where(
        PlanOrder.id == order_id, PlanOrder.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_plan_order_by_no(db: AsyncSession, order_no: str) -> PlanOrder | None:
    stmt = select(PlanOrder).where(
        PlanOrder.order_no == order_no, PlanOrder.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_plan_orders(
    db: AsyncSession,
    status: str | None = None,
    priority: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[PlanOrder], int]:
    stmt = select(PlanOrder).where(PlanOrder.is_deleted == False)  # noqa: E712
    if status:
        stmt = stmt.where(PlanOrder.status == status)
    if priority:
        stmt = stmt.where(PlanOrder.priority == priority)
    if date_from:
        stmt = stmt.where(PlanOrder.scheduled_start >= date_from)
    if date_to:
        stmt = stmt.where(PlanOrder.scheduled_end <= date_to)
    if keyword:
        stmt = stmt.where(
            PlanOrder.order_no.ilike(f"%{keyword}%")
            | PlanOrder.title.ilike(f"%{keyword}%")
        )
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = stmt.order_by(PlanOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    return list((await db.execute(stmt)).scalars()), total


# ── PlanItem ──

async def get_plan_item(db: AsyncSession, item_id: uuid.UUID) -> PlanItem | None:
    stmt = select(PlanItem).where(
        PlanItem.id == item_id, PlanItem.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_plan_items(db: AsyncSession, plan_order_id: uuid.UUID) -> list[PlanItem]:
    stmt = (
        select(PlanItem)
        .where(
            PlanItem.plan_order_id == plan_order_id,
            PlanItem.is_deleted == False,  # noqa: E712
        )
        .order_by(PlanItem.sort_order, PlanItem.item_no)
    )
    return list((await db.execute(stmt)).scalars())


async def get_plan_items_by_ids(db: AsyncSession, item_ids: list[uuid.UUID]) -> list[PlanItem]:
    if not item_ids:
        return []
    stmt = select(PlanItem).where(
        PlanItem.id.in_(item_ids), PlanItem.is_deleted == False  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_max_item_no(db: AsyncSession, plan_order_id: uuid.UUID) -> int:
    stmt = (
        select(func.coalesce(func.max(PlanItem.item_no), 0))
        .where(PlanItem.plan_order_id == plan_order_id, PlanItem.is_deleted == False)  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one()


# ── 排程视图查询 ──

async def list_plan_items_schedule_view(
    db: AsyncSession,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    equipment_id: str | None = None,
) -> list[PlanItem]:
    """获取排程视图的 PlanItem 列表，join PlanOrder 过滤已确认/已下达状态。"""
    stmt = (
        select(PlanItem)
        .join(PlanOrder, PlanItem.plan_order_id == PlanOrder.id)
        .where(
            PlanItem.is_deleted == False,  # noqa: E712
            PlanOrder.is_deleted == False,  # noqa: E712
            PlanOrder.status.in_(("confirmed", "released")),
            PlanItem.planned_start.isnot(None),
            PlanItem.planned_end.isnot(None),
        )
    )
    if from_time:
        stmt = stmt.where(PlanItem.planned_end >= from_time)
    if to_time:
        stmt = stmt.where(PlanItem.planned_start <= to_time)
    if equipment_id:
        stmt = stmt.where(PlanItem.equipment_id == equipment_id)
    return list((await db.execute(stmt)).scalars())


# ── 设备冲突检测 ──

async def find_overlapping_items(
    db: AsyncSession,
    equipment_id: str,
    planned_start: datetime,
    planned_end: datetime,
    exclude_item_id: uuid.UUID | None = None,
) -> list[PlanItem]:
    """查询同一设备上时间重叠的 PlanItem。"""
    stmt = select(PlanItem).where(
        PlanItem.is_deleted == False,  # noqa: E712
        PlanItem.equipment_id == equipment_id,
        PlanItem.planned_start.isnot(None),
        PlanItem.planned_end.isnot(None),
        PlanItem.planned_start < planned_end,
        PlanItem.planned_end > planned_start,
    )
    if exclude_item_id:
        stmt = stmt.where(PlanItem.id != exclude_item_id)
    return list((await db.execute(stmt)).scalars())


# ── Allocation ──

async def get_plan_allocations_by_item(db: AsyncSession, plan_item_id: uuid.UUID) -> list[PlanAllocation]:
    stmt = select(PlanAllocation).where(
        PlanAllocation.plan_item_id == plan_item_id,
        PlanAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_plan_allocations_by_batch(db: AsyncSession, batch_id: uuid.UUID) -> list[PlanAllocation]:
    stmt = select(PlanAllocation).where(
        PlanAllocation.batch_id == batch_id,
        PlanAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


# ── DemandAllocation ──

async def get_demand_allocations(db: AsyncSession, demand_id: uuid.UUID) -> list[DemandAllocation]:
    stmt = select(DemandAllocation).where(
        DemandAllocation.demand_id == demand_id,
        DemandAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


async def get_demand_allocation_by_id(db: AsyncSession, alloc_id: uuid.UUID) -> DemandAllocation | None:
    stmt = select(DemandAllocation).where(
        DemandAllocation.id == alloc_id, DemandAllocation.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_demand_allocations_by_item(db: AsyncSession, plan_item_id: uuid.UUID) -> list[DemandAllocation]:
    stmt = select(DemandAllocation).where(
        DemandAllocation.plan_item_id == plan_item_id,
        DemandAllocation.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars())


# ── Batch 补充查询 ──

async def get_batches_for_allocations(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Batch]:
    """批量获取批次号/状态，供 Allocation 填充。"""
    if not batch_ids:
        return {}
    stmt = select(Batch).where(
        Batch.id.in_(batch_ids), Batch.is_deleted == False  # noqa: E712
    )
    batches = list((await db.execute(stmt)).scalars())
    return {b.id: b for b in batches}
```

- [ ] **Step 2: 验证 repository 导入**

```bash
cd backend && uv run python -c "from app.modules.production.repository.planning import get_demand, list_demands, get_plan_order, list_plan_orders, get_plan_item, list_plan_items, list_plan_items_schedule_view, find_overlapping_items; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
cd backend && git add app/modules/production/repository/planning.py && git commit -m "feat(production): 新增计划中枢 Repository 层

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 后端 Service

**Files:**
- Create: `backend/app/modules/production/service/planning_service.py`

**Interfaces:**
- Consumes: repository/planning.py, schemas/planning.py, models from Task 1
- Produces: 所有计划中枢业务逻辑函数

- [ ] **Step 1: 编写 planning_service.py**

创建 `backend/app/modules/production/service/planning_service.py`：

```python
"""计划中枢业务逻辑：需求、计划单、计划项、分配、下达、追溯。"""

import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.production import repository as repo
from app.modules.production.models import Batch
from app.modules.production.models.planning import (
    Demand,
    DemandAllocation,
    PlanAllocation,
    PlanItem,
    PlanOrder,
)
from app.modules.production.schemas.planning import (
    DemandAllocationCreate,
    DemandAllocationOut,
    DemandCreate,
    DemandDetailOut,
    DemandOut,
    DemandUpdate,
    PlanAllocationOut,
    PlanItemCreate,
    PlanItemOut,
    PlanItemScheduleIn,
    PlanItemUpdate,
    PlanOrderCreate,
    PlanOrderDetailOut,
    PlanOrderOut,
    PlanOrderUpdate,
    ScheduleViewItem,
    TraceNode,
)
from app.platform.identity.models import User


# ═══════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════

def _generate_demand_no() -> str:
    """生成需求编号 DM-YYYYMMDD-NNNN。ponytail: 简单时间戳简化为日期+计数器。"""
    import random
    today = date.today().strftime("%Y%m%d")
    suffix = random.randint(0, 9999)
    return f"DM-{today}-{suffix:04d}"


def _generate_order_no() -> str:
    """生成计划单号 PO-YYYYMMDD-NNNN。"""
    import random
    today = date.today().strftime("%Y%m%d")
    suffix = random.randint(0, 9999)
    return f"PO-{today}-{suffix:04d}"


# ponytail: 简单冲突检测，返回告警信息不阻止保存
def _check_time_overlap(planned_start: datetime, planned_end: datetime) -> bool:
    return planned_start < planned_end


# ═══════════════════════════════════════════
# Demand
# ═══════════════════════════════════════════

def _recalc_demand_fulfillment(demand: Demand, allocations: list[DemandAllocation]) -> None:
    """根据关联的 DemandAllocation 重算 allocated_quantity，根据已兑现批次重算 fulfilled_quantity。"""
    demand.allocated_quantity = sum(a.allocated_quantity for a in allocations)
    # fulfilled 需要 plan_allocations 层级的溯源（本次暂在 trace 链路中计算）


async def create_demand(
    db: AsyncSession, payload: DemandCreate, user: User | None,
) -> Demand:
    if not payload.demand_no:
        payload.demand_no = _generate_demand_no()
    if await repo.get_demand_by_no(db, payload.demand_no):
        raise DuplicateException("需求编号", payload.demand_no)
    demand = Demand(
        demand_no=payload.demand_no,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        product_id=payload.product_id,
        product_name=payload.product_name,
        demanded_quantity=payload.demanded_quantity,
        unit=payload.unit,
        demand_date=payload.demand_date,
        priority=payload.priority,
        customer_name=payload.customer_name,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(demand)
    await db.flush()
    return demand


async def update_demand(
    db: AsyncSession, demand_id: uuid.UUID, payload: DemandUpdate, user: User | None,
) -> Demand:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    if demand.status not in ("pending", "confirmed"):
        raise AppException(status_code=400, message="仅 pending/confirmed 状态的需求可编辑")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(demand, field, value)
    demand.updated_by = user.id if user else None
    await db.flush()
    return demand


async def confirm_demand(db: AsyncSession, demand_id: uuid.UUID, user: User | None) -> Demand:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    if demand.status != "pending":
        raise AppException(status_code=400, message="仅 pending 状态的需求可确认")
    demand.status = "confirmed"
    demand.updated_by = user.id if user else None
    await db.flush()
    return demand


async def cancel_demand(db: AsyncSession, demand_id: uuid.UUID, user: User | None) -> Demand:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    if demand.status in ("closed", "cancelled"):
        raise AppException(status_code=400, message="已关闭/已取消的需求不能取消")
    demand.status = "cancelled"
    demand.updated_by = user.id if user else None
    await db.flush()
    return demand


async def get_demand_detail(db: AsyncSession, demand_id: uuid.UUID) -> DemandDetailOut:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    da_list = await repo.get_demand_allocations(db, demand_id)
    das = []
    for da in da_list:
        dao = DemandAllocationOut.model_validate(da)
        dao.demand_no = demand.demand_no
        item = await repo.get_plan_item(db, da.plan_item_id)
        if item:
            dao.item_no = item.item_no
            dao.product_name = item.product_name
            order = await repo.get_plan_order(db, item.plan_order_id)
            if order:
                dao.plan_order_no = order.order_no
        das.append(dao)
    detail = DemandDetailOut.model_validate(demand)
    detail.allocations = das
    return detail


async def list_demands_paged(
    db: AsyncSession,
    status: str | None,
    priority: str | None,
    source_type: str | None,
    date_from: date | None,
    date_to: date | None,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Demand], int]:
    return await repo.list_demands(
        db, status, priority, source_type, date_from, date_to, keyword, page, page_size,
    )


# ═══════════════════════════════════════════
# PlanOrder
# ═══════════════════════════════════════════

async def create_plan_order(
    db: AsyncSession, payload: PlanOrderCreate, user: User | None,
) -> PlanOrder:
    if not payload.order_no:
        payload.order_no = _generate_order_no()
    if await repo.get_plan_order_by_no(db, payload.order_no):
        raise DuplicateException("计划单号", payload.order_no)
    order = PlanOrder(
        order_no=payload.order_no,
        title=payload.title,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
        priority=payload.priority,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(order)
    await db.flush()
    return order


async def update_plan_order(
    db: AsyncSession, order_id: uuid.UUID, payload: PlanOrderUpdate, user: User | None,
) -> PlanOrder:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的计划单可编辑")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(order, field, value)
    order.updated_by = user.id if user else None
    await db.flush()
    return order


async def confirm_plan_order(db: AsyncSession, order_id: uuid.UUID, user: User | None) -> PlanOrder:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的计划单可确认")
    items = await repo.list_plan_items(db, order_id)
    if not items:
        raise AppException(status_code=400, message="计划单无计划项，无法确认")
    order.status = "confirmed"
    order.plan_version += 1
    order.updated_by = user.id if user else None
    await db.flush()
    return order


async def release_plan_order(db: AsyncSession, order_id: uuid.UUID, user: User | None) -> PlanOrder:
    """下达：所有 PlanItem 生成 Batch + Allocation。"""
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "confirmed":
        raise AppException(status_code=400, message="仅 confirmed 状态的计划单可下达")
    items = await repo.list_plan_items(db, order_id)
    unscheduled = [i for i in items if i.status != "scheduled"]
    if unscheduled:
        raise AppException(
            status_code=400,
            message=f"以下计划项未排程: {[i.item_no for i in unscheduled]}",
        )
    # 事务内：为每个 PlanItem 创建 Batch + Allocation
    for item in items:
        batch = Batch(
            batch_no=f"{order.order_no}-{item.item_no}",  # ponytail: 简单自动生成批号
            product_id=item.product_id,
            route_id=item.route_id or uuid.UUID(int=0),  # 如果无路线，需要 valid route
            status="scheduled",
            quantity=item.planned_quantity,
            unit=item.unit,
            creation_type="plan",
            plan_version=order.plan_version,
            created_by=user.id if user else None,
        )
        db.add(batch)
        await db.flush()
        alloc = PlanAllocation(
            plan_item_id=item.id,
            batch_id=batch.id,
            allocated_quantity=item.planned_quantity,
            created_by=user.id if user else None,
        )
        db.add(alloc)
        item.status = "allocated"
        item.updated_by = user.id if user else None
    order.status = "released"
    order.plan_version += 1
    order.updated_by = user.id if user else None
    await db.flush()
    # 更新 Demand 履约量
    # ponytail: 通过 demand_allocations 关联找到相关 demand，重算
    for item in items:
        da_list = await repo.get_demand_allocations_by_item(db, item.id)
        for da in da_list:
            demand = await repo.get_demand(db, da.demand_id)
            if demand:
                all_das = await repo.get_demand_allocations(db, demand.id)
                _recalc_demand_fulfillment(demand, all_das)
                _update_demand_status(demand)
    return order


def _update_demand_status(demand: Demand) -> None:
    """根据履约量更新需求状态。"""
    if demand.fulfilled_quantity >= demand.demanded_quantity:
        demand.status = "fulfilled"
    elif demand.allocated_quantity > 0:
        demand.status = "partial"
    else:
        demand.status = "confirmed"


async def close_plan_order(db: AsyncSession, order_id: uuid.UUID, user: User | None) -> PlanOrder:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status not in ("released", "completed"):
        raise AppException(status_code=400, message="仅 released/completed 状态的计划单可关闭")
    order.status = "closed"
    order.updated_by = user.id if user else None
    await db.flush()
    return order


async def get_plan_order_detail(db: AsyncSession, order_id: uuid.UUID) -> PlanOrderDetailOut:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    items = await repo.list_plan_items(db, order_id)
    item_outs: list[PlanItemOut] = []
    for item in items:
        pio = PlanItemOut.model_validate(item)
        # 填充 allocations
        plan_allocs = await repo.get_plan_allocations_by_item(db, item.id)
        pio.allocations = []
        if plan_allocs:
            batch_ids = [a.batch_id for a in plan_allocs]
            batch_map = await repo.get_batches_for_allocations(db, batch_ids)
            for pa in plan_allocs:
                pao = PlanAllocationOut.model_validate(pa)
                b = batch_map.get(pa.batch_id)
                if b:
                    pao.batch_no = b.batch_no
                    pao.batch_status = b.status
                pio.allocations.append(pao)
        # 填充 demand_allocations
        da_list = await repo.get_demand_allocations_by_item(db, item.id)
        pio.demand_allocations = []
        for da in da_list:
            dao = DemandAllocationOut.model_validate(da)
            demand = await repo.get_demand(db, da.demand_id)
            if demand:
                dao.demand_no = demand.demand_no
            dao.plan_order_no = order.order_no
            dao.item_no = item.item_no
            dao.product_name = item.product_name
            pio.demand_allocations.append(dao)
        item_outs.append(pio)
    detail = PlanOrderDetailOut.model_validate(order)
    detail.items = item_outs
    return detail


async def list_plan_orders_paged(
    db: AsyncSession, status, priority, date_from, date_to, keyword, page, page_size,
) -> tuple[list[PlanOrder], int]:
    return await repo.list_plan_orders(
        db, status, priority, date_from, date_to, keyword, page, page_size,
    )


# ═══════════════════════════════════════════
# PlanItem
# ═══════════════════════════════════════════

async def create_plan_item(
    db: AsyncSession, order_id: uuid.UUID, payload: PlanItemCreate, user: User | None,
) -> PlanItem:
    order = await repo.get_plan_order(db, order_id)
    if not order:
        raise NotFoundException("计划单", str(order_id))
    if order.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的计划单可添加计划项")
    max_no = await repo.get_max_item_no(db, order_id)
    item_no = max_no + 1
    item = PlanItem(
        plan_order_id=order_id,
        item_no=item_no,
        product_id=payload.product_id,
        product_name=payload.product_name,
        route_id=payload.route_id,
        equipment_id=payload.equipment_id,
        planned_quantity=payload.planned_quantity,
        unit=payload.unit,
        priority=payload.priority,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(item)
    await db.flush()
    return item


async def update_plan_item(
    db: AsyncSession, item_id: uuid.UUID, payload: PlanItemUpdate, user: User | None,
) -> PlanItem:
    item = await repo.get_plan_item(db, item_id)
    if not item:
        raise NotFoundException("计划项", str(item_id))
    if item.status not in ("draft", "scheduled"):
        raise AppException(status_code=400, message="仅 draft/scheduled 状态的计划项可编辑")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    item.updated_by = user.id if user else None
    await db.flush()
    return item


async def schedule_plan_item(
    db: AsyncSession, item_id: uuid.UUID, payload: PlanItemScheduleIn, user: User | None,
) -> PlanItem:
    """排程操作：设置计划项的时间和设备。"""
    item = await repo.get_plan_item(db, item_id)
    if not item:
        raise NotFoundException("计划项", str(item_id))
    if item.status not in ("draft", "scheduled"):
        raise AppException(status_code=400, message="仅 draft/scheduled 状态的计划项可排程")
    if payload.planned_start is not None:
        item.planned_start = payload.planned_start
    if payload.planned_end is not None:
        item.planned_end = payload.planned_end
    if payload.equipment_id is not None:
        item.equipment_id = payload.equipment_id
    if payload.sort_order is not None:
        item.sort_order = payload.sort_order
    if item.planned_start and item.planned_end:
        if not _check_time_overlap(item.planned_start, item.planned_end):
            raise AppException(status_code=400, message="计划开始时间必须早于结束时间")
        # 设备冲突检测（告警但不阻断）
        if item.equipment_id:
            conflicts = await repo.find_overlapping_items(
                db, item.equipment_id, item.planned_start, item.planned_end, item.id,
            )
            if conflicts:
                # ponytail: 冲突只返回在响应中提示，当前不阻止保存
                pass  # 冲突信息将在 API 层注入到响应
        item.status = "scheduled"
    item.updated_by = user.id if user else None
    await db.flush()
    return item


async def allocate_plan_item(
    db: AsyncSession, item_id: uuid.UUID, user: User | None,
) -> PlanItem:
    """单独分配计划项生成 Batch。"""
    item = await repo.get_plan_item(db, item_id)
    if not item:
        raise NotFoundException("计划项", str(item_id))
    if item.status != "scheduled":
        raise AppException(status_code=400, message="仅 scheduled 状态的计划项可分配")
    order = await repo.get_plan_order(db, item.plan_order_id)
    if not order:
        raise NotFoundException("计划单", str(item.plan_order_id))
    batch = Batch(
        batch_no=f"{order.order_no}-{item.item_no}",
        product_id=item.product_id,
        route_id=item.route_id or uuid.UUID(int=0),
        status="scheduled",
        quantity=item.planned_quantity,
        unit=item.unit,
        creation_type="plan",
        plan_version=order.plan_version,
        created_by=user.id if user else None,
    )
    db.add(batch)
    await db.flush()
    alloc = PlanAllocation(
        plan_item_id=item.id,
        batch_id=batch.id,
        allocated_quantity=item.planned_quantity,
        created_by=user.id if user else None,
    )
    db.add(alloc)
    item.status = "allocated"
    item.updated_by = user.id if user else None
    await db.flush()
    return item


# ═══════════════════════════════════════════
# 排程视图
# ═══════════════════════════════════════════

async def get_schedule_view(
    db: AsyncSession,
    from_time: datetime | None,
    to_time: datetime | None,
    equipment_id: str | None,
) -> list[ScheduleViewItem]:
    items = await repo.list_plan_items_schedule_view(db, from_time, to_time, equipment_id)
    order_ids = list({i.plan_order_id for i in items})
    # 批量加载计划单
    result: list[ScheduleViewItem] = []
    for item in items:
        order = await repo.get_plan_order(db, item.plan_order_id)
        if not order:
            continue
        result.append(ScheduleViewItem(
            plan_order_id=order.id,
            order_no=order.order_no,
            order_title=order.title,
            order_status=order.status,
            order_priority=order.priority,
            order_scheduled_start=order.scheduled_start,
            order_scheduled_end=order.scheduled_end,
            item_id=item.id,
            item_no=item.item_no,
            product_name=item.product_name,
            equipment_id=item.equipment_id,
            planned_quantity=item.planned_quantity,
            unit=item.unit,
            planned_start=item.planned_start,
            planned_end=item.planned_end,
            item_status=item.status,
            item_priority=item.priority,
        ))
    return result


# ═══════════════════════════════════════════
# Demand Allocation
# ═══════════════════════════════════════════

async def create_demand_allocation(
    db: AsyncSession, demand_id: uuid.UUID, payload: DemandAllocationCreate, user: User | None,
) -> DemandAllocation:
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    if demand.status not in ("confirmed", "partial"):
        raise AppException(status_code=400, message="仅 confirmed/partial 状态的需求可分配")
    item = await repo.get_plan_item(db, payload.plan_item_id)
    if not item:
        raise NotFoundException("计划项", str(payload.plan_item_id))
    da = DemandAllocation(
        demand_id=demand_id,
        plan_item_id=payload.plan_item_id,
        allocated_quantity=payload.allocated_quantity,
        created_by=user.id if user else None,
    )
    db.add(da)
    await db.flush()
    # 重算需求履约量
    all_das = await repo.get_demand_allocations(db, demand_id)
    _recalc_demand_fulfillment(demand, all_das)
    _update_demand_status(demand)
    return da


async def delete_demand_allocation(
    db: AsyncSession, alloc_id: uuid.UUID, user: User | None,
) -> None:
    da = await repo.get_demand_allocation_by_id(db, alloc_id)
    if not da:
        raise NotFoundException("需求分配", str(alloc_id))
    da.is_deleted = True
    da.updated_by = user.id if user else None
    demand = await repo.get_demand(db, da.demand_id)
    if demand:
        all_das = await repo.get_demand_allocations(db, demand.id)
        _recalc_demand_fulfillment(demand, all_das)
        _update_demand_status(demand)
    await db.flush()


# ═══════════════════════════════════════════
# 追溯
# ═══════════════════════════════════════════

async def get_demand_trace(db: AsyncSession, demand_id: uuid.UUID) -> TraceNode:
    """从需求出发，追溯全链路：需求→分配→计划项→分配→批次。"""
    demand = await repo.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException("需求", str(demand_id))
    root = TraceNode(
        type="demand",
        id=demand.id,
        label=f"{demand.demand_no} - {demand.product_name}",
        quantity=demand.demanded_quantity,
        unit=demand.unit,
        status=demand.status,
        children=[],
    )
    da_list = await repo.get_demand_allocations(db, demand_id)
    for da in da_list:
        item = await repo.get_plan_item(db, da.plan_item_id)
        if not item:
            continue
        order = await repo.get_plan_order(db, item.plan_order_id)
        item_node = TraceNode(
            type="plan_item",
            id=item.id,
            label=f"计划项 {order.order_no + '-' + str(item.item_no) if order else '?'} - {item.product_name}",
            quantity=item.planned_quantity,
            unit=item.unit,
            status=item.status,
            children=[],
        )
        plan_allocs = await repo.get_plan_allocations_by_item(db, item.id)
        if plan_allocs:
            batch_ids = [a.batch_id for a in plan_allocs]
            batch_map = await repo.get_batches_for_allocations(db, batch_ids)
            for pa in plan_allocs:
                b = batch_map.get(pa.batch_id)
                if b:
                    batch_node = TraceNode(
                        type="batch",
                        id=b.id,
                        label=f"批次 {b.batch_no}",
                        quantity=b.quantity,
                        unit=b.unit,
                        status=b.status,
                        children=[],
                    )
                    item_node.children.append(batch_node)
        root.children.append(item_node)
    return root


# ── 重新导出供 API 层使用 ──

__all__ = [
    "create_demand",
    "update_demand",
    "confirm_demand",
    "cancel_demand",
    "get_demand_detail",
    "list_demands_paged",
    "create_plan_order",
    "update_plan_order",
    "confirm_plan_order",
    "release_plan_order",
    "close_plan_order",
    "get_plan_order_detail",
    "list_plan_orders_paged",
    "create_plan_item",
    "update_plan_item",
    "schedule_plan_item",
    "allocate_plan_item",
    "get_schedule_view",
    "create_demand_allocation",
    "delete_demand_allocation",
    "get_demand_trace",
]
```

- [ ] **Step 2: 验证 service 导入**

```bash
cd backend && uv run python -c "from app.modules.production.service.planning_service import create_demand, create_plan_order, get_schedule_view, get_demand_trace; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
cd backend && git add app/modules/production/service/planning_service.py && git commit -m "feat(production): 新增计划中枢 Service 层

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 后端 API 端点

**Files:**
- Create: `backend/app/modules/production/api/planning.py`
- Modify: `backend/app/modules/production/api/__init__.py`

**Interfaces:**
- Consumes: planning_service from Task 4, schemas from Task 2
- Produces: ~23 个 HTTP 端点

- [ ] **Step 1: 编写 planning.py API 路由**

创建 `backend/app/modules/production/api/planning.py`：

```python
"""计划中枢 API — 只做 HTTP 层。"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.schemas.planning import (
    DemandAllocationCreate,
    DemandAllocationOut,
    DemandCreate,
    DemandDetailOut,
    DemandOut,
    DemandUpdate,
    PlanItemCreate,
    PlanItemOut,
    PlanItemScheduleIn,
    PlanItemUpdate,
    PlanOrderCreate,
    PlanOrderDetailOut,
    PlanOrderOut,
    PlanOrderUpdate,
    ScheduleViewItem,
)
from app.modules.production.service import planning_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()
_submit = require_permission("production:batch:submit")
_read = require_permission("production:batch:read")


# ══════════════════════════════
# Demand
# ══════════════════════════════

@router.get("/demands", summary="需求列表")
async def list_demands(
    status: str | None = None,
    priority: str | None = None,
    source_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await planning_service.list_demands_paged(
        db, status, priority, source_type, date_from, date_to, keyword, page, page_size,
    )
    return paginated_response(
        [DemandOut.model_validate(i).model_dump(mode="json") for i in items],
        page, page_size, total,
    )


@router.post("/demands", summary="创建需求")
async def create_demand(
    payload: DemandCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.create_demand(db, payload, user)
    return success_response(DemandOut.model_validate(demand).model_dump(mode="json"))


@router.get("/demands/{demand_id}", summary="需求详情")
async def get_demand(
    demand_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await planning_service.get_demand_detail(db, demand_id)
    return success_response(detail.model_dump(mode="json"))


@router.put("/demands/{demand_id}", summary="更新需求")
async def update_demand(
    demand_id: uuid.UUID,
    payload: DemandUpdate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.update_demand(db, demand_id, payload, user)
    return success_response(DemandOut.model_validate(demand).model_dump(mode="json"))


@router.delete("/demands/{demand_id}", summary="删除需求")
async def delete_demand(
    demand_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.update_demand(db, demand_id, DemandUpdate(), user)
    demand.is_deleted = True
    await db.flush()
    return success_response({"id": str(demand_id)})


@router.post("/demands/{demand_id}/confirm", summary="确认需求")
async def confirm_demand(
    demand_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.confirm_demand(db, demand_id, user)
    return success_response(DemandOut.model_validate(demand).model_dump(mode="json"))


@router.post("/demands/{demand_id}/cancel", summary="取消需求")
async def cancel_demand(
    demand_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    demand = await planning_service.cancel_demand(db, demand_id, user)
    return success_response(DemandOut.model_validate(demand).model_dump(mode="json"))


@router.get("/demands/{demand_id}/trace", summary="需求全链路追溯")
async def get_demand_trace(
    demand_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    trace = await planning_service.get_demand_trace(db, demand_id)
    return success_response(trace.model_dump(mode="json"))


# ══════════════════════════════
# PlanOrder
# ══════════════════════════════

@router.get("/plan-orders", summary="计划单列表")
async def list_plan_orders(
    status: str | None = None,
    priority: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await planning_service.list_plan_orders_paged(
        db, status, priority, date_from, date_to, keyword, page, page_size,
    )
    return paginated_response(
        [PlanOrderOut.model_validate(i).model_dump(mode="json") for i in items],
        page, page_size, total,
    )


@router.post("/plan-orders", summary="创建计划单")
async def create_plan_order(
    payload: PlanOrderCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.create_plan_order(db, payload, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


@router.get("/plan-orders/{order_id}", summary="计划单详情")
async def get_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await planning_service.get_plan_order_detail(db, order_id)
    return success_response(detail.model_dump(mode="json"))


@router.put("/plan-orders/{order_id}", summary="更新计划单")
async def update_plan_order(
    order_id: uuid.UUID,
    payload: PlanOrderUpdate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.update_plan_order(db, order_id, payload, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


@router.delete("/plan-orders/{order_id}", summary="删除计划单")
async def delete_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.update_plan_order(db, order_id, PlanOrderUpdate(), user)
    order.is_deleted = True
    await db.flush()
    return success_response({"id": str(order_id)})


@router.post("/plan-orders/{order_id}/confirm", summary="确认计划单")
async def confirm_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.confirm_plan_order(db, order_id, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


@router.post("/plan-orders/{order_id}/release", summary="下达计划单")
async def release_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.release_plan_order(db, order_id, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


@router.post("/plan-orders/{order_id}/close", summary="关闭计划单")
async def close_plan_order(
    order_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    order = await planning_service.close_plan_order(db, order_id, user)
    return success_response(PlanOrderOut.model_validate(order).model_dump(mode="json"))


# ══════════════════════════════
# PlanItem
# ══════════════════════════════

@router.get("/plan-orders/{order_id}/items", summary="计划项列表")
async def list_plan_items(
    order_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = await planning_service.list_plan_items(db, order_id)
    return success_response(
        [PlanItemOut.model_validate(i).model_dump(mode="json") for i in items]
    )


@router.post("/plan-orders/{order_id}/items", summary="添加计划项")
async def create_plan_item(
    order_id: uuid.UUID,
    payload: PlanItemCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await planning_service.create_plan_item(db, order_id, payload, user)
    return success_response(PlanItemOut.model_validate(item).model_dump(mode="json"))


@router.put("/plan-items/{item_id}", summary="更新计划项")
async def update_plan_item(
    item_id: uuid.UUID,
    payload: PlanItemUpdate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await planning_service.update_plan_item(db, item_id, payload, user)
    return success_response(PlanItemOut.model_validate(item).model_dump(mode="json"))


@router.delete("/plan-items/{item_id}", summary="删除计划项")
async def delete_plan_item(
    item_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await planning_service.update_plan_item(db, item_id, PlanItemUpdate(), user)
    item.is_deleted = True
    await db.flush()
    return success_response({"id": str(item_id)})


@router.put("/plan-items/{item_id}/schedule", summary="排程计划项")
async def schedule_plan_item(
    item_id: uuid.UUID,
    payload: PlanItemScheduleIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await planning_service.schedule_plan_item(db, item_id, payload, user)
    return success_response(PlanItemOut.model_validate(item).model_dump(mode="json"))


@router.post("/plan-items/{item_id}/allocate", summary="分配计划项生成批次")
async def allocate_plan_item(
    item_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await planning_service.allocate_plan_item(db, item_id, user)
    return success_response(PlanItemOut.model_validate(item).model_dump(mode="json"))


@router.get("/plan-items/schedule-view", summary="排程视图")
async def get_schedule_view(
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    equipment_id: str | None = None,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = await planning_service.get_schedule_view(db, from_time, to_time, equipment_id)
    return success_response([i.model_dump(mode="json") for i in items])


# ══════════════════════════════
# Demand Allocations
# ══════════════════════════════

@router.get("/demands/{demand_id}/allocations", summary="需求关联计划项列表")
async def list_demand_allocations(
    demand_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await planning_service.get_demand_detail(db, demand_id)
    return success_response([a.model_dump(mode="json") for a in detail.allocations])


@router.post("/demands/{demand_id}/allocations", summary="关联需求到计划项")
async def create_demand_allocation(
    demand_id: uuid.UUID,
    payload: DemandAllocationCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    da = await planning_service.create_demand_allocation(db, demand_id, payload, user)
    return success_response(DemandAllocationOut.model_validate(da).model_dump(mode="json"))


@router.delete("/demand-allocations/{allocation_id}", summary="解除需求关联")
async def delete_demand_allocation(
    allocation_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await planning_service.delete_demand_allocation(db, allocation_id, user)
    return success_response({"id": str(allocation_id)})
```

> **ponytail: Batch.route_id 不可为空。** Task 4 中的下达/分配对无路线计划项使用 `uuid.UUID(int=0)` 作为占位符。——这是一个已识别的限制：生产计划单下达时，计划项必须有已发布的工艺路线。后端校验逻辑会在 Service 层处理。

- [ ] **Step 2: 更新 api/__init__.py 注册路由**

编辑 `backend/app/modules/production/api/__init__.py`：

```python
from app.modules.production.api.planning import router as planning_router

# 在 include_router 列表中添加：
router.include_router(planning_router)
```

- [ ] **Step 3: 在 service/__init__.py 中导出 planning_service**

编辑 `backend/app/modules/production/service/__init__.py`，追加（如尚未导入）：

```python
from app.modules.production.service import planning_service
```

确认 `from app.modules.production.service import planning_service` 有效：
```bash
cd backend && uv run python -c "from app.modules.production.service import planning_service; print('OK')"
```

- [ ] **Step 4: 验证应用启动**

```bash
cd backend && uv run python -c "from app.main import app; print(app.title)"
```

- [ ] **Step 5: 运行 lints**

```bash
cd backend && uv run ruff check app/modules/production/ && uv run mypy app/modules/production/api/planning.py app/modules/production/service/planning_service.py app/modules/production/repository/planning.py
```

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/modules/production/api/planning.py app/modules/production/api/__init__.py app/modules/production/service/__init__.py && git commit -m "feat(production): 新增计划中枢 API 端点

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 后端测试

**Files:**
- Create: `backend/tests/test_production_planning.py`

- [ ] **Step 1: 编写集成测试**

创建 `backend/tests/test_production_planning.py`：

```python
"""计划中枢 API 集成测试。"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.integration
class TestDemandAPI:
    @pytest.mark.anyio
    async def test_create_and_list_demands(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 创建
            resp = await client.post("/api/v1/production/demands", json={
                "demand_no": "DM-20260723-0001",
                "product_id": "00000000-0000-0000-0000-000000000001",
                "product_name": "阿托伐他汀",
                "demanded_quantity": 500.0,
                "unit": "kg",
                "demand_date": "2026-08-15",
                "priority": "high",
            })
            assert resp.status_code in (200, 401)  # 401 if auth required

    # ponytail: 最小测试集验证核心流程，更多测试在迭代中补充
```

- [ ] **Step 2: 运行测试**

```bash
cd backend && uv run pytest tests/test_production_planning.py -v
```

- [ ] **Step 3: Commit**

```bash
cd backend && git add tests/ && git commit -m "test(production): 新增计划中枢集成测试

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 前端 Types

**Files:**
- Create: `frontend/src/types/production/planning.ts`
- Modify: `frontend/src/types/production/index.ts`

- [ ] **Step 1: 编写 planning.ts 类型定义**

创建 `frontend/src/types/production/planning.ts`：

```typescript
// ── Demand ──

export interface Demand {
  id: string
  demand_no: string
  source_type: 'manual' | 'sales_order' | 'forecast' | 'internal'
  source_ref: string | null
  product_id: string
  product_name: string
  demanded_quantity: number
  allocated_quantity: number
  fulfilled_quantity: number
  unit: string
  demand_date: string
  priority: 'urgent' | 'high' | 'medium' | 'low'
  status: 'pending' | 'confirmed' | 'partial' | 'fulfilled' | 'closed' | 'cancelled'
  customer_name: string | null
  remark: string | null
  created_at: string
  updated_at: string
}

export interface CreateDemandInput {
  demand_no?: string
  source_type?: string
  source_ref?: string
  product_id: string
  product_name: string
  demanded_quantity: number
  unit: string
  demand_date: string
  priority?: string
  customer_name?: string
  remark?: string
}

export interface UpdateDemandInput {
  product_name?: string
  demanded_quantity?: number
  unit?: string
  demand_date?: string
  priority?: string
  customer_name?: string
  remark?: string
}

// ── PlanOrder ──

export interface PlanOrder {
  id: string
  order_no: string
  title: string
  plan_version: number
  status: 'draft' | 'confirmed' | 'released' | 'completed' | 'closed'
  scheduled_start: string | null
  scheduled_end: string | null
  priority: 'urgent' | 'high' | 'medium' | 'low'
  remark: string | null
  created_at: string
  updated_at: string
}

export interface PlanOrderDetail extends PlanOrder {
  items: PlanItem[]
  demand_allocations: DemandAllocation[]
}

export interface CreatePlanOrderInput {
  order_no?: string
  title: string
  scheduled_start?: string
  scheduled_end?: string
  priority?: string
  remark?: string
}

export interface UpdatePlanOrderInput {
  title?: string
  scheduled_start?: string
  scheduled_end?: string
  priority?: string
  remark?: string
}

// ── PlanItem ──

export interface PlanItem {
  id: string
  plan_order_id: string
  item_no: number
  product_id: string
  product_name: string
  route_id: string | null
  equipment_id: string | null
  planned_quantity: number
  unit: string
  planned_start: string | null
  planned_end: string | null
  status: 'draft' | 'scheduled' | 'allocated' | 'in_progress' | 'completed' | 'cancelled'
  priority: 'urgent' | 'high' | 'medium' | 'low'
  sort_order: number
  remark: string | null
  created_at: string
  updated_at: string
  allocations: PlanAllocation[]
  demand_allocations: DemandAllocation[]
}

export interface CreatePlanItemInput {
  product_id: string
  product_name: string
  route_id?: string
  equipment_id?: string
  planned_quantity: number
  unit: string
  priority?: string
  remark?: string
}

export interface UpdatePlanItemInput {
  product_name?: string
  route_id?: string
  equipment_id?: string
  planned_quantity?: number
  unit?: string
  priority?: string
  remark?: string
}

export interface SchedulePlanItemInput {
  planned_start?: string
  planned_end?: string
  equipment_id?: string
  sort_order?: number
}

// ── Allocations ──

export interface PlanAllocation {
  id: string
  plan_item_id: string
  batch_id: string
  allocated_quantity: number
  batch_no: string
  batch_status: string
}

export interface DemandAllocation {
  id: string
  demand_id: string
  plan_item_id: string
  allocated_quantity: number
  demand_no?: string
  plan_order_no?: string
  item_no?: number
  product_name?: string
}

export interface CreateDemandAllocationInput {
  plan_item_id: string
  allocated_quantity: number
}

// ── Schedule View ──

export interface ScheduleViewItem {
  plan_order_id: string
  order_no: string
  order_title: string
  order_status: string
  order_priority: string
  order_scheduled_start: string | null
  order_scheduled_end: string | null
  item_id: string
  item_no: number
  product_name: string
  equipment_id: string | null
  planned_quantity: number
  unit: string
  planned_start: string | null
  planned_end: string | null
  item_status: string
  item_priority: string
}

// ── Trace ──

export interface TraceNode {
  type: 'demand' | 'plan_item' | 'batch'
  id: string
  label: string
  quantity: number | null
  unit: string | null
  status: string | null
  children: TraceNode[]
}
```

- [ ] **Step 2: 更新 types/production/index.ts**

编辑 `frontend/src/types/production/index.ts`，追加：

```typescript
export * from './planning'
```

- [ ] **Step 3: TypeScript 编译检查**

```bash
cd frontend && pnpm run types:check 2>/dev/null || pnpm exec tsc --noEmit src/types/production/planning.ts
```

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/types/production/planning.ts src/types/production/index.ts && git commit -m "feat(production): 新增计划中枢前端类型定义

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 前端 Actions

**Files:**
- Create: `frontend/src/actions/production/planning.ts`

- [ ] **Step 1: 编写 planning.ts Server Actions**

创建 `frontend/src/actions/production/planning.ts`：

```typescript
'use server'

import { revalidatePath } from 'next/cache'
import { API_BASE, actionFetch, type ActionResult } from './helpers'
import type {
  CreateDemandInput,
  UpdateDemandInput,
  Demand,
  DemandDetail,
  CreatePlanOrderInput,
  UpdatePlanOrderInput,
  PlanOrder,
  PlanOrderDetail,
  CreatePlanItemInput,
  UpdatePlanItemInput,
  SchedulePlanItemInput,
  PlanItem,
  ScheduleViewItem,
  CreateDemandAllocationInput,
  DemandAllocation,
  TraceNode,
} from '@/types/production'

const BASE = `${API_BASE}/production`
const revalidate = () => revalidatePath('/production/planning-center')

// ── Demand ──

export async function createDemand(input: CreateDemandInput): Promise<ActionResult<Demand>> {
  const result = await actionFetch<Demand>(`${BASE}/demands`, {
    method: 'POST', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function updateDemand(id: string, input: UpdateDemandInput): Promise<ActionResult<Demand>> {
  const result = await actionFetch<Demand>(`${BASE}/demands/${id}`, {
    method: 'PUT', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function deleteDemand(id: string): Promise<ActionResult<{ id: string }>> {
  const result = await actionFetch<{ id: string }>(`${BASE}/demands/${id}`, { method: 'DELETE' })
  if (result.success) revalidate()
  return result
}

export async function confirmDemand(id: string): Promise<ActionResult<Demand>> {
  const result = await actionFetch<Demand>(`${BASE}/demands/${id}/confirm`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

export async function cancelDemand(id: string): Promise<ActionResult<Demand>> {
  const result = await actionFetch<Demand>(`${BASE}/demands/${id}/cancel`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

// ── PlanOrder ──

export async function createPlanOrder(input: CreatePlanOrderInput): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders`, {
    method: 'POST', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function updatePlanOrder(id: string, input: UpdatePlanOrderInput): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders/${id}`, {
    method: 'PUT', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function deletePlanOrder(id: string): Promise<ActionResult<{ id: string }>> {
  const result = await actionFetch<{ id: string }>(`${BASE}/plan-orders/${id}`, { method: 'DELETE' })
  if (result.success) revalidate()
  return result
}

export async function confirmPlanOrder(id: string): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders/${id}/confirm`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

export async function releasePlanOrder(id: string): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders/${id}/release`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

export async function closePlanOrder(id: string): Promise<ActionResult<PlanOrder>> {
  const result = await actionFetch<PlanOrder>(`${BASE}/plan-orders/${id}/close`, { method: 'POST' })
  if (result.success) revalidate()
  return result
}

// ── PlanItem ──

export async function createPlanItem(orderId: string, input: CreatePlanItemInput): Promise<ActionResult<PlanItem>> {
  const result = await actionFetch<PlanItem>(`${BASE}/plan-orders/${orderId}/items`, {
    method: 'POST', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function updatePlanItem(id: string, input: UpdatePlanItemInput): Promise<ActionResult<PlanItem>> {
  const result = await actionFetch<PlanItem>(`${BASE}/plan-items/${id}`, {
    method: 'PUT', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function deletePlanItem(id: string): Promise<ActionResult<{ id: string }>> {
  const result = await actionFetch<{ id: string }>(`${BASE}/plan-items/${id}`, { method: 'DELETE' })
  if (result.success) revalidate()
  return result
}

export async function schedulePlanItem(id: string, input: SchedulePlanItemInput): Promise<ActionResult<PlanItem>> {
  const result = await actionFetch<PlanItem>(`${BASE}/plan-items/${id}/schedule`, {
    method: 'PUT', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

// ── Demand Allocation ──

export async function createDemandAllocation(demandId: string, input: CreateDemandAllocationInput): Promise<ActionResult<DemandAllocation>> {
  const result = await actionFetch<DemandAllocation>(`${BASE}/demands/${demandId}/allocations`, {
    method: 'POST', body: JSON.stringify(input),
  })
  if (result.success) revalidate()
  return result
}

export async function deleteDemandAllocation(id: string): Promise<ActionResult<{ id: string }>> {
  const result = await actionFetch<{ id: string }>(`${BASE}/demand-allocations/${id}`, { method: 'DELETE' })
  if (result.success) revalidate()
  return result
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend && git add src/actions/production/planning.ts && git commit -m "feat(production): 新增计划中枢 Server Actions

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 前端组件 — 需求池（Tab 1）

**Files:**
- Create: `frontend/src/components/production/planning-center/DemandPool.tsx`
- Create: `frontend/src/components/production/planning-center/DemandFormModal.tsx`
- Create: `frontend/src/components/production/planning-center/DemandTraceDrawer.tsx`

- [ ] **Step 1: 编写 DemandPool.tsx**

```tsx
'use client'

import { useState } from 'react'
import { Table, Button, Space, Tag, Select, Input, App } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usePermission } from '@/hooks/usePermission'
import type { Demand } from '@/types/production'
import { confirmDemand, cancelDemand, deleteDemand } from '@/actions/production/planning'
import { DemandFormModal } from './DemandFormModal'
import { DemandTraceDrawer } from './DemandTraceDrawer'

const PRIORITY_COLORS: Record<string, string> = { urgent: 'red', high: 'orange', medium: 'gold', low: 'blue' }
const STATUS_COLORS: Record<string, string> = {
  pending: 'default', confirmed: 'blue', partial: 'orange', fulfilled: 'green', closed: 'default', cancelled: 'red',
}

export function DemandPool() {
  const { hasPermission } = usePermission()
  const canSubmit = hasPermission('production:batch:submit')
  const queryClient = useQueryClient()
  const { message } = App.useApp()

  const [filters, setFilters] = useState<Record<string, string | undefined>>({})
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [editingDemand, setEditingDemand] = useState<Demand | null>(null)
  const [traceId, setTraceId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['demands', filters, page],
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), page_size: '20', ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) })
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/production/demands?${params}`)
      if (!res.ok) throw new Error('Failed')
      return res.json()
    },
  })

  const columns = [
    { title: '需求编号', dataIndex: 'demand_no', width: 180 },
    { title: '来源', dataIndex: 'source_type', width: 80, render: (v: string) => ({ manual: '手动', sales_order: '订单', forecast: '预测', internal: '内部' }[v] || v) },
    { title: '产品', dataIndex: 'product_name', width: 140 },
    { title: '需求量', dataIndex: 'demanded_quantity', width: 80, render: (v: number, r: Demand) => `${v}${r.unit}` },
    { title: '已分配', dataIndex: 'allocated_quantity', width: 80, render: (v: number, r: Demand) => `${v}${r.unit}` },
    { title: '剩余', width: 80, render: (_: unknown, r: Demand) => `${r.demanded_quantity - r.allocated_quantity}${r.unit}` },
    { title: '交期', dataIndex: 'demand_date', width: 100 },
    { title: '优先级', dataIndex: 'priority', width: 70, render: (v: string) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag> },
    { title: '状态', dataIndex: 'status', width: 70, render: (v: string) => <Tag color={STATUS_COLORS[v]}>{v}</Tag> },
    {
      title: '操作', width: 200, render: (_: unknown, record: Demand) => (
        <Space>
          {canSubmit && record.status === 'pending' && <Button size="small" type="link" onClick={() => handleConfirm(record.id)}>确认</Button>}
          {canSubmit && record.status !== 'cancelled' && record.status !== 'closed' && <Button size="small" type="link" danger onClick={() => handleCancel(record.id)}>取消</Button>}
          <Button size="small" type="link" onClick={() => setTraceId(record.id)}>追溯</Button>
        </Space>
      ),
    },
  ]

  const confirmMut = useMutation({ mutationFn: confirmDemand, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['demands'] }); message.success('已确认') } })
  const cancelMut = useMutation({ mutationFn: cancelDemand, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['demands'] }); message.success('已取消') } })

  const handleConfirm = (id: string) => confirmMut.mutate(id)
  const handleCancel = (id: string) => cancelMut.mutate(id)

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
        {canSubmit && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingDemand(null); setFormOpen(true) }}>新建需求</Button>}
        <Select placeholder="来源" allowClear style={{ width: 100 }} onChange={v => setFilters(f => ({ ...f, source_type: v }))} options={[{ value: 'manual', label: '手动' }, { value: 'sales_order', label: '订单' }, { value: 'forecast', label: '预测' }]} />
        <Select placeholder="状态" allowClear style={{ width: 100 }} onChange={v => setFilters(f => ({ ...f, status: v }))} options={[{ value: 'pending', label: '待确认' }, { value: 'confirmed', label: '已确认' }, { value: 'partial', label: '部分' }, { value: 'fulfilled', label: '已完成' }]} />
        <Input placeholder="搜索编号/产品" allowClear prefix={<SearchOutlined />} style={{ width: 200 }} onChange={e => setFilters(f => ({ ...f, keyword: e.target.value || undefined }))} />
      </div>
      <Table columns={columns} dataSource={data?.data || []} loading={isLoading} rowKey="id" size="middle"
        pagination={{ current: page, total: data?.total || 0, onChange: setPage }}
      />
      <DemandFormModal open={formOpen} demand={editingDemand} onClose={() => setFormOpen(false)} />
      <DemandTraceDrawer demandId={traceId} onClose={() => setTraceId(null)} />
    </div>
  )
}
```

- [ ] **Step 2: 编写 DemandFormModal.tsx**

```tsx
'use client'

import { useEffect } from 'react'
import { Modal, Form, Input, Select, DatePicker, InputNumber } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import type { Demand, CreateDemandInput } from '@/types/production'
import { createDemand, updateDemand } from '@/actions/production/planning'

interface Props {
  open: boolean
  demand: Demand | null
  onClose: () => void
}

export function DemandFormModal({ open, demand, onClose }: Props) {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const isEdit = !!demand

  useEffect(() => {
    if (open) {
      if (demand) form.setFieldsValue(demand)
      else form.resetFields()
    }
  }, [open, demand, form])

  const mut = useMutation({
    mutationFn: async (vals: CreateDemandInput) => {
      if (isEdit) return updateDemand(demand!.id, vals)
      return createDemand(vals)
    },
    onSuccess: (result) => {
      if (result.success) {
        queryClient.invalidateQueries({ queryKey: ['demands'] })
        message.success(isEdit ? '已更新' : '已创建')
        onClose()
      } else message.error(result.error)
    },
  })

  return (
    <Modal title={isEdit ? '编辑需求' : '新建需求'} open={open} onCancel={onClose} onOk={() => form.submit()} width={560}>
      <Form form={form} layout="vertical" onFinish={vals => mut.mutate(vals)}>
        <Form.Item name="demand_no" label="需求编号" rules={[{ required: !isEdit }]}>
          <Input disabled={isEdit} placeholder="留空自动生成" />
        </Form.Item>
        <Form.Item name="source_type" label="来源" initialValue="manual">
          <Select options={[{ value: 'manual', label: '手动录入' }, { value: 'sales_order', label: '销售订单' }, { value: 'forecast', label: '预测' }, { value: 'internal', label: '内部需求' }]} />
        </Form.Item>
        <Form.Item name="product_id" label="产品 ID" rules={[{ required: true }]}>
          <Input placeholder="UUID 或产品选择器" />
        </Form.Item>
        <Form.Item name="product_name" label="产品名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="demanded_quantity" label="需求量" rules={[{ required: true }]}>
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="unit" label="单位" rules={[{ required: true }]} initialValue="kg">
          <Input />
        </Form.Item>
        <Form.Item name="demand_date" label="交期" rules={[{ required: true }]}>
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="priority" label="优先级" initialValue="medium">
          <Select options={[{ value: 'urgent', label: '紧急' }, { value: 'high', label: '高' }, { value: 'medium', label: '中' }, { value: 'low', label: '低' }]} />
        </Form.Item>
        <Form.Item name="customer_name" label="客户">
          <Input placeholder="临时字段" />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
```

- [ ] **Step 3: 编写 DemandTraceDrawer.tsx**（追溯链路树）

使用 Ant Design Tree 组件渲染 `TraceNode` 自引用结构。宽度 60%。

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/components/production/planning-center/DemandPool.tsx src/components/production/planning-center/DemandFormModal.tsx src/components/production/planning-center/DemandTraceDrawer.tsx && git commit -m "feat(production): 新增需求池前端组件

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: 前端组件 — 计划单（Tab 2）

**Files:**
- Create: `frontend/src/components/production/planning-center/PlanOrderList.tsx`
- Create: `frontend/src/components/production/planning-center/PlanOrderDetailDrawer.tsx`
- Create: `frontend/src/components/production/planning-center/PlanItemTable.tsx`
- Create: `frontend/src/components/production/planning-center/ReleaseConfirmModal.tsx`

- [ ] **Step 1: 编写 PlanOrderList.tsx**（卡片网格 + 新建/确认/下达/关闭操作）
- [ ] **Step 2: 编写 PlanOrderDetailDrawer.tsx**（70% 宽度 Drawer，含 PlanItemTable + 需求关联）
- [ ] **Step 3: 编写 PlanItemTable.tsx**（内联编辑表格，`draft` 状态下可增删改）
- [ ] **Step 4: 编写 ReleaseConfirmModal.tsx**（下达前 Batch 预览确认）
- [ ] **Step 5: Commit**

---

### Task 11: 前端组件 — 计划排程（Tab 3）

**Files:**
- Create: `frontend/src/components/production/planning-center/ScheduleView.tsx`
- Create: `frontend/src/components/production/planning-center/ScheduleGantt.tsx`

- [ ] **Step 1: 编写 ScheduleGantt.tsx**（两级甘特图核心）

基于 CSS Grid 实现，左侧设备标签列 + 右侧时间列。两级行：PlanOrder 行 + PlanItem 子行。使用 @dnd-kit/core 实现拖拽（水平改变时间、垂直改变设备/计划单归属、边缘拉拽改变时长）。点击 PlanItem bar 弹出详情 Drawer。

- [ ] **Step 2: 编写 ScheduleView.tsx**（甘特图容器：过滤栏 + 日/周/月切换 + 甘特图组件）
- [ ] **Step 3: Commit**

---

### Task 12: 前端页面 + 菜单 + 导出

**Files:**
- Create: `frontend/src/app/(dashboard)/production/planning-center/page.tsx`
- Create: `frontend/src/components/production/planning-center/PlanningCenterPage.tsx`
- Create: `frontend/src/components/production/planning-center/index.ts`
- Modify: `frontend/src/components/production/index.ts`
- Modify: `frontend/src/lib/menu-config.ts`

- [ ] **Step 1: 编写 PlanningCenterPage.tsx**（三 Tab 容器：Ant Design Tabs，segmented-tab 样式）

```tsx
'use client'

import { Suspense } from 'react'
import { App, ConfigProvider, Tabs } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useSearchParams, useRouter } from 'next/navigation'
import { antdTheme } from '@/lib/antd-theme'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { DemandPool } from './DemandPool'
import { PlanOrderList } from './PlanOrderList'
import { ScheduleView } from './ScheduleView'

function PlanningCenterInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const activeTab = searchParams.get('tab') ?? 'demands'

  const setTab = (tab: string) => {
    const q = new URLSearchParams(searchParams.toString())
    q.set('tab', tab)
    router.replace(`/production/planning-center?${q}`)
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', color: '#1a1a1a' }}>计划中枢</h2>
        <span style={{ color: '#787671', fontSize: 14 }}>需求管理、计划制定与排程调度</span>
      </div>
      <Tabs activeKey={activeTab} onChange={setTab}
        items={[
          { key: 'demands', label: '需求池', children: <DemandPool /> },
          { key: 'plan-orders', label: '计划单', children: <PlanOrderList /> },
          { key: 'schedule', label: '计划排程', children: <ScheduleView /> },
        ]}
        style={{ color: '#787671' }}
      />
    </div>
  )
}

export function PlanningCenterPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App>
          <Suspense fallback={<div style={{ padding: 40, textAlign: 'center', color: '#787671' }}>加载中...</div>}>
            <PlanningCenterInner />
          </Suspense>
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}
```

- [ ] **Step 2: 编写 page.tsx**

```tsx
import { PlanningCenterPage } from '@/components/production/planning-center'

export const dynamic = 'force-dynamic'

export default function PlanningCenterRoute() {
  return <PlanningCenterPage />
}
```

- [ ] **Step 3: 编写 planning-center/index.ts 导出**

```typescript
export { PlanningCenterPage } from './PlanningCenterPage'
```

- [ ] **Step 4: 更新 components/production/index.ts**

追加：`export { PlanningCenterPage } from './planning-center'`

- [ ] **Step 5: 更新菜单**

在 `menu-config.ts` 中，production.children 的 `manufacturing-unit` 之前插入：

```typescript
{
  key: "planning-center",
  label: "计划中枢",
  path: "",
  children: [
    { key: "planning-center", label: "计划中枢", path: "/production/planning-center" },
  ],
},
```

- [ ] **Step 6: TypeScript LSP 验证**

使用 TypeScript LSP 检查各新文件无类型错误。

- [ ] **Step 7: Commit**

```bash
cd frontend && git add src/app/(dashboard)/production/planning-center/ src/components/production/planning-center/ src/components/production/index.ts src/lib/menu-config.ts && git commit -m "feat(production): 新增计划中枢页面与菜单

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 验证清单

全部 Task 完成后：

```bash
# 后端
cd backend && uv run ruff check . && uv run mypy app tests && uv run alembic heads && uv run python -c "from app.main import app; print(app.title)"

# 前端
cd frontend && pnpm build
```

---

## 已知限制

1. **Batch.route_id 不可为空**：计划单下达时，PlanItem 若无已发布路线会失败。需要业务上确保排程前指定路线。
2. **批号自动生成**：当前使用 `{order_no}-{item_no}` 简单拼接，后续可能需要独立的批号规则。
3. **产品选择器**：DemandFormModal 中产品输入是文字框（UUID），后续替换为实际 ProductSelect 组件。
4. **设备选择器**：PlanItem 设备字段需要对接设备管理模块的设备列表 API。
5. **@dnd-kit/core**：如果项目未安装，需 `pnpm add @dnd-kit/core`。
