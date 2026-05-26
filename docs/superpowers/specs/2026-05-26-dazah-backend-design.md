# 大杂烩后端系统架构设计

## 1. 背景与目标

### 1.1 业务背景

原料药事业部需要构建一个工厂数字化基座系统，用于收集各部门和车间的业务数据。系统作为数据收集渠道，业务系统作为上层设施。

### 1.2 核心需求

- **数据收集**：生产管理、环保管理、人事管理、设备管理、采购管理等
- **审计追踪**：完整的操作日志和数据变更追踪
- **外部集成**：飞书（SSO、审批、IM）、ERP、LIMS
- **可维护性**：模块化设计，支持不同技术人员负责不同模块

### 1.3 约束条件

| 约束 | 说明 |
|------|------|
| 团队规模 | 1-2 人 |
| 技术栈 | FastAPI + PostgreSQL + Redis + uv |
| 部署方式 | 本地机房，Docker Compose |
| 用户规模 | 50+ 并发用户 |
| 数据量 | 每天几百条业务记录 |

---

## 2. 架构方案

### 2.1 架构选型：模块化单体

采用模块化单体架构（Modular Monolith），理由：

1. **匹配团队规模**：1-2 人不需要微服务的运维复杂度
2. **模块隔离足够**：通过 Python package 边界 + PostgreSQL schema 隔离
3. **后期可拆**：模块化单体是微服务的"前身"
4. **部署简单**：一个 `docker compose up` 就能跑起来

### 2.2 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (反向代理)                          │
├─────────────────────────────────────────────────────────────┤
│                    FastAPI 应用                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    API 路由层                           │ │
│  │  /api/v1/production/*  /api/v1/equipment/*  ...        │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    业务服务层                           │ │
│  │  ProductionService  EquipmentService  ...              │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    数据访问层                           │ │
│  │  SQLAlchemy 2.0 Async + Alembic                        │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    基础设施层                           │ │
│  │  审计日志 | 事件总线 | 配置管理 | 缓存                   │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL  │  Redis  │  外部系统 (飞书/ERP/LIMS)          │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 项目结构

```
dazah-backend/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── alembic/
│   ├── versions/
│   └── env.py
├── alembic.ini
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI 应用入口
│   ├── core/                       # 公共基础设施
│   │   ├── __init__.py
│   │   ├── config.py               # 配置管理（Pydantic Settings）
│   │   ├── database.py             # SQLAlchemy async engine/session
│   │   ├── redis.py                # Redis 连接
│   │   ├── security.py             # 认证/授权工具
│   │   ├── audit.py                # 审计日志中间件/装饰器
│   │   ├── deps.py                 # FastAPI 公共依赖注入
│   │   ├── exceptions.py           # 统一异常定义
│   │   ├── response.py             # 统一响应格式
│   │   └── events.py               # 进程内事件总线
│   ├── models/                     # SQLAlchemy ORM 模型
│   │   ├── __init__.py
│   │   ├── base.py                 # 基础模型
│   │   ├── production/
│   │   ├── environment/
│   │   ├── equipment/
│   │   ├── hr/
│   │   └── procurement/
│   ├── schemas/                    # Pydantic 请求/响应模型
│   │   ├── production/
│   │   ├── environment/
│   │   ├── equipment/
│   │   ├── hr/
│   │   └── procurement/
│   ├── modules/                    # 业务逻辑层
│   │   ├── production/
│   │   │   ├── __init__.py
│   │   │   ├── router.py           # 路由定义
│   │   │   ├── service.py          # 业务逻辑
│   │   │   └── crud.py             # 数据库操作
│   │   ├── environment/
│   │   ├── equipment/
│   │   ├── hr/
│   │   └── procurement/
│   ├── integrations/               # 外部系统对接（Phase 2）
│   │   ├── base.py                 # 集成基类
│   │   ├── feishu/
│   │   ├── erp/
│   │   └── lims/
│   └── api/                        # 路由注册
│       └── v1/
│           ├── __init__.py
│           └── api.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
└── docs/
```

### 3.1 模块职责边界

每个业务模块遵循统一的三层结构：

| 层 | 文件 | 职责 |
|---|---|---|
| **路由层** | `router.py` | 接收 HTTP 请求，参数校验，调用 service |
| **服务层** | `service.py` | 业务逻辑编排，事务管理 |
| **数据层** | `crud.py` | 数据库 CRUD 操作 |

**关键约定**：
- 模块之间不允许直接 import，需要跨模块操作时通过 service 层调用
- 每个模块的 ORM 模型放在 `models/` 下对应子目录
- Schema 放在 `schemas/` 下，路由层只暴露 Schema，不暴露 ORM 模型

---

## 4. 数据层设计

### 4.1 技术选型

| 组件 | 技术 | 说明 |
|------|------|------|
| ORM | SQLAlchemy 2.0 async | 使用 asyncpg 驱动 |
| 迁移 | Alembic | 统一管理所有模块的表结构变更 |
| 缓存 | Redis | 会话缓存、热点数据、分布式锁 |

### 4.2 多模块表隔离

采用 PostgreSQL Schema 隔离：

```sql
-- 每个模块一个 schema
CREATE SCHEMA production;
CREATE SCHEMA environment;
CREATE SCHEMA equipment;
CREATE SCHEMA hr;
CREATE SCHEMA procurement;
CREATE SCHEMA audit;

-- 示例表
CREATE TABLE production.batches (
    id UUID PRIMARY KEY,
    batch_no VARCHAR(50) NOT NULL,
    ...
);
```

### 4.3 公共模型基类

```python
# app/models/base.py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import func
from datetime import datetime
import uuid

class Base(DeclarativeBase):
    pass

class BaseModel(Base):
    __abstract__ = True
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None]
    updated_by: Mapped[uuid.UUID | None]
    is_deleted: Mapped[bool] = mapped_column(default=False)
```

### 4.4 Redis 用途

1. **会话/Token 缓存**（Phase 2 飞书 SSO）
2. **热点数据缓存**（字典表、配置项）
3. **分布式锁**（防止并发操作冲突）

---

## 5. 事件总线

### 5.1 方案选择

采用进程内事件总线，后期可升级为 Redis Pub/Sub。

### 5.2 使用场景

- **跨模块通知**：生产模块发事件，其他模块按需监听
- **异步副作用**：记录操作日志、发送通知等

### 5.3 实现方案

```python
# app/core/events.py
from typing import Callable, Any
from collections import defaultdict

class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
    
    def subscribe(self, event_type: str, handler: Callable):
        self._handlers[event_type].append(handler)
    
    async def publish(self, event_type: str, data: Any):
        for handler in self._handlers[event_type]:
            await handler(data)

# 全局事件总线实例
event_bus = EventBus()
```

---

## 6. 审计日志与操作追踪

### 6.1 设计目标

记录：**谁、在什么时间、对什么数据、做了什么操作**

### 6.2 双轨制方案

#### 自动审计（中间件层）

通过 FastAPI 中间件自动记录所有 API 请求：

```
请求 → 中间件（记录请求信息） → 业务处理 → 中间件（记录响应/异常）
```

自动记录：
- 请求路径、方法、参数
- 响应状态码
- 请求耗时
- 操作人（Phase 1 无认证，user_id 为 NULL；Phase 2 从飞书 SSO 获取）
- 客户端 IP

#### 业务审计（装饰器/显式调用）

关键业务操作需要记录更详细的业务语义：

```python
@audit_log(resource="production.batch", action="create")
async def create_batch(db, batch_data):
    ...
```

记录内容：
- 资源类型（如 `production.batch`）
- 资源 ID（具体哪条记录）
- 操作类型（create / update / delete / export）
- 变更内容（old_value / new_value）
- 操作人

### 6.3 审计日志表结构

```sql
CREATE TABLE audit.logs (
    id UUID PRIMARY KEY,
    request_id VARCHAR(50),         -- 关联请求
    user_id UUID,                   -- 操作人
    resource_type VARCHAR(100),     -- 资源类型
    resource_id UUID,               -- 资源 ID
    action VARCHAR(50),             -- 操作类型
    old_value JSONB,                -- 变更前
    new_value JSONB,                -- 变更后
    ip_address VARCHAR(50),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    extra JSONB                     -- 扩展字段
);

-- 索引
CREATE INDEX idx_audit_user_id ON audit.logs(user_id);
CREATE INDEX idx_audit_resource ON audit.logs(resource_type, resource_id);
CREATE INDEX idx_audit_created_at ON audit.logs(created_at);
```

---

## 7. 认证与权限

### 7.1 Phase 1：不做认证

Phase 1 不实现用户认证系统，但预留认证扩展点：

```python
# app/core/deps.py
async def get_current_user(request: Request) -> User | None:
    """Phase 1: 返回 None；Phase 2: 从飞书 SSO 获取用户"""
    return None
```

### 7.2 Phase 2：飞书 SSO

接入飞书 SSO 后：
- 用户通过飞书扫码登录
- 本地 `users` 表通过 `feishu_user_id` 关联
- Token 验证逻辑替换为飞书 OAuth2 流程

### 7.3 用户档案表（预留）

```sql
CREATE TABLE hr.users (
    id UUID PRIMARY KEY,
    name VARCHAR(100),
    employee_id VARCHAR(50),
    department VARCHAR(100),
    role VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    feishu_user_id VARCHAR(100),    -- 预留，Phase 2 用
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 8. API 规范

### 8.1 路由规范

```
/api/v1/{module}/{resource}

示例：
POST   /api/v1/production/batches          # 创建批次
GET    /api/v1/production/batches           # 列表查询
GET    /api/v1/production/batches/{id}      # 详情
PUT    /api/v1/production/batches/{id}      # 更新
DELETE /api/v1/production/batches/{id}      # 删除（软删除）
```

### 8.2 统一响应格式

成功响应：
```json
{
    "code": 200,
    "message": "success",
    "data": { ... },
    "meta": {
        "page": 1,
        "page_size": 20,
        "total": 100
    }
}
```

异常响应：
```json
{
    "code": 400,
    "message": "批次编号已存在",
    "detail": "batch_no: 该编号已被使用"
}
```

### 8.3 分页参数

```
GET /api/v1/production/batches?page=1&page_size=20&sort_by=created_at&sort_order=desc
```

---

## 9. 部署架构

### 9.1 Docker Compose

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/dazah
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - ./app:/app/app

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: dazah
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    ports:
      - "6379:6379"

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - app

volumes:
  pgdata:
  redisdata:
```

### 9.2 环境配置

```env
# .env
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/dazah
REDIS_URL=redis://redis:6379/0
APP_ENV=development
SECRET_KEY=your-secret-key-here
```

---

## 10. 外部系统集成（Phase 2）

### 10.1 集成架构

```
app/integrations/
├── base.py              # 集成基类（统一接口）
├── feishu/
│   ├── client.py        # 飞书 API 客户端
│   ├── sso.py           # SSO 登录
│   ├── approval.py      # 审批流程
│   └── messenger.py     # 消息通知
├── erp/
│   ├── client.py        # ERP API 客户端
│   └── sync.py          # 数据同步
└── lims/
    ├── client.py        # LIMS API 客户端
    └── sync.py          # 数据同步
```

### 10.2 飞书集成

| 功能 | 实现方式 |
|------|----------|
| SSO 登录 | 飞书 OAuth2，用户扫码 → 获取 token → 关联本地用户 |
| 审批流程 | 调用飞书审批 API 创建审批实例，通过回调获取审批结果 |
| 消息通知 | 调用飞书机器人 API 发送群消息/个人消息 |

### 10.3 ERP/LIMS 集成

| 功能 | 实现方式 |
|------|----------|
| 数据拉取 | 定时任务（APScheduler）或手动触发 |
| 数据推送 | 业务事件触发 |
| 数据映射 | 统一的数据映射层，处理字段名/格式差异 |

### 10.4 设计原则

1. **集成层与业务层隔离**：业务模块不直接调用外部 API
2. **失败重试**：外部 API 调用带重试机制（exponential backoff）
3. **幂等性**：数据同步操作保证幂等

---

## 11. 开发规范

### 11.1 代码规范

| 项目 | 规范 |
|------|------|
| 代码风格 | Ruff 格式化 + lint |
| 类型标注 | 全量 type hints，mypy 检查 |
| 提交规范 | Conventional Commits（feat/fix/chore/docs） |
| 分支策略 | main + feature branches |

### 11.2 技术栈版本

```
Python:        3.12+
FastAPI:       最新稳定版
SQLAlchemy:    2.0+（async 模式）
Alembic:       最新稳定版
Pydantic:      2.0+（V2）
asyncpg:       PostgreSQL async 驱动
redis-py:      Redis 客户端
uvicorn:       ASGI 服务器
uv:            包管理
```

### 11.3 测试策略

| 层级 | 工具 | 覆盖范围 |
|------|------|----------|
| 单元测试 | pytest | service 层业务逻辑 |
| 集成测试 | pytest + httpx | API 端点 |

---

## 12. 首期开发计划

### 12.1 开发顺序

```
Phase 1: 基础框架 + 生产管理
├── 项目骨架搭建（目录结构、配置、数据库连接）
├── 公共基础（响应格式、异常处理、审计中间件）
├── 生产管理 - 批次管理 CRUD
├── 生产管理 - 生产记录
├── 生产管理 - 数据查询/统计
└── Docker Compose 部署配置

Phase 2: 飞书集成 + 其他模块
├── 飞书 SSO 登录
├── 飞书消息通知
├── 飞书审批流程
├── 环保管理模块
├── 设备管理模块
└── ...

Phase 3: 外部系统对接
├── ERP 数据同步
├── LIMS 数据同步
└── ...
```

---

## 13. 待确认事项

- [ ] 生产管理模块的具体业务字段和表结构（需要与业务部门确认）
- [ ] 审计日志的保留策略（保留多久？是否需要归档？）
- [ ] 是否需要数据导出功能（Excel/PDF）
