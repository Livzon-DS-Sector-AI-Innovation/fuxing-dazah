# 07 — 办公工具 + HITL 确认门（第二批·Harness）

**What to build:** `warehouse/agent/tools/office.py` + ConfirmService——send_card(target: user|group, title, content)（**HITL**：先出预览卡片[确认发送][取消]→d bail drafts 表 scene=confirm_action→点确认（仅发起人生效）→真发 notification）；create_reminder(time, content, target)（scheduler register_generator 动态任务，到点发提醒卡片）。回调路由接入 gateway（02 留的 scene 字段）。

**Blocked by:** 04。

**Status:** done (2026-09-04, agent 实现 + 全部验收通过)

- [x] 组件测试：确认门全流程（请求→预览→点确认→dry-run 捕获发送内容）；非发起人点击拒绝；取消/超时（TTL 10min）清理
- [x] create_reminder：注册动态任务 + 取消；到点触发（可注入短间隔验证）
- [x] 主接缝 live：「把呆料清单发给陈玉英」→ 预览卡片 → 点确认 → 发送成功（真发到测试目标）——按主会话任务书以「把呆料清单发给 group:XXX 测试群」执行（dry-run 捕获，真 LLM 流程）

## Comments

**实现文件（2026-09-04）**

- `backend/app/modules/warehouse/agent/tools/office.py`（新增）— 2 个工具 + 确认回调 + 轻量调度：
  - `send_card`（工具壳）→ `request_card_send`：parse_target 校验（仅 `user:<ou_…>` / `group:<oc_…>`，人名当 ID 直接 error 引导 LLM 向用户索取）→ `confirm.request_confirm`（drafts：scene=send_card、pending_confirm、TTL 600s、payload=target/title/content/发起人/chat_id/session_id）→ `cards.render_confirm_preview_card` 发预览卡片（优先发 ctx.chat_id 所在会话，无 chat_id 私聊发发起人）→ 返回 pending_confirm 给 LLM（提示词引导提醒用户确认）
  - `_execute_send_card`（scene=send_card 确认回调，模块导入即注册）：`render_outgoing_card` → notification 真发目标（user→send_card_to_user / group→send_card）；失败抛异常 → 草稿保持 pending 可重试 + audit error
  - `create_reminder`（工具壳）→ `schedule_reminder`：ISO 时间解析（naive 按北京时间 UTC+8 固定偏移解释）、未来时间校验、目标格式校验 → drafts（scene=reminder、status=scheduled、expires_at=触发时间）→ 模块级 `_reminder_tasks` dict + `asyncio.create_task` 延时任务 → 到点 `render_reminder_card` 投递（显式 target > 发起会话 > 发起人私聊）→ 状态 fired/failed；`cancel_reminder(reminder_id)` 撤销任务 + 置 cancelled
- `backend/app/modules/warehouse/agent/confirm.py` — 补 `is_registered_scene()`（gateway 路由分发依据）；状态机骨架（发起人/TTL/cancel 校验、回调执行、audit）票02 已完整，未改
- `backend/app/modules/warehouse/agent/cards.py` — +3 渲染器：`render_confirm_preview_card(payload, scene, draft_id)`（title/content 摘要 + 目标精确展示 + [✅ 确认发送][❌ 取消]，按钮 value 携 scene+draft_id）、`render_outgoing_card(title, content)`（确认后真实外发卡片）、`render_reminder_card(reminder)`（到点提醒卡片）
- `backend/app/modules/warehouse/agent/gateway.py` — 最小改动（1 处条件）：`handle_card_action_trigger` 路由从仅 `CONFIRM_SCENE` 扩为「CONFIRM_SCENE 或已注册回调的 scene」，send_card 场景才能进确认门；未注册场景仍返回 None（S2 扩展位语义不变）
- `backend/app/modules/warehouse/agent/tools/query.py` — `OFFICE_TOOL_FUNCS`/`OFFICE_TOOLS_SCHEMA` 并入 `TOOL_FUNCS`/`TOOLS`
- `backend/app/modules/warehouse/agent/prompts.py` — 工具使用规则 +2 条：send_card（target 格式、人名必须追问不猜、确认门提醒）与 create_reminder（ISO 未来时间、相对表达按今天推算）
- `backend/tests/modules/warehouse/test_live_office.py` — 10 测试全 PASSED（含 live）

**确认门时序（文字版）**

```
用户「把呆料清单发给 group:oc_x」
 → gateway.handle_im_message（去重/会话定位/占位卡片）
 → Runner LLM 循环 → office.send_card 工具
    → request_card_send：parse_target → confirm.request_confirm
      （drafts: scene=send_card, pending_confirm, TTL 10min, payload 全量载荷）
    → render_confirm_preview_card → 发预览卡片给发起人（此时目标地址零发送）
    → 工具返回 pending_confirm → LLM 回复提醒用户去确认
用户点 [✅ 确认发送]（card.action.trigger, value={scene:send_card, draft_id, action:confirm}）
 → gateway.handle_card_action_trigger（is_registered_scene ✓ → 路由进确认门）
 → confirm.handle_action 校验链：pending ✓ → 仅发起人 ✓ → TTL 内 ✓
 → 注册回调 _execute_send_card：render_outgoing_card → 真实发送到目标
 → drafts=confirmed + audit ok
分支：cancel→cancelled｜非发起人→denied 保持 pending｜过期→expired｜回调异常→保持 pending 可重试 + audit error
提醒：create_reminder → 未来时间校验 → drafts(scene=reminder, scheduled, expires_at=触发) → asyncio 延时任务
  → 到点 render_reminder_card 投递 → fired（失败 failed；cancel→cancelled）
```

**测试逐条摘要（`test_live_office.py`，10 passed）**

1. test_office_tools_registered — 工具并入 query 注册表（schema+func 双断言）+ send_card 回调已注册
2. test_send_card_confirm_gate_full_flow — 工具调用→预览卡片（标题/目标/内容断言、目标零发送）→发起人点确认→dry-run 捕获发往目标私聊的真实卡片→drafts=confirmed
3. test_send_card_non_requester_rejected — 非发起人点击：仅发起人提示、零新增发送、草稿保持 pending_confirm
4. test_send_card_cancel_no_send — 取消：cancelled 不发送；取消后再点确认拒绝（「已被处理」）
5. test_send_card_expired_no_send — 默认 TTL>9min 断言 + 回拨 expires_at 注入过期：expired 拒绝不发送
6. test_send_card_invalid_target_error — 「陈玉英」/「user:」/「user:陈玉英」/「group:张三的群」均 error 并提示向用户索取
7. test_create_reminder_fires_and_captured — 0.6s 短间隔注入→到点捕获提醒卡片（会话投递+内容断言）→drafts=fired
8. test_create_reminder_past_or_unparseable_time_error — 过去时间/无法解析/空 content 均 error 不落库
9. test_cancel_reminder — 取消撤销延时任务→零发送→cancelled；重复取消 False
10. test_live_send_card_via_gateway — live 主接缝（真 LLM）：gateway 全链路「把呆料清单发给 group:oc_livetest_target_group 测试群」→ LLM 调 send_card → 预览卡片出现（目标群零发送）→ 模拟发起人点确认 → 捕获到目标群的真实卡片（chat_id 通道）→ drafts=confirmed

全量回归：`tests/modules/warehouse/` **133 passed**（基线 123 + 本票 10）。`uv run ruff check`（agent 模块+新测试）0 告警；`uv run mypy app/modules/warehouse/agent/` strict Success（13 文件）。platform/safety 零改动。

**实现决策与偏差处理**

- **调度方案偏差（按主会话任务书执行）**：ticket 原文写 scheduler register_generator 动态任务，主会话任务书明确改为「asyncio 延时任务表（模块级 dict + create_task）+ drafts 落库记录」轻量方案——进程重启后未触发提醒不恢复（完整方案 V1.1），S1 进程内 + 落库审计。
- **drafts 状态扩展**：reminder 场景用 scheduled→fired/failed/cancelled；models 列注释保持不动（避免迁移噪音），状态语义记录在 office.py 模块 docstring。
- **gateway 必要的最小改动**：ticket 说「保持 gateway 零改动或最小改动」——scene=send_card 要进确认门必须放宽路由条件，采用「CONFIRM_SCENE 或已注册回调」双条件，对既有 confirm_action 行为零影响（test_live_gateway 8 测试回归通过）。
- **target ID 形态校验加强**：在 user:/group: 前缀之外增加 ou_/oc_ 前缀校验，「user:陈玉英」这类把人名当 ID 的参数直接 error 引导 LLM 向用户索取，落实「不猜」要求。
- **预览卡片目标行绕过 _clean**：cards._clean 会把 ID 中下划线当 markdown 字符洗掉（ou_target_person→ou target person），HITL 预览要求目标精确展示，目标行只做换行折叠不做 markdown 清洗（代码有注释）；其他渲染器行为未动。
- **cancel_reminder 未注册为 LLM 工具**：ticket 只要求 2 个工具，取消作为服务函数实现并测试（S1 用户口头取消的需求可后补工具壳）。
- **存量注意（未动）**：pytest `-k "not live"` 会按文件名匹配误伤整个 test_live_* 模块，选择子需避开「live」字样（如 `-k "not via_gateway"`）。
