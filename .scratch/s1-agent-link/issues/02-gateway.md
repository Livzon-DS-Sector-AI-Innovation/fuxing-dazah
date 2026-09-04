# 02 — Gateway 消息路由（第一批·链路）

**What to build:** `warehouse/agent/gateway.py`——事件入口与组装层。职责：事件去重（Redis SETNX，仿 platform event_handler）、机器人自身消息排除、私聊/群@路由、会话定位（chat_id+open_id → warehouse_agent_sessions 表 upsert + 历史加载）、占位卡片（「⏳ 正在处理…」）与结果卡片替换、卡片按钮回调路由（→ ConfirmService，留 scene 扩展）、图片消息友好引导（S2 接管话术）、异常兜底降级话术、工具调用审计写 warehouse_agent_audit。Handler 注册到 event_client（@on_event）。

**Blocked by:** 01。

**Status:** done (2026-09-04, agent 实现 + 全部验收通过)

- [x] 主接缝测试：模拟文本事件 payload → handle_event 全链路（Runner 桩链路打通、卡片 dry-run 捕获两次发送；Runner 真调与 Base 真查在票03 实装后经同一接缝回归）
- [x] 群@才响应：群内非@消息忽略（零发送零会话）；私聊全响应；机器人自身消息排除（sender_type=app 或机器人 open_id）
- [x] 去重：同一 message_id 二次投递只处理一次（真 Redis SETNX EX 120，第二次零发送）
- [x] 会话：首次对话创建 sessions 记录，二次对话复用（同 id 不新建）且 history 追加两轮对话
- [x] 异常注入：Runner 抛错时用户收到降级话术卡片，audit 记录 error（error_code=RuntimeError、session_id 关联）

## Comments

**实现文件（2026-09-04）**

- `backend/app/modules/warehouse/agent/repository.py` — sessions upsert（get_or_create_session，唯一索引冲突回滚重查兜底）/ history 更新 / audit insert / drafts 读写与状态流转。只读写不含业务规则，软删除全过滤
- `backend/app/modules/warehouse/agent/runner.py` — `Reply` dataclass + `Runner` 桩（固定 echo 文案「链路打通」）+ `get_runner()` 工厂（模块级单例）。票03 实装时只改本文件/工厂内部
- `backend/app/modules/warehouse/agent/confirm.py` — ConfirmService：`request_confirm()`（写 pending_confirm 草稿 + TTL 10min + summary/payload 存 aligned JSONB）→ `build_confirm_card()`（确认/取消按钮，value 携带 scene+draft_id）→ `handle_action()`（校验链：草稿 pending → 仅发起人 → 未过期 → 执行注册回调 → audit）。回调注册表按 scene 分发（S1 仅 confirm_action，票07/S2 复用）
- `backend/app/modules/warehouse/agent/gateway.py` — @on_event 注册 `im.message.receive_v1`（handle_im_message）与 `card.action.trigger`（handle_card_action_trigger，返回卡片更新 dict 供 event_client ACK 包装）。去重（`feishu:msg:{message_id}` SETNX EX 120，Redis 异常降级放行）/ 机器人排除 / 群@检测（mentions.id.open_id）/ 文本解析（@占位符替换）/ 图片引导 / 占位+结果卡片两段式 / 降级兜底 + 审计
- `backend/app/main.py` — +1 行有效改动：lifespan 内 warehouse WS 接线处 `import app.modules.warehouse.agent.gateway  # noqa: F401`（触发 @on_event 注册，仿 production.mcp_tools 的 import 注册先例；必须位于 create_task(start_ws()) 之前）
- `backend/tests/modules/warehouse/test_live_gateway.py` — 8 测试全 PASSED

**gateway↔Runner 接口契约（票03 对接用）**

- `get_runner() -> Runner`：gateway 每次文本消息调用；票03 只改工厂内部返回真 Runner，gateway 不动
- `Runner.run(session, text) -> Reply`：session 为已定位的 `WarehouseAgentSession`（history 属性已加载；对象可能已脱离创建它的 AsyncSession——**Runner 需要新事务时自开 session，勿复用调用方事务**）；text 为解析后的用户文本（群聊 @占位符已替换为 `@名称`）
- Reply.text 为 markdown 文本，gateway 渲染进结果卡片（「仓储助手」蓝头卡片）新发（S1 不做卡片 patch）
- Runner 业务失败/内部错误直接抛异常，gateway 统一兜底降级卡片 + audit error
- 会话 history 结构：`{"messages": [{"role": "user"|"assistant", "content": str}, ...]}`，gateway 每轮追加 2 条、保留最近 24 条（≈12 轮，对齐 SESSION_ROUNDS 语义；票03 可统一配置化）

**ConfirmService 机制（票07 复用基础）**

- 发起：`request_confirm(db, requester_open_id=…, summary=…, payload=…, scene="confirm_action", expires_in_seconds=600)` → drafts 表 pending_confirm 草稿（业务载荷存 aligned.payload）；卡片用 `build_confirm_card(draft)`
- 回调注册：`register_confirm_callback(scene, callback)`，签名 `callback(db, draft) -> str | None`（同事务执行业务动作，返回用户提示）；重复注册抛 ValueError，`unregister_confirm_callback` 供测试清理
- 点击：gateway.handle_card_action_trigger 解析 value（scene 路由）→ `handle_action(db, value, operator_open_id)`：非发起人 denied / 过期置 expired / cancel 置 cancelled / confirm 执行回调后置 confirmed；回调异常保持 pending_confirm（可重试）+ audit error
- 状态机：pending_confirm → confirmed / cancelled / expired；audit tool_name="confirm"，状态 ok/denied/error

**gateway db 会话注入口（测试隔离设计）**

- `gateway._db_session`：生产=应用全局 async_session_factory 包装（ctx 退出统一 commit，gateway 不散落 commit）；测试 monkeypatch 为包装 conftest `db_session` 的无 commit 上下文，随 fixture rollback 隔离
- Runner 调用在 db ctx 之外（避免 LLM 循环期间占用连接），会话对象以 detach 态传入（expire_on_commit=False，已加载属性可用）

**测试与质量**

- 指定命令 `DATABASE_URL=…whdev uv run pytest tests/modules/warehouse/test_live_gateway.py -v`：8 passed（私聊文本 E2E 两段卡片 / 群非@零发送 / 群@响应走 chat_id 通道 / 真去重二次零发送 / 图片引导 / 会话持久化+复用+历史追加 / Runner 抛错降级+audit error / 确认流三段：发起人确认回调执行+非发起人拒绝+过期拒绝）
- warehouse 全量回归 68 passed（S0 47 + 票01 13 + 本票 8）
- `uv run ruff check` 新文件+main.py 0 告警；`uv run mypy app/modules/warehouse/agent/` strict Success（6 文件）
- `from app.main import app` 冒烟通过；import gateway 后 event_client._handlers 含两个处理器（lifespan 时序：import 注册 → create_task(start_ws())）

**发现的存量问题（未动，不属本票）**

- pytest-asyncio 每测试新建 event loop，`app.core.redis.redis_client` 模块级单例连接池跨 loop 复用抛异常——测试用 `fresh_redis` fixture 每测试替换客户端解决；生产单 loop 无此问题。其他模块测试若将来直连 redis_client 需注意同样的坑
- gateway 对群聊 @ 的判定依赖 mentions 数组的 `id.open_id`；若飞书改版只在 content 留占位符不带 mentions，需补 chat_type=group 的兜底（当前实测结构含 mentions）
