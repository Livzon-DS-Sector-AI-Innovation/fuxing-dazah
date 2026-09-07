# 03 — Draft 状态机 + 确认卡片 + 对话修改

**What to build:** ① `warehouse/agent/pipeline/draft_flow.py`：状态机封装（create_draft 识别落库 created / mark_aligned / send_confirm_card → pending_confirm / expire/cancel；每次迁移 audit；幂等=状态前置校验）。② 确认卡片渲染（cards.py 加 render_receipt_confirm_card）：必提/选提分区 + 低置信度 ⚠ 高亮 + 物料名称未命中提示 + [确认入库][取消]按钮（value={scene:"receipt", action, draft_id}）。③ ConfirmService 注册 scene=receipt 回调（指向票04 submit——本票先注册到桩）。④ 新工具 `update_draft(draft_no: str | None, fields: dict)`（注册进工具表；LLM 从 _pending_summary 获知 draft_no——**repository.list_actionable_drafts 扩展 aligned 状态**；修改后重发确认卡片）。

**Blocked by:** 02。

**Status:** done

- [x] 单测：状态机全迁移路径+非法迁移拒绝+幂等（同 draft 二次 confirm 拒）+TTL 过期
- [x] 确认卡片渲染：必提/选提分区+⚠高亮+按钮 value 断言
- [x] live 主接缝前段：图片事件 → 识别 → 对齐 → 确认卡片（dry-run 捕获）→ drafts 全程落库
- [x] live 对话修改：「数量改成 200」→ aligned 数量更新 + 新确认卡片

## Comments

2026-09-07 实现完成（S2 ticket 03）。

**交付物**
- `backend/app/modules/warehouse/agent/pipeline/draft_flow.py`（新）——状态机封装：`create_receipt_draft(db, *, recognized, image_file_token, open_id, chat_id)`（recognized model_dump JSONB + source_image + scene=receipt + status=created + expires_at=now+10min；draft_no=WR+YYYYMMDD+3位序号仿 WP，唯一索引冲突重试 3 次）、`mark_aligned(db, draft, aligned)`（created→aligned；aligned JSONB=对齐字段+match_confidence+match_detail，recognized 不改写）、`send_confirm_card(db, draft, *, chat_id, open_id)`（aligned→pending_confirm 或 pending_confirm 重发；chat_id 优先、缺省私聊发 open_id；发送失败不回滚迁移、audit error_code=send_failed）、`cancel_draft`（活跃→cancelled）、`expire_stale(db, *, now)`（活跃+expires_at 已过→expired，返回数量）。每次迁移 insert_agent_audit（tool_name="draft_flow"，args 含 action/from/to、draft_id 关联）；幂等=`_TRANSITIONS` 状态前置校验，非法迁移抛 `DraftFlowError`（终态 confirmed/submitted/cancelled/expired/failed 不可再迁移）。**票③回调桩**：`confirm.register_confirm_callback("receipt", _receipt_submit_stub)` 模块导入即注册（office.py 同款模式），桩返回「入库提交逻辑将在票04 接入」，draft 由 handle_action 置 confirmed；`pipeline/__init__.py` re-export，gateway 导入 pipeline 保证卡片回调 scene=receipt 分发可用。
- `backend/app/modules/warehouse/agent/cards.py`——`render_receipt_confirm_card(draft)`：标题「📋 入库确认」（orange）；必提 8 / 选提 5 分区（值优先取 aligned 覆盖=对话修改后最新值，否则 recognized；低置信 <0.7 加 ⚠，必提缺失显示 — ⚠，选提缺失显示 — 不加 ⚠，人工改过的字段不再 ⚠）；match_confidence=none →「⚠ 物料名称未匹配主数据，请核对」，非 none →「**物料对齐**：标准名（代码 X｜大类 Y）」；对话修改引导行（spec 决策 5：[修改] 无按钮引导文本）；按钮 [✅ 确认入库] value={scene:"receipt", action:"confirm", draft_id} / [❌ 取消] action="cancel"；渲染防御 recognized/aligned 缺字段一律降级不抛错。
- `backend/app/modules/warehouse/agent/tools/draft_update.py`（新）——`update_draft(draft_no, fields, _ctx)`：draft_no 缺省时经 `list_actionable_drafts` 取该用户最近一张 scene=receipt 且 aligned/pending_confirm 的草稿；仅发起人可改；fields 业务字段名（数量/厂家批号…含别名）或 canonical 键均可映射，未知字段返回 error 列出可改 13 字段；数量自动数字化（"1,200"→1200）；新值写 aligned JSONB（working set，票04 submit 的写入来源；recognized 保留原始识别值供审计）→ `draft_flow.send_confirm_card` 重发确认卡片；工具内自开事务 `_db_session` 注入口、错误返回 `{"error"}` 不中断 Runner；注册进 query.TOOL_FUNCS/TOOLS（现 13 工具）。
- `backend/app/modules/warehouse/agent/repository.py`——`list_actionable_drafts` status 扩展 `["aligned","pending_confirm","scheduled"]`（S1 修5，顺带修复该函数既有 I001 import 排序偏差）；新增 `get_agent_draft_by_no` / `get_latest_draft_no_on_prefix`（draft_no 定位与序号生成）。
- `backend/app/modules/warehouse/agent/runner.py`——`_pending_summary` 扩展 aligned 分支（receipt 草稿提示含 draft_no，update_draft 靠它获知编号）；pending_confirm 的 receipt 场景单独文案。
- `backend/app/modules/warehouse/agent/prompts.py`——工具规则加 1 条 update_draft（何时调、draft_no 来源、fields 格式、修改后提醒用户到新卡片确认）。
- `backend/app/modules/warehouse/agent/gateway.py`——导入 pipeline（回调注册链，noqa F401 注释说明依赖）。
- `backend/tests/modules/warehouse/test_live_draft_flow.py`（新）——20 用例：单测 18（落库/序号递增/对齐迁移 payload/非法迁移 4 例/重发 resend 审计/confirm 桩+重复确认拒/cancel 双路径+重复拒/expire_stale 只过期该过期的/过期后确认拒/发送失败保持 pending+audit/卡片渲染 4 例含降级与人工覆盖/update_draft 组件 2 例/list_actionable_drafts 含 aligned 回归）+ live 2。

**语义要点（票04/05 相关）**
1. **确认卡片只在 pending_confirm 状态发出**（首发出自 send_confirm_card，唯一迁移入口）；aligned 状态不出卡片，handle_action 校验 status==pending_confirm 天然拒绝终态/过期重复点击——语义自洽。update_draft 修改后 aligned→pending_confirm 或 pending_confirm→pending_confirm（resend=true 审计）。
2. **aligned=working set、recognized=原始留痕**：对话修改写 aligned（键=canonical 字段名，如 aligned["quantity"]=200），卡片取值 aligned 覆盖优先；票04 submit 读 aligned + aligned["material_name"]（对齐标准名/人工改后的名）。
3. **chat_id 不落 drafts**（模型无此列）：卡片发送目标由调用方显式传（pipeline 传会话 chat_id；update_draft 经 _ctx.chat_id），缺失时兜底私聊发发起人 open_id。
4. 同事务内多条 audit/draft 的 created_at 恒等（PG now()=事务起始时间）——测试断言全部顺序无关；生产每次调用独立事务不受影响。
5. expire_stale 是全量扫（活跃+expires_at 过期），会连带清理库中其他历史过期活跃草稿（dev 库实测安全）；调度接入归 V1.1。

**验收结果**
- 单测 18 passed；live 2 passed：`test_live_pipeline_front_segment`（rec05roRO9.jpg → 真识别 material_name=硫酸铵 → 真主数据 match=exact → WR20260907-001 created→aligned→pending_confirm + 确认卡片 dry-run 捕获 + create/mark_aligned/send_confirm_card 三条 audit）；`test_live_conversation_update_draft`（真 Runner LLM 经 gateway，一次通过：pending 摘要获知 draft_no → update_draft(fields={'数量': 200}) → aligned.quantity=200 + 状态回 pending_confirm + 新确认卡片含「数量：200」+ update_draft audit ok）
- 全量回归 **190 passed + 1 skipped**（基线 170 + 本票 20，零破坏）
- ruff/mypy strict 全绿（本票文件零偏差；models.py 既有 I001 未触碰）
- platform/safety 零改动；无 DB schema/依赖/权限变更
