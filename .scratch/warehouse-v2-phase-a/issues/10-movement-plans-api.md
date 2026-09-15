# 10: 计划单数据底座

**What to build:** 引入出入库计划单：新表 warehouse_movement_plans（plan_no 唯一、direction: inbound/outbound、source_type 沿用 movement 枚举、物料/批次/库位冗余字段、planned_quantity、planned_date、status: planned/in_progress/completed/cancelled、cancel_reason、movement_id 回填、remark）；CRUD + 状态流转端点（start/cancel）；权限键 warehouse:plans:list/create/update/cancel 注册。planned→in_progress→completed 单向，任意非完成态可取消且必填原因，非法流转返回 4xx。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] 迁移在空库可执行；软删唯一约束对齐既有惯例
- [x] CRUD + start/cancel 路由测试全绿（含非法流转 400、缺原因 422、无权限 403）
- [x] 权限键注册并对齐既有 PermissionDef 声明模式（plans:list/create/update/cancel）
