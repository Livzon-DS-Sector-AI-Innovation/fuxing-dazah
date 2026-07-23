# dazah-backend AI 编程规范

## 项目原则

`dazah-backend` 是原料药事业部的工厂数字化基座后端，采用模块化单体架构，承载生产、设备、安全、环保、能源、仓储、采购、行政、人事、研发、注册、质量等业务模块。

目标是让各模块在统一平台能力下独立演进，并保留审计、身份扩展、外部系统集成能力。不要把项目改成微服务，也不要引入与当前需求无关的复杂架构。

技术栈：Python 3.12+、FastAPI、SQLAlchemy 2.0 async、PostgreSQL、Redis、Alembic、Pydantic v2、uv、pytest、ruff、mypy、MinIO。
MCP：模型上下文协议，用于给Agent智能体工具调用能力，操作系统资源。

涉及不确定的新 API 或库写法时，先查最新官方文档或 Context7，再实现。

## 目录边界

- `app/core/`：技术基础设施，例如配置、数据库、Redis、异常、统一响应、事件总线。
- `app/shared/`：跨平台和业务模块共享的轻量契约，例如 ORM 基类、模块注册表、通用 schema。
- `app/platform/`：工厂级平台能力，例如审计、身份、本地用户档案、外部系统集成。
- `app/modules/`：业务模块。每个模块维护自己的 API、Schema、Service、Repository、Model。
- `app/api/router.py`：全局 API 路由装配入口。
- `alembic/`：数据库迁移。

禁止把新业务代码放回旧式横向目录，例如 `app/models/`、`app/schemas/`、`app/integrations/`。模块清单以 `app/shared/module_registry.py` 和实际目录为准。

## 协作编辑边界

只能修改自己负责模块内的代码。除非需求明确要求并经过负责人确认，不要编辑项目架构、全局基础设施、平台能力或其他人负责的业务模块。

涉及跨模块改动时，优先通过目标模块的 `public_api.py`、模块注册表或既有扩展点完成协作；确实需要修改其他模块内部实现时，必须先说明影响范围、原因和验证方式，并尽量让对应负责人处理。

严禁借一次需求顺手重构不归自己负责的模块、移动目录、调整公共抽象或改变架构边界。对 `app/core/`、`app/shared/`、`app/platform/`、`app/api/router.py`、`alembic/` 等全局或平台级文件的编辑应保持最小化，并只限于当前需求不可避免的变更。

## 业务模块结构

每个业务模块默认使用：

```text
app/modules/{module}/
├── __init__.py
├── api.py          # HTTP 路由、入参、依赖注入、响应
├── schemas.py      # Pydantic 请求/响应模型
├── models.py       # SQLAlchemy ORM 模型
├── repository.py   # 数据库查询和持久化
├── service.py      # 业务流程、规则校验、事务编排
└── public_api.py   # 可选；提供给其他模块调用的稳定公共接口
```

职责规则：

- `api.py` 只做 HTTP 层：接收入参、注入依赖、调用 service、返回统一响应。不要写 ORM 查询、复杂业务规则、外部 API 调用或审计落库逻辑。
- `schemas.py` 只描述 API 契约。不要 import ORM model，不承载数据库行为。
- `models.py` 只描述表结构、字段、约束、索引和简单只读属性。不要写业务流程。
- `repository.py` 只负责数据读写。不要决定“是否允许审批”“是否可以删除”等业务语义。
- `service.py` 负责编排业务流程、事务、状态流转、跨表校验、审计和外部集成调用。
- 跨模块调用只能通过对方模块的 `public_api.py`，不要直接 import 其他模块的 `service.py`、`repository.py`、`models.py` 或内部拆分文件。

当 `service.py`、`models.py`、`schemas.py` 单文件超过约 300 行时，拆成同名目录，并在目录级 `__init__.py` re-export 公开对象，保持外部 import 路径稳定。`api.py` 和 `repository.py` 只有确实过大时再按同样规则拆分。

## API 规范

路由统一挂在 `/api/v1` 下，常用形式：

```text
GET    /api/v1/{module}/
POST   /api/v1/{module}/{resource}
GET    /api/v1/{module}/{resource}
GET    /api/v1/{module}/{resource}/{id}
PUT    /api/v1/{module}/{resource}/{id}
DELETE /api/v1/{module}/{resource}/{id}
```

- 入参和出参使用本模块 `schemas.py`。
- 返回格式优先使用 `app/core/response.py`。
- 业务异常优先使用 `app/core/exceptions.py`。
- 删除业务数据默认软删除，例如 `is_deleted`；除非需求明确要求，不做物理删除。

## 数据库与迁移

数据库使用 PostgreSQL schema 做边界隔离：

- `identity`：本地轻量用户档案，后续关联飞书 SSO。
- `audit`：审计日志和操作追踪。
- 每个业务模块一个 schema，例如 `production`、`quality`、`equipment`。

ORM 和 migration 规则：

- 业务模型继承 `app/shared/base_model.py` 中的 `BaseModel`。
- 每张业务表必须有清晰的 `__tablename__` 和 `__table_args__ = {"schema": "<module_schema>"}`。
- 字段命名使用英文 `snake_case`。
- 唯一约束、外键、常用查询索引要显式声明。
- 修改 ORM 模型后必须新增 Alembic migration。
- 不要修改已经合并或执行过的历史 migration，除非用户明确要求。
- 新增 schema 时同步更新 `app/shared/module_registry.py` 和 migration。
- **autogenerate 不会自动生成 `CREATE SCHEMA` 语句**。每次新增 schema 或生成包含新 schema 建表语句的迁移时，必须在 `upgrade()` 开头手动添加 `op.execute("CREATE SCHEMA IF NOT EXISTS <schema_name>")`，否则空库部署会报错。

常用命令：

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
uv run alembic downgrade -1
```

多人协作迁移规范：

Alembic 的 revision ID 是随机哈希，多人同时创建 migration 会产生多个 head（分支），导致 `alembic upgrade head` 失败或生产环境 ORM 与数据库不一致。必须遵守以下流程：

**创建 migration 前的固定步骤（每次都要做）：**

```bash
git pull                                    # 1. 拉取最新代码
uv run alembic heads                        # 2. 检查 head 数量
uv run alembic merge heads -m "merge heads" # 3. 多个 head 时先合并
uv run alembic upgrade head                 # 4. 升级本地数据库
uv run alembic revision --autogenerate -m "xxx"  # 5. 再创建自己的 migration
```

**禁止事项：**

- 禁止提交包含 git 冲突标记（`<<<<<<<`）的 migration 文件，这会让整个 alembic 崩溃。
- 禁止手动写 revision ID（如 `20260615_0001`），使用 alembic 自动生成的随机哈希，避免 ID 重复。
- 禁止在生产环境出现多个 head。合并代码后、部署前，必须确认 `alembic heads` 只有一个。
- 禁止跳过 `alembic upgrade head` 直接创建 migration，否则 `down_revision` 会指向过时的节点。

**部署前检查清单：**

```bash
uv run alembic heads     # 必须只有一个 head
uv run alembic current   # 确认数据库版本
uv run alembic upgrade head  # 确保能顺利升级
```

如果 `autogenerate` 混入了其他模块的无关变更，手动清理 migration 文件，只保留自己模块的 DDL。

## 审计、身份与外部集成

- 新增、修改、删除、审批、导入、同步等关键业务操作，应考虑通过 `app/platform/audit/service.py` 记录审计信息。
- 需要当前用户时，通过 `app/platform/identity/deps.py` 的依赖注入获取，不要在业务模块里直接解析 header、cookie 或飞书 token。
- 飞书、ERP、LIMS 等外部系统统一放在 `app/platform/integrations/`，业务模块通过 integration service 或 adapter 调用，不直接散落 HTTP 请求。
- 外部调用要考虑超时、重试、幂等和失败记录。

## 编码风格

- 使用 Python 3.12 类型标注。
- Pydantic 使用 v2 写法。
- SQLAlchemy 使用 2.0 typed ORM：`Mapped[...]` 和 `mapped_column(...)`。
- 异步数据库访问使用 `AsyncSession`。
- 函数保持短小，业务逻辑放 `service.py`，查询放 `repository.py`。
- 不引入无必要的大型抽象。
- 不做与当前需求无关的重构。
- 不提交临时调试代码、`print` 或无用注释。
- 中文业务名可以写在 API `summary`、`description` 和文档中；代码标识符使用英文。
- **SQLAlchemy async 铁律：禁止 `db.refresh()`、禁止直接赋值未加载的 relationship。写操作后统一用 `select+selectinload` eager re-fetch 返回对象。**（不遵守会出 MissingGreenlet）
  - **为什么 INSERT 后 `flush()` 就够了？** PostgreSQL 方言对 INSERT 使用 `RETURNING` 子句，SQLAlchemy 会自动回填 `id`、`created_at`、`updated_at` 等 server default 值到内存对象。所以 `create` 类操作可以 flush 后直接返回，无需 re-fetch。
  - **为什么 UPDATE 后必须 re-fetch？** `flush()` 对 UPDATE 不使用 RETURNING，`onupdate` 的 `updated_at` 不会回填到内存对象。若后续 Pydantic `model_validate` 或上层代码访问该属性，SQLAlchemy 会触发懒加载——此时若已脱离 async session 上下文（如 FastAPI 响应序列化阶段），即报 MissingGreenlet。
  - **简单记忆：INSERT → flush 返回即可；UPDATE/DELETE → flush 后必须 select re-fetch。**
- 设计数据库表时，不要用外键约束。
- 如果新增/修改了本地env文件，需要同步修改到env example中。

## AI 工作流程

1. 先阅读 `CLAUDE.md` 和必要的架构/代码文件，判断需求属于哪个模块或平台能力。
2. 明确自己负责的模块边界，默认只修改该模块目录内的代码；不要编辑其他人负责的模块或项目架构。
3. 只有当前需求确实需要平台能力时，才最小范围修改 `core`、`shared` 或 `platform`，并说明原因。
4. 字段、流程、权限规则不明确时，先按现有架构做保守实现；不能合理推断时再提出待确认点。
5. 涉及数据库变更时，同步 ORM、migration、模块注册和测试。
6. 完成后说明修改文件、验证结果、跨模块或架构影响，以及未完成事项。

## 验证

完成代码修改后至少运行：

```bash
uv run ruff check .
uv run mypy app tests
uv run pytest
```

如果修改了 Alembic：

```bash
uv run alembic heads
```

如果修改了应用启动、路由或依赖注入：

```bash
uv run python -c "from app.main import app; print(app.title)"
```

## 禁止事项

- 不要把业务表、schema、查询和业务规则集中到全局文件或同一个模块文件里。
- 不要在 `api.py` 定义 Pydantic schema、ORM model、repository 查询或复杂业务逻辑。
- 不要让业务模块直接 import 其他模块的内部实现。
- 不要把内部 service 函数当作跨模块公共接口；跨模块接口必须经过 `public_api.py`。
- 不要在业务模块中直接写飞书、ERP、LIMS 的 HTTP 调用。
- 不要绕过 Alembic 要求用户手工改数据库。
- 不要在没有需求的情况下引入微服务、消息队列、复杂权限系统或前端代码。
- 不要修改不属于自己负责范围的模块、项目架构或全局公共代码，除非需求明确要求且已说明影响范围。
- 不要删除或重写用户已有改动，除非用户明确要求。


## 代码设计注意
由于数据表使用软删除，所以设计数据表约束时需要避免在**重复添加→删除→添加→删除时触发**的隐形bug

## 已交付功能清单（保护区域）

以下模块已完成开发和测试，**新增代码时必须保持兼容，不得回退或删除已有功能**：

### 后端（fuxing-dazah/backend/app/modules/hr/）

| 文件 | 功能 | 保护级别 |
|------|------|----------|
| `api.py` | 全部HR API端点（员工/部门/培训/台账/通知/出题/成绩单） | ⚠️ 修改前需确认影响 |
| `models.py` | AnnualTrainingPlan, AnnualTrainingPlanItem(含location/assessment_method/notes字段), DeptTrainingPersonnel, OnboardingRecord(含source字段) | ⚠️ 字段只能新增不能删除 |
| `schemas.py` | 全部Pydantic请求/响应模型 | ⚠️ 字段只能新增不能删除 |
| `service.py` | _PLAN_COLUMN_MAP(16列映射), upload_annual_plan(Excel解析逻辑) | ⚠️ 列映射修改需同步更新测试 |
| `deps.py` | _HR_PATH_PERMISSIONS(权限路由映射) | ⚠️ 新增路由需同步添加权限 |
| `ai_service.py` | AiChatService(DeepSeek API) | ⚠️ 修改前需确认 |
| `assessment_score_generator.py` | 考核成绩单Word生成器 | ✅ 可扩展 |
| `notification_document_generator.py` | 培训通知Word生成器 | ✅ 可扩展 |

### 前端（fuxing-dazah/frontend/src/）

| 文件 | 功能 | 保护级别 |
|------|------|----------|
| `app/(dashboard)/hr/training/annual-plan/page.tsx` | 年度计划页(卡片列表+明细表+新建弹窗+通知跳转) | ⚠️ 修改前需确认 |
| `app/(dashboard)/hr/training/trainers/page.tsx` | 内训师台账+部门培训人员表(Tab双页) | ⚠️ 修改前需确认 |
| `app/(dashboard)/hr/training/notification/page.tsx` | 培训通知页 | ⚠️ 修改前需确认 |
| `components/hr/TrainingNotificationClient.tsx` | 培训通知核心组件(表单/预览/出题/成绩单) | ⚠️ 修改前需确认 |
| `components/hr/OnboardingPrejobClient.tsx` | 新员工入职培训组件 | ✅ 可扩展 |
| `lib/api/hr.ts` | API_BASE='', 全部API调用函数 | ⚠️ API_BASE不能改为绝对路径 |
| `lib/menu-config.ts` | 菜单配置(已移除评估补录入口) | ⚠️ 修改前需确认 |

### 新增功能时的安全规则

1. **新增路由**：在api.py末尾添加，不要在现有路由之间插入
2. **新增字段**：在模型末尾添加，保持现有字段顺序不变
3. **新增前端组件**：在components/hr/下新建文件，通过index.ts导出
4. **修改已有函数**：如非必要不要修改函数签名，通过新增参数(带默认值)扩展
5. **数据库迁移**：每次修改模型后必须创建新迁移文件
6. **测试**：新功能必须写测试(tests/modules/hr/下新建或追加)
7. **前端构建**：修改后必须通过`pnpm build`验证
8. **Excel列映射**：修改_PLAN_COLUMN_MAP后必须用年度计划表.xlsx做回归测试