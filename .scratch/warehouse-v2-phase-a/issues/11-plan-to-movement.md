# 11: 计划单联动登记

**What to build:** 仓库管理员从"执行中"计划单点"生成登记"：弹出预填（物料/批次/库位/数量，数量可改）的出入库登记表单，提交复用既有 movements 创建逻辑；成功后计划单自动置 completed 并回填 movement_id；已完成计划单不可再次生成，与该计划关联的登记可追溯。

**Blocked by:** 10 (计划单数据底座)

**Status:** done

- [x] 生成登记走既有 createMovement 事务（库存同步行为不变）
- [x] 成功后计划单状态 completed 且 movement_id 回填（路由测试）
- [x] 重复生成/对已完成计划生成被拒（400）
- [x] movement 侧可通过 plan 关联反查（movement_id 回填 + 审计 warehouse.plan.complete）

> 备注：端点 POST /plans/{id}/movement（权限 plans:update），body 可选 quantity/occurred_at/remark 覆盖；断言走 API 响应。
