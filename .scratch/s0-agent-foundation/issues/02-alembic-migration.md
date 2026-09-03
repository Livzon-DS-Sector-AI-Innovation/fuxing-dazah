# 02 — Alembic 迁移：5 张 Agent 状态表

**What to build:** 一次迁移建齐 5 张 Agent 状态表（黄色操作已确认）。schema=`warehouse`（已存在，无需 CREATE SCHEMA）。全部继承 `app/shared/base_model.py` 的 BaseModel。字段定义按设计文档 V1.0-4：drafts（draft_no 唯一、scene、source_image、recognized/aligned JSONB、status、target_base/table/record_id、created_by、expires_at）、sessions（chat_id+user 唯一、历史摘要 JSONB）、audit（tool_name、args 摘要、结果状态、耗时、draft_id/plan_id 关联、session 关联）、plans（plan_id 唯一、title、steps JSONB、status）、memories（scope、owner_open_id、type、content、hit_count）。常用查询索引显式声明。

**Blocked by:** None — can start immediately.

**Status:** done

> 实现记录（2026-09-03）：迁移 `7bf849ceb7e2`；upgrade → downgrade -1 → upgrade 往返已在 dazah_whdev 实跑通过（12 索引全就位，含 sessions 部分唯一索引）。

- [ ] 新增迁移文件（创建前先查 `alembic heads` 确认单 head，遵守多人协作规范）
- [ ] ORM 模型落在 `app/modules/warehouse/models.py`（或 models/ 拆分，当前规模单文件即可）
- [ ] `alembic upgrade head` 到 dazah_whdev 成功（DATABASE_URL 覆盖），downgrade -1 再 upgrade 往返成功
- [ ] 表结构断言：5 张表存在、schema=warehouse、draft_no/plan_id 唯一索引、关键 JSONB 列
