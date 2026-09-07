# 01 — GMP 对话式登记

**What to build:** ① `tools/gmp.py`：`create_gmp_draft(fields: dict)` 工具（_ctx；缺字段在工具返回中列 missing 让 LLM 追问；单据类型默认出库；单位/领用部门为自由收集）→ 复用 draft_flow.create_receipt_draft 变体（scene=gmp_outbound，recognized 存收集字段）→ mark_aligned（GMP 无对齐，直接 aligned 状态带字段）→ send_confirm_card。② submit_gmp（pipeline/submit.py 扩展）：可写字段 7 个（物料批号/日期=今天/单据类型/领用品种/领用部门/单位/领用数量/生产批号——lookup 与创建人拒写），validate+读回核对（批号/数量/单位）+ 回执卡片。③ 确认卡片按 scene 分支渲染（gmp_outbound 字段集）。④ update_draft 通用化（MUTABLE_STATUSES 场景放宽 + 字段别名映射扩展 gmp 字段）。⑤ prompts 补 GMP 登记规则。⑥ draft_flow 的 RECEIPT_SCENE 常量体系扩展为按 scene 的字段配置（保持向后兼容）。

**Blocked by:** None — can start immediately.

**Status:** done

- [x] live 主接缝：对话「三氯甲烷 10423-260601 出库 25kg，生产批号 MA-ET-2026-050A，领用部门提炼工程一部」→ 草稿 → 确认卡片 → 确认 → 写 GMP 出库总账（record_id 精记 finally 删）→ 读回一致 → 回执
  - 注：物料批号因测试版 Base 字段级编辑限制降级不写入（见 Comments #2），读回一致覆盖 数量/单位/生产批号/日期/单据类型/领用部门，批号标注人工补填。
- [x] 缺字段追问：只说「三氯甲烷 10423-260601 出库 25kg」→ LLM 追问生产批号/部门而非硬写
  - live 实测回复：「还需要补充**生产批号**才能完成登记。请问这笔出库的生产批号是多少？」
- [x] 单测：submit_gmp 字段映射/降级纯函数；update_draft gmp 场景（test_live_gmp.py 15 用例全过）
- [x] 单据类型默认出库；领用品种/部门为空可过（Base 非必填）

## Comments

1. **2026-09-07 实现**（S3 ticket 01）：
   - `pipeline/draft_flow.py`：`SCENE_CONFIG: dict[str, SceneConfig]`（name_cn/required_fields/writable_fields/submit 回调引用；receipt 零行为变化，finished_outbound 为票02 预留 submit=None 不注册）；`create_dialog_draft`（created→aligned 一步，recognized=aligned=收集字段）；gmp_outbound 确认回调注册。
   - `pipeline/submit.py`：`build_gmp_fields`/`submit_gmp`/`_gmp_table_fields`（运行时刷新选项集——静态快照批号仅 50 条而 Base 实测 1753 条，直接校验会误杀）；audit tool_name=submit_gmp。
   - `tools/gmp.py`：`create_gmp_draft`（必收四件套缺→missing；批号/单位不在选项集→error 不猜；单据类型默认出库；部门/品种选集未命中→warning 降级）；经 refresh_table_fields 用最新选项集校验。
   - `cards.py`：确认/回执卡片按 draft.scene 分支（GMP 标题「🧪 GMP 出库登记」/按钮「✅ 确认登记」/核对行「✅ 批号/数量/单位 与 Base 读回一致」）；receipt 渲染零变化（S2 卡片测试全过为准）。
   - `tools/draft_update.py`：可改草稿 scene 过滤放宽为 SCENE_CONFIG 三场景；字段别名补 物料批号/生产批号/单据类型/领用品种/领用部门（「批号」仍指入库厂家批号，提示词已说明）。
   - `prompts.py`：GMP 登记规则（批号逐字使用用户原话、禁止补写 (W) 等后缀——live 实测 LLM 曾把批号"纠正"为 10423-260601(W) 被不猜守卫正确拦截）+ 场景判定 + 字段字典收录 gmp_outbound。
   - `runner.py`：待处理摘要补 gmp_outbound 分支文案。
2. **⚠ Base 侧待治理（非代码问题）**：测试版 GMP Base「物料出库总账」对「物料批号」单选字段存在字段级编辑限制——任何合法选项值的 create/update 均被拒（1254062 SingleSelectFieldConvFail；同表 单位/单据类型/领用部门 写入正常；同 Base 入库总账 gmp_receipt 整表拒写报 "Table can not apply action"，疑似高级权限字段配置）。处理：`submit.SUBMIT_GMP_BATCH_ENABLED = False` 降级开关（S2 物料名称降级同款机制）——批号不写入，回执/audit/工具 warning 三处标注「需人工在 Base 补填」；**Base 管理员放开字段权限后置 True 即恢复自动写入，代码无其他改动**。
3. **偏差**：票面 live 文本「领用部门提炼一部」——真 Base 领用部门选项集为「提炼工程一部」等 12 项，live 测试改用「提炼工程一部」（写「提炼一部」会走选集未命中降级，属预期行为）。
4. 测试：`tests/modules/warehouse/test_live_gmp.py` 17 用例（15 单测 + 2 live）全过；全量回归 receipt 零破坏；ruff/mypy 无新增。
