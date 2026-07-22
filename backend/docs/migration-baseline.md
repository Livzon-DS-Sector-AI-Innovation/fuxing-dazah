# Alembic 迁移压缩方案

## 适用场景

- 迁移文件积累过多（几十甚至上百个）
- 迁移链出现大量 mergepoint 和分支交叉
- 新环境部署耗时长、频繁报错
- 团队多人协作时迁移冲突频发

## 核心思路

把全部历史迁移文件压缩成 **1 个 baseline 迁移**，它包含当前所有 ORM 模型的完整建表语句。之后新环境部署只需执行这 1 个文件，秒级完成。

原理：让 Alembic autogenerate 对比 **ORM 模型** 与 **空白数据库**，生成一个"从零开始建所有表"的迁移。

## 执行步骤

### 第 1 步：创建临时空白数据库

```bash
# 在已有的 PostgreSQL 实例中创建一个空库
psql -U postgres -c "CREATE DATABASE temp_baseline"
```

### 第 2 步：删除所有旧迁移文件，生成 baseline

```bash
# 删除全部历史迁移
rm alembic/versions/*.py

# 临时切换数据库连接到空白库，生成完整建表迁移
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/temp_baseline"
alembic revision --autogenerate -m "baseline"

# 恢复原始数据库连接
unset DATABASE_URL
```

此时 `alembic/versions/` 下只剩下 1 个文件，包含所有表的 `CREATE TABLE` 语句。

### 第 3 步：补充 CREATE SCHEMA（仅限 PostgreSQL schema 隔离项目）

Alembic autogenerate 不会生成 `CREATE SCHEMA` 语句。如果你的项目使用 PostgreSQL schema 做模块隔离，必须在 `upgrade()` 开头手动添加：

```python
def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS schema_a")
    op.execute("CREATE SCHEMA IF NOT EXISTS schema_b")
    # ... autogenerate 生成的 op.create_table(...)
```

查找迁移文件中所有引用的 schema：

```bash
grep -o "schema='[^']*'" alembic/versions/*_baseline.py | cut -d"'" -f2 | sort -u
```

### 第 4 步：保护本地开发数据库

本地数据库已有全部表和数据，不能执行 baseline（会报"表已存在"）。只需更新版本号，标记为"已应用"：

```bash
# 获取新 revision ID
alembic heads

# 直接更新 alembic_version 表
psql -U postgres -d your_db -c "UPDATE public.alembic_version SET version_num = '<新_revision_id>';"
```

### 第 5 步：验证并清理

```bash
# 确认版本对齐
alembic current

# 删除临时空库
psql -U postgres -c "DROP DATABASE temp_baseline"
```

## 团队其他成员如何同步

执行压缩的人 push 代码后，其他成员 pull 下来需要处理本地数据库的版本号对齐。

### 情况 A：本地数据库有数据需要保留

```bash
# 一条 SQL 搞定，不碰业务数据
psql -U postgres -d your_db -c "UPDATE public.alembic_version SET version_num = '<新_revision_id>';"
```

### 情况 B：本地数据库无所谓

```bash
# 删库重建，启动时自动执行 baseline
docker compose down -v
docker compose up -d
```

### 情况 C：服务器空库部署

无需任何额外操作。启动时 `alembic upgrade head` 自动建表。

## 后续日常开发

压缩后，每次修改模型只需两步：

```bash
alembic revision --autogenerate -m "add_xxx_field"
alembic upgrade head
```

永远只有一条线性链，不会再出现 mergepoint 和分支冲突。

## 常见坑

| 问题 | 原因 | 解决 |
|------|------|------|
| 空库部署报 `schema "xxx" does not exist` | autogenerate 不生成 CREATE SCHEMA | 在 upgrade() 开头手动加 `op.execute("CREATE SCHEMA IF NOT EXISTS xxx")` |
| `alembic stamp head` 报 `Can't locate revision` | 旧 revision 已删除，stamp 无法解析当前版本 | 直接用 SQL 更新 `alembic_version` 表 |
| baseline 迁移为空（无建表语句） | 生成时连的是已有表的数据库而非空库 | 必须指向空白数据库生成 |
| 同事 pull 后 alembic 报错 | 本地 alembic_version 仍指向已删除的旧 revision | 执行情况 A 的 SQL |