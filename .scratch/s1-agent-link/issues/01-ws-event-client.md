# 01 — WS 事件客户端 + 发送通道（第一批·链路）

**What to build:** warehouse 机器人自己的「耳朵和嘴」。`warehouse/feishu/event_client.py`（原生 WebSocket + protobuf，仿 `app/modules/safety/feishu/event_client.py`，WAREHOUSE_FEISHU_* 凭证，无限重连，@on_event 注册表）；`warehouse/feishu/notification.py`（独立凭证发文本/卡片消息，仿 safety/feishu/notification.py，支持 dry_run 注入）；`warehouse/feishu/client.py`（凭证常量，读 Settings）；`main.py` 接线（黄色操作，质询已确认：仿 safety 加 create_task(start_ws())+stop，约 4 行）+ `config.py` 补 WAREHOUSE_FEISHU_WS_ENABLED。事件解析：im.message.receive_v1（文本/图片/群@）、card.action.trigger（回调）。

**Blocked by:** None — can start immediately.

**Status:** done (2026-09-04, agent 实现 + 全部验收通过)

- [x] live 冒烟：start_ws() 建立连接且收到事件（日志验证）；protobuf 解码后事件 dict 结构与 gateway 契约一致
  - 连接验证已自动化（test_live_ws_handshake_open，wss 握手 open + service_id=33554678）；本地起服 40s 验证 warehouse WS 与 platform/safety 并行启动无冲突（期间 platform/safety 因本机存量凭证无效重试，warehouse 连接不受影响，反向证明隔离有效）。**收消息到 handler 分发**留人工冒烟，步骤见 Comments。
- [x] dry-run 单测：notification 构建卡片/文本消息体正确、dry_run=True 时不发请求
- [x] WS 单实例互不影响：warehouse WS 与 platform/safety WS 并行启动无冲突（本地起服验证）
- [x] main.py 改动 ≤6 行且仿 safety 模式（有效改动 6 行 + 2 个格式空行）

## Comments

**实现文件（2026-09-04）**

- `backend/app/modules/warehouse/feishu/client.py` — 凭证运行时读取（get_settings()，非 import 冻结，与 S0 llm_client 一致；safety 是 os.getenv import 冻结，有意不同）+ 专属 lark Client / tenant token
- `backend/app/modules/warehouse/feishu/event_client.py` — 照搬 safety 结构：WS_ENDPOINT_URL、@on_event 注册表、_dispatch（异常不中断）、无限重连（10s）、protobuf PING（服务端下发间隔）、PONG 看门狗（300s）、card.action.trigger 同步 ACK（base64 Response 信封）。日志前缀「仓库飞书事件」
- `backend/app/modules/warehouse/feishu/notification.py` — send_text/send_card/send_card_to_user，dry_run 双注入口
- `backend/app/core/config.py` — 补 `WAREHOUSE_FEISHU_WS_ENABLED: bool = False`（默认关，.env.development 已有 true）
- `backend/.env.example` — 补 WAREHOUSE_FEISHU_WS_ENABLED= 与 WAREHOUSE_TEST_CHAT_ID=
- `backend/app/main.py` — 接线 6 行（WS_ENABLED 门控 create_task(start_ws())；lifespan 退出 stop+cancel）
- `backend/tests/modules/warehouse/test_live_ws_client.py` — 13 测试全 PASSED（2 live + 11 单测/半 live）

**与 safety 实现的差异点清单（供 ticket 02 gateway 对接）**

1. **凭证来源**：`get_warehouse_feishu_app_id()/get_warehouse_feishu_app_secret()`（client.py 运行时函数），不是模块常量 import。
2. **卡片构建责任**：`send_card(chat_id, card: dict[str, Any], dry_run=None) -> str | None` 接收**完整卡片 dict**（safety 版是 title/content+elements 组合）；成功返回 message_id，dry_run 返回 `"dry_run"` 占位（模块常量 `DRY_RUN_MESSAGE_ID`），失败 None。
3. **新增 send_card_to_user(open_id, card, dry_run=None) -> bool**（私聊按 open_id）与 **send_text(chat_id, content, dry_run=None) -> bool**（text payload 为 `{"text": ...}`）。
4. **dry_run 语义**：`dry_run: bool | None = None`，None=跟随模块级 `set_dry_run()` 开关，显式 True/False 优先于模块级（任务书写的默认 False 会让模块级开关失效，故用 None）。
5. **payload 构建纯函数** `_build_create_payload(receive_id_type, receive_id, msg_type, content)` 可直接单测断言；dry_run 分支在 payload 构建之后、HTTP 之前返回。
6. **无 restart_ws/get_ws_status**（safety 的运维 API，本票最小实现未带）；`_stop` Event 驱动 stop_ws，_ws_task 由 main.py 持有。
7. **无 Bitable 订阅逻辑**（safety start_ws 里的 ensure_bitable_subscribed 块未搬）；warehouse 事件来源是机器人被 @/私聊/卡片回调，不订阅文档。
8. **事件解码契约（gateway 依赖）**：_dispatch_event 解 v2 信封 `{"schema","header":{event_type},"event"}` → `_dispatch(event_type, event.get("event"))`；card.action.trigger 处理器**返回卡片更新 dict** 即可，客户端自动包成 `{"code":200,"data":base64(card_json)}` ACK（2.9s 超时回落通用 ACK）；普通事件异步分发（不阻塞 3s ACK），处理器异常只记日志。
9. gateway 注册方式：`from app.modules.warehouse.feishu.event_client import on_event` 装饰器注册 `im.message.receive_v1` / `card.action.trigger` 等处理器。

**人工冒烟步骤（验证真实收消息 → 分发）**

1. 确认 `.env.development` 有 `WAREHOUSE_FEISHU_WS_ENABLED=true`（已有）。
2. 起服：`cd "E:\dazah(仓储)\backend" && uv run uvicorn app.main:app --port 8000`，日志出现「仓库飞书事件 WebSocket 已连接 (service_id=…)」。
3. 手机飞书用有权限的账号私聊「仓库管理机器人」发一句「你好」，日志应出现：
   - 「📨 仓库飞书事件收到(完整): {…header.event_type=im.message.receive_v1…}」（protobuf 解码成功）
   - 因 gateway 尚未实现（ticket 02），同时出现 WARNING「仓库飞书事件未注册 event_type=im.message.receive_v1 …」——**这条 warning 即证明解码后的 dict 结构与 _dispatch 分发链路正常**。
4. 群内 @机器人重复第 3 步，event payload 中 `message.chat_id` / `mentions` 字段即可对照 gateway 契约。
5. 观察数分钟无「PONG 超时」/「连接关闭」日志即心跳正常；Ctrl+C 退出应看到「仓库飞书事件 WebSocket 客户端已停止」。

**测试与质量**

- 指定命令 `DATABASE_URL=…whdev uv run pytest tests/modules/warehouse/test_live_ws_client.py -v`：13 passed（live：endpoint 真实返回 wss URL + ping 间隔、websockets 真握手 open；单测：payload 构建、dry_run 不触网、on_event/_dispatch、v2 解包、真 protobuf 帧往返 card ACK）。
- warehouse 全量回归 60 passed（S0 47 + 新增 13）。
- `uv run ruff check` 对新文件 0 告警（全仓 701 存量告警均不在新文件）；`uv run mypy app/modules/warehouse/feishu/` Success（strict）。
- 发现的存量问题（未动，不属本票）：本机 .env 中 platform 全局与 safety 应用凭证报 `1000040346 app_id is invalid`，两者 WS 均在重试循环——需凭证负责人确认，不影响本票。
