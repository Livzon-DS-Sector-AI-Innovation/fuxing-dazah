# Spec — 隐患 AI 识别 P2-3：成本优化（附件缓存 + 上下文压缩，Token -30% 冲刺）+ P2-2 灰度冒烟 + build 欠账收口

> feature: hazard-cost-p23 ｜ 日期：2026-11-10 ｜ 分支：feature/warehouse-module（唯一工作分支）
> 前置：P2-2 已 3-commit 落库未 push（738ae589/2ef4f8d8/144d81d5）；P2-1 3-commit 未 push。P0-0 效率止血（bfb3f54d A6）已落：只下缺陷图 / tenant token 缓存 / AI 客户端单例 / to_thread。
> 设计依据：docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md §3.1（成本构成）§3.3-E（E17/E19/E22）§4.7（P2 验收 Token -30%）

## Problem Statement

① 隐患 AI 识别主链单条 input ≈ 8.75k tokens（30 天 4.34M / 496 次实测），其中知识库注入段占 ~47%、fewshot 占静态段 ~48%，存在大额可压缩浪费；同一记录的缺陷附件被 ①失败重试（退避最多 5 次）、②初审、例外复核员三方各自重复下载（store_bytes 确定性键已存在但从未回读短路）。§4.7 P2 阶段四项验收中 Token -30% 是本期唯一未达项。同时 P2-2 的 Thread 留痕基建（SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED 默认关）从未真机验证，P1-2 起累计 5 期 next build 验证欠账。

## Solution

三个交付目标：

1. **G2 附件缓存**：`download_photos` 下载前按确定性存储键探测 attachment_store（本地磁盘 / MinIO），命中直接返回存量路径跳过网络下载——①②例外复核员三方共享、重试零重复下载。开关默认开、可热关。
2. **G2 上下文压缩**：①主链注入前的知识上下文按 per-chunk 句子边界截断（保「第X条」行优先，chunks 集合与 CitationEvidence 引用证据完全不变）+ fewshot 5 例压至 3 例（保例 1/4/5，例内文本零改动；golden fixtures 有意重生成）。目标单条 token 可测量下降 ≥28%（冲刺 -30%）。
3. **G3+G4 收口**：P2-2 四链灰度冒烟（限时开 trace 开关、每链 ≤5 条、真 Bitable 写回前确认、curl 证据贴档、验收后另拍板常开）；next build 补验 + 提交（不 push）。

判定语义与写入口径零变化：检索截断不动 chunks/引用证据/质量闸门输入；fewshot 删例是用户拍板的唯一有意变更，以 166 条评测集 + replay 离线回归 + 真机冒烟三重验证防回归。

## User Stories

1. As a 安全模块开发者, I want 同一附件跨轮次/跨链路（①②复核员）不重复下载, so that 消除 §3.1 中 19% 耗时占比里的重复下载浪费与飞书 API 配额消耗。
2. As a 安全模块开发者, I want 附件缓存可一键热关, so that 存量存储若出现同键脏数据时能立即回退到全量下载行为。
3. As a 安全模块开发者, I want ①主链注入的知识上下文按 chunk 句子边界截断且条号行优先保留, so that 在不改变检索命中集合与引用证据的前提下压缩 ~47% 的知识段 token。
4. As a 安全模块开发者, I want 截断上限可配且 0=关闭, so that 压缩率可调、可热回滚到零截断行为。
5. As a 安全模块开发者, I want fewshot 从 5 例压至 3 例（保 1/4/5）, so that 静态段 token 再降 ~40% fewshot 占比，达成单条 -28% 以上。
6. As a 安全模块开发者, I want golden 快照有意重生成且其余 9 条静态快照字节不变, so that 变更面被精确限定在 fewshot 范畴、可审计。
7. As a 安全模块开发者, I want 检索评测集 166 条与 replay 离线回归全绿, so that 证明压缩未伤害检索质量与输出规则合规。
8. As a 安全模块开发者, I want 离线 estimate_tokens 前后对比与真机 ≤5 条 ai_call_audits 实测双层证据, so that Token -30% 达标有可重复的量化口径。
9. As a 安全运维者, I want P2-2 trace 开关真机四链验证并留 curl 证据, so that ①②③⑤与辨识流的 thread_key 聚合历史可核对后再决定常开。
10. As a 安全模块开发者, I want next build 补齐 P1-2 以来累计欠账, so that 前端 tsc/构建回归面清零。
11. As a 仓库协作者, I want 只动自己 hunk、registry 走 commit-tree 流水线, so that 不误伤工作树里 invitation/②-b/fire_inspection/仓储前端等他人 WIP。

## Implementation Decisions

- **附件缓存（exists 短路）**：`bitable_repo.download_photos` 内，构造与既有落盘一致的确定性键（`direct_{record_id}_{file_token[:12]}_{safe_name}`），下载策略 1/2/3 之前先 `attachment_store.exists(key)`，命中直接返回存量路径；未命中走原三级回退并照常 store_bytes。失效口径：飞书 file_token 内容不可变、重传即新 token，天然无需 TTL；人工删附件只影响 Bitable 展示不影响缓存正确性。开关 `SAFETY_HAZARD_ATTACHMENT_CACHE_ENABLED`（bool，默认 True，热生效）。②/例外复核员的 download_photos 调用点自动获益（同一函数）。
- **检索截断器**：新纯函数模块 `hazard_direct/context_compression.py`——输入 `KnowledgeContext`（非解析 markdown 字符串），按 build_markdown 同款格式重建注入文本，每 chunk 正文截断至 `max_chunk_chars`（**默认 200**，0=关闭返回原 markdown；初值 350 经离线四象限度量后用户拍板调至 200：350→-22.6% 未达标 / 250→-28.0% / 200→-30.6% 冲刺达成，30 样本条号头行 0 丢失、引用句永不丢）；截断点必须在句末标点（。；；\n）之后，含「第X条/第X.X条」或书名号引用的行永不丢弃（条号行优先保留策略）；chunk 元数据行（`[i] 《doc》 article`）完整保留；graph_path 原样保留。接线点：`ai_analysis._identify_one` 在 `knowledge_text = context.markdown` 之后、传给 plugin 之前；chunks 与 CitationEvidence 对象不动。开关 `SAFETY_HAZARD_KNOWLEDGE_CONTEXT_MAX_CHARS`（int，默认 200，0=off，热生效）。仅接①主链（②/复核员共享压缩器但本期不接）。
- **fewshot 压缩**：`prompt_skills/fewshot.md` 删例 2（unsafe_action 安全带）与例 3（environmental 消防通道），保留例 1（unsafe_condition）/例 4（management_defect + substantive 正例）/例 5（procedural 负例，v2 核心），例内文本零改动；`prompts.py` 的 FEWSHOT_EXAMPLES 兜底常量同步（md 缺失回退行为一致）。golden fixtures 有意重生成：`fewshot_examples.json` + 含 fewshot 的组装快照（text_full / text_knowledge / vision 相关）；`fewshot_marker.txt`、system-role、work-rules、defect-substance-rules、output-format、critical-constraints、text_nofewshot、text-template、vision-template 等 9 条字节不变；manifest prompt_version bump。无运行时开关（md 本身即软配置 + git revert 回滚）。
- **registry 新键**：上述两键走 P2-2 先例的 commit-tree 流水线（HEAD blob + 自己 hunk，zsh 无关联数组）。无 DB 迁移、无新依赖。
- **度量口径（双层）**：①确定性层——离线脚本对同一批样本描述调 `build_full_prompt`（压缩开/关 × fewshot 新/旧）用 `business_agent.core.compaction.estimate_tokens`（tiktoken）计量并输出前后对比表；②真机层——冒烟限量 ≤5 条真实轮询，`ai_call_audits`（scenario=hazard_identification）input_tokens 均值对比，基线=近 30 天均值 8.75k。达标线：单条均值降幅 ≥28% 视为达标（≥30% 为冲刺完成），<28% 回到调参迭代。
- **G3 冒烟**：app_config 热开 `SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED` → ①②⑤轮询 + 危险源辨识流各真实触发一轮（每链 ≤5 条；真 Bitable 写回执行前向用户确认）→ `GET /platform/superagent/triggers?thread_key=` 与 `/threads/{thread_key}/history` 逐记录验证 ①②③⑤ 与辨识 Task 全历史 → curl 证据贴档 → 关开关；常开与否验收后另拍板。
- **G4 build**：与用户约 dev:3000 停窗口跑 `next build`（P1-2/P1-3/P1-4/P2-1/P2-2 累计欠账）；GOVERNANCE 列数与 GB 30871 补录不动（等用户通知）。
- **提交**：3 commit——C1 附件缓存 / C2 上下文压缩（截断器 + fewshot + golden 重生成 + 度量）/ C3 冒烟证据 + build 收口 + 文档；均不 push。

## Testing Decisions

- 只测外部行为：S1 wiring 主接缝（`_identify_one`，fake 全家桶不连真实网络/DB/Redis/Bitable/AI——先例 `test_hazard_efficiency_wiring.py`）断言：截断后文本被注入 plugin 且 evidence 对象未变、截断关闭时原样透传、附件 exists 命中时 fake client 零下载调用、开关关闭时回退全量下载。S2 纯函数直测（先例：citations/citation_evidence 纯文本判定测试）：句子边界完整性、条号行保留、短 chunk 不变、0=off、多 chunk 重建格式与 build_markdown 一致。S3 golden 字节锁（先例 `test_hazard_prompt_skills.py`）：重生成后锁死新快照、9 条不变快照逐字节校验。
- 全部 fake；真实链路验证仅 G3 冒烟（先问且限量）。基线对比按「失败清单与预存基线 diff 为空」口径（test_script4_optimize 2 个 caplog 用例预存隔离缺陷、policy_db 8 红同族污染为已知基线）。
- 回归双保险：`hazard_retrieval_eval.py` 166 条评测集（检索质量不受截断影响的机械验证——截断不动检索，但跑一遍固化口径）+ `hazard_ai_quality_replay.py` 离线重放（fewshot 新快照下 140 条历史成功样本规则 error=0 复验）。

## Out of Scope

- 两阶段链路（E23）、模型分级（E20）、批量写回合并（E21）、事件驱动替代轮询（E24）。
- work-rules / system-role / output-format 等其余静态段精简。
- ②初审与例外复核员接入检索压缩（共享压缩器已就位，下期评估）。
- 图片编码/降采样的内存 LRU 二级缓存（exists 短路已消除网络下载，URI 转换留 to_thread）。
- GOVERNANCE 列数 50→44、GB 30871 补录（等用户通知）。
- push 远程（红色操作，听用户指示）。
- trace 开关常开（验收后另拍板）。

## Further Notes

- 工作树他人 WIP（invitation/②-b autopass/fire_inspection/仓储前端/rag_health）：动前 `git diff` 复核，只加自己 hunk；registry.py 走 commit-tree 流水线。
- golden 重生成是有意变更非漂移：manifest 记录 prompt_version bump 与变更理由，回滚 = revert fixtures + md。
- 冒烟真 Bitable 写回为黄色操作：每链执行前截图/清单向用户确认。
