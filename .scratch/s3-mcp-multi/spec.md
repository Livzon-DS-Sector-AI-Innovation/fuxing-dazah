# S3 — 多场景写入 + MCP 端点（Spec）

**日期**: 2026-09-07
**状态**: ready-for-agent
**上游**: 设计文档 V1.0-2（MCP 双用途）/ V1.0-3 场景 C/D / V1.0-8 S3；S2 已交付识别 Pipeline/draft_flow/submit 模式（scene 机制可扩展）

## Problem Statement

V1.0 的写入目前只有原辅料入库一个场景。计划文档 1.3（GMP 出库）、成品 2（成品出库+快递单）仍是手工录入；「送货单识别 + MCP 查询」试点中的 MCP 查询端点未暴露，外部 Agent（妙搭等）无法接入。

## Solution

三块独立交付 + 收官回归：**① GMP 对话式登记**（质量部对机器人说出库信息 → LLM 收集 → 草稿确认 → submit_gmp）；**② 成品出库识别 + 快递推送**（拍照出库单/快递面单 → 识别 → 写台账 → 快递号对话确认目标后推送）；**③ MCP 端点**（/mcp/warehouse 挂载，只读暴露 4 个 query 工具，API Key 认证）。

## User Stories

1. 作为质量部人员，我对机器人说「三氯甲烷 10423-260601 出库 25kg，生产批号 MA-ET-2026-050A，领用部门提炼一部」，确认卡片点一下即完成 GMP 出库登记。
2. 作为质量部人员，字段说漏了机器人会追问，不说单据类型默认「出库」。
3. 作为成品仓管员，我拍出库单/快递面单发机器人，确认后写入成品出库台账（含快递号）。
4. 作为成品仓管员，快递号登记后机器人问我推送给谁，确认后对方收到发货通知卡片。
5. 作为外部系统/Agent，我持 API Key 经 /mcp/warehouse 查询仓储库存/物料/流水/报告（只读）。
6. 作为开发者，MCP 工具调用有平台级日志与审计，密钥无效请求被拒。

## Implementation Decisions（2026-09-07 质询定稿）

1. **GMP 对话式登记**：新工具 `create_gmp_draft(fields)`（LLM 从对话收集：物料名称/物料批号/数量/单位/生产批号/领用部门，缺字段追问；单据类型默认「出库」）→ 复用 draft_flow（scene=gmp_outbound）→ 确认卡片（复用渲染器按场景分支）→ submit_gmp（字段映射：日期=当天、单据类型/单位等单选字符串、validate+读回核对，参照 submit_receipt 模式）。drafts.scene 已预留该值。
2. **成品出库识别**：新识别 prompt `recognize_finished_outbound`（产品名称/产品批号/出库量/单位/销售客户/用途/快递号/温度计——选提为主，产品名称与数量必提）→ 复用 draft_flow（scene=finished_outbound）→ submit_outbound（出库日期=当天、用途等单选适配）。gateway 图片路由按场景分流：现 receipt Pipeline 为主；**成品出库识别入口=对话触发**（用户说「登记成品出库」+发图，LLM 调工具取最近图片草稿？——简化：图片仍走 receipt 识别；成品出库登记本期走对话式（同 GMP），拍照识别成品出库单留 V1.1（测试集同样需要真实照片））。
3. **快递推送对话确认**：submit_outbound 成功后若识别到快递号 → 回执卡片附「要推送给谁？」→ 用户答目标（group:chat_id/user:open_id）→ 复用 send_card 确认门发送（不预配置路由表）。
4. **MCP 只读暴露**：`warehouse/mcp_tools/query_mcp.py`——@mcp.tool() 包装 4 个查询（query_stock/query_material/query_movements/query_report，签名扁平化，内部复用 tools/query.py 的函数）；`main.py` 挂载 `get_mcp_app(get_module_mcp("warehouse"), ...)` + mount "/mcp/warehouse"（黄色操作，仿 equipment 三例，≤6 行）；认证复用 MCPAuthMiddleware（MCP_AGENT_API_KEYS，api-key header）；**不暴露写入工具**（外部 Agent 写入绕过 HITL，留 V1.1）。
5. **update_draft 通用化**：MUTABLE_STATUSES 与 scene 过滤从 receipt 硬编码放宽为 receipt/gmp_outbound/finished_outbound（草稿修改三场景通用）。
6. **提示词**：Runner 系统提示词补 GMP 登记与成品出库规则（场景判定/默认值/追问策略）；注意三场景叠加后的提示词长度控制（字段字典保持按需）。

## Testing Decisions

- 接缝沿用既有哲学：gateway 主接缝（对话文本 → GMP 草稿 → 确认 → submit live 写删读回）+ 组件直测（submit_gmp/outbound 字段映射纯函数、MCP 工具经 FastMCP client 调用测试）+ **MCP 端点级测试**（httpx ASGI 带 api-key 调 /mcp/warehouse，无效 key 401）。
- live 测试写 Base 后按 record_id 精确 finally 清理（S2 事故纪律）。
- 运行：`DATABASE_URL=...whdev uv run pytest tests/modules/warehouse/ -v`。

## Out of Scope

- 成品出库拍照识别（V1.1，需真实照片测试集）；MCP 写入暴露（V1.1）；GMP 退库流程（单据类型=退库的差异化处理，先支持出库）；快递推送固定路由表（V1.1）。

## Further Notes

- gmp_outbound 13 字段：物料名称(lookup 只读)/物料代码(lookup)/物料批号(单选)/日期/单据类型(出库|退库)/领用品种/领用部门/单位(kg|瓶|L)/领用数量/生产批号/物料大类(lookup)/公式计算/创建人(created_user 只读)——**可写字段仅 7 个**（lookup/创建人拒写）。
- finished_outbound 21 字段：产品名称(15 选项)/品规/产品批号/出库量/单位(kg|十亿|g)/销售客户/用途(8 选项)/快递号/温度计/业务员(user)等。
- MCP_AGENT_API_KEYS 为空时中间件拒绝全部请求（现状），试点前需配置至少一个 key。
