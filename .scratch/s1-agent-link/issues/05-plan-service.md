# 05 — 任务计划器（第二批·Harness）

**What to build:** `warehouse/agent/tools/plan.py` + PlanService——plan_task(title, steps)（≥3 步任务由系统提示词强制先规划，plans 表持久化+进度卡片首帧）、update_plan(plan_no, step_no, status, note?)（步骤状态迁移+进度卡片 patch：✅/⏳/⬜）。Runner 系统提示词补计划规则。plans 表 S0 已建。

**Blocked by:** 04。

**Status:** done

- [x] 组件测试：create_plan → plans 表记录 + 步骤初始状态；update 状态迁移合法值校验
- [x] 主接缝 live：「帮我盘点呆料并按班组长分组，再汇总」→ Agent 先出计划卡片再逐步执行（进度卡片可见）
- [x] 中断恢复：会话中再次提到该任务，Agent 从 plans 表恢复上下文

## Comments

- 交付文件：
  - `backend/app/modules/warehouse/agent/tools/plan.py`（新）：PlanService 业务函数（create_plan / update_step / get_plan_detail）+ 3 个工具壳 + OpenAI tools schema；`_db_session` 自开事务注入口（与 runner/gateway 同模式）。
  - `backend/app/modules/warehouse/agent/repository.py`：plans 表读写（insert_plan / get_plan_by_no / get_active_plans / get_latest_plan_no_on_prefix）。
  - `backend/app/modules/warehouse/agent/cards.py`：`render_progress_card`（⬜⏳✅⏭❌ 图标 + note + 进度行，plan.status=done 转绿卡）。
  - `backend/app/modules/warehouse/agent/tools/query.py`：注册表并入 plan 工具（TOOL_FUNCS/TOOLS 合并）；`execute_tool` 增加可选 `ctx` 参数。
  - `backend/app/modules/warehouse/agent/prompts.py`：工具规则段补 plan_task/update_plan/get_plan 三条。
  - `backend/app/modules/warehouse/agent/runner.py`：`_run_tool` 改传 session 对象并构造 ctx。
- 工具上下文传递方式：`execute_tool(name, arguments, ctx=...)` 可选 ctx（Runner 构造 `{"session_id", "chat_id", "open_id"}`，取自 session 对象列属性）；注册表中**声明 `_ctx` 形参的工具自动接收**（inspect.signature 判定），4 个查询工具签名零改动。plan 工具内经 `notification.send_card(ctx.chat_id)` 发进度卡片（群/私聊统一按 chat_id 发，会话定位时即消息真实 chat_id）。
- 偏差 1：票面说 2 个工具，实际交付 3 个——`get_plan`（缺省取最近 active 计划，本会话优先、其次按发起人）是「中断恢复」验收的必要支撑（LLM 靠它从 plans 表拉回剩余步骤），已写进系统提示词与 schema。
- 偏差 2：进度卡片实现方式按任务描述选了「工具侧每次重发新卡」（S1 不做卡片 patch）；plan_task 发首帧、update_plan 每次重发，gateway 结果卡片路径不重复渲染进度卡。
- 进度卡片发送失败只记日志不阻断计划数据更新；全部步骤终态（done/skipped/failed）→ plan.status=done。
- 发现（ticket 范围外，供后续参考）：WAREHOUSE_AGENT_MAX_TURNS=6 对多步规划任务偏紧（live 实测 plan_task+5 次 update_plan+2 次查询已耗尽 6 轮，进度卡片与 plans 数据正常产出，但终局文本易落兜底话术）；建议后续 ticket 评估调大或对 plan 类任务放宽。
- 测试：`tests/modules/warehouse/test_live_planner.py` 13 个（组件 11 + live 2）全过；warehouse 全量 111 passed（基线 98 + 新增 13）；mypy strict 无告警；ruff 仅 models.py 预先存在的 I001（本票未触碰该文件）。plan_no 同日序号断言用相对递增（dev 库当天可能有其他已提交计划，基线不写死）。
