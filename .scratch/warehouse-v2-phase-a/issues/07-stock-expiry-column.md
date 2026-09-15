# 07: 库存效期列

**What to build:** 仓库管理员录入批次效期后，库存列表新增"效期"列并按紧急度着色（<30 天红、<90 天黄、其余正常），临期批次一眼可见。含库存表 expiry_date 可空列的 Alembic 迁移、API 创建/更新与返回、前端列渲染。空效期显示"—"。

**Blocked by:** 01 (前端测试设施与脚本)

**Status:** done

- [x] 迁移在空库与已有数据库均可执行（可空列，默认 NULL）
- [x] API create/update 接受并校验 expiry_date，GET 返回该字段（实际落地：MovementCreate 增加 expiry_date 且仅入库允许——model_validator 出库带效期返回 422；_add_stock_delta 建行/更新写入；StockResponse 返回）
- [x] 列表列着色规则正确（组件测试覆盖三档：lib/warehouse-expiry.ts expiryTone 纯函数 5 用例 + 列表临期渲染）
- [x] mypy/ruff 对照基线零新增

> 备注：V1.0 库存行由出入库派生、无独立 create/update 端点，效期录入路径落在入库登记（含表单字段仅入库方向显示）；测试造数编码带随机后缀避免跨测试残留，断言走 API（client 会话未提交跨会话不可见）。
