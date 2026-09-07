# 02 — 成品出库对话登记 + 快递推送

**What to build:** ① `create_finished_outbound_draft(fields)` 工具（对话式，同 GMP 模式：产品名称/产品批号/出库量/单位/销售客户/用途/快递号/温度计；用途单选适配）→ draft_flow(scene=finished_outbound) → 确认卡片 → submit_outbound（可写字段映射+读回核对）。② 快递推送：submit 成功且快递号非空 → 回执附「要推送给谁？」提示；用户答目标（group:/user: 前缀）→ LLM 调 send_card（S1 确认门）发发货通知卡片（品名/数量/快递号/客户）。③ update_draft 字段映射扩展成品字段。④ prompts 补成品出库规则。

**Blocked by:** None（与 01 并行，但串行执行）。

**Status:** done

- [x] live 主接缝：「登记成品出库：硫酸黏菌素 批号 X2609 出库 225000 十亿，客户 can，快递 SF123456」→ 草稿 → 确认 → 写台账（finally 删）→ 回执含推送提示
- [x] 对话推送：「推送给 group:oc_test」→ send_card 确认门 → 预览 → 确认 → dry-run 捕获通知卡片
- [x] 单测：submit_outbound 字段映射/用途单选适配/单位换算字段直传
- [x] 快递号为空时回执无推送提示

## Comments

**实现摘要（2026-09-07）**
- `tools/finished.py`：`create_finished_outbound_draft`（照 GMP 模式）——必收 5 字段（产品名称/产品批号/出库量/单位/销售客户，SCENE_CONFIG.required_fields）；产品名称/单位硬校验选项集（error_code=product_not_found/unit_invalid）；用途缺省「销售」（选项集收录才生效）、用途/温度计软校验（未命中 warning 不阻断）；快递号/备注透传。
- `pipeline/submit.py`：`build_finished_fields` + `submit_outbound`（audit tool_name=`submit_outbound`）——出库日期=当天毫秒；只读字段（品规/各品种库存/质量状态/库存数量/出库人=公式/lookup/created_user）不进映射；读回核对 4 字段（产品批号/出库量/单位/销售客户）；快递号非空时回执 note 附加「要推送给谁？回复 group:群ID 或 user:open_id」。
- 快递推送链：无新工具，send_card（S1 确认门）复用；prompts 补快递推送规则（title「📦 发货通知」，content=品名/数量/单位/客户/快递号）。
- SCENE_CONFIG 注册 finished_outbound 确认回调（draft_flow._finished_submit_callback 薄包装）；确认卡片/回执卡片新增 finished 分支（「📦 成品出库登记」/「✅ 成品出库已登记」）；update_draft 别名扩展 9 个成品字段 + scene 文案。
- **偏差处理**：成品台账「快递号」字段实测为**附件类型（type 17，写入需 file_token）**，文本快递单号无法写入——按票01「SUBMIT_GMP_BATCH_ENABLED」同款降级开关模式处理（`SUBMIT_FINISHED_EXPRESS_ENABLED=False`，submit 跳过写入 + degraded 标注「快递号需在 Base 人工补填（附件字段…）」）；快递号仍保留在草稿/确认卡片/回执/推送卡片中（推送链正常使用）。Base 若改文本类型置 True 即恢复。
- 测试：`test_live_finished.py` 16 单测 + 1 live 全链（登记→submit→推送一次通过）；live 实测 fields=[产品名称,产品批号,出库日期,出库量,单位,用途,销售客户] degraded=[快递号]，record_id recvuwwyQQoJJg finally 精确删除，只读复核残留 0。
- 关联改动：`test_live_gmp.py` 场景注册断言更新（finished_outbound 票02 落地后已注册）。
