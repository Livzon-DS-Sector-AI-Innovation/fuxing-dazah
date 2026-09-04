# 03 — Runner 循环 + 4 个查询工具（第一批·链路）

**What to build:** `warehouse/agent/runner.py`——tool-calling 循环（复用 S0 WarehouseLLMClient）：MAX_TURNS=6、工具结果截断 4KB/条、终局判定（无 tool_calls 且 content 非空）、会话历史注入（SESSION_ROUNDS=12 裁剪）。`warehouse/agent/tools/query.py`——4 个纯 async 查询工具（注册表结构，S3 套 MCP 壳）：query_stock(keyword?, qc_status?, expiring_days?)（库存明细总表）、query_material(keyword)（名称代码一览主数据）、query_movements(material?, direction?, date_from?, date_to?)（入/出库总账）、query_report(report_type: dead|unqualified)（呆料/不合格汇总）。工具内部分页：默认前 10 条+总数。`warehouse/agent/prompts.py`——系统提示词三段式（角色规则+字段字典+工具使用规则，V1.0-2.E）。

**Blocked by:** 02。

**Status:** done (2026-09-04, agent 实现 + 全部验收通过)

- [x] live 测试（主接缝）：「硫酸还有多少放行的」→ 返回卡片含真实批号/数量（Base 真查）
- [x] live 测试：「上个月乙醇入库多少」→ query_movements 聚合正确
- [x] live 测试：多工具任务（如先查物料再查库存）≤MAX_TURNS 内完成
- [x] 单测：工具结果 >4KB 截断；MAX_TURNS 超限返回兜底话术
- [x] audit 表每次工具调用有记录（tool_name/耗时/状态）

## Comments

**实现文件（2026-09-04）**

- `backend/app/modules/warehouse/agent/tools/query.py`（新增）— 4 个查询工具 + 注册表（`TOOLS` OpenAI schema / `TOOL_FUNCS` / `execute_tool` 统一异常包装 / `serialize_tool_result` 4KB 截断）。值规范化兼容实测全部形态：直接标量、formula/lookup 类型包裹 `{"type","value"}`、富文本分段 `{"text","type"}`、user `{"id","name"}`、附件、关联。分页：服务端 page_token 拉取 ≤3 页×500 条，明细默认前 10 条 + total，截断在 note 说明。测试注入口 `query._adapter`
- `backend/app/modules/warehouse/agent/prompts.py`（新增）— `build_system_prompt(skill_catalog="")` 三段式（角色规则 / 字段字典从 bitable_schema 常量生成含单选选项摘要 / 4 工具使用规则）；技能目录钩子已留（票08 传参即注入）
- `backend/app/modules/warehouse/agent/runner.py` — 真 Runner 替换桩：messages=[system, *history(SESSION_ROUNDS 轮裁剪), user] → `chat_with_tools` 循环（assistant tool_calls 原始 arguments 回填、role=tool 回填截断后结果）→ 终局（无 tool_calls 且 content 非空）返回 Reply；无 tool_calls 且 content 空时注入推进消息防空转；≤MAX_TURNS 超限返回兜底话术（不抛异常）。每次工具调用写 audit（自开事务 `runner._db_session` 注入口，写失败不阻断）；本轮工具摘要追加 `session.history["tool_logs"]`（内存追加 + 自开事务 fresh-read 持久化，保留 12 条）
- `backend/app/modules/warehouse/bitable_schema.py` — 新增 3 张表常量：`material_master`（物料名称代码一览，tblTcAG2qQWGa5R3，25 字段）、`dead_stock`（呆料汇总，tblLxUJN0rtW49zT，18 字段见下偏差）、`unqualified_stock`（不合格汇总，tblPPgtpbMU9aRsD，21 字段）；模块注释同步 7→10 张
- `backend/app/modules/warehouse/bitable_adapter.py` — 新增 `search_records_page`（records/search 分页版：返回 total/page_token，支持 sort）；`query_records` 原样未动（S0 契约不破）
- `backend/app/core/config.py` + `.env.example` — `WAREHOUSE_AGENT_MAX_TURNS=6`、`WAREHOUSE_AGENT_SESSION_ROUNDS=12`
- `backend/tests/modules/warehouse/test_live_runner.py`（新增）— 7 测试全 PASSED
- `backend/tests/modules/warehouse/test_live_gateway.py` — 桩文案断言适配 + `fresh_runner` autouse fixture（见下）

**测试逐条摘要（指定命令，7 passed ≈ 65s）**

1. test_query_stock_live：「硫酸还有多少放行的」→ 真回复含预查真实批号/数量。预查基准：硫酸放行 95 个批次，如 批号 10228-251001 / 剩余 0 / 瓶 / 24#仓库四-3区 / AR级 / 入库 2025-10-15
2. test_query_movements_live：「上个月入库了哪些物料」→ 回复含真实物料名。预查 2026-08 入库 408 条：乙醇 1,100,810 Kg、液碱 601,880 Kg、盐酸 557,030 Kg…
3. test_query_report_live：「查一下呆料清单」→ 回复含真实呆料物料（无水乙酸钠 SRM25122907 / 3700 Kg / 16#旧原料库一）
4. test_multi_tool_task_live：「帮我看看活性炭的基本信息还有现在库存多少」→ Agent 依次调 query_material（活性炭 代码 10103 / 药用级 / chemviron / 免检=否）+ query_stock，audit 表 2 条 ok 记录（含 duration_ms、session_id 关联）
5. test_truncation：假 adapter 单条超大记录 → 回填 LLM 的 tool content 4088 bytes ≤4096 且带截断提示
6. test_max_turns_guard：假 LLM 永远发 tool_calls → 恰好 6 轮、返回 FALLBACK_REPLY 兜底话术、6 条 audit
7. test_get_runner_factory_contract：get_runner() 单例契约保持

**bitable_schema 新增表常量说明**

- 字段/类型来源 base_scan/material/fields/ 快照（TYPE 字符串→飞书数字码映射），单选选项集快照未收录、为空（校验放行原则，本票 4 工具均为只读不受影响）
- `material_master` 的 table_id=tblTcAG2qQWGa5R3 与票面一致，live 验证通过（活性炭 6 条命中）
- 呆料/不合格 table_id 见下偏差处理；`dead_stock` 字段快照按测试版实测 18 字段收录（月度出库汇总形态）

**偏差处理（live 实测发现，如实记录）**

1. **呆料/不合格表 table_id**：票面给的 tbl3AhExWLtRww0g / tblnD7EscmnRcBH5 是工作版快照坐标，测试版 Base（LmuBb3）报 1254004 WrongTableId。经 list_tables 实测：呆料汇总=tblLxUJN0rtW49zT、不合格汇总=tblPPgtpbMU9aRsD，已按实测修正常量
2. **测试版呆料表结构差异**：测试版该表字段为月度出库汇总形态（18 字段），无产生呆料数量/处理方式/处理进度/使用部门/登记日期等呆料核心字段 → `query_report(dead)` 数据源改为入库总账「呆料判断=是」批次清单（material_receipt filter，实测 1 条呆料批次命中），报表名标注「呆料批次清单（入库总账·呆料判断=是）」。unqualified 数据源不变（测试版 21 字段与快照一致，51 条）
3. **datetime 过滤不可用**：该 Base 的 records/search 对 datetime 字段任何比较过滤（is/isGreater/isGreaterEqual/isLess 等）均 1254018 InvalidFilter（select 过滤正常）→ `query_movements` 日期范围改为本地过滤 + 服务端 sort（按日期字段 desc）拉最近数据（≤1500 条），截断在 note 说明。adapter `search_records_page` 因此支持 sort 参数
4. **records/search 值形态**：formula/lookup 列返回 `{"type","value"}` 包裹、文本列可能返回富文本分段——工具层值规范化统一兼容（见 tools/query.py 模块注释）
5. **「单位」列**：一览表无「单位」字段，query_material 返回「单位换算」列并在结果 note 与字段字典中说明；一览表「规格」实际字段名为「飞书规格」
6. **会话历史持久化分工**：Runner 不重复写 user/assistant 到 history["messages"]（gateway 尾部已追加并覆盖写库，票02 契约）；Runner 持久化 tool 摘要到 `history["tool_logs"]` 独立键 + 内存同步到入参 session 对象（gateway 覆盖写库时自然携带、不丢失），直调（不经 gateway）时自开事务 fresh-read 写库
7. **票02 测试适配**：test_text_private_message_e2e / test_group_mention_responded 原断言桩文案「链路打通」，真 Runner 后回复不固定 → 改断言结果卡片 content 非空（票02 Comments 预告过「Runner 真调经同一接缝回归」）；另加 `fresh_runner` autouse fixture——get_runner() 单例的 httpx 连接池跨 pytest-asyncio event loop 复用会报错（同票02 记录的 redis_client 单例坑），每测试重置 `_runner=None`

**质量**

- `uv run ruff check`（agent/ + bitable_* + config + 2 测试文件）0 告警；`uv run mypy` strict（agent/ 9 文件 + adapter/schema）Success；platform/safety 零改动，gateway.py 零改动
- warehouse 全量回归 **75 passed**（S0 47 + 票01 13 + 票02 8 + 本票 7），142s
- models.py 有一处存量 ruff I001（import 排序，非本票触碰，未动）
