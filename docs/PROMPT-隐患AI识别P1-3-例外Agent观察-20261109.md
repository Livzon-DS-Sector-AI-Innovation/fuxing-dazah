使用 feature-flow 技能，按完整流程开发「隐患 AI 识别 P1-3：例外复核 Agent（observe）+ skills 化 prompt」。
仓库：/Users/cheris/Agent work/fuxing-dazah（路径含空格）。
参数建议：--feature hazard-exception-reviewer。

【前置状态（必读）】
1. P1-2 已 3-commit 落库（b7adfc85 D2+D4 / 18e59e77 D5+D1 / 70c5a6e1 D3，未
   push）；工作树仍有他人未提交 WIP（review.py ②-b/②-c 链、bulletin/config、
   fire_inspection、business_agent/* 等）——动前 git diff 复核，只加自己
   hunk，冲突先报告；严禁 revert/stash/提交无关文件。
2. P1-2 遗留（顺带收口，不新开特性）：next build 补验（dev:3000 与 build 互杀
   .next，需 dev 停止窗口，P1-4 欠账一起补）；用户按 docs/GOVERNANCE-隐患登记
   表字段处置清单-20261106.md 执行人工操作（删6列/停7列/双值改较大/改单选），
   执行完通知工程侧复核列数 50→44；GB 30871 等真 PDF 后按 RUNBOOK §3.4 补录。
3. 已交付基座（勿重做）：失败治理管线（failure_ledger 退避/死信 + 死信水位
   入 /safety/ai-quality 看板 + scripts/hazard_dead_letters.py 只读查询）；
   superagent 平台底座（Source→Trigger→Task→Effect + Policy observe/auto，
   R1 六件套是范例）；business_agent（确认卡/PendingAction/权限/会话/技能）；
   P0 门禁（知识层降级不写回/占位不写回/JSON 修复重试）。
4. 需求来源：docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md §3.3-B/D-15、
   §4.3 方案B、§4.4 目标架构（「AI 识别复核员」五工具）、§4.7 P1 验收行、
   §5 P1-3 行。
5. 仓库根 AGENTS.md、CLAUDE.md、CLAUDE.local.md 与 backend/AGENTS.md、
   backend/CLAUDE.md。CLAUDE.local.md：只能在 feature/warehouse-module 工作，
   禁止新建/切换分支。

【已拍板决策（设计文档定案，质询不重复问）】
- ① 主链不 Agent 化（成本/确定性前提）；本特性只做「例外处理器」（§4.1）。
- observe 先行：只记录/产出复核报告，**不写回任何 Bitable 列**；auto+写前
  人工确认属 P2-1。
- 人工列唯一权威、AI 列仅候选证据（§2.3）；复核建议落点=AiVsManual 同款
  「候选证据」语义，绝不直接改人工列。
- ①识别主链 prompt 行为零变化（skills 化只拆文件不改语义，回归靠 P1-1 评测
  基线快照锁定）。

【需业务确认（Step 1 质询必答清单，逐项给选项）】
- 例外捞取范围：仅死信 / 死信+重试中(attempts≥N) / 死信+人工指定 record_id；
- 复核员触发：定时任务（频率？）/ 安全管理员群内指令 / superagent Source 化
  （bitable_poll/dead-letter 源，注意 P0-6 ①收编未做，Source 化范围要拍）；
- observe 报告落点：Attention/确认卡到安全管理员 / /safety/ai-quality 看板新
  Tab / 两者（推荐卡+看板留痕）；
- 五工具集（view_images/search_regulations/get_record_context/cross_check/
  propose_writeback）逐个做/裁剪（propose_writeback 在 observe 期降级为
  propose_only？）；
- skills 化范围：仅复核员 prompt / 含①识别主链 prompt 拆 md+版本号；
- 成本护栏：单条复核 token/调用上限、每日复核条数上限、超限行为。

【本次范围（§4.3-B observe + §3.3-D-15 + skills 化）】
- E1 例外判据与捞取：从 failure_ledger/dead_letters 取例外记录，判据函数化
  （可测纯函数），含分类标签（RAG降级/JSON持续非法/引用不可验证/依据空）。
- E2 复核员 Agent：business_agent 体系内「AI 识别复核员」——五工具（图片/
  法规检索/记录上下文/交叉核对/结构化建议）+ 多步补检产出结构化复核报告
  （record_id/失败原因/检索证据/AI 新结论 vs 人工结论 diff/建议动作）。
- E3 observe 落点：复核报告→确认卡（复用 PendingAction/Attention 形态，标注
  「observe·不写回」）+ 看板留痕（quality_dashboard 或独立 Tab，observe 口径
  rescued 计数=「复核结论与人工一致或给出可用依据」的条数占比）。
- E4 skills 化 prompt：拆 md+版本号+场景注册（硬护栏留代码），安全管理员可改
  软性内容；①主链 prompt 迁移零语义变化（评测基线快照对比锁定）。
- E5 指标：例外率（例外条数/已分析条数）与 rescued 率进看板（observe 口径）。

【硬性边界】
- 后端改动限 safety 模块（含 tests）+ business_agent 体系；前端限
  frontend/src/ 安全域页面；不改 platform/、app/core/、app/shared/、alembic/
  （superagent 平台文件如需接入走既有扩展点，动前先问）。
- observe 不写 Bitable、不发普通通知（确认卡属既有确认流可发，收件人白名单）；
  无 DB 迁移优先（确需存 observe 报告先出方案质询）；无新依赖。
- 测试全 fake/mock（死信 fake/retriever fake/AI fake/卡片 fake）；真实只读
  验证先问且限量（跑前报条数）。
- 不改 P0 门禁与 P1-1 检索行为、P1-2 CAS/口径行为、P1-4 看板既有端点行为。
- 黄色操作先确认；红色操作（push/发布/删数据）不做；不新建/切换分支；只提交
  本窗口 hunk；不 push。

【验收/测试】
- E1-E5 每项有单测：例外判据纯函数、五工具单测（含权限/越权）、复核报告
  结构 schema 校验、observe 写白名单零命中断言（写路径不得包含任何 Bitable
  列——field_authority 断言复用）、①主链 prompt skills 化前后 P1-1 评测快照
  零漂移。
- 全量：pytest tests/modules/safety + ai_hazard_identification/tests，与开工
  父 commit 干净快照对比 0 新增失败；ruff/mypy 窗口 0 新增；前端 tsc（+
  dev 停窗口补 build，与 P1-2 欠账一起）。
- 提交前给：变更文件清单、验证命令与结果、逐项验收、遗留风险、WIP touched
  说明；用户确认后提交（粒度质询定）、不 push。

【流程】
- Step 1 质询至少覆盖：上述业务确认 6 项、observe 报告的数据形态与保留时长、
  与 superagent Policy 的关系（复用 observe 语义还是独立开关）、测试接缝、
  提交粒度；
- Step 2 spec 写 .scratch/hazard-exception-reviewer/spec.md，先定测试接缝并
  确认；
- Step 3 垂直切片 tickets（2-4h/个，标 Blocked by 与验收），先确认粒度；
- Step 4 TDD（先 RED）；Step 5 双轴审查（Standards/Spec 并行）；Step 6 用户
  确认后提交（不 push）。
