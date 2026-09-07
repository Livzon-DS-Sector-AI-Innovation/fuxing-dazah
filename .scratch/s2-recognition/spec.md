# S2 — 识别入库旗舰场景（Spec）

**日期**: 2026-09-03
**状态**: ready-for-agent
**上游**: 设计文档 V1.0-2（双模编排：Pipeline 确定性状态机）/ V1.0-3 场景 A / V1.0-5 写契约 / V1.0-8；S1 已交付 gateway/Runner/ConfirmService/卡片渲染

## Problem Statement

仓管员目前手工填一张入库单（物料系统入库总账 62 字段）需 3-5 分钟，且常在手机上操作不便。S2 交付旗舰场景：**手机拍送货单发给机器人 → AI 识别结构化字段 → 主数据对齐 → 确认卡片 → 自动写入 Base（含原图附件）→ 读回核对**，目标单据录入 <1 分钟。这是《仓库AI应用实施计划》第 1 项「拍照自动识别录入物料入库信息」的落地。

## Solution

识别 Pipeline（确定性状态机 + LLM 只参与识别与对齐两阶段）：gateway 图片消息 → im resource 下载 → vision 识别（严格 JSON，核心 8 字段必提 + 选提 5 字段）→ 主数据对齐（602 条物料字典模糊匹配 + 置信度）→ Draft（created→aligned→pending_confirm）→ 确认卡片（低置信度高亮，[确认入库][修改][取消]）→ 用户确认 → submit（写契约校验 + 原图附件上传 + 写入测试版入库总账 + 读回核对）→ 回执卡片。

## User Stories

1. 作为仓管员，我拍送货单发机器人，收到字段已填好的确认卡片（低置信度字段高亮），点确认即完成入库，全程 <1 分钟。
2. 作为仓管员，我对识别结果说「数量改成 200」，卡片更新为新值后我再确认。
3. 作为仓管员，识别没把握的字段我看到 ⚠ 高亮提示，知道哪些要重点核对。
4. 作为仓管员，确认后 Base 记录带送货单原图（附件列），与手工录入记录一致可溯源。
5. 作为质量负责人，写入的记录关键字段（数量/批号/单位）经读回核对，不一致有告警留痕。
6. 作为开发者，识别质量有 60 条真值测试集量化（字段级 ≥90% 门禁），prompt/模型变更可回归。

## Implementation Decisions（2026-09-03 质询定稿）

1. **测试集自动抽样 60 条**：`scripts/build_recognition_dataset.py` 从测试版入库总账筛「外包装/厂家报告单/送货单照片」非空记录，按物料大类分层抽样，下载附件到 `.scratch/s2-recognition/dataset/`（图片不入库，backend/.gitignore 加 .dataset 条目），真值导出 truth.jsonl。后续业务方补真实送货单增强。
2. **识别字段分级**：必提 8（物料名称/厂家批号/数量/单位/供应商/生产商/车牌/合同号——低置信度也强制给值）+ 选提 5（包装规格/生产日期/到货时间段/备注/联系人——识别不到留空）。识别 prompt 输出严格 JSON（含每字段 confidence 0-1）。
3. **原图写入附件列**：新建 `warehouse/feishu/media.py`（POST /open-apis/drive/v1/medias/upload_all，parent_type=bitable_image，独立凭证）拿 file_token，submit 时写入「外包装/厂家报告单/送货单照片」。
4. **Draft 状态机**（复用 S0 drafts 表 + S1 ConfirmService 扩展）：created（识别落库）→ aligned（对齐落库）→ pending_confirm（确认卡片已发）→ confirmed → submitted（读回核对完成）；expired（TTL 10min）/cancelled/failed。幂等：draft_no 唯一 + 状态前置校验；每次迁移写 audit。
5. **确认与修改**：确认卡片 [确认入库] 走 ConfirmService（scene=receipt，回调=submit）；[修改] 无按钮（引导文本对话）；对话修改走新工具 `update_draft(draft_no?, fields)`（LLM 从 pending 摘要获知 draft_no，S1 修5 的 _pending_summary 需扩展 aligned 状态）；修改后重发确认卡片。
6. **写入与读回**：submit 前validate_write_fields（S0 写契约）；**物料名称字段降级**——测试版该字段重复选项导致按名写入必失败（业务方暂缓治理），submit 跳过该字段，卡片与 audit 标注「物料名称需在 Base 人工补选」；写入后 get_record 读回核对关键字段（数量/批号/单位/供应商），不一致 → 回执卡片 ⚠ + audit error_code=mismatch。
7. **对齐器**：主数据源 = material_master 表实时拉取（记录级缓存 TTL 300s，602 条）；匹配优先级：ERP编码精确 > 名称归一化精确 > 前缀 > 模糊（difflib ratio ≥0.6）；输出 aligned 字段（物料名称标准化值/代码/大类/细分类/单位建议）+ confidence；未命中 → 卡片提示人工选择（不阻塞其他字段）。
8. **gateway 集成**：图片消息 → 占位卡片「🖼 识别中…」→ Pipeline 异步（create_task）→ 完成发确认卡片；识别失败降级话术 + audit。原「图片识别即将上线」引导移除。

## Testing Decisions

- **接缝**（沿用 S1 已确认哲学）：主接缝 gateway（模拟 image 事件 payload → 全链路 dry-run：下载 mock→识别真 LLM→对齐真主数据→卡片 dry-run 捕获→确认→submit live 写删读回）；组件直测：recognizer（真实图片 live + JSON 解析单测）、aligner（匹配算法单测 + 真主数据 live）、draft 状态机（迁移/幂等/过期单测）、submit（live 写→读回→删除清理）。
- **回归门禁**：测试集脚本跑 60 条 → 字段级命中率报告（必提字段 ≥90%、主数据对齐 ≥95% 为验收线）；prompt/模型变更重跑。评估不入 pytest（独立脚本），结果落 `.scratch/s2-recognition/eval_report.md`。
- 运行：`DATABASE_URL=...whdev uv run pytest tests/modules/warehouse/ -v`（全量回归）。

## Out of Scope

- GMP/成品出库/快递单识别（S3）；多图连续识别；语音输入；修改批号之外的草稿版本管理；Base 端人工补填物料名称的提醒推送（卡片提示+audit 已覆盖）。

## Further Notes

**实现偏差补记（2026-09-03 审查确认）**：
- 决策 7 的「ERP编码精确」匹配层未实现——识别字段清单（核心 8+选提 5）不含 ERP 编码，该层不可触发；匹配实际为 名称归一化 exact > prefix > fuzzy 三层（truth 集命中率 100%）；
- eval 门禁未达（34.5%/55.2%）：主因测试集图片为 Base 现存外包装/报告单照片（图上无合同号/车牌/实收数量），与人工录入真值（参照纸质送货单）错配——**需业务方提供真实送货单照片 10-20 张重建测试集后再回归**，识别偏差（供应商/生产商混淆、数量口径）与模型档位分析见 eval_report.md；

- vision 调用：`WarehouseLLMClient.chat_with_tools(messages=视觉消息, tools=None)`——messages 纯透传已验证（S0 五重验证⑤），无需新方法；识别 prompt 独立于 Runner 系统提示词（温度/token 独立配置）。
- 图片下载：GET /open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=image（im:resource 已由业务方确认开通）。
- 物料名称降级的前提是测试版该字段重复选项未治理——治理后移除降级逻辑（代码留开关注释）。
