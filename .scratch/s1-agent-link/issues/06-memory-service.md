# 06 — 长期记忆（第二批·Harness）

**What to build:** `warehouse/agent/tools/memory.py` + MemoryService——recall_memory(keyword?) / save_memory(type, content) 工具（memories 表）；会话开始注入（用户偏好 top3 + 全局惯例 top5，hit_count 累加）；用户显式纠正时 Agent 主动保存并告知。记忆只影响表达与默认参数（红线：不参与数据正确性）。

**Blocked by:** 04。

**Status:** done（2026-09-04）

- [x] 组件测试：save → recall 命中；user/global 作用域隔离；hit_count 递增
- [x] 主接缝 live：「记住我只要看危化品的」→ 后续查询回复只含危化品（或明确说明已记住并生效）
- [x] 注入测试：第二次会话开始时历史偏好出现在系统上下文

## Comments

- 实现（与票05 plan.py 同模式）：`agent/tools/memory.py` MemoryService 三函数 `save / recall / inject_context`（`_db_session` 注入口、异常兜底返回 `{"error"}`、绝不中断 Runner）+ 2 工具壳 `save_memory / recall_memory`（`_ctx` 拿 open_id）；注册表经 `tools/query.py` 合并（`MEMORY_TOOL_FUNCS` / `MEMORY_TOOLS_SCHEMA`）。repository 层新增 `insert_memory / list_recallable_memories / list_user_preferences / list_global_knowledge / bump_memory_hit_counts`（`agent/repository.py`）。
- scope 推导：工具壳按 memory_type 定 scope（preference→user；convention/alias→global，owner 置空）；`save()` 独立校验（scope/type/空 content/user 缺 owner 均 `{"error"}`）。content ≤200 字符，超长截断 + message 提示 + `truncated` 标记。
- 注入：`inject_context` = 用户偏好 top3 + 全局条目 top5（scope=global 且 type∈convention/alias，updated_at 倒序；**偏差解释**：全局桶并入 alias——术语别名同样是全局知识，排除会让第三种类型在注入侧失效；上限仍为 top5）。无记忆/注入失败返回空串（红线：不阻断会话）。
- prompts：`build_system_prompt` 改 async，签名加 `owner_open_id`（runner 传 `session.user_open_id`，1 行适配）；新增「## 四、长期记忆」段=注入片段（空则省略）+ 常驻规则段（显式纠正必须 save_memory 并确认；数字永远来自工具结果）；技能钩子顺延「## 五、可用技能」（票08 未实现，无破坏）。
- **已知行为（非偏差）**：`updated_at` 带 onupdate，hit_count 递增（UPDATE）会刷新 updated_at——被命中记忆在后续注入按「最近命中时间」上浮（recency+frequency 混合）；单次注入取数先于 bump，结果集稳定。
- recall 的 keyword 对 content 做 ILIKE（%/_ 不转义，业务关键词场景足够）；recall 上限 20 条。
- live 偏差说明：接缝2 采用「预置偏好 → monkeypatch 捕获 build_system_prompt 返回断言含偏好」验证注入生效（与主会话给的方案一致）；LLM 回复内容不断言。
- 测试：`tests/modules/warehouse/test_live_memory.py` 12 条全 PASSED（组件 10 + live 2）；全量回归见下。
