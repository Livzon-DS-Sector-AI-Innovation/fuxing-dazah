# dazah-backend 项目架构

本项目采用模块化单体架构。业务模块按“纵向包”组织，每个模块拥有自己的 API、Schema、Service、Repository 和 ORM Model，适合不同技术人员分别维护生产、设备、安全、质量等模块。

## 目录结构

```text
app/
├── main.py
├── api/
│   └── router.py                 # 全局 API 路由装配
├── core/                         # 技术基础设施
│   ├── config.py
│   ├── database.py
│   ├── redis.py
│   ├── events.py
│   ├── exceptions.py
│   └── response.py
├── shared/                       # 跨平台和业务模块共享的轻量契约
│   ├── base_model.py
│   ├── module_api.py
│   ├── module_registry.py
│   └── schemas.py
├── platform/                     # 工厂级平台能力
│   ├── audit/                    # 审计日志和操作追踪
│   ├── identity/                 # 本地轻量用户档案，后续接飞书 SSO
│   ├── integrations/             # 飞书、ERP、LIMS 等外部系统适配
│   └── system/                   # 系统元数据接口
└── modules/                      # 业务模块，按负责人边界维护
    ├── production/
    ├── equipment/
    ├── safety/
    ├── environment/
    ├── energy/
    ├── warehouse/
    ├── procurement/
    ├── administration/
    ├── hr/
    ├── research/
    ├── registration/
    └── quality/
```

## 模块约定

每个 `app/modules/{module}` 包内固定保留：

- `api.py`：HTTP 路由和请求参数处理
- `schemas.py`：Pydantic 请求/响应模型
- `service.py`：业务流程编排
- `repository.py`：数据库查询与持久化
- `models.py`：本模块 SQLAlchemy ORM 模型

跨模块调用优先通过对方模块的 `public_api.py`，不要直接跨模块 import 对方 `service.py`、`repository.py` 或内部拆分文件。飞书、ERP、LIMS 等外部系统只从 `platform/integrations` 接入，业务模块不直接散落第三方 API 调用。

## 数据库边界

- `identity` schema：本地轻量用户档案，用于后续关联飞书 SSO。
- `audit` schema：审计日志和操作追踪，默认保留策略为 7 天。
- 每个业务模块一个 PostgreSQL schema，例如 `production`、`quality`、`equipment`。

首版迁移文件：`alembic/versions/20260529_0001_initial_platform.py`。

## 当前可用接口

- `GET /health`
- `GET /api/v1/system/modules`
- `GET /api/v1/{module}/`
