# 03 — MCP 端点挂载（只读）

**What to build:** ① `warehouse/mcp_tools/__init__.py` + `query_mcp.py`：mcp = get_module_mcp("warehouse")；@mcp.tool() 包装 4 个只读查询（扁平签名：query_stock(keyword, qc_status, expiring_days)/query_material(keyword)/query_movements(material, direction, date_from, date_to)/query_report(report_type)——内部调 tools/query.py 函数，返回 ToolResult 文本摘要；DB 依赖照 equipment 模式）。② main.py 挂载（黄色操作仿 equipment：warehouse_mcp_asgi = get_mcp_app(get_module_mcp("warehouse"), path="/", middleware=mcp_middleware) + lifespan + mount("/mcp/warehouse")，≤6 行）。③ 不暴露任何写入工具（安全决策）。④ 接入文档 `docs/mcp-warehouse.md`：端点/认证（api-key header）/工具清单/妙搭接入示例。

**Blocked by:** None（与 01/02 并行，串行执行）。

**Status:** done

- [x] 端点测试：httpx ASGI /mcp/warehouse 不带/带错 api-key → 401（error.code -32001，真实挂载 app；另有独立子应用无 key 401 佐证中间件在协议链路生效）
- [x] 工具调用测试：经 MCP 协议调 query_stock 返回库存摘要（live Base）
- [x] 只读断言：mcp 实例工具清单无 submit/create/update/delete 类工具
- [x] main.py 挂载 ≤6 行（4 行有效：import / get_mcp_app / lifespan / mount）；接入文档产出 `backend/docs/mcp-warehouse.md`

## Comments

- 实现：`app/modules/warehouse/mcp_tools/__init__.py` + `query_mcp.py`（mcp = get_module_mcp("warehouse")，4 个 @mcp.tool() 扁平签名，内部直调 agent/tools/query.py 同名函数复用全部规范化/分页/过滤逻辑，返回 markdown 表格 + structuredContent JSON）。4 个查询不依赖 DB 会话（数据源为 Bitable adapter），未用 get_db()；DB session 由 MCPToolLoggingMiddleware 按调用粒度创建仅用于审计日志，与 equipment 模式一致。
- main.py 挂载 4 处共 4 行有效：`import app.modules.warehouse.mcp_tools`、`warehouse_mcp_asgi = get_mcp_app(...)`、lifespan 组合加一行、`app.mount("/mcp/warehouse", ...)`。
- 测试 `tests/modules/warehouse/test_live_mcp_endpoint.py` 5 passed：401 拒绝（真实挂载 app，无 key/错 key，注意挂载根要带尾斜杠否则 307）、独立子应用无 key 401、tools/list 集合 == 预期 4 个、tools/call query_stock("硫酸") live Base 真数据（95 条）、写入前缀断言。
- 测试要点：MCP_AGENT_API_KEYS 在 main.py 导入时冻结（dev env 为空即全拒），有效 key 用例按 main.py 同配方注入 `Middleware(MCPAuthMiddleware, valid_keys={测试key})` 构建 ASGI 并在测试协程内进出 lifespan（anyio cancel scope 要求同 task 进出，不能用 async generator fixture）；MCPAuthMiddleware 只拦 path 以 /mcp 开头的请求，独立子应用需 path="/mcp" 才过认证（与挂载场景 Mount 保留完整 path 一致）。
- mypy 偏差：`app/main.py` 新增 mount 行使既有同类误报 `Module has no attribute "mount" [attr-defined]` 从 5 处变 6 处（与 production/equipment/platform 三行同款同因，mypy 对 FastAPI mount 模式的既有问题）；新文件 query_mcp.py 单独检查 0 错误。main.py 在改动前即不满足 ruff format（既有长行），按最小改动原则未重排。
- platform/safety 零改动。全量回归见最终汇报。
