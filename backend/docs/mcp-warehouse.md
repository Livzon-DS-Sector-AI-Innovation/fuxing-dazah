# 仓储 MCP 端点接入指南（/mcp/warehouse，只读）

面向外部 AI Agent / 系统（妙搭、Claude、自建 Agent 等）接入仓储查询能力的说明。
端点经 **API Key 认证**，**只读**暴露 4 个查询工具；任何写入能力均不在此端点。

- 端点 URL：`http://<host>:<port>/mcp/warehouse`（Streamable HTTP，MCP 协议版本 2025-06-18）
- 认证方式：HTTP header `api-key: <你的key>`（key 由管理员在服务端环境变量 `MCP_AGENT_API_KEYS` 中配置，逗号分隔多个，与设备/生产等端点共用一套）
- 只读边界：仅查询，不落库；详见下文「安全边界」

## 工具清单（4 个，全部只读）

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `query_stock` | `keyword?`（物料名/批号模糊）、`qc_status?`（放行/条件放行/否决）、`expiring_days?`（临期天数） | 物料库存明细：每批次的剩余数量、单位、贮存位置、QA放行、入库日期、有效期 |
| `query_material` | `keyword`（必填，名称/代码/ERP名称模糊） | 物料主数据：代码、级别、规格、物料大类、生产商、复验期、包装规格 |
| `query_movements` | `material?`、`direction?`（inbound/outbound/both）、`date_from?`、`date_to?`（YYYY-MM-DD） | 出入库流水：按物料聚合汇总数量 + 最近明细 |
| `query_report` | `report_type?`（dead=呆料批次清单，默认 / unqualified=不合格物料清单） | 汇总报表，前 10 条 + 总数 |

返回为 markdown 摘要表格（`content`）+ 结构化 JSON（`structuredContent`，含 `total` / `records` / `note`）。明细默认前 10 条 + 总数；拉取上限 1500 条，超出在 `note` 中说明，请加关键词/日期缩小范围。

## 安全边界

- **只读暴露，不暴露任何写入工具**：工具清单里不存在 submit/create/update/delete 类工具（有自动化测试断言兜底）。外部 Agent 需要写入（入库/出库登记等）请走飞书对话机器人——写入操作在机器人内有草稿确认门（HITL），人工点确认才落库；MCP 端点绕过了这道门，因此永不开放写入。
- 密钥无效的请求一律 401（JSON-RPC error code -32001），并记录告警日志；每次工具调用有平台级日志（调用方 key 前 8 位、工具名、入参、返回摘要、耗时）用于审计。
- 请妥善保管 key，不要提交进代码仓库；泄露后由管理员从 `MCP_AGENT_API_KEYS` 移除并轮换。

## 手动验证（curl 握手）

```bash
BASE=http://localhost:8000
KEY=<你的key>

# 1) initialize（从响应头拿 mcp-session-id）
curl -s -D init.headers -o init.json -X POST "$BASE/mcp/warehouse/" \
  -H "api-key: $KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
SID=$(grep -i mcp-session-id init.headers | sed 's/.*: //' | tr -d '\r')

# 2) initialized 通知
curl -s -X POST "$BASE/mcp/warehouse/" \
  -H "api-key: $KEY" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <上一步响应头里的值>" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 3) tools/list
curl -s -X POST "$BASE/mcp/warehouse/" \
  -H "api-key: $KEY" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <同上>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 4) tools/call 查库存
curl -s -X POST "$BASE/mcp/warehouse/" \
  -H "api-key: $KEY" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <同上>" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"query_stock","arguments":{"keyword":"硫酸"}}}'
```

注意：挂载根路径 `/mcp/warehouse` 会 307 重定向到 `/mcp/warehouse/`，客户端请直接使用带尾斜杠的 URL（或开启跟随重定向）。

## 妙搭（MCP 客户端）配置示例

在妙搭的 MCP 工具/连接器配置中填入：

```json
{
  "mcpServers": {
    "dazah-warehouse": {
      "url": "http://<host>:<port>/mcp/warehouse/",
      "transport": "streamable-http",
      "headers": {
        "api-key": "<你的key>"
      }
    }
  }
}
```

## Claude（Claude Desktop / Claude Code）配置示例

Claude Desktop（`claude_desktop_config.json`）或 Claude Code（`~/.claude.json` 的 mcpServers）：

```json
{
  "mcpServers": {
    "dazah-warehouse": {
      "type": "http",
      "url": "http://<host>:<port>/mcp/warehouse/",
      "headers": {
        "api-key": "<你的key>"
      }
    }
  }
}
```

任意支持 Streamable HTTP + 自定义 header 的 MCP 客户端均可按同样方式接入：URL 指向 `/mcp/warehouse/`，认证头为 `api-key`。

## 试点验证记录

### 2026-09-07 本地四步握手验证（真实挂载 app，S3 ticket 04）

- **环境**：Windows 10 / 本地 `uv run uvicorn app.main:app`（127.0.0.1:8765），连接 whdev 库与测试版 Base；服务端以环境变量 `MCP_AGENT_API_KEYS=wh-pilot-verify-key-2026` 启动（试点时换成正式 key，逗号分隔可配多个，与设备/生产等 MCP 端点共用一套中间件）。
- **对象**：`app.main` 实际挂载的 `/mcp/warehouse/`（非测试替身），协议版本 2025-06-18。
- **结果：四步全部通过**：

| 步骤 | 请求 | 结果 |
| --- | --- | --- |
| 1. initialize | POST `/mcp/warehouse/` + api-key | HTTP 200，响应头返回 `mcp-session-id`，`protocolVersion=2025-06-18` |
| 2. notifications/initialized | 带 `mcp-session-id` | HTTP 202 |
| 3. tools/list | 同上 | HTTP 200，工具清单恰好 4 个只读工具：`query_stock`、`query_material`、`query_movements`、`query_report` |
| 4. tools/call `query_stock {"keyword":"硫酸"}` | 同上 | HTTP 200，`isError=false`；返回 markdown 表格 + `structuredContent`（total=95，records 含 物料名称/物料批号/剩余数量/单位/贮存位置/QA放行/入库日期/有效期，仅前 10 条 + 总数） |

- **响应样例（tools/call，截断）**：

```json
{"jsonrpc":"2.0","id":3,"result":{"isError":false,"content":[{"type":"text","text":"物料库存明细：共 95 条\n| 物料名称 | 物料批号 | 剩余数量 | ...\n| 硫酸 | 10228-251001 | 0 | 瓶 | 24#仓库四-3区 | 放行 | ..."}],"structuredContent":{"total":95,"records":[{"物料名称":"硫酸","物料批号":"10228-251001","剩余数量":"0","单位":"瓶","贮存位置":"24#仓库四-3区","QA放行":"放行"}],"note":"数据量超过拉取上限（1500 条）..."}]}
```

- **Windows 客户端注意事项**：Windows 的 `curl.exe` 会把命令行内联的中文按本地代码页（GBK）发送，服务端按 UTF-8 解码将报 `-32603 utf-8 decode` 错误。解决办法任选其一：中文参数写成 JSON `\u` 转义（如 `"keyword":"\u786b\u9178"`）；或把请求体存为 UTF-8 文件后 `--data-binary @body.json` 发送。Linux/macOS 终端与各 MCP 客户端（妙搭/Claude）不受影响。
- **审计确认**：本次 tools/call 在服务端日志留下平台级审计两条（`app.platform.mcp.logging_middleware`）：`event=mcp_tool_start tool=query_stock agent=wh-pilot... args={"keyword":"硫酸"}` 与 `event=mcp_tool_success ... duration_ms=3716.94`（调用方 key 前 8 位、工具名、入参、返回摘要、耗时）；HTTP 层另有 `app.platform.audit.middleware` 的 audit_request 访问日志。

### 试点上线清单（核对于 2026-09-07）

| 事项 | 状态 | 说明 |
| --- | --- | --- |
| 服务端 `MCP_AGENT_API_KEYS` 配置 | 待生产配置 | 环境变量，逗号分隔多个 key；**为空时中间件拒绝全部请求**（有自动化测试兜底：无 key/错 key → 401，error code -32001）。key 不要提交进仓库 |
| 妙搭配置 JSON | 见上文「妙搭配置示例」 | url 填 `http://<host>:<port>/mcp/warehouse/`（带尾斜杠，根路径会 307）、headers 加 `api-key` |
| 只读边界 | 已验证 | tools/list 恰好 4 个查询工具，无 submit/create/update/delete 类写入工具（`tests/modules/warehouse/test_live_mcp_endpoint.py` 自动化断言）；写入必须走飞书机器人 HITL 确认门 |
| 审计位置 | 已验证 | 工具调用审计在服务端应用日志（`MCPToolLoggingMiddleware`：key 前 8 位/工具名/入参/返回摘要/耗时）；HTTP 访问审计在平台 audit 中间件日志。密钥无效请求 401 并记告警日志 |
| 端点连通性 | 已验证 | 本地真实挂载 app 四步握手通过（见上表） |
