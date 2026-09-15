# 07: 库存效期列

**What to build:** 仓库管理员录入批次效期后，库存列表新增"效期"列并按紧急度着色（<30 天红、<90 天黄、其余正常），临期批次一眼可见。含库存表 expiry_date 可空列的 Alembic 迁移、API 创建/更新与返回、前端列渲染。空效期显示"—"。

**Blocked by:** 01 (前端测试设施与脚本)

**Status:** ready-for-agent

- [ ] 迁移在空库与已有数据库均可执行（可空列，默认 NULL）
- [ ] API create/update 接受并校验 expiry_date，GET 返回该字段
- [ ] 列表列着色规则正确（组件测试覆盖三档）
- [ ] mypy/ruff 对照基线零新增
