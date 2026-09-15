# 11: 计划单联动登记

**What to build:** 仓库管理员从"执行中"计划单点"生成登记"：弹出预填（物料/批次/库位/数量，数量可改）的出入库登记表单，提交复用既有 movements 创建逻辑；成功后计划单自动置 completed 并回填 movement_id；已完成计划单不可再次生成，与该计划关联的登记可追溯。

**Blocked by:** 10 (计划单数据底座)

**Status:** ready-for-agent

- [ ] 生成登记走既有 createMovement 事务（库存同步行为不变）
- [ ] 成功后计划单状态 completed 且 movement_id 回填（路由测试）
- [ ] 重复生成/对已完成计划生成被拒绝（4xx）
- [ ] movement 侧可通过 plan 关联反查（字段或 remark 约定落地）
