# 安全 Agent 验收缺陷修复日志（fix-plan.md 实施）

实施：2026-10-29，ZCode。分支 feature/warehouse-module（唯一分支直提直推）。

## 拍板点处置

开工前 4 个拍板点用户未应答，按任务指示「不空等」全部采用 fix-plan 建议案：

| 拍板点 | 采用 |
|---|---|
| #1 匿名 web 口径 | 登录未绑定→viewer；匿名（无 cookie）→全拒 |
| #3 显式群与总卡 | 点名群只发点名群，不双写总卡 |
| #2/#6 超时档位 | LLM 120s / 轮次 150s / 工具 120s / overview 单域 30s |
| #9 记忆 | 默认保留注入 + 新增 /forget |

## 基线

- 全量 pytest 基线 R1（批次①改码后、含新增测试）：**64 failed / 3606 passed / 11 skipped / 3 errors**
- 预存红家族（与本任务无关，回归判罚=不新增）：production/workbench 8、safety domain_pages 2、facility_dispatch 1、facility_map_suggestions 3、overview 3（数据污染）、ragplus 1、regulation_ingest 3、warehouse live_submit/push_center/push_center_api/web_gateway 4+3 errors、以及其余散布红
- 复核证明 overview 3 红在未改动代码时同样失败（git stash 对照）

## 批次① 稳定性（#2 + #6 + #8）

**改动文件**
- `backend/app/modules/safety/business_agent/agent.py` — AgentRuntimeConfig 增 timeout 字段（ai_config registry 默认 120 接线），指纹并入 timeout；_build_agent 构造 `httpx.AsyncClient(timeout=Timeout(120, connect=5))` 传入 DeepSeekProvider（openai SDK 默认 600s 是挂死根因）
- `backend/app/modules/safety/business_agent/executor.py` — ①轮次看门狗：run_turn/resume 两处 `_agent_run` 外包 `asyncio.wait_for(timeout=cfg.timeout+30)`，TimeoutError 单独分支出友好话术 + failed 审计（resume 超时话术防重复发起）；②#8 pending 守门：`_has_unprocessed_write_call`（历史尾部未回包写 ToolCall → 拦截新消息不进模型，防 pydantic-ai UserError 报废会话）
- `backend/app/modules/safety/business_agent/core/pipeline.py` — execute_tool 工具层 120s 超时（顺带兜住慢工具）
- `backend/app/modules/safety/service/overview.py` — build_overview `_run` 单域 30s 超时降级（`_DOMAIN_TIMEOUT`）
- `backend/app/modules/safety/business_agent/session_store.py` — **#8 深挖出的 web 断链修复**：get_or_create_session 在 chat_id 可解析为 UUID 时先按行 id 回查（前端续轮回传行 id，原按 chat_id 查永远 miss → 每轮新建空会话、历史断链、首轮事件孤儿化）
- `backend/app/modules/safety/api/business_agent.py` — _execute_turn_and_persist 会话解析后将 deps.session_id 对齐真实行 id（事件/派生历史/记忆提取归位）
- `frontend/src/components/safety/AgentChat.tsx` — #2 层3 前端止损：fetch AbortController + 160s 计时（服务端看门狗 150s+余量）；/stop 真正 abort fetch，话术改「已停止显示（后台可能仍在处理）」
- `backend/tests/modules/safety/test_agent_acceptance_fixes.py` — 新增 11 测试（timeout 接线/指纹/看门狗/守门/工具超时/overview 超时/会话续链）

**测试**：新测试 11 绿；agent_chat_stream / session_concurrency / agent_config_runtime / overview 套件无新增红；全量（见批次 commit 时记录）。

**真机验证（2026-10-29 本机 uvicorn --reload + creator token）**
- 正常问「未关闭隐患」→ 11.5s 真实作答（44+5 条）——正常路径无回归
- B05d 序列：请求建文档 → 📋确认卡 → 不点卡发新消息 → **⚠️守门话术**（原为 UserError 报废会话）
- 取消卡片 → 同会话追问演练 → 正常作答且**上下文续链**（断链修复生效；修复前同操作每轮新建空会话）

## 批次② 权限面（#1）

（待填）

## 批次③ 推送正确性（#3 + #5）

（待填）

## 批次④ 数据正确性（#4）

（待填）

## 批次⑤ 体验（#7 → #10 → #9 → #11）

（待填）

## 统一回归清单复测

（待填：A05/A09/A10/A13/A15/A29 挂死六问法 · B05c · B07 · B08+b/B08b · B05d · C3/C1v · A26 · A19/B06 · D1 · A14 · B01-B03/B09 · 定时链路比对）
