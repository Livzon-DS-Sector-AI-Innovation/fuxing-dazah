# 01: 预警数据底座

**What to build:** 仓库管理员可查看与调整预警阈值：新表 alert_rules（rule_key: low_stock/zero_stock/idle/expiry/cover_days，threshold JSONB，enabled）、alert_rule_audits（变更审计）、alert_records（异常记录：rule_key/level/status/material·location 冗余/detail/resolved_by/at）、replenishment_suggestions（建议+状态）；默认阈值播种；CRUD 端点 GET/PUT /intelligence/rules + 审计；权限键 warehouse:intelligence:read/update、warehouse:replenishment:read/update 注册。

**Blocked by:** None (can start immediately)

**Status:** done

- [x] 迁移空库可执行（含默认规则播种，幂等语义）
- [x] GET /intelligence/rules 返回五条默认规则；PUT 修改 threshold/enabled 落审计
- [x] 无权限 403；非法 rule_key 404
- [x] 权限键注册对齐既有模式；conftest 权限集扩充

> 备注：新增 GET /intelligence/rules/{key}/audits（配置抽屉展示审计用）；dashboard/snapshot 测试因真机验收残留数据改为差值/过滤断言（对环境鲁棒）。
